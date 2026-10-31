"""Attendance API views (API Spec doc 07 §§24-32).

Start session -> select checkpoints -> generate tokens -> rotate -> students scan.
"""
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Sum, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.academics.models import (
    ClassDefinition, ClassSchedule, ClassSession, CourseOffering, Enrollment, Semester,
)
from apps.academics.serializers import ClassScheduleSerializer
from apps.academics.services import enroll_cohort
from apps.core.scoping import can_administer_offering, is_offering_teacher, scope_by_department
from apps.core.permissions import IsLecturer, IsStudent
from apps.core.throttling import PollingRateThrottle
from apps.audit.services import audit

from .models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession, PointsLedger
from .offline import record_v2_scan
from .permissions import can_launch_attendance, launchable_offerings
from .points import POINTS, award_manual_points, award_station_points, auto_select_stations
from .read_cache import (
    cached_read, history_key, is_enrolled, points_key, session_checkpoints,
    session_snapshot, station_assignment, station_scan_count,
)
from .serializers import (
    AttendanceCheckpointSerializer,
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CredentialBundleSerializer,
    OfflineSyncSerializer,
    ScanRequestSerializer,
)
from .token_store import (
    TOKEN_V2, TokenVerificationError, credential_bundle, decode_token_version,
    generate_tokens_for_session, validate_and_record_scan, verify_hmac_token,
)

ADMIN_ROLES = {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN"}


def _can_manage_attendance(user, offering, lecturer_id):
    if not getattr(user, "is_authenticated", False):
        return False
    # Whoever opened the session owns it, even when they are a student
    # delegate rather than the assigned lecturer.
    if lecturer_id and lecturer_id == user.id:
        return True
    # A co-lecturer, the class delegate or a departmental course delegate may
    # run attendance for the offering.
    return can_launch_attendance(user, offering)


def _parse_headcount(value):
    """Return a valid positive int or None."""
    if value is None:
        return None
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_duration(value, default, maximum):
    """Return a session TTL in seconds, clamped to ``maximum``.

    Malformed or non-positive input falls back to ``default`` instead of
    escaping as an unhandled 500 (``int("abc")`` used to raise ValueError).
    """
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = default
    if seconds <= 0:
        seconds = default
    return min(seconds, maximum)


class StartAttendanceView(APIView):
    """POST /api/v1/class-sessions/{session_id}/attendance

    Lecturer starts an attendance session for a class.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_start"

    def post(self, request, session_id):
        class_session = get_object_or_404(ClassSession, id=session_id)
        if not _can_manage_attendance(request.user, class_session.class_definition.course_offering, class_session.class_definition.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not the assigned lecturer for this class."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        duration = _parse_duration(
            request.data.get("duration_seconds"),
            getattr(settings, "ATTENDANCE_SESSION_DEFAULT_SECONDS", 60),
            getattr(settings, "ATTENDANCE_SESSION_MAX_SECONDS", 10800),
        )
        now = timezone.now()
        session = AttendanceSession.objects.create(
            class_session=class_session,
            lecturer=request.user,
            started_at=now,
            expires_at=now + timezone.timedelta(seconds=duration),
            expected_headcount=_parse_headcount(request.data.get("expected_headcount")),
        )
        audit(user=request.user, action="ATTENDANCE_STARTED", resource_type="AttendanceSession", resource_id=session.id, request=request)
        return Response(AttendanceSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class FlexibleStartAttendanceView(APIView):
    """POST /api/v1/attendance/start-flex/

    Lecturer-friendly attendance start. Prefills from the weekly timetable
    when a schedule_id is given, but also accepts a fully custom time for
    swapped/rescheduled periods.

    Body:
      offering_id      (required)
      schedule_id      (optional) - prefill class_type/location from timetable
      class_type       (optional, default from schedule or LECTURE)
      starts_at        (optional ISO datetime, default now)
      ends_at          (optional ISO datetime, default starts_at + 2h)
      duration_seconds (optional token validity, default 60, max 10800)
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_start"

    @transaction.atomic
    def post(self, request):
        offering_id = request.data.get("offering_id")
        if not offering_id:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "offering_id is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offering = get_object_or_404(CourseOffering.objects.select_for_update(), id=offering_id)
        if not _can_manage_attendance(request.user, offering, offering.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not the assigned lecturer for this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Safety net for a classroom that was assigned before assignment-time
        # provisioning existed (or created with no roster): if nobody is
        # enrolled at all, enrol the course cohort now so the session has
        # students to mark. An offering with real registrations is left as-is.
        # The offering row is locked, so concurrent starts cannot double-enrol.
        if not Enrollment.objects.filter(course_offering=offering).exists():
            enroll_cohort(offering)

        schedule = None
        schedule_id = request.data.get("schedule_id")
        if schedule_id:
            schedule = get_object_or_404(ClassSchedule, id=schedule_id, course_offering=offering)

        class_type = request.data.get("class_type") or (schedule.class_type if schedule else ClassDefinition.ClassType.LECTURE)

        # Find-or-create the ClassDefinition for this offering + class type.
        default_name = f"{offering.course.code} {class_type.title()}"
        class_def, _ = ClassDefinition.objects.get_or_create(
            course_offering=offering,
            class_type=class_type,
            defaults={"lecturer": offering.lecturer or request.user, "name": default_name,
                      "location": schedule.location if schedule else ""},
        )

        # Resolve times: explicit -> schedule -> now.
        starts_at = request.data.get("starts_at")
        if starts_at:
            try:
                starts_at = timezone.datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                if timezone.is_naive(starts_at):
                    starts_at = timezone.make_aware(starts_at)
            except (ValueError, AttributeError):
                return Response(
                    {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid starts_at datetime."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            starts_at = timezone.now()

        ends_at = request.data.get("ends_at")
        if ends_at:
            try:
                ends_at = timezone.datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
                if timezone.is_naive(ends_at):
                    ends_at = timezone.make_aware(ends_at)
            except (ValueError, AttributeError):
                return Response(
                    {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid ends_at datetime."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif schedule:
            duration = timezone.datetime.combine(starts_at.date(), schedule.end_time) - timezone.datetime.combine(
                starts_at.date(), schedule.start_time
            )
            ends_at = starts_at + duration
        else:
            ends_at = starts_at + timezone.timedelta(hours=2)

        class_session = ClassSession.objects.create(
            class_definition=class_def, starts_at=starts_at, ends_at=ends_at, status="ONGOING"
        )

        duration = _parse_duration(
            request.data.get("duration_seconds"),
            getattr(settings, "ATTENDANCE_SESSION_DEFAULT_SECONDS", 60),
            getattr(settings, "ATTENDANCE_SESSION_MAX_SECONDS", 10800),
        )
        now = timezone.now()
        mode = request.data.get("mode")
        if mode not in {AttendanceSession.SessionMode.PROJECTOR, AttendanceSession.SessionMode.STATIONS}:
            mode = AttendanceSession.SessionMode.STATIONS

        # One live attendance session per class at a time. Starting another
        # supersedes the previous one instead of piling up duplicates.
        superseded = 0
        for existing in AttendanceSession.objects.filter(
            class_session__class_definition=class_def,
            status=AttendanceSession.Status.ACTIVE,
            expires_at__gt=now,
        ):
            if existing.lecturer_id == request.user.id:
                existing.status = AttendanceSession.Status.CLOSED
                existing.save(update_fields=["status"])
                superseded += 1

        session = AttendanceSession.objects.create(
            class_session=class_session,
            lecturer=request.user,
            started_at=now,
            expires_at=now + timezone.timedelta(seconds=duration),
            expected_headcount=_parse_headcount(request.data.get("expected_headcount")),
            mode=mode,
        )
        audit(user=request.user, action="ATTENDANCE_STARTED_FLEX", resource_type="AttendanceSession", resource_id=session.id,
              request=request, metadata={"offering_id": str(offering.id), "schedule_id": schedule_id or None})
        payload = AttendanceSessionSerializer(session).data
        payload["class_session_id"] = str(class_session.id)
        payload["class_definition_id"] = str(class_def.id)
        payload["course_code"] = offering.course.code
        payload["eligible_students"] = Enrollment.objects.filter(
            course_offering=offering, status=Enrollment.Status.ACTIVE
        ).count()
        return Response(payload, status=status.HTTP_201_CREATED)


# NOTE: a `get` listing an attendance session's checkpoints used to sit here.
# It took an `attendance_session_id` that this URL does not supply, so a GET to
# /attendance/start-flex/ raised TypeError -> 500, and it duplicated
# CheckpointsView.get, which serves the same data at
# /attendance/{attendance_session_id}/checkpoints/.


class AutoSelectStationsView(APIView):
    """POST /api/v1/attendance/{session_id}/checkpoints/auto-select {count?}

    System picks a few of the most consistent attendees at random as QR
    stations (FR-047). Auto stations earn full points when used.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def post(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can select stations."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not session.is_active:
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance session is no longer active."}},
                status=status.HTTP_410_GONE,
            )
        min_verified = getattr(settings, "ATTENDANCE_AUTO_MIN_VERIFIED", 15)
        verified_count = (
            AttendanceRecord.objects.filter(attendance_session=session)
            .values("student_id")
            .distinct()
            .count()
        )
        if verified_count < min_verified:
            return Response(
                {"success": False, "error": {"code": "NOT_ENOUGH_ATTENDANCE",
                 "message": f"Auto-select needs at least {min_verified} students checked in for this session first "
                            f"(currently {verified_count}). Stations are picked only from students proven present - "
                            "have a few more students scan, then try again."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        max_stations = min(
            getattr(settings, "ATTENDANCE_MAX_CHECKPOINTS", 10),
            getattr(settings, "ATTENDANCE_MAX_AUTO_STATIONS", 3),
        )
        try:
            count = int(request.data.get("count", 3))
        except (TypeError, ValueError):
            count = 3
        auto_already = session.checkpoints.filter(selection_method="AUTO").count()
        if auto_already >= max_stations:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": f"Auto-selection is capped at {max_stations} stations per session."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        count = max(1, min(count, max_stations - auto_already, max_stations - session.checkpoints.count()))
        if count <= 0:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Station limit reached."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        created = auto_select_stations(session, count)
        return Response({
            "selected": AttendanceCheckpointSerializer(created, many=True).data,
            "total_stations": session.checkpoints.count(),
            "auto_stations_remaining": max_stations - session.checkpoints.filter(selection_method="AUTO").count(),
            "scans_per_station": getattr(settings, "ATTENDANCE_SCANS_PER_STATION", 20),
        }, status=status.HTTP_201_CREATED)


class ManualAttendanceView(APIView):
    """POST /api/v1/attendance/{session_id}/manual {student_id, status?}

    Lecturer manually adds a student who missed the QR window.
    Manual entries earn ZERO points (FR-048) to discourage skipping the scan.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def post(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can add manual attendance."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        student_id = request.data.get("student_id")
        new_status = request.data.get("status", "PRESENT")
        if new_status not in {"PRESENT", "LATE", "ABSENT", "EXCUSED"}:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid status."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.academics.models import Enrollment
        if not Enrollment.objects.filter(student_id=student_id, course_offering=session.course_offering, status=Enrollment.Status.ACTIVE).exists():
            return Response(
                {"success": False, "error": {"code": "NOT_ELIGIBLE", "message": "Student is not enrolled in this course."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record, created = AttendanceRecord.objects.get_or_create(
            attendance_session=session, student_id=student_id,
            defaults={"verification_method": AttendanceRecord.VerificationMethod.MANUAL, "status": new_status},
        )
        if created:
            award_manual_points(session, student=student_id)
        return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED if created else 200)


class ManualAttendanceBatchView(APIView):
    """POST /api/v1/attendance/{session_id}/manual/batch
    {student_ids: [uuid, ...], status?}

    Add up to 15 students in one request. Students who are not enrolled or
    already have a record for this session are skipped (reported back) instead
    of failing the whole batch. Manual entries still earn ZERO points (FR-048).
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"
    MAX_BATCH = 15

    def post(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can add manual attendance."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        new_status = request.data.get("status", "PRESENT")
        if new_status not in {"PRESENT", "LATE", "ABSENT", "EXCUSED"}:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid status."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_ids = request.data.get("student_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Select at least one student."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student_ids = []
        for value in raw_ids:
            try:
                parsed = value if isinstance(value, UUID) else UUID(str(value))
            except (TypeError, ValueError, AttributeError):
                return Response(
                    {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "One of the selected students has an invalid id."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if parsed not in student_ids:
                student_ids.append(parsed)
        if len(student_ids) > self.MAX_BATCH:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": f"You can add at most {self.MAX_BATCH} students at once."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_records = []
        skipped = []
        with transaction.atomic():
            eligible = set(
                Enrollment.objects.filter(
                    student_id__in=student_ids,
                    course_offering=session.course_offering,
                    status=Enrollment.Status.ACTIVE,
                ).values_list("student_id", flat=True)
            )
            existing = set(
                AttendanceRecord.objects.filter(
                    attendance_session=session, student_id__in=student_ids
                ).values_list("student_id", flat=True)
            )
            for student_id in student_ids:
                if student_id not in eligible:
                    skipped.append({"student_id": str(student_id), "reason": "NOT_ENROLLED"})
                    continue
                if student_id in existing:
                    skipped.append({"student_id": str(student_id), "reason": "ALREADY_RECORDED"})
                    continue
                record, created = AttendanceRecord.objects.get_or_create(
                    attendance_session=session,
                    student_id=student_id,
                    defaults={
                        "verification_method": AttendanceRecord.VerificationMethod.MANUAL,
                        "status": new_status,
                    },
                )
                if not created:
                    skipped.append({"student_id": str(student_id), "reason": "ALREADY_RECORDED"})
                    continue
                award_manual_points(session, student=student_id)
                created_records.append(record)

        payload = {
            "created": AttendanceRecordSerializer(created_records, many=True).data,
            "skipped": skipped,
            "count": len(created_records),
        }
        return Response(payload, status=status.HTTP_201_CREATED if created_records else status.HTTP_200_OK)


class StudentOfClassView(APIView):
    """POST /api/v1/attendance/{session_id}/student-of-class/

    Algorithm picks one attendee as Student of the Class (+10 pts).
    Never repeats for the same course; still eligible for other courses.
    Idempotent - calling twice returns the same winner.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, attendance_session_id):
        from .points import award_student_of_class

        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can pick the Student of the Class."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        winner = award_student_of_class(session)
        if winner is None:
            return Response(
                {"success": False, "error": {"code": "NO_CANDIDATES", "message": "No eligible attendees - everyone qualified has already been Student of the Class for this course."}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            "student_id": str(winner.student_id),
            "student_name": winner.student.get_full_name(),
            "student_email": winner.student.email,
            "points": winner.points,
            "category": winner.category,
            "is_special_day": winner.points != 10,
        })


class MyStationView(APIView):
    """GET /api/v1/students/me/station - the student's active station
    assignment, if any (so their phone can display the rotating QR)."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_station_poll"

    def get(self, request):
        assignment = station_assignment(request.user.id)
        if assignment is None:
            return Response(None)
        snapshot = session_snapshot(assignment["attendance_session_id"])
        if snapshot["status"] != AttendanceSession.Status.ACTIVE or snapshot["expires_at"] <= timezone.now():
            return Response(None)
        return Response(assignment)


class MyPointsView(APIView):
    """GET /api/v1/students/me/points - total points + breakdown."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_history_poll"

    def get(self, request):
        from .points import POINTS, SPECIAL_DAY_MULTIPLIER, is_special_day

        def load():
            entries = PointsLedger.objects.filter(student_id=request.user.id)
            by_category = {
                row["category"]: row["total"]
                for row in entries.values("category").annotate(total=Sum("points"))
            }
            birthday = is_special_day(request.user)
            return {
                "total_points": sum(by_category.values()),
                "points_config": POINTS,
                "special_day_multiplier": SPECIAL_DAY_MULTIPLIER if birthday else 1,
                "is_special_day": birthday,
                "by_category": by_category,
                "recent": [
                    {
                        "category": e.category,
                        "points": e.points,
                        "session_date": e.attendance_session.started_at.date().isoformat(),
                    }
                    for e in entries.select_related("attendance_session")[:10]
                ],
            }

        return Response(cached_read(points_key(request.user.id), load, timeout=300))


class StationTokenView(APIView):
    """GET /api/v1/attendance/{session_id}/my-station-token/

    A student serving as a station requests a fresh 10-second token for
    their own checkpoint. Their phone displays the rotating QR; classmates
    scan it. Backend remains the token authority (BR-061).
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_station_token"

    def get(self, request, attendance_session_id):
        assignment = station_assignment(request.user.id, attendance_session_id)
        if assignment is None:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not a station in this session."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        snapshot = session_snapshot(attendance_session_id)
        if snapshot["status"] != AttendanceSession.Status.ACTIVE or snapshot["expires_at"] <= timezone.now():
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance is closed."}},
                status=status.HTTP_410_GONE,
            )
        from .token_store import TOKEN_TTL, generate_token_for_checkpoint
        session = SimpleNamespace(
            id=attendance_session_id,
            started_at=snapshot["started_at"],
            expires_at=snapshot["expires_at"],
        )
        checkpoint = SimpleNamespace(
            id=assignment["checkpoint_id"],
            checkpoint_number=assignment["checkpoint_number"],
            selection_method=assignment["selection_method"],
            student=SimpleNamespace(email=request.user.email),
        )
        version = TOKEN_V2 if settings.ATTENDANCE_TOKEN_VERSION == 2 and request.query_params.get("token_version") == "2" else 1
        try:
            data = generate_token_for_checkpoint(session, checkpoint, version=version)
        except ValueError:
            return Response(
                {"success": False, "error": {"code": "TOKEN_WINDOW_EXPIRED", "message": "No full QR slot remains in this session."}},
                status=status.HTTP_410_GONE,
            )
        scans_at_station = station_scan_count(checkpoint.id)
        is_auto = checkpoint.selection_method in {"AUTO", "SCAN"}
        scans_remaining = None
        if is_auto:
            from .points import SCANS_PER_STATION
            scans_remaining = max(0, SCANS_PER_STATION - scans_at_station)
        return Response({
            "token": data["token"],
            "checkpoint_number": checkpoint.checkpoint_number,
            "selection_method": checkpoint.selection_method,
            "expires_in_seconds": TOKEN_TTL,
            "scans_at_station": scans_at_station,
            "scans_remaining": scans_remaining,
            "total_checked_in": snapshot["present"],
            "expected_headcount": snapshot["expected_headcount"],
        })


class CheckpointsView(APIView):
    """POST /api/v1/attendance/{session_id}/checkpoints

    Lecturer selects checkpoint students who are physically present (BR-050-053).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def post(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can select checkpoints."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not session.is_active:
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance session is no longer active."}},
                status=status.HTTP_410_GONE,
            )
        student_ids = request.data.get("student_ids", [])
        max_checkpoints = getattr(settings, "ATTENDANCE_MAX_CHECKPOINTS", 10)
        if len(student_ids) > max_checkpoints:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": f"Maximum {max_checkpoints} checkpoints allowed."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offering = session.course_offering
        enrolled_ids = set(
            Enrollment.objects.filter(
                course_offering=offering, status=Enrollment.Status.ACTIVE
            ).values_list("student_id", flat=True)
        )
        enrolled_id_strings = {str(e) for e in enrolled_ids}
        for sid in student_ids:
            if str(sid) not in enrolled_id_strings:
                return Response(
                    {"success": False, "error": {"code": "NOT_ELIGIBLE", "message": f"Student {sid} is not enrolled in this course."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        checkpoints = []
        with transaction.atomic():
            for sid in student_ids:
                # Idempotent: re-selecting a student does not raise a duplicate error.
                cp, created = AttendanceCheckpoint.objects.get_or_create(
                    attendance_session=session,
                    student_id=sid,
                    defaults={"checkpoint_number": session.checkpoints.count() + 1},
                )
                if created:
                    # Selecting a student as a station confirms their presence and
                    # awards their station points immediately (not on first scan).
                    award_station_points(session, cp)
                checkpoints.append(cp)
        # Renumber so the stations read 1..n in the order chosen.
        for i, cp in enumerate(session.checkpoints.order_by("created_at"), 1):
            if cp.checkpoint_number != i:
                cp.checkpoint_number = i
                cp.save(update_fields=["checkpoint_number"])
        return Response(AttendanceCheckpointSerializer(checkpoints, many=True).data, status=status.HTTP_201_CREATED)

    def get(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, session.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(AttendanceCheckpointSerializer(session.checkpoints.all(), many=True).data)


class CheckpointDetailView(APIView):
    """DELETE /api/v1/attendance/{session_id}/checkpoints/{checkpoint_id}/

    Removes a station the lecturer picked by mistake."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, attendance_session_id, checkpoint_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can remove a station."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        checkpoint = get_object_or_404(
            AttendanceCheckpoint, id=checkpoint_id, attendance_session=session
        )
        checkpoint.delete()
        for i, cp in enumerate(session.checkpoints.order_by("created_at"), 1):
            if cp.checkpoint_number != i:
                cp.checkpoint_number = i
                cp.save(update_fields=["checkpoint_number"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class TokensView(APIView):
    """POST /api/v1/attendance/{session_id}/tokens

    Generate new QR tokens (rotation, FR-043).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def post(self, request, attendance_session_id):
        snapshot = session_snapshot(attendance_session_id)
        # Fast path: the session owner needs no extra queries, which keeps the
        # live token rotation served entirely from the cache snapshot.
        allowed = str(request.user.id) == snapshot["lecturer_id"]
        if not allowed:
            offering = get_object_or_404(
                CourseOffering.objects.select_related("course", "department"),
                id=snapshot["offering_id"],
            )
            allowed = _can_manage_attendance(request.user, offering, None)
        if not allowed:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can generate tokens."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if snapshot["status"] != AttendanceSession.Status.ACTIVE or snapshot["expires_at"] <= timezone.now():
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance session is no longer active."}},
                status=status.HTTP_410_GONE,
            )
        checkpoints = [SimpleNamespace(
            id=cp["id"], checkpoint_number=cp["checkpoint_number"],
            student=SimpleNamespace(email=cp["student__email"]),
        ) for cp in session_checkpoints(attendance_session_id)
            if cp["selection_method"] != AttendanceCheckpoint.SelectionMethod.SCAN]
        session = SimpleNamespace(
            id=attendance_session_id, mode=snapshot["mode"],
            started_at=snapshot["started_at"], expires_at=snapshot["expires_at"],
        )
        version = TOKEN_V2 if settings.ATTENDANCE_TOKEN_VERSION == 2 and request.query_params.get("token_version") == "2" else 1
        try:
            data = generate_tokens_for_session(session, checkpoints=checkpoints, version=version)
        except ValueError:
            return Response(
                {"success": False, "error": {"code": "TOKEN_WINDOW_EXPIRED", "message": "No full QR slot remains in this session."}},
                status=status.HTTP_410_GONE,
            )
        return Response(data)


class ScanView(APIView):
    """POST /api/v1/attendance/scan

    Student scans a QR code token (FR-045, API Spec §29-30).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_scan"

    def post(self, request):
        serializer = ScanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = validate_and_record_scan(serializer.validated_data["token"], request.user)
        http_status = result.pop("http_status")
        if result.get("success"):
            return Response(result, status=http_status)
        return Response(
            {"success": False, "error": {"code": result["error_code"], "message": result["message"]}},
            status=http_status,
        )


class OfflineSyncView(APIView):
    """Sync a bounded batch of signed QR captures for the signed-in student."""

    permission_classes = [IsAuthenticated, IsStudent]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_sync"

    def post(self, request):
        serializer = OfflineSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data["session_id"]
        captures = serializer.validated_data["captures"]
        batch_id = uuid4()
        results = []

        # Serialize writes with a manual close or headcount close. One enrollment
        # and existing-record lookup serve the entire bounded batch.
        with transaction.atomic():
            session = get_object_or_404(
                AttendanceSession.objects.select_for_update().select_related(
                    "class_session__class_definition__course_offering"
                ), id=session_id,
            )
            enrolled = Enrollment.objects.filter(
                student=request.user, course_offering=session.course_offering,
                status=Enrollment.Status.ACTIVE,
            ).exists()
            existing = AttendanceRecord.objects.filter(
                attendance_session=session, student=request.user,
            ).first()

            for index, capture in enumerate(captures):
                token = capture["token"]
                if decode_token_version(token) != TOKEN_V2:
                    result = {"success": False, "error_code": "TOKEN_VERSION_UNSUPPORTED", "message": "Offline sync requires a v2 QR token."}
                else:
                    try:
                        claims = verify_hmac_token(token)
                    except TokenVerificationError:
                        result = {"success": False, "error_code": "TOKEN_INVALID", "message": "Invalid QR code."}
                    else:
                        if claims["session_id"] != session.id or (
                            "checkpoint_id" in capture and capture["checkpoint_id"] != claims["checkpoint_id"]
                        ):
                            result = {"success": False, "error_code": "TOKEN_INVALID", "message": "QR code does not match this session or station."}
                        else:
                            result = record_v2_scan(
                                session, request.user, claims, offline=True,
                                batch_id=batch_id, enrolled=enrolled,
                                existing_record=existing, existing_checked=True,
                            )
                            if result["success"] and not result.get("duplicate"):
                                existing = SimpleNamespace(id=UUID(result["attendance_record_id"]))

                item = {"index": index}
                if result["success"]:
                    item.update({
                        "status": "DUPLICATE" if result.get("duplicate") else "ACCEPTED",
                        "record_id": result["attendance_record_id"],
                    })
                else:
                    item.update({"status": "REJECTED", "code": result["error_code"], "message": result["message"]})
                results.append(item)

        response = Response({"batch_id": str(batch_id), "results": results})
        response["Cache-Control"] = "private, no-store"
        return response


class StationCredentialView(APIView):
    """Give the assigned station its session-scoped v2 signing material."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def get(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        checkpoint = session.checkpoints.filter(student=request.user).first()
        if checkpoint is None:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not a station in this session."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not session.is_active:
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance is closed."}},
                status=status.HTTP_410_GONE,
            )
        response = Response(CredentialBundleSerializer(credential_bundle(session, checkpoint.id)).data)
        response["Cache-Control"] = "private, no-store"
        return response


class ProjectorCredentialView(APIView):
    """Give the session lecturer a projector-scoped v2 signing key."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "attendance_admin"

    def get(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only this session's lecturer can use the projector credential."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not session.is_active:
            return Response(
                {"success": False, "error": {"code": "SESSION_EXPIRED", "message": "Attendance is closed."}},
                status=status.HTTP_410_GONE,
            )
        response = Response(CredentialBundleSerializer(credential_bundle(session)).data)
        response["Cache-Control"] = "private, no-store"
        return response


class CloseAttendanceView(APIView):
    """POST /api/v1/attendance/{session_id}/close

    Lecturer manually closes an attendance session (e.g. once the full class
    has checked in). Closes the window for further scans.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        if not _can_manage_attendance(request.user, session.course_offering, session.lecturer_id):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the session lecturer can close this session."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if session.status != AttendanceSession.Status.ACTIVE:
            return Response(
                {"success": False, "error": {"code": "SESSION_INACTIVE", "message": "Session is already closed or expired."}},
                status=status.HTTP_409_CONFLICT,
            )
        session.status = AttendanceSession.Status.CLOSED
        session.save(update_fields=["status", "updated_at"])
        audit(user=request.user, action="ATTENDANCE_CLOSED", resource_type="AttendanceSession", resource_id=session.id,
              request=request)
        return Response(AttendanceSessionSerializer(session).data)


class AttendanceStatusView(APIView):
    """GET /api/v1/attendance/{session_id} - live status for lecturer."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_live_poll"

    def get(self, request, attendance_session_id):
        snapshot = session_snapshot(attendance_session_id)
        if request.user.role in ADMIN_ROLES:
            offering = get_object_or_404(CourseOffering, id=snapshot["offering_id"])
            if not can_administer_offering(request.user, offering):
                return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == "STUDENT":
            if not is_enrolled(request.user.id, snapshot["offering_id"]):
                offering = CourseOffering.objects.filter(id=snapshot["offering_id"]).select_related("course").first()
                if offering is None or not can_launch_attendance(request.user, offering):
                    return Response(
                        {"success": False, "error": {"code": "FORBIDDEN", "message": "Access denied."}},
                        status=status.HTTP_403_FORBIDDEN,
                    )
        elif request.user.role not in ADMIN_ROLES and (
            request.user.role != "LECTURER" or str(request.user.id) != snapshot["lecturer_id"]
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)
        total_eligible = snapshot["total_eligible"]
        total_present = snapshot["present"]
        headcount_remaining = None
        if snapshot["expected_headcount"] is not None:
            headcount_remaining = max(0, snapshot["expected_headcount"] - total_present)
        return Response({
            "status": snapshot["status"],
            "is_active": snapshot["status"] == AttendanceSession.Status.ACTIVE and snapshot["expires_at"] > timezone.now(),
            "total_eligible": total_eligible,
            "present": total_present,
            "remaining": total_eligible - total_present,
            "expires_at": snapshot["expires_at"],
            "expected_headcount": snapshot["expected_headcount"],
            "headcount_remaining": headcount_remaining,
            "headcount_reached_at": snapshot["headcount_reached_at"],
        })


class LaunchableCoursesView(APIView):
    """GET /api/v1/attendance/launchable-courses/

    The offerings this user may open an attendance session for: their taught
    courses, plus any offering covered by a departmental course delegation or
    a class delegation. Powers the course picker for delegates, who are
    students rather than lecturers.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_semester = Semester.objects.filter(is_active=True).first()
        qs = (
            launchable_offerings(
                request.user,
                CourseOffering.objects.select_related(
                    "course", "department", "semester", "lecturer", "co_lecturer"
                ).filter(status="ACTIVE"),
            )
            .order_by(
                Case(
                    When(semester=active_semester, then=0),
                    default=1,
                    output_field=IntegerField(),
                ),
                "course__code",
            )
        )
        result = []
        for off in qs:
            result.append({
                "offering_id": str(off.id),
                "course_code": off.course.code,
                "course_title": off.course.title,
                "department": off.department.name if off.department else "",
                "semester": off.semester.name,
                "lecturer_name": off.lecturer.get_full_name() if off.lecturer else "",
                "enrolled_students": off.enrollments.filter(status=Enrollment.Status.ACTIVE).count(),
                "class_definitions": [
                    {"id": str(cd.id), "name": cd.name, "class_type": cd.class_type, "location": cd.location}
                    for cd in off.class_definitions.all()
                ],
                "schedules": ClassScheduleSerializer(
                    off.schedules.filter(is_active=True), many=True
                ).data,
            })
        return Response(result)


class MyAttendanceSessionsView(APIView):
    """GET /api/v1/attendance/sessions/ - the lecturer's own sessions.

    Lets the dashboard rebuild its session list after a page reload instead of
    starting from an empty state. Live sessions are returned first, then the
    most recent finished ones.
    """

    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_live_poll"

    def get(self, request):
        qs = AttendanceSession.objects.filter(
            Q(lecturer=request.user)
            | Q(class_session__class_definition__course_offering__co_lecturer=request.user)
        ).select_related(
            "class_session",
            "class_session__class_definition",
            "class_session__class_definition__course_offering__course",
        )
        if request.user.role in ADMIN_ROLES:
            qs = scope_by_department(qs, request.user, "class_session__class_definition__course_offering__department")
        now = timezone.now()
        live_filter = {"status": AttendanceSession.Status.ACTIVE, "expires_at__gt": now}
        live = list(qs.filter(**live_filter))
        recent = list(qs.exclude(**live_filter).order_by("-started_at")[:10])
        sessions = live + recent
        session_ids = [s.id for s in sessions]
        offering_ids = {
            s.class_session.class_definition.course_offering_id for s in sessions
        }
        present_by_session = {
            row["attendance_session_id"]: row["total"]
            for row in AttendanceRecord.objects.filter(
                attendance_session_id__in=session_ids,
                status__in=["PRESENT", "LATE"],
            ).values("attendance_session_id").annotate(total=Count("id"))
        }
        eligible_by_offering = {
            row["course_offering_id"]: row["total"]
            for row in Enrollment.objects.filter(
                course_offering_id__in=offering_ids,
                status=Enrollment.Status.ACTIVE,
            ).values("course_offering_id").annotate(total=Count("id"))
        }
        payload = []
        for s in sessions:
            data = AttendanceSessionSerializer(
                s, context={"present_by_session": present_by_session}
            ).data
            offering = s.course_offering
            present = present_by_session.get(s.id, 0)
            # A session whose window has passed is finished for display, whatever
            # the stored status says - otherwise dead sessions look ACTIVE.
            effective_status = s.status
            if s.status == AttendanceSession.Status.ACTIVE and not s.is_active:
                effective_status = AttendanceSession.Status.CLOSED
            data.update({
                "course_code": offering.course.code,
                "class_name": s.class_session.class_definition.name,
                "class_session_id": str(s.class_session_id),
                "is_active": s.is_active,
                "status": effective_status,
                "present": present,
                "total_eligible": eligible_by_offering.get(offering.id, 0),
                "headcount_remaining": (
                    max(0, s.expected_headcount - present)
                    if s.expected_headcount is not None else None
                ),
            })
            payload.append(data)
        return Response(payload)


class SessionRecordsView(APIView):
    """GET /api/v1/class-sessions/{session_id}/attendance - attendance records for a session.
    Restricted to the lecturer who owns the class (or an admin)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        cs = get_object_or_404(ClassSession, id=session_id)
        owner = cs.class_definition.lecturer_id
        offering = cs.class_definition.course_offering
        if request.user.role in ADMIN_ROLES:
            allowed = can_administer_offering(request.user, offering)
        else:
            allowed = request.user.id == owner or can_launch_attendance(request.user, offering)
        if not allowed:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only view attendance for classes you teach."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        sessions = AttendanceSession.objects.filter(class_session=cs)
        records = AttendanceRecord.objects.filter(attendance_session__in=sessions).select_related(
            "student", "student__student_profile", "student__student_profile__department"
        ).order_by("student__last_name", "student__first_name")
        return Response(AttendanceRecordSerializer(records, many=True).data)


class AttendanceSessionDetailView(APIView):
    """GET /api/v1/attendance/{attendance_session_id}/records/

    Everything the lecturer detail page needs for one specific session: the
    session header (course, class, times, counts) and the per-student check-in
    rows, each with the student's matricule, department and level.
    Restricted to the lecturer who owns the class (or an admin).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, attendance_session_id):
        session = get_object_or_404(AttendanceSession, id=attendance_session_id)
        class_definition = session.class_session.class_definition
        offering = class_definition.course_offering
        owner = class_definition.lecturer_id
        if request.user.role in ADMIN_ROLES:
            allowed = can_administer_offering(request.user, offering)
        else:
            allowed = request.user.id == owner or can_launch_attendance(request.user, offering)
        if not allowed:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only view attendance for classes you teach."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        records = AttendanceRecord.objects.filter(
            attendance_session=session
        ).select_related(
            "student", "student__student_profile", "student__student_profile__department"
        )
        present = records.filter(status__in=["PRESENT", "LATE"]).count()
        eligible = Enrollment.objects.filter(
            course_offering=offering,
            status=Enrollment.Status.ACTIVE,
        ).count()
        effective_status = session.status
        if session.status == AttendanceSession.Status.ACTIVE and not session.is_active:
            effective_status = AttendanceSession.Status.CLOSED

        return Response({
            "session": {
                "id": str(session.id),
                "class_session_id": str(session.class_session_id),
                "course_code": offering.course.code,
                "course_title": offering.course.title,
                "class_name": class_definition.name,
                "started_at": session.started_at,
                "expires_at": session.expires_at,
                "effective_end_at": session.effective_end_at,
                "status": effective_status,
                "mode": session.mode,
                "present": present,
                "total_eligible": eligible,
            },
            "records": AttendanceRecordSerializer(records, many=True).data,
        })



class MyAttendanceView(APIView):
    """GET /api/v1/students/me/attendance - student's own attendance history."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [PollingRateThrottle]
    throttle_scope = "attendance_history_poll"

    def get(self, request):
        def load():
            records = AttendanceRecord.objects.filter(student_id=request.user.id).select_related(
                "attendance_session", "attendance_session__class_session",
                "attendance_session__class_session__class_definition__course_offering__course",
            )
            result = []
            for r in records:
                cs = r.attendance_session.class_session
                cd = cs.class_definition
                result.append({
                    "id": r.id,
                    "recorded_at": r.recorded_at,
                    "status": r.status,
                    "class_name": cd.name,
                    "course_code": cd.course_offering.course.code,
                    "session_date": cs.starts_at.date().isoformat(),
                })
            return result

        return Response(cached_read(history_key(request.user.id), load, timeout=300))


def _owns_record(request, record):
    """Only the lecturer who owns the class session (or an admin) may
    correct/delete a record. Prevents cross-course tampering."""
    lecturer_id = record.attendance_session.lecturer_id
    return _can_manage_attendance(request.user, record.attendance_session.course_offering, lecturer_id)


class CorrectRecordView(APIView):
    """PATCH /api/v1/attendance/records/{record_id} - correct attendance (BR-042).
    DELETE /api/v1/attendance/records/{record_id} - remove a bad/test record.
    Both actions are recorded in the audit log; never silently overwrite."""
    permission_classes = [IsAuthenticated]

    def patch(self, request, record_id):
        record = get_object_or_404(AttendanceRecord, id=record_id)
        if not _owns_record(request, record):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only correct attendance for classes you teach."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        old_status = record.status
        new_status = request.data.get("status", old_status)
        if new_status not in {"PRESENT", "ABSENT", "LATE", "EXCUSED"}:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid status."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record.status = new_status
        record.save(update_fields=["status", "updated_at"])
        audit(user=request.user, action="ATTENDANCE_CORRECTED", resource_type="AttendanceRecord", resource_id=record.id,
              request=request, metadata={"old_status": old_status, "new_status": new_status, "student_id": str(record.student_id)})
        return Response(AttendanceRecordSerializer(record).data)

    def delete(self, request, record_id):
        """Remove a record entirely (e.g. a test/duplicate entry)."""
        record = get_object_or_404(AttendanceRecord, id=record_id)
        if not _owns_record(request, record):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only delete attendance for classes you teach."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        metadata = {
            "student_id": str(record.student_id),
            "status": record.status,
            "session_id": str(record.attendance_session_id),
        }
        PointsLedger.objects.filter(attendance_session=record.attendance_session, student=record.student).delete()
        record.delete()
        audit(user=request.user, action="ATTENDANCE_RECORD_DELETED", resource_type="AttendanceRecord",
              resource_id=record_id, request=request, metadata=metadata)
        return Response(status=status.HTTP_204_NO_CONTENT)
