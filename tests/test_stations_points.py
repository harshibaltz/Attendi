"""Tests for QR rotation, stations and points (FR-043, FR-047, FR-048).

Covers:
  - BR-035/BR-061: QR tokens expire after 10s; rotation keeps working
    until the attendance window closes
  - FR-047: auto-selection picks top attendees at random as stations
  - FR-048: points - station 5 (awarded on assignment), scan 4, manual 0
"""
import json

import pytest
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

from apps.attendance.models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession, PointsLedger
from apps.attendance.points import (
    POINTS,
    auto_select_stations,
    award_manual_points,
    award_scan_points,
    award_station_points,
)
from apps.attendance.token_store import generate_token_key, generate_tokens_for_session, validate_and_record_scan


def _setup_session(class_session, lecturer_user, seconds=60):
    now = timezone.now()
    return AttendanceSession.objects.create(
        class_session=class_session, lecturer=lecturer_user,
        started_at=now, expires_at=now + timedelta(seconds=seconds),
    )


def _put_token(session, checkpoint, token="tok"):
    data = json.dumps({
        "attendance_session_id": str(session.id),
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_number": checkpoint.checkpoint_number,
        "student_email": checkpoint.student.email,
    })
    cache.set(generate_token_key(str(session.id), token), data, timeout=10)
    cache.set(f"att:token:{token}", data, timeout=10)


@pytest.mark.django_db
class TestQRRotation:
    def test_token_expires_after_8s(self, class_session, lecturer_user, enrolled_student):
        """BR-035: token TTL is 8 seconds."""
        from apps.attendance.token_store import TOKEN_TTL
        assert TOKEN_TTL == 8

    def test_rotation_generates_fresh_tokens_while_session_active(self, class_session, lecturer_user, enrolled_student):
        """BR-061/FR-043: each rotation produces a new token; old token
        dies after TTL; scanning still works after rotation (window open)."""
        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(attendance_session=session, student=enrolled_student, checkpoint_number=1)

        # Rotation 1
        batch1 = generate_tokens_for_session(session)
        assert batch1["expires_in_seconds"] == 8
        tok1 = batch1["tokens"][0]["token"]

        # Rotation 2 (10s later in real life) - new token, old one still valid until TTL
        batch2 = generate_tokens_for_session(session)
        tok2 = batch2["tokens"][0]["token"]
        assert tok1 != tok2
        result_old = validate_and_record_scan(tok1, enrolled_student)
        assert result_old["success"] is True  # old token still within TTL

        # A second student scans the rotated token
        from tests.conftest import Enrollment
        from apps.academics.models import Enrollment as Enr
        Enr.objects.create(student=lecturer_user, course_offering=class_session.class_definition.course_offering)  # not a student; use another
        _put_token(session, cp, "tok-rot")
        result2 = validate_and_record_scan("tok-rot", enrolled_student)
        assert result2["success"] is False  # already attended
        assert result2["error_code"] == "ALREADY_ATTENDED"

    def test_expired_token_rejected_after_ttl(self, class_session, lecturer_user, enrolled_student):
        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(attendance_session=session, student=enrolled_student, checkpoint_number=1)
        _put_token(session, cp, "tok-exp")
        # Simulate TTL passing
        cache.delete(generate_token_key(str(session.id), "tok-exp"))
        cache.delete("att:token:tok-exp")
        result = validate_and_record_scan("tok-exp", enrolled_student)
        assert result["success"] is False
        assert result["error_code"] == "TOKEN_INVALID"

    def test_real_generated_token_is_scannable(self, class_session, lecturer_user, enrolled_student):
        """Regression: tokens from generate_tokens_for_session must validate
        end-to-end (reverse lookup key must be written)."""
        session = _setup_session(class_session, lecturer_user)
        AttendanceCheckpoint.objects.create(attendance_session=session, student=enrolled_student, checkpoint_number=1)
        batch = generate_tokens_for_session(session)
        result = validate_and_record_scan(batch["tokens"][0]["token"], enrolled_student)
        assert result["success"] is True, result

    def test_scan_rejected_after_window_closes(self, class_session, lecturer_user, enrolled_student):
        """Rotation continues only until the attendance time is up."""
        session = _setup_session(class_session, lecturer_user, seconds=1)
        cp = AttendanceCheckpoint.objects.create(attendance_session=session, student=enrolled_student, checkpoint_number=1)
        _put_token(session, cp, "tok-late")
        session.expires_at = timezone.now() - timedelta(seconds=1)
        session.save(update_fields=["expires_at"])
        result = validate_and_record_scan("tok-late", enrolled_student)
        assert result["success"] is False
        assert result["error_code"] == "SESSION_EXPIRED"


@pytest.mark.django_db
class TestAutoStationSelection:
    def test_auto_select_picks_from_students_verified_present_this_session(
        self, class_session, lecturer_user, enrolled_student, student2_user
    ):
        """FR-047 (reworked): auto stations come ONLY from students who have
        already checked in to THIS session."""
        session = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)
        AttendanceRecord.objects.create(attendance_session=session, student=student2_user)

        created = auto_select_stations(session, count=2)
        assert len(created) >= 1
        assert all(c.selection_method == AttendanceCheckpoint.SelectionMethod.AUTO for c in created)
        chosen_ids = {c.student_id for c in created}
        assert chosen_ids.issubset({enrolled_student.id, student2_user.id})

    def test_past_history_alone_does_not_qualify(self, class_session, lecturer_user, enrolled_student, student2_user):
        """The seat-of-the-pants case: a historically consistent student who
        has NOT checked in today can never be picked, no matter how strong
        their past record is."""
        session = _setup_session(class_session, lecturer_user)
        # enrolled_student has a stellar past record (3 prior attendances)...
        for _ in range(3):
            past = _setup_session(class_session, lecturer_user, seconds=1)
            past.expires_at = timezone.now() - timedelta(seconds=5)
            past.save(update_fields=["expires_at"])
            AttendanceRecord.objects.create(attendance_session=past, student=enrolled_student)
        # ...but today only student2 has checked in
        AttendanceRecord.objects.create(attendance_session=session, student=student2_user)

        created = auto_select_stations(session, count=3)
        assert created
        assert all(c.student_id == student2_user.id for c in created)

    def test_auto_select_capped_at_three_per_session(self, offering, class_session, lecturer_user, enrolled_student, student2_user, cs_department, db):
        """Only 3 auto-selected stations exist in the entire class per session."""
        from apps.academics.models import Enrollment
        from apps.accounts.models import StudentProfile, User as U

        students = [enrolled_student, student2_user]
        for i in range(6):
            s = U.objects.create_user(email=f"cap{i}@test.edu", password="pass1234", first_name=f"C{i}", last_name="T", role="STUDENT")
            StudentProfile.objects.create(user=s, student_number=f"CAP{i:03d}", department=cs_department)
            Enrollment.objects.create(student=s, course_offering=offering)
            students.append(s)

        session = _setup_session(class_session, lecturer_user)
        for s in students:
            AttendanceRecord.objects.create(attendance_session=session, student=s)

        first = auto_select_stations(session, count=5)  # ask for 5
        assert len(first) == 3  # hard cap at 3
        second = auto_select_stations(session, count=2)
        assert second == []
        assert session.checkpoints.filter(selection_method="AUTO").count() == 3

    def test_picked_students_receive_rules_notification(self, class_session, lecturer_user, enrolled_student):
        from apps.notifications.models import Notification
        session = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)

        created = auto_select_stations(session, count=1)
        assert created
        n = Notification.objects.filter(user=created[0].student, title__icontains="station").latest("created_at")
        assert "first 20" in n.message and "5 station points" in n.message and "4 pts" in n.message

    def test_auto_selected_station_is_present_and_paid_immediately(self, class_session, lecturer_user, enrolled_student):
        """Being picked as a station confirms attendance and pays 5 points
        right away - before any classmate scans the station QR."""
        session = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)

        created = auto_select_stations(session, count=1)
        assert created
        cp = created[0]
        assert AttendanceRecord.objects.filter(
            attendance_session=session, student=cp.student, status="PRESENT"
        ).exists()
        entry = PointsLedger.objects.get(student=cp.student, attendance_session=session)
        assert entry.category == "AUTO_STATION" and entry.points == POINTS["AUTO_STATION"] == 5

    def test_auto_station_upgrades_the_scan_entry_to_the_station_award(
        self, class_session, lecturer_user, enrolled_student
    ):
        """Auto stations must already have checked in, so they usually hold a
        SCAN ledger row. Being picked replaces that row with the 5-point
        station award instead of being skipped by the unique constraint."""
        session = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)
        PointsLedger.objects.create(
            student=enrolled_student, attendance_session=session,
            category="SCAN", points=POINTS["SCAN"],
        )

        created = auto_select_stations(session, count=1)
        assert created
        entries = PointsLedger.objects.filter(
            student=enrolled_student, attendance_session=session
        )
        assert entries.count() == 1
        entry = entries.get()
        assert entry.category == "AUTO_STATION"
        assert entry.points == POINTS["AUTO_STATION"] == 5

    def test_no_verified_present_students_returns_empty(self, class_session, lecturer_user, enrolled_student):
        """Past history does not count - nobody verified present this session."""
        session = _setup_session(class_session, lecturer_user)
        past = _setup_session(class_session, lecturer_user, seconds=1)
        past.expires_at = timezone.now() - timedelta(seconds=5)
        past.save(update_fields=["expires_at"])
        AttendanceRecord.objects.create(attendance_session=past, student=enrolled_student)

        assert auto_select_stations(session, count=3) == []


@pytest.mark.django_db
class TestAutoSelectView:
    def test_auto_select_blocked_until_minimum_attendance(
        self, offering, class_session, lecturer_user, student2_user, enrolled_student, api_client, cs_department, db
    ):
        """Auto-select requires ATTENDANCE_AUTO_MIN_VERIFIED students checked
        in first; below that the endpoint refuses with NOT_ENOUGH_ATTENDANCE."""
        from django.test import override_settings
        from apps.accounts.models import StudentProfile, User as U
        from apps.academics.models import Enrollment

        third = U.objects.create_user(email="third@test.edu", password="pass1234", first_name="Third", last_name="S", role="STUDENT")
        StudentProfile.objects.create(user=third, student_number="THR001", department=cs_department)
        Enrollment.objects.create(student=third, course_offering=offering)

        api_client.force_authenticate(user=lecturer_user)
        session = _setup_session(class_session, lecturer_user)

        with override_settings(ATTENDANCE_AUTO_MIN_VERIFIED=3):
            # Only 2 verified so far
            AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)
            AttendanceRecord.objects.create(attendance_session=session, student=student2_user)
            resp = api_client.post(f"/api/v1/attendance/{session.id}/checkpoints/auto-select/", {"count": 2}, format="json")
            assert resp.status_code == 400
            assert resp.data["error"]["code"] == "NOT_ENOUGH_ATTENDANCE"

            # Third student checks in -> now allowed
            AttendanceRecord.objects.create(attendance_session=session, student=third)
            resp = api_client.post(f"/api/v1/attendance/{session.id}/checkpoints/auto-select/", {"count": 2}, format="json")
            assert resp.status_code == 201
            assert resp.data["total_stations"] > 0
            assert session.checkpoints.filter(selection_method="AUTO").count() == 2


@pytest.mark.django_db
class TestTeacherStationAssignment:
    def test_teacher_selected_station_marked_present_and_awarded_immediately(
        self, class_session, lecturer_user, enrolled_student, api_client
    ):
        """Assigning a station from the roster confirms the student present
        and pays their 5 station points without waiting for a scan."""
        api_client.force_authenticate(user=lecturer_user)
        session = _setup_session(class_session, lecturer_user)

        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/checkpoints/",
            {"student_ids": [str(enrolled_student.id)]}, format="json",
        )
        assert resp.status_code == 201, resp.data

        record = AttendanceRecord.objects.get(attendance_session=session, student=enrolled_student)
        assert record.status == "PRESENT"
        assert record.verification_method == AttendanceRecord.VerificationMethod.QR_STATION
        entry = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        assert entry.category == "TEACHER_STATION" and entry.points == POINTS["TEACHER_STATION"] == 5


@pytest.mark.django_db
class TestStationScanLimits:
    def test_auto_station_serves_up_to_twenty_scanners(self, offering, class_session, lecturer_user, enrolled_student, cs_department, db):
        """Auto/scan stations: 20 scans; the 21st is rejected with
        STATION_FULL. Scanners earn 4 pts."""
        from apps.academics.models import Enrollment
        from apps.accounts.models import StudentProfile, User as U

        scanners = []
        for i in range(21):
            s = U.objects.create_user(email=f"scan{i}@test.edu", password="pass1234", first_name=f"S{i}", last_name="T", role="STUDENT")
            StudentProfile.objects.create(user=s, student_number=f"SCN{i:03d}", department=cs_department)
            Enrollment.objects.create(student=s, course_offering=offering)
            scanners.append(s)

        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.AUTO,
        )

        results = []
        for i, scanner in enumerate(scanners):
            _put_token(session, cp, f"tok-{i}")
            results.append(validate_and_record_scan(f"tok-{i}", scanner))

        assert all(r["success"] for r in results[:20])
        assert results[20]["success"] is False
        assert results[20]["error_code"] == "STATION_FULL"

        # The twenty successful scanners earned STATION_SCAN 4 pts
        for scanner in scanners[:20]:
            entry = PointsLedger.objects.get(student=scanner, attendance_session=session)
            assert entry.category == "STATION_SCAN" and entry.points == POINTS["STATION_SCAN"] == 4

        # Owner got their 5 points and a notification
        owner_entry = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        assert owner_entry.category == "AUTO_STATION"
        from apps.notifications.models import Notification
        assert Notification.objects.filter(user=enrolled_student, title__icontains="Station points locked in").exists()

    def test_teacher_selected_station_unlimited_scans(self, offering, class_session, lecturer_user, enrolled_student, cs_department, db):
        """Teacher-selected student stations have NO scan limit — only auto
        stations are capped at 20 scans."""
        from apps.academics.models import Enrollment
        from apps.accounts.models import StudentProfile, User as U

        scanners = []
        for i in range(6):
            s = U.objects.create_user(email=f"tscan{i}@test.edu", password="pass1234", first_name=f"T{i}", last_name="S", role="STUDENT")
            StudentProfile.objects.create(user=s, student_number=f"TSC{i:03d}", department=cs_department)
            Enrollment.objects.create(student=s, course_offering=offering)
            scanners.append(s)

        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.TEACHER,
        )

        # All 6 scans should succeed — no cap
        results = []
        for i, scanner in enumerate(scanners):
            _put_token(session, cp, f"ttok-{i}")
            results.append(validate_and_record_scan(f"ttok-{i}", scanner))

        assert all(r["success"] for r in results)
        # 6 scanner records + 1 station owner record (from award_station_points)
        assert AttendanceRecord.objects.filter(checkpoint=cp).count() == 7

        # All scanners earned station scan 4 pts
        for scanner in scanners:
            entry = PointsLedger.objects.get(student=scanner, attendance_session=session)
            assert entry.category == "STATION_SCAN" and entry.points == 4

        # Owner got 5 pts (same as an auto station)
        owner_entry = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        assert owner_entry.category == "TEACHER_STATION" and owner_entry.points == POINTS["TEACHER_STATION"]

    def test_projector_scans_unlimited_and_three_points(self, offering, class_session, lecturer_user, enrolled_student, cs_department, db):
        """Projector checkpoints (lecturer-owned) have no scan cap; scanners
        earn the regular 4 pts."""
        from apps.academics.models import Enrollment
        from apps.accounts.models import StudentProfile, User as U

        scanners = []
        for i in range(4):
            s = U.objects.create_user(email=f"proj{i}@test.edu", password="pass1234", first_name=f"P{i}", last_name="T", role="STUDENT")
            StudentProfile.objects.create(user=s, student_number=f"PRJ{i:03d}", department=cs_department)
            Enrollment.objects.create(student=s, course_offering=offering)
            scanners.append(s)

        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=lecturer_user, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.TEACHER,
        )
        for i, scanner in enumerate(scanners):
            _put_token(session, cp, f"ptok-{i}")
            r = validate_and_record_scan(f"ptok-{i}", scanner)
            assert r["success"] is True
            entry = PointsLedger.objects.get(student=scanner, attendance_session=session)
            assert entry.category == "SCAN" and entry.points == POINTS["SCAN"] == 4


@pytest.mark.django_db
class TestPoints:
    def test_scan_at_teacher_station_earns_four_and_notification(self, class_session, lecturer_user, enrolled_student, student2_user):
        """Scanning at a teacher-selected classmate's station: 4 pts + notification."""
        from apps.academics.models import Enrollment
        Enrollment.objects.create(student=student2_user, course_offering=class_session.class_definition.course_offering)
        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.TEACHER,
        )
        _put_token(session, cp, "tok-pts")
        result = validate_and_record_scan("tok-pts", student2_user)
        assert result["success"] is True
        ledger = PointsLedger.objects.get(student=student2_user, attendance_session=session)
        assert ledger.category == "STATION_SCAN" and ledger.points == POINTS["STATION_SCAN"] == 4
        from apps.notifications.models import Notification
        assert Notification.objects.filter(user=student2_user, type="ATTENDANCE").exists()

    def test_birthday_doubles_points(self, class_session, lecturer_user, enrolled_student):
        """Special day: every award is doubled."""
        enrolled_student.date_of_birth = timezone.localdate().replace(year=2000)
        enrolled_student.save(update_fields=["date_of_birth", "updated_at"])
        session = _setup_session(class_session, lecturer_user)
        award_scan_points(session, enrolled_student)
        ledger = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        assert ledger.points == POINTS["SCAN"] * 2  # 8 on birthday

    def test_auto_station_owner_gets_full_points_on_first_scan(self, class_session, lecturer_user, enrolled_student, student2_user):
        """Auto station: owner 5, scanner 4 (FR-048)."""
        from apps.academics.models import Enrollment
        Enrollment.objects.create(student=student2_user, course_offering=class_session.class_definition.course_offering)

        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.AUTO,
        )
        _put_token(session, cp, "tok-auto")
        assert validate_and_record_scan("tok-auto", student2_user)["success"] is True

        owner_points = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        scanner_points = PointsLedger.objects.get(student=student2_user, attendance_session=session)
        assert owner_points.category == "AUTO_STATION" and owner_points.points == POINTS["AUTO_STATION"]
        assert scanner_points.category == "STATION_SCAN" and scanner_points.points == POINTS["STATION_SCAN"]

    def test_teacher_station_owner_gets_same_points(self, class_session, lecturer_user, enrolled_student, student2_user):
        from apps.academics.models import Enrollment
        Enrollment.objects.create(student=student2_user, course_offering=class_session.class_definition.course_offering)

        session = _setup_session(class_session, lecturer_user)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
            selection_method=AttendanceCheckpoint.SelectionMethod.TEACHER,
        )
        _put_token(session, cp, "tok-teach")
        assert validate_and_record_scan("tok-teach", student2_user)["success"] is True

        owner_points = PointsLedger.objects.get(student=enrolled_student, attendance_session=session)
        assert owner_points.category == "TEACHER_STATION"
        assert owner_points.points == POINTS["TEACHER_STATION"] == POINTS["AUTO_STATION"]

    def test_manual_entry_zero_points(self, class_session, lecturer_user, enrolled_student):
        session = _setup_session(class_session, lecturer_user)
        pts = award_manual_points(session, enrolled_student)
        assert pts == 0
        assert PointsLedger.objects.get(student=enrolled_student, attendance_session=session).category == "MANUAL"

    def test_one_ledger_entry_per_student_per_session(self, class_session, lecturer_user, enrolled_student):
        session = _setup_session(class_session, lecturer_user)
        award_scan_points(session, enrolled_student)
        award_scan_points(session, enrolled_student)  # duplicate scan attempt
        assert PointsLedger.objects.filter(student=enrolled_student, attendance_session=session).count() == 1


@pytest.mark.django_db
class TestStudentOfClass:
    def test_picked_once_then_never_same_course(self, offering, class_session, lecturer_user, enrolled_student, student2_user):
        """Winner of a course is excluded from future picks in THAT course
        but stays eligible for other courses."""
        from apps.academics.models import Enrollment
        from apps.attendance.points import award_student_of_class

        Enrollment.objects.create(student=student2_user, course_offering=offering)
        session = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session, student=enrolled_student)
        AttendanceRecord.objects.create(attendance_session=session, student=student2_user)

        winner = award_student_of_class(session)
        assert winner is not None
        first_winner_id = winner.student_id

        # Next session of the SAME course: winner excluded, other student wins
        session2 = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=session2, student=enrolled_student)
        AttendanceRecord.objects.create(attendance_session=session2, student=student2_user)
        winner2 = award_student_of_class(session2)
        assert winner2.student_id != first_winner_id

        # Idempotent within the same session
        again = award_student_of_class(session)
        assert again.student_id == winner.student_id

    def test_eligible_for_other_course(self, offering, class_session, lecturer_user, enrolled_student, cs_department, academic_period):
        """Same student CAN win in a different course."""
        from apps.academics.models import ClassDefinition, ClassSession as CS, Course, CourseOffering, Enrollment
        from apps.attendance.points import award_student_of_class

        other_course = Course.objects.create(code="CSC999", title="Other Course", department=cs_department, credit_units=3)
        other_offering = CourseOffering.objects.create(course=other_course, semester=academic_period, department=cs_department, lecturer=lecturer_user)
        Enrollment.objects.create(student=enrolled_student, course_offering=other_offering)

        s1 = _setup_session(class_session, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=s1, student=enrolled_student)
        w1 = award_student_of_class(s1)
        assert w1.student_id == enrolled_student.id

        # Different course: still eligible and wins
        cd = ClassDefinition.objects.create(course_offering=other_offering, lecturer=lecturer_user, name="Other course class")
        real_cs = CS.objects.create(class_definition=cd, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(hours=2))
        s2 = _setup_session(real_cs, lecturer_user)
        AttendanceRecord.objects.create(attendance_session=s2, student=enrolled_student)
        w2 = award_student_of_class(s2)
        assert w2.student_id == enrolled_student.id

    def test_no_candidates_returns_none(self, class_session, lecturer_user):
        from apps.attendance.points import award_student_of_class
        session = _setup_session(class_session, lecturer_user)
        assert award_student_of_class(session) is None


@pytest.mark.django_db
class TestHeadcountAutoClose:
    def test_session_closes_when_headcount_reached(self, class_session, lecturer_user, enrolled_student, student2_user, offering):
        """When expected_headcount is set and reached, session auto-closes."""
        from apps.academics.models import Enrollment
        Enrollment.objects.create(student=student2_user, course_offering=offering)

        session = _setup_session(class_session, lecturer_user, seconds=600)
        session.expected_headcount = 2
        session.save(update_fields=["expected_headcount"])

        # First scan: headcount not reached yet
        cp1 = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
        )
        _put_token(session, cp1, "tok-hc-1")
        r1 = validate_and_record_scan("tok-hc-1", enrolled_student)
        assert r1["success"] is True
        session.refresh_from_db()
        assert session.status == "ACTIVE"
        assert session.headcount_reached_at is None

        # Second scan: headcount reached → session auto-closes
        cp2 = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=student2_user, checkpoint_number=2,
        )
        _put_token(session, cp2, "tok-hc-2")
        r2 = validate_and_record_scan("tok-hc-2", student2_user)
        assert r2["success"] is True
        session.refresh_from_db()
        assert session.status == "CLOSED"
        assert session.headcount_reached_at is not None

        # Lecturer got a notification
        from apps.notifications.models import Notification
        assert Notification.objects.filter(user=lecturer_user, title__icontains="Headcount reached").exists()

    def test_no_headcount_does_not_auto_close(self, class_session, lecturer_user, enrolled_student):
        """Without expected_headcount, session stays open regardless of scans."""
        session = _setup_session(class_session, lecturer_user, seconds=600)
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
        )
        _put_token(session, cp, "tok-nhc")
        validate_and_record_scan("tok-nhc", enrolled_student)
        session.refresh_from_db()
        assert session.status == "ACTIVE"
        assert session.headcount_reached_at is None

    def test_headcount_reached_notification_sent(self, class_session, lecturer_user, enrolled_student, offering):
        from apps.academics.models import Enrollment
        session = _setup_session(class_session, lecturer_user, seconds=600)
        session.expected_headcount = 1
        session.save(update_fields=["expected_headcount"])

        cp = AttendanceCheckpoint.objects.create(
            attendance_session=session, student=enrolled_student, checkpoint_number=1,
        )
        _put_token(session, cp, "tok-hcn")
        validate_and_record_scan("tok-hcn", enrolled_student)

        from apps.notifications.models import Notification
        n = Notification.objects.filter(user=lecturer_user, title__icontains="Headcount").latest("created_at")
        assert "1" in n.message


@pytest.mark.django_db
class TestManualStationSelection:
    """The lecturer picks which students act as QR stations (BR-050-053)."""

    def _enrol(self, offering, student):
        from apps.academics.models import Enrollment
        Enrollment.objects.get_or_create(student=student, course_offering=offering)

    def test_lecturer_assigns_students_by_id(self, api_client, class_session, lecturer_user, enrolled_student, student2_user, offering):
        from apps.academics.models import Enrollment
        Enrollment.objects.get_or_create(student=student2_user, course_offering=offering)
        session = _setup_session(class_session, lecturer_user, seconds=600)
        api_client.force_authenticate(user=lecturer_user)

        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/checkpoints/",
            {"student_ids": [str(enrolled_student.id), str(student2_user.id)]},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        numbers = sorted(c["checkpoint_number"] for c in resp.json()["data"])
        assert numbers == [1, 2]
        assert session.checkpoints.count() == 2

    def test_selecting_the_same_student_twice_is_safe(self, api_client, class_session, lecturer_user, enrolled_student, offering):
        session = _setup_session(class_session, lecturer_user, seconds=600)
        api_client.force_authenticate(user=lecturer_user)
        for _ in range(2):
            resp = api_client.post(
                f"/api/v1/attendance/{session.id}/checkpoints/",
                {"student_ids": [str(enrolled_student.id)]},
                format="json",
            )
            assert resp.status_code == 201
        assert session.checkpoints.count() == 1

    def test_unenrolled_student_is_rejected(self, api_client, class_session, lecturer_user, student2_user):
        session = _setup_session(class_session, lecturer_user, seconds=600)
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/checkpoints/",
            {"student_ids": [str(student2_user.id)]},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "NOT_ELIGIBLE"

    def test_other_lecturer_cannot_assign(self, api_client, class_session, lecturer_user, enrolled_student, db):
        from apps.accounts.models import User
        session = _setup_session(class_session, lecturer_user, seconds=600)
        intruder = User.objects.create_user(
            email="intruder@test.edu", password="test1234",
            first_name="In", last_name="Truder", role="LECTURER",
        )
        api_client.force_authenticate(user=intruder)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/checkpoints/",
            {"student_ids": [str(enrolled_student.id)]},
            format="json",
        )
        assert resp.status_code == 403

    def test_lecturer_can_remove_a_station_and_numbers_renumber(self, api_client, class_session, lecturer_user, enrolled_student, student2_user, offering):
        from apps.academics.models import Enrollment
        Enrollment.objects.get_or_create(student=student2_user, course_offering=offering)
        session = _setup_session(class_session, lecturer_user, seconds=600)
        api_client.force_authenticate(user=lecturer_user)
        created = api_client.post(
            f"/api/v1/attendance/{session.id}/checkpoints/",
            {"student_ids": [str(enrolled_student.id), str(student2_user.id)]},
            format="json",
        ).json()["data"]
        target = next(c for c in created if c["student"] == str(enrolled_student.id))

        resp = api_client.delete(f"/api/v1/attendance/{session.id}/checkpoints/{target['id']}/")
        assert resp.status_code == 204
        assert session.checkpoints.count() == 1
        assert session.checkpoints.first().checkpoint_number == 1  # renumbered

    def test_roster_includes_matricule_for_search(self, api_client, class_session, lecturer_user, enrolled_student):
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.get(f"/api/v1/class-sessions/{class_session.id}/eligible-students/")
        assert resp.status_code == 200
        row = next(r for r in resp.json()["data"] if r["id"] == str(enrolled_student.id))
        assert "student_number" in row
        assert row["student_number"] == "STU001"

    def test_student_cannot_read_the_roster(self, api_client, class_session, enrolled_student):
        api_client.force_authenticate(user=enrolled_student)
        resp = api_client.get(f"/api/v1/class-sessions/{class_session.id}/eligible-students/")
        assert resp.status_code == 403

    def test_delegated_lecturer_running_attendance_can_read_roster(
        self, api_client, class_session, enrolled_student, db
    ):
        """Whoever is running attendance needs the roster, class owner or not."""
        from apps.accounts.models import User

        runner = User.objects.create_user(
            email="delegate@test.edu", password="test1234",
            first_name="Del", last_name="Egated", role="LECTURER",
        )
        _setup_session(class_session, runner, seconds=600)
        api_client.force_authenticate(user=runner)
        resp = api_client.get(f"/api/v1/class-sessions/{class_session.id}/eligible-students/")
        assert resp.status_code == 200, resp.content
        assert len(resp.json()["data"]) > 0

    def test_lecturer_with_no_attendance_role_is_still_refused(
        self, api_client, class_session, db
    ):
        from apps.accounts.models import User

        bystander = User.objects.create_user(
            email="bystander@test.edu", password="test1234",
            first_name="By", last_name="Stander", role="LECTURER",
        )
        api_client.force_authenticate(user=bystander)
        resp = api_client.get(f"/api/v1/class-sessions/{class_session.id}/eligible-students/")
        assert resp.status_code == 403
