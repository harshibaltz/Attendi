"""Self-service edits for institutional email and registration numbers."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import LecturerProfile, StudentProfile, User

pytestmark = pytest.mark.django_db
PASSWORD = "test1234"


def _student(email="student@test.edu", number="STU001"):
    user = User.objects.create_user(
        email=email, password=PASSWORD, first_name="Test", last_name="Student", role=User.Role.STUDENT
    )
    StudentProfile.objects.create(user=user, student_number=number)
    return user


def _lecturer(email="lecturer@test.edu", number="STAFF001"):
    user = User.objects.create_user(
        email=email, password=PASSWORD, first_name="Test", last_name="Lecturer", role=User.Role.LECTURER
    )
    LecturerProfile.objects.create(user=user, staff_number=number)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_student_can_change_email_and_matricule_and_log_in_with_them():
    user = _student()
    resp = _client(user).patch(
        "/api/v1/auth/me/",
        {"email": "new.student@student.ubuea.cm", "student_number": "FE25A123"},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    user.refresh_from_db()
    assert user.email == "new.student@student.ubuea.cm"
    assert user.student_profile.student_number == "FE25A123"

    anon = APIClient()
    old_email = anon.post(
        "/api/v1/auth/login/",
        {"email": "student@test.edu", "password": PASSWORD},
        format="json",
    )
    assert old_email.status_code == 401
    by_email = anon.post(
        "/api/v1/auth/login/",
        {"email": "new.student@student.ubuea.cm", "password": PASSWORD},
        format="json",
    )
    assert by_email.status_code == 200
    by_matricule = anon.post(
        "/api/v1/auth/login/",
        {"matricule": "FE25A123", "password": PASSWORD},
        format="json",
    )
    assert by_matricule.status_code == 200


def test_lecturer_can_change_staff_number():
    user = _lecturer()
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"staff_number": "STAFF999"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.lecturer_profile.staff_number == "STAFF999"


def test_duplicate_email_is_rejected_case_insensitively():
    user = _student()
    User.objects.create_user(
        email="taken@test.edu", password=PASSWORD, first_name="Other", last_name="User"
    )
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"email": "TAKEN@test.edu"}, format="json"
    )
    assert resp.status_code == 400
    assert "email" in resp.json()["error"]["details"]
    user.refresh_from_db()
    assert user.email == "student@test.edu"


def test_duplicate_matricule_is_rejected_case_insensitively():
    user = _student()
    other = _student(email="other@test.edu", number="STU002")
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"student_number": "stu002"}, format="json"
    )
    assert resp.status_code == 400
    assert "student_number" in resp.json()["error"]["details"]
    user.refresh_from_db()
    assert user.student_profile.student_number == "STU001"
    other.refresh_from_db()
    assert other.student_profile.student_number == "STU002"


def test_student_cannot_set_staff_number():
    user = _student()
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"staff_number": "STAFF999"}, format="json"
    )
    assert resp.status_code == 400
    assert "staff_number" in resp.json()["error"]["details"]


def test_lecturer_cannot_set_matricule():
    user = _lecturer()
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"student_number": "FE25A123"}, format="json"
    )
    assert resp.status_code == 400
    assert "student_number" in resp.json()["error"]["details"]


def test_email_and_matricule_must_not_be_blank():
    user = _student()
    client = _client(user)
    for field in ("email", "student_number"):
        resp = client.patch("/api/v1/auth/me/", {field: "   "}, format="json")
        assert resp.status_code == 400, field


def test_student_can_change_level():
    user = _student()
    resp = _client(user).patch("/api/v1/auth/me/", {"level": "500"}, format="json")
    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.student_profile.level == "500"


def test_student_level_must_be_supported():
    user = _student()
    resp = _client(user).patch("/api/v1/auth/me/", {"level": "600"}, format="json")
    assert resp.status_code == 400
    assert "level" in resp.json()["error"]["details"]
    user.refresh_from_db()
    assert user.student_profile.level != "600"


def test_student_can_change_name():
    user = _student()
    resp = _client(user).patch(
        "/api/v1/auth/me/", {"first_name": "Ada", "last_name": "Lovelace"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    user.refresh_from_db()
    assert user.first_name == "Ada"
    assert user.last_name == "Lovelace"
