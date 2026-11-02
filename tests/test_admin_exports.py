"""CSV exports for the admin directory and the course catalogue."""
import csv
import io

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.models import Course, Department, Enrollment
from apps.accounts.models import StudentProfile, User

pytestmark = pytest.mark.django_db


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _admin(email="admin@test.edu"):
    return User.objects.create_user(
        email=email, password="test1234", first_name="Sys", last_name="Admin", role=User.Role.SYSTEM_ADMIN
    )


def _rows(resp):
    text = resp.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_user_export_lists_every_state(student_user, student2_user):
    User.objects.filter(pk=student2_user.pk).update(status=User.Status.SUSPENDED, is_active=False)
    resp = _client(_admin()).get(reverse("user-export"))

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment;" in resp["Content-Disposition"]
    assert resp.content.startswith("\ufeff".encode())

    rows = {row["Email"]: row for row in _rows(resp)}
    assert rows["student@test.edu"]["Account status"] == "ACTIVE"
    assert rows["student@test.edu"]["Is active"] == "Yes"
    assert rows["student@test.edu"]["Matricule"] == "STU001"
    assert rows["student@test.edu"]["Department"] == "Computer Science"
    assert rows["student2@test.edu"]["Account status"] == "SUSPENDED"
    assert rows["student2@test.edu"]["Is active"] == "No"


def test_user_export_respects_search_and_role_filters(student_user, lecturer_user):
    client = _client(_admin())
    resp = client.get(reverse("user-export"), {"search": "STU001"})
    assert [row["Email"] for row in _rows(resp)] == ["student@test.edu"]

    resp = client.get(reverse("user-export"), {"role": "LECTURER"})
    assert [row["Email"] for row in _rows(resp)] == ["lecturer@test.edu"]


def test_user_export_scoped_to_admin_department(student_user, cs_department, faculty):
    other = Department.objects.create(code="EE", name="Electrical Engineering", faculty=faculty)
    outsider = User.objects.create_user(
        email="outsider@test.edu", password="test1234", first_name="Out", last_name="Sider", role=User.Role.STUDENT
    )
    StudentProfile.objects.create(user=outsider, student_number="EE001", department=other)
    dept_admin = User.objects.create_user(
        email="deptadmin@test.edu", password="test1234", first_name="Dept", last_name="Admin",
        role=User.Role.DEPARTMENT_ADMIN, admin_department=cs_department,
    )

    rows = _rows(_client(dept_admin).get(reverse("user-export")))
    emails = {row["Email"] for row in rows}
    assert "student@test.edu" in emails
    assert "outsider@test.edu" not in emails


def test_user_export_forbidden_for_non_admins(student_user):
    assert _client(student_user).get(reverse("user-export")).status_code == 403


def test_course_export_includes_usage_counts(course, offering, enrolled_student):
    resp = _client(_admin()).get(reverse("course-export"))

    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    rows = _rows(resp)
    assert len(rows) == 1
    row = rows[0]
    assert row["Course code"] == "CSC301"
    assert row["Course title"] == "Database Systems"
    assert row["Department"] == "Computer Science"
    assert row["Faculty"] == "Faculty of Engineering and Technology"
    assert row["Offerings"] == "1"
    assert row["Active enrolments"] == "1"


def test_course_export_scoped_to_admin_department(course, cs_department, faculty):
    other = Department.objects.create(code="EE", name="Electrical Engineering", faculty=faculty)
    Course.objects.create(code="EEE201", title="Circuits", department=other)
    dept_admin = User.objects.create_user(
        email="deptadmin@test.edu", password="test1234", first_name="Dept", last_name="Admin",
        role=User.Role.DEPARTMENT_ADMIN, admin_department=cs_department,
    )

    rows = _rows(_client(dept_admin).get(reverse("course-export")))
    assert [row["Course code"] for row in rows] == ["CSC301"]


def test_course_export_forbidden_for_non_admins(student_user):
    assert _client(student_user).get(reverse("course-export")).status_code == 403
