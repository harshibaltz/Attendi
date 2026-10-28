"""Tests for batch manual attendance.

POST /api/v1/attendance/{attendance_session_id}/manual/batch/
  {student_ids: [...], status?}

The lecturer can add up to 15 students in one request. Non-enrolled or
already-recorded students are skipped and reported, not fatal.
"""
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.academics.models import Enrollment
from apps.accounts.models import StudentProfile, User
from apps.attendance.models import AttendanceRecord, AttendanceSession, PointsLedger


def _student(index, department):
    user = User.objects.create_user(
        email=f"batch{index}@test.edu",
        password="test1234",
        first_name="Batch",
        last_name=f"Student{index}",
        role="STUDENT",
    )
    StudentProfile.objects.create(
        user=user, student_number=f"BAT{index:03d}", department=department
    )
    return user


def _enroll(students, offering):
    for student in students:
        Enrollment.objects.create(
            student=student, course_offering=offering, status=Enrollment.Status.ACTIVE
        )
    return students


@pytest.mark.django_db
class TestManualAttendanceBatch:
    def _session(self, class_session, lecturer_user):
        now = timezone.now()
        return AttendanceSession.objects.create(
            class_session=class_session,
            lecturer=lecturer_user,
            started_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(minutes=5),
        )

    def test_adds_fifteen_students_in_one_request(
        self, api_client, class_session, lecturer_user, offering, cs_department
    ):
        session = self._session(class_session, lecturer_user)
        students = _enroll([_student(i, cs_department) for i in range(15)], offering)

        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(s.id) for s in students], "status": "LATE"},
            format="json",
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["count"] == 15
        assert body["skipped"] == []
        assert len(body["created"]) == 15

        records = AttendanceRecord.objects.filter(attendance_session=session)
        assert records.count() == 15
        assert set(records.values_list("status", flat=True)) == {"LATE"}
        assert set(records.values_list("verification_method", flat=True)) == {"MANUAL"}

        ledgers = PointsLedger.objects.filter(attendance_session=session)
        assert ledgers.count() == 15
        assert set(ledgers.values_list("points", flat=True)) == {0}

    def test_skips_students_already_recorded(
        self, api_client, class_session, lecturer_user, offering, cs_department
    ):
        session = self._session(class_session, lecturer_user)
        first, second = _enroll([_student(1, cs_department), _student(2, cs_department)], offering)
        AttendanceRecord.objects.create(
            attendance_session=session, student=first, status="PRESENT"
        )

        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(first.id), str(second.id)]},
            format="json",
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["count"] == 1
        assert body["skipped"] == [
            {"student_id": str(first.id), "reason": "ALREADY_RECORDED"}
        ]
        assert AttendanceRecord.objects.filter(attendance_session=session).count() == 2

    def test_skips_students_not_enrolled(
        self, api_client, class_session, lecturer_user, offering, cs_department
    ):
        session = self._session(class_session, lecturer_user)
        enrolled = _enroll([_student(1, cs_department)], offering)
        outsider = _student(99, cs_department)

        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(enrolled[0].id), str(outsider.id)]},
            format="json",
        )

        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["count"] == 1
        assert body["skipped"] == [
            {"student_id": str(outsider.id), "reason": "NOT_ENROLLED"}
        ]

    def test_rejects_more_than_fifteen(
        self, api_client, class_session, lecturer_user
    ):
        session = self._session(class_session, lecturer_user)
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(uuid.uuid4()) for _ in range(16)]},
            format="json",
        )

        assert resp.status_code == 400
        assert "15" in resp.json()["error"]["message"]

    def test_rejects_empty_selection(self, api_client, class_session, lecturer_user):
        session = self._session(class_session, lecturer_user)
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": []},
            format="json",
        )

        assert resp.status_code == 400

    def test_other_lecturer_is_forbidden(
        self, api_client, class_session, lecturer_user, offering, cs_department
    ):
        session = self._session(class_session, lecturer_user)
        student = _enroll([_student(1, cs_department)], offering)[0]
        stranger = User.objects.create_user(
            email="batch-stranger@test.edu", password="test1234", role="LECTURER"
        )

        api_client.force_authenticate(user=stranger)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(student.id)]},
            format="json",
        )

        assert resp.status_code == 403
        assert not AttendanceRecord.objects.filter(attendance_session=session).exists()

    def test_requires_authentication(self, api_client, class_session, lecturer_user):
        session = self._session(class_session, lecturer_user)
        resp = api_client.post(
            f"/api/v1/attendance/{session.id}/manual/batch/",
            {"student_ids": [str(uuid.uuid4())]},
            format="json",
        )

        assert resp.status_code in (401, 403)
