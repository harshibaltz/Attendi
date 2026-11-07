"""Registration rules: level eligibility, shared courses, and deadlines."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course, Department, Enrollment
from apps.academics.services import cohort_queryset
from apps.accounts.models import StudentProfile, User

pytestmark = pytest.mark.django_db


def _student(email, department, level):
    user = User.objects.create_user(
        email=email, password="test1234", first_name="Test", last_name="Student", role=User.Role.STUDENT
    )
    StudentProfile.objects.create(user=user, student_number=email.split("@")[0].upper(), department=department, level=level)
    return user


def _admin(email="admin@test.edu"):
    return User.objects.create_user(
        email=email, password="test1234", first_name="Sys", last_name="Admin", role=User.Role.SYSTEM_ADMIN
    )


def _activate(semester):
    semester.is_active = True
    semester.save(update_fields=["is_active"])
    return semester


def _offering_with_level(course, offering, level):
    course.level = level
    course.save(update_fields=["level"])
    return offering


def _register(user, offering):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.post(
        "/api/v1/students/me/register/", {"offering_ids": [str(offering.id)]}, format="json"
    )


def test_higher_level_student_can_see_and_register_lower_level_course(offering, course, academic_period, cs_department):
    _activate(academic_period)
    _offering_with_level(course, offering, "300")
    student = _student("level500@test.edu", cs_department, "500")

    client = APIClient()
    client.force_authenticate(user=student)
    listing = client.get("/api/v1/students/me/available-courses/")
    assert listing.status_code == 200, listing.content
    rows = {row["offering_id"]: row for row in listing.json()["data"]["courses"]}
    assert rows[str(offering.id)]["course_level"] == "300"
    assert rows[str(offering.id)]["registration_closed"] is False

    response = _register(student, offering)
    assert response.status_code == 201, response.content
    assert Enrollment.objects.filter(student=student, course_offering=offering, status="ACTIVE").exists()


def test_lower_level_student_cannot_register_higher_level_course(offering, course, academic_period, cs_department):
    _activate(academic_period)
    _offering_with_level(course, offering, "400")
    student = _student("level300@test.edu", cs_department, "300")

    client = APIClient()
    client.force_authenticate(user=student)
    listing = client.get("/api/v1/students/me/available-courses/")
    assert listing.json()["data"]["courses"] == []

    response = _register(student, offering)
    assert response.status_code == 200, response.content
    assert response.json()["data"]["registered_count"] == 0
    assert response.json()["data"]["errors"][0]["offering_id"] == str(offering.id)
    assert not Enrollment.objects.filter(student=student, course_offering=offering).exists()


def test_higher_level_student_can_register_lower_level_course_shared_by_their_department(
    offering, course, academic_period, cs_department, faculty
):
    _activate(academic_period)
    _offering_with_level(course, offering, "300")
    other = Department.objects.create(code="ME", name="Mechanical Engineering", faculty=faculty)
    offering.departments.add(other)
    student = _student("shared500@test.edu", other, "500")

    response = _register(student, offering)
    assert response.status_code == 201, response.content
    assert Enrollment.objects.filter(student=student, course_offering=offering, status="ACTIVE").exists()


def test_higher_level_student_cannot_register_unshared_other_department_course(offering, course, academic_period, faculty):
    _activate(academic_period)
    _offering_with_level(course, offering, "300")
    other = Department.objects.create(code="ME", name="Mechanical Engineering", faculty=faculty)
    student = _student("unshared500@test.edu", other, "500")

    response = _register(student, offering)
    assert response.status_code == 200, response.content
    assert response.json()["data"]["registered_count"] == 0


def test_registration_blocked_after_semester_deadline(offering, course, academic_period, cs_department):
    _activate(academic_period)
    _offering_with_level(course, offering, "300")
    academic_period.registration_deadline = timezone.localdate() - timedelta(days=1)
    academic_period.save(update_fields=["registration_deadline"])
    student = _student("late@test.edu", cs_department, "300")

    client = APIClient()
    client.force_authenticate(user=student)
    listing = client.get("/api/v1/students/me/available-courses/").json()["data"]
    assert listing["registration_closed"] is True
    assert listing["courses"][0]["registration_closed"] is True

    response = _register(student, offering)
    assert response.status_code == 200, response.content
    assert response.json()["data"]["registered_count"] == 0
    assert "closed" in response.json()["data"]["errors"][0]["error"].lower()
    assert not Enrollment.objects.filter(student=student, course_offering=offering).exists()


def test_offering_deadline_can_extend_or_close_registration(offering, course, academic_period, cs_department):
    _activate(academic_period)
    _offering_with_level(course, offering, "300")
    academic_period.registration_deadline = timezone.localdate() - timedelta(days=1)
    academic_period.save(update_fields=["registration_deadline"])
    offering.registration_deadline = timezone.localdate() + timedelta(days=7)
    offering.save(update_fields=["registration_deadline"])
    student = _student("extended@test.edu", cs_department, "300")

    assert _register(student, offering).json()["data"]["registered_count"] == 1

    offering.registration_deadline = timezone.localdate() - timedelta(days=1)
    offering.save(update_fields=["registration_deadline"])
    academic_period.registration_deadline = timezone.localdate() + timedelta(days=7)
    academic_period.save(update_fields=["registration_deadline"])
    student2 = _student("closed@test.edu", cs_department, "300")
    response = _register(student2, offering)
    assert response.json()["data"]["registered_count"] == 0
    assert "closed" in response.json()["data"]["errors"][0]["error"].lower()


def test_system_admin_can_set_semester_deadline(academic_period):
    deadline = (timezone.localdate() + timedelta(days=10)).isoformat()
    client = APIClient()
    client.force_authenticate(user=_admin())
    response = client.patch(
        reverse("semester-detail", kwargs={"semester_id": academic_period.id}),
        {"registration_deadline": deadline},
        format="json",
    )
    assert response.status_code == 200, response.content
    academic_period.refresh_from_db()
    assert academic_period.registration_deadline.isoformat() == deadline


def test_non_admin_cannot_set_semester_deadline(academic_period, student_user):
    client = APIClient()
    client.force_authenticate(user=student_user)
    response = client.patch(
        reverse("semester-detail", kwargs={"semester_id": academic_period.id}),
        {"registration_deadline": timezone.localdate().isoformat()},
        format="json",
    )
    assert response.status_code == 403


def test_admin_can_set_per_course_deadline(offering):
    deadline = (timezone.localdate() + timedelta(days=5)).isoformat()
    client = APIClient()
    client.force_authenticate(user=_admin())
    response = client.patch(
        reverse("offering-detail", kwargs={"offering_id": offering.id}),
        {"registration_deadline": deadline},
        format="json",
    )
    assert response.status_code == 200, response.content
    offering.refresh_from_db()
    assert offering.registration_deadline.isoformat() == deadline


def test_cohort_includes_higher_level_students_for_a_lower_level_course(offering, course, cs_department):
    _offering_with_level(course, offering, "300")
    higher = _student("cohort500@test.edu", cs_department, "500")
    lower = _student("cohort200@test.edu", cs_department, "200")

    ids = set(cohort_queryset(offering).values_list("id", flat=True))
    assert higher.id in ids
    assert lower.id not in ids
