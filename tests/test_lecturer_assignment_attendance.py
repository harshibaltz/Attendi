"""Assigning a lecturer hands them the course and lets them run attendance,
whether or not the offering sits in the currently active semester. The roster
is not auto-enrolled: students register themselves.

These guard the flow: admin assigns -> lecturer sees classroom -> student
registers -> start-flex -> student scans.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import StudentProfile, User
from apps.academics.models import Enrollment, Semester
from apps.attendance.models import AttendanceRecord


@pytest.fixture
def system_admin(db):
    return User.objects.create_user(
        email="assign.admin@test.edu",
        password="test1234",
        first_name="Sys",
        last_name="Admin",
        role="SYSTEM_ADMIN",
        is_staff=True,
    )


@pytest.fixture
def other_semester(db):
    """A second semester that we make active, so the offering's own semester is
    NOT the active one."""
    semester = Semester.objects.create(
        name="2027/2028 Semester 1",
        academic_year="2027/2028",
        number="1",
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timedelta(days=120),
    )
    semester.is_active = True
    semester.save()
    return semester


@pytest.mark.django_db
def test_assigned_lecturer_sees_offering_from_non_active_semester(
    api_client, offering, lecturer_user, system_admin, other_semester
):
    """Regression: the active-semester filter used to hide an offering the admin
    had just assigned, leaving the lecturer with an empty classroom list."""
    assert offering.semester != other_semester

    api_client.force_authenticate(user=system_admin)
    resp = api_client.patch(
        f"/api/v1/course-offerings/{offering.id}/",
        {"lecturer": str(lecturer_user.id)},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    api_client.force_authenticate(user=lecturer_user)
    resp = api_client.get("/api/v1/lecturers/me/courses/")
    assert resp.status_code == 200, resp.content
    courses = resp.json()["data"]
    assert any(c["offering_id"] == str(offering.id) for c in courses), courses


@pytest.mark.django_db
def test_assigning_lecturer_does_not_enroll_the_cohort(
    api_client, offering, lecturer_user, student_user, system_admin
):
    """Assignment only hands over the classroom; students choose to register."""
    assert not Enrollment.objects.filter(course_offering=offering).exists()

    api_client.force_authenticate(user=system_admin)
    resp = api_client.patch(
        f"/api/v1/course-offerings/{offering.id}/",
        {"lecturer": str(lecturer_user.id)},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    assert not Enrollment.objects.filter(course_offering=offering).exists()


@pytest.mark.django_db
def test_reassigning_lecturer_does_not_reset_existing_enrollments(
    api_client, offering, lecturer_user, student_user, system_admin
):
    """Idempotent: a second assignment must not wipe or duplicate enrollments."""
    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )

    api_client.force_authenticate(user=system_admin)
    resp = api_client.patch(
        f"/api/v1/course-offerings/{offering.id}/",
        {"lecturer": str(lecturer_user.id)},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    assert Enrollment.objects.filter(course_offering=offering).count() == 1


@pytest.mark.django_db
def test_assigned_lecturer_can_run_attendance_in_non_active_semester(
    api_client, offering, lecturer_user, student_user, system_admin, other_semester
):
    api_client.force_authenticate(user=system_admin)
    api_client.patch(
        f"/api/v1/course-offerings/{offering.id}/",
        {"lecturer": str(lecturer_user.id)},
        format="json",
    )

    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )

    api_client.force_authenticate(user=lecturer_user)
    resp = api_client.post(
        "/api/v1/attendance/start-flex/",
        {"offering_id": str(offering.id), "mode": "PROJECTOR", "duration_seconds": 300},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()["data"]
    session_id = body["id"]
    assert body["eligible_students"] >= 1

    resp = api_client.post(f"/api/v1/attendance/{session_id}/tokens/")
    assert resp.status_code == 200, resp.content
    token = resp.json()["data"]["tokens"][0]["token"]

    api_client.force_authenticate(user=student_user)
    resp = api_client.post("/api/v1/attendance/scan/", {"token": token}, format="json")
    assert resp.status_code == 201, resp.content

    assert AttendanceRecord.objects.filter(
        attendance_session_id=session_id, student=student_user
    ).exists()


@pytest.mark.django_db
def test_starting_attendance_does_not_prime_an_unprimed_offering(
    api_client, offering, lecturer_user, student_user
):
    """An empty classroom stays empty until students register themselves."""
    offering.lecturer = lecturer_user
    offering.save(update_fields=["lecturer"])
    assert not Enrollment.objects.filter(course_offering=offering).exists()

    api_client.force_authenticate(user=lecturer_user)
    resp = api_client.post(
        "/api/v1/attendance/start-flex/",
        {"offering_id": str(offering.id), "mode": "PROJECTOR", "duration_seconds": 300},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["data"]["eligible_students"] == 0
    assert not Enrollment.objects.filter(course_offering=offering).exists()


@pytest.mark.django_db
def test_starting_attendance_does_not_touch_a_populated_offering(
    api_client, offering, lecturer_user, student_user, student2_user
):
    offering.lecturer = lecturer_user
    offering.save(update_fields=["lecturer"])
    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )

    api_client.force_authenticate(user=lecturer_user)
    resp = api_client.post(
        "/api/v1/attendance/start-flex/",
        {"offering_id": str(offering.id), "mode": "PROJECTOR", "duration_seconds": 300},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["data"]["eligible_students"] == 1
    assert not Enrollment.objects.filter(
        course_offering=offering, student=student2_user
    ).exists()


@pytest.mark.django_db
def test_assignment_skips_enrollment_when_offering_already_has_students(
    api_client, offering, lecturer_user, student_user, student2_user, system_admin
):
    """If the offering already has a roster (e.g. real registrations), assigning a
    lecturer must not bulk-add the whole cohort over it."""
    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )

    api_client.force_authenticate(user=system_admin)
    api_client.patch(
        f"/api/v1/course-offerings/{offering.id}/",
        {"lecturer": str(lecturer_user.id)},
        format="json",
    )

    assert not Enrollment.objects.filter(
        course_offering=offering, student=student2_user
    ).exists()
