"""Validation and persistence shared by live v2 scans and delayed sync."""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.models import Enrollment
from apps.notifications.models import Notification

from .models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession
from .points import SCANS_PER_STATION, award_scan_points, award_station_points
from .token_store import TokenVerificationError, token_slot_bounds


def idempotency_key(student_id, session_id, slot_index, checkpoint_id):
    """A stable 64-character key for the student, session, slot and station."""
    raw = f"v2:{student_id}:{session_id}:{slot_index}:{checkpoint_id or 'projector'}"
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def reject(code, message, http_status=400):
    return {"success": False, "error_code": code, "message": message, "http_status": http_status}


def validate_capture_window(session, claims, *, offline, now=None):
    """Bind the signed slot to the persisted session and its effective end."""
    now = now or timezone.now()
    try:
        slot_start, slot_end = token_slot_bounds(session, claims)
    except (TokenVerificationError, OverflowError, OSError):
        return None, reject("TOKEN_INVALID", "Invalid QR code.")

    if not (session.started_at <= slot_start and slot_end <= session.effective_end):
        return None, reject("CAPTURE_WINDOW_EXPIRED", "The QR slot is outside the attendance window.")
    if offline:
        grace = max(0, settings.ATTENDANCE_OFFLINE_GRACE_SECONDS)
        if now > session.effective_end + timedelta(seconds=grace):
            return None, reject("SYNC_GRACE_EXPIRED", "The offline sync period has ended.")
        if slot_start > now:
            return None, reject("CAPTURE_IN_FUTURE", "The QR slot has not started yet.")
    elif not (session.is_active and (slot_start <= now or (claims["slot_index"] == 0 and session.started_at <= now)) and now < slot_end):
        return None, reject("TOKEN_EXPIRED", "QR code has expired. Please scan the current QR code.", 410)
    return (slot_start, slot_end), None


def record_v2_scan(
    session, student, claims, *, offline=False, batch_id=None,
    enrolled=None, existing_record=None, existing_checked=False,
):
    """Write one validated capture while the caller holds the session lock."""
    now = timezone.now()
    bounds, error = validate_capture_window(session, claims, offline=offline, now=now)
    if error:
        return error
    slot_start, slot_end = bounds
    if enrolled is None:
        enrolled = Enrollment.objects.filter(
            student=student, course_offering=session.course_offering,
            status=Enrollment.Status.ACTIVE,
        ).exists()
    if not enrolled:
        return reject("NOT_ENROLLED", "You are not enrolled in this course.", 403)

    key = idempotency_key(student.id, session.id, claims["slot_index"], claims["checkpoint_id"])
    if not existing_checked:
        existing_record = AttendanceRecord.objects.filter(
            attendance_session=session, student=student,
        ).first()
    if existing_record:
        if offline:
            return {
                "success": True, "duplicate": True,
                "attendance_record_id": str(existing_record.id), "http_status": 200,
            }
        return reject("ALREADY_ATTENDED", "Attendance already recorded for this session.", 409)

    checkpoint = None
    scans_served = 0
    if claims["checkpoint_id"]:
        checkpoint = AttendanceCheckpoint.objects.select_for_update().select_related("student").filter(
            id=claims["checkpoint_id"], attendance_session=session,
        ).first()
        if checkpoint is None:
            return reject("TOKEN_INVALID", "Invalid QR code.")
        if offline and checkpoint.created_at >= slot_end:
            return reject("CAPTURE_WINDOW_EXPIRED", "The station was not active in that QR slot.")
        is_station = checkpoint.student.role == "STUDENT"
        is_capped_station = is_station and checkpoint.selection_method in {
            AttendanceCheckpoint.SelectionMethod.AUTO,
            AttendanceCheckpoint.SelectionMethod.SCAN,
        }
        if is_capped_station:
            scans_served = AttendanceRecord.objects.filter(
                checkpoint=checkpoint,
                verification_method=AttendanceRecord.VerificationMethod.QR_SCAN,
            ).count()
            if scans_served >= SCANS_PER_STATION:
                return reject(
                    "STATION_FULL",
                    f"This station already served {SCANS_PER_STATION} classmates.",
                    409,
                )
    else:
        is_auto_station = False

    try:
        with transaction.atomic():
            record = AttendanceRecord.objects.create(
                attendance_session=session,
                student=student,
                checkpoint=checkpoint,
                verification_method=AttendanceRecord.VerificationMethod.QR_SCAN,
                status="PRESENT",
                recorded_at=slot_start if offline else now,
                offline_idempotency_key=key,
                capture_slot_index=claims["slot_index"],
                capture_verified_at=now,
                sync_batch_id=batch_id,
            )
    except IntegrityError:
        existing_record = AttendanceRecord.objects.filter(
            attendance_session=session, student=student,
        ).first()
        if existing_record and offline:
            return {
                "success": True, "duplicate": True,
                "attendance_record_id": str(existing_record.id), "http_status": 200,
            }
        return reject("ALREADY_ATTENDED", "Attendance already recorded for this session.", 409)

    station = None
    if not offline:
        from .points import activate_scanned_station

        station = activate_scanned_station(session, student)
    award_scan_points(session, student, checkpoint=checkpoint, when=slot_start if offline else now)
    if checkpoint and checkpoint.student.role == "STUDENT":
        award_station_points(session, checkpoint, when=slot_start if offline else now)
        if is_capped_station and scans_served + 1 == SCANS_PER_STATION:
            Notification.objects.create(
                user=checkpoint.student,
                type="ATTENDANCE",
                title="Station complete - all scans used!",
                message=f"All {SCANS_PER_STATION} classmates have scanned your station.",
                reference_type="AttendanceSession",
                reference_id=session.id,
            )

    if session.is_active and session.expected_headcount is not None:
        checked_in = AttendanceRecord.objects.filter(attendance_session=session).count()
        if checked_in >= session.expected_headcount and session.headcount_reached_at is None:
            session.headcount_reached_at = now
            session.status = AttendanceSession.Status.CLOSED
            session.save(update_fields=["headcount_reached_at", "status", "updated_at"])
            Notification.objects.create(
                user=session.lecturer,
                type="ATTENDANCE",
                title="Headcount reached - session closed!",
                message=f"All {session.expected_headcount} expected students have checked in.",
                reference_type="AttendanceSession",
                reference_id=session.id,
            )

    result = {
        "success": True,
        "attendance_record_id": str(record.id),
        "message": "Attendance recorded.",
        "http_status": 201,
    }
    if station and session.is_active:
        from .token_store import TOKEN_V2, station_qr_payload

        qr = station_qr_payload(session, station, version=TOKEN_V2)
        if qr:
            result["station_qr"] = qr
    return result
