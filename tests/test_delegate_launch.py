"""Delegates may launch attendance.

Two kinds of delegate:

  * class delegate - ``projects.ClassDelegate`` for one course offering,
  * departmental course delegate - ``Course.department_delegates`` M2M,
    covering every offering of the course.

Both are students, so they need the attendance launcher without being given
the lecturer role, and they must be able to operate the session they opened.
"""
import pytest

from apps.attendance.models import AttendanceSession
from apps.projects.models import ClassDelegate


@pytest.mark.django_db
class TestClassDelegate:
    def _appoint(self, offering, student, by=None):
        return ClassDelegate.objects.create(
            course_offering=offering, student=student, appointed_by=by
        )

    def test_class_delegate_can_start_attendance(
        self, api_client, offering, enrolled_student
    ):
        self._appoint(offering, enrolled_student)
        api_client.force_authenticate(user=enrolled_student)
        resp = api_client.post(
            "/api/v1/attendance/start-flex/",
            {"offering_id": str(offering.id), "mode": "PROJECTOR", "duration_seconds": 300},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        session = AttendanceSession.objects.get(id=resp.json()["data"]["id"])
        assert session.lecturer_id == enrolled_student.id

    def test_class_delegate_can_start_scheduled_class(
        self, api_client, offering, class_session, enrolled_student
    ):
        self._appoint(offering, enrolled_student)
        api_client.force_authenticate(user=enrolled_student)
        resp = api_client.post(
            f"/api/v1/class-sessions/{class_session.id}/attendance/",
            {"duration_seconds": 300},
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_delegate_can_operate_own_session(
        self, api_client, offering, enrolled_student
    ):
        self._appoint(offering, enrolled_student)
        api_client.force_authenticate(user=enrolled_student)
        started = api_client.post(
            "/api/v1/attendance/start-flex/",
            {"offering_id": str(offering.id), "mode": "PROJECTOR"},
            format="json",
        )
        sid = started.json()["data"]["id"]

        tokens = api_client.post(f"/api/v1/attendance/{sid}/tokens/")
        assert tokens.status_code == 200, tokens.content

        roster = api_client.get(
            f"/api/v1/class-sessions/{started.json()['data']['class_session_id']}/eligible-students/"
        )
        assert roster.status_code == 200, roster.content

        close = api_client.post(f"/api/v1/attendance/{sid}/close/")
        assert close.status_code == 200, close.content

    def test_unrelated_student_cannot_start(self, api_client, offering, student2_user):
        api_client.force_authenticate(user=student2_user)
        resp = api_client.post(
            "/api/v1/attendance/start-flex/",
            {"offering_id": str(offering.id), "mode": "PROJECTOR"},
            format="json",
        )
        assert resp.status_code == 403

    def test_launchable_courses_and_me_flags(
        self, api_client, offering, enrolled_student
    ):
        self._appoint(offering, enrolled_student)
        api_client.force_authenticate(user=enrolled_student)

        resp = api_client.get("/api/v1/attendance/launchable-courses/")
        assert resp.status_code == 200, resp.content
        courses = resp.json()["data"]
        assert [c["offering_id"] for c in courses] == [str(offering.id)]
        assert courses[0]["course_code"] == "CSC301"

        me = api_client.get("/api/v1/auth/me/")
        assert me.status_code == 200, me.content
        delegations = me.json()["data"]["delegations"]
        assert delegations["is_class_delegate"] is True
        assert delegations["can_launch_attendance"] is True
        assert str(offering.id) in delegations["offering_ids"]

    def test_my_courses_flags(self, api_client, academic_period, offering, enrolled_student):
        academic_period.is_active = True
        academic_period.save(update_fields=["is_active"])
        self._appoint(offering, enrolled_student)
        api_client.force_authenticate(user=enrolled_student)

        resp = api_client.get("/api/v1/students/me/courses/")
        assert resp.status_code == 200, resp.content
        courses = resp.json()["data"]
        assert courses[0]["is_class_delegate"] is True
        assert courses[0]["can_launch_attendance"] is True


@pytest.mark.django_db
class TestDepartmentDelegate:
    def test_department_delegate_can_start_without_enrollment(
        self, api_client, course, offering, student2_user
    ):
        course.department_delegates.add(student2_user)
        api_client.force_authenticate(user=student2_user)
        resp = api_client.post(
            "/api/v1/attendance/start-flex/",
            {"offering_id": str(offering.id), "mode": "PROJECTOR"},
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_department_delegate_sees_launchable_course(
        self, api_client, course, offering, student2_user
    ):
        course.department_delegates.add(student2_user)
        api_client.force_authenticate(user=student2_user)
        resp = api_client.get("/api/v1/attendance/launchable-courses/")
        assert resp.status_code == 200, resp.content
        assert str(offering.id) in [c["offering_id"] for c in resp.json()["data"]]

    def test_appointment_endpoint_requires_privilege(
        self, api_client, course, offering, lecturer_user, student2_user
    ):
        offering.lecturer = lecturer_user
        offering.save(update_fields=["lecturer"])
        api_client.force_authenticate(user=student2_user)
        resp = api_client.get(f"/api/v1/courses/{course.id}/department-delegates/")
        assert resp.status_code == 403

    def test_lecturer_can_appoint_and_remove_delegates(
        self, api_client, course, offering, lecturer_user, enrolled_student, student2_user
    ):
        offering.lecturer = lecturer_user
        offering.save(update_fields=["lecturer"])
        api_client.force_authenticate(user=lecturer_user)

        resp = api_client.get(f"/api/v1/courses/{course.id}/department-delegates/")
        assert resp.status_code == 200, resp.content
        candidate_ids = [c["id"] for c in resp.json()["data"]["candidates"]]
        assert str(enrolled_student.id) in candidate_ids

        resp = api_client.post(
            f"/api/v1/courses/{course.id}/department-delegates/",
            {"student_ids": [str(enrolled_student.id)]},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert [d["id"] for d in resp.json()["data"]["delegates"]] == [str(enrolled_student.id)]

        # Reloading the page must show the same appointed student.
        reloaded = api_client.get(f"/api/v1/courses/{course.id}/department-delegates/")
        assert reloaded.status_code == 200, reloaded.content
        assert [d["id"] for d in reloaded.json()["data"]["delegates"]] == [str(enrolled_student.id)]

        # Clearing the list removes the delegation again.
        resp = api_client.post(
            f"/api/v1/courses/{course.id}/department-delegates/",
            {"student_ids": []},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["data"]["delegates"] == []

    def test_invalid_student_id_is_a_clean_400(
        self, api_client, course, offering, lecturer_user
    ):
        offering.lecturer = lecturer_user
        offering.save(update_fields=["lecturer"])
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/courses/{course.id}/department-delegates/",
            {"student_ids": ["not-a-uuid"]},
            format="json",
        )
        assert resp.status_code == 400

    def test_cannot_appoint_student_outside_the_course(
        self, api_client, course, offering, lecturer_user, student2_user
    ):
        offering.lecturer = lecturer_user
        offering.save(update_fields=["lecturer"])
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            f"/api/v1/courses/{course.id}/department-delegates/",
            {"student_ids": [str(student2_user.id)]},
            format="json",
        )
        assert resp.status_code == 400
        assert course.department_delegates.count() == 0


@pytest.mark.django_db
class TestLecturerUnchanged:
    def test_offering_lecturer_can_still_start(self, api_client, offering, lecturer_user):
        offering.lecturer = lecturer_user
        offering.save(update_fields=["lecturer"])
        api_client.force_authenticate(user=lecturer_user)
        resp = api_client.post(
            "/api/v1/attendance/start-flex/",
            {"offering_id": str(offering.id), "mode": "PROJECTOR"},
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_non_delegate_student_sees_no_delegation(
        self, api_client, student2_user
    ):
        api_client.force_authenticate(user=student2_user)
        me = api_client.get("/api/v1/auth/me/")
        assert me.status_code == 200, me.content
        delegations = me.json()["data"]["delegations"]
        assert delegations["can_launch_attendance"] is False
        assert delegations["offering_ids"] == []
