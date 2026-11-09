"""Tests for authentication flow."""
import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import StudentProfile, User
from apps.academics.models import Department, Faculty


@pytest.mark.django_db
class TestAuth:
    def test_register_is_admin_only(self):
        """BR-002: public self-registration is disabled."""
        client = Client()
        resp = client.post(
            reverse("auth-register"),
            data={"email": "new@test.edu", "password": "secure1234", "first_name": "New", "last_name": "User"},
            content_type="application/json",
        )
        assert resp.status_code == 401
        assert not User.objects.filter(email="new@test.edu").exists()

    def test_register_duplicate_email(self):
        User.objects.create_user(email="dup@test.edu", password="test1234", first_name="A", last_name="B")
        admin = User.objects.create_user(email="adm@test.edu", password="test1234", first_name="A", last_name="D", role="SYSTEM_ADMIN")
        client = Client()
        client.force_login(admin)
        resp = client.post(
            reverse("auth-register"),
            data={"email": "dup@test.edu", "password": "test1234", "first_name": "C", "last_name": "D"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_login_success(self):
        User.objects.create_user(email="login@test.edu", password="pass1234", first_name="A", last_name="B")
        client = Client()
        resp = client.post(
            reverse("auth-login"),
            data={"email": "login@test.edu", "password": "pass1234"},
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_login_ignores_access_cookie_for_deleted_account(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework.test import APIClient

        stale_user = User.objects.create_user(email="deleted@test.edu", password="pass1234")
        stale_access = str(RefreshToken.for_user(stale_user).access_token)
        stale_user.delete()
        target = User.objects.create_user(email="target@test.edu", password="pass1234")

        client = APIClient()
        client.cookies["fet_access"] = stale_access
        response = client.post(
            reverse("auth-login"),
            {"email": target.email, "password": "pass1234"},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json()["data"]["email"] == target.email

    def test_login_sets_httponly_cookies_not_body_tokens(self):
        """Security: JWTs are httpOnly-cookie-only. Never serialized in the body."""
        User.objects.create_user(email="secure@test.edu", password="pass1234", first_name="A", last_name="B")
        from rest_framework.test import APIClient

        client = APIClient()
        resp = client.post(
            reverse("auth-login"),
            {"email": "secure@test.edu", "password": "pass1234"},
            format="json",
        )
        assert resp.status_code == 200
        body = resp.json()
        # No JWT material in the body
        assert "tokens" not in body
        assert "access" not in body
        assert "refresh" not in body
        # Access + refresh set as cookies
        assert resp.cookies.get("fet_access") is not None
        assert resp.cookies.get("fet_refresh") is not None
        # The access cookie is httpOnly (not readable from JS)
        assert resp.cookies["fet_access"]["httponly"] is True

    def test_me_works_with_access_cookie(self):
        """CookieJWT auth: /me succeeds using only the httpOnly access cookie."""
        user = User.objects.create_user(email="cookie@test.edu", password="pass1234", first_name="A", last_name="B")
        from rest_framework.test import APIClient

        client = APIClient()
        login = client.post(reverse("auth-login"), {"email": "cookie@test.edu", "password": "pass1234"}, format="json")
        assert login.status_code == 200
        me = client.get(reverse("auth-me"))
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "cookie@test.edu"

    def test_login_wrong_password(self):
        User.objects.create_user(email="login2@test.edu", password="pass1234", first_name="A", last_name="B")
        client = Client()
        resp = client.post(
            reverse("auth-login"),
            data={"email": "login2@test.edu", "password": "wrong"},
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_me_requires_auth(self):
        client = Client()
        resp = client.get(reverse("auth-me"))
        assert resp.status_code == 401

    def test_self_register_student_saves_level(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "student@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "New",
                "last_name": "Student",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026TST01",
                "level": "300",
                "personal_email": "student.personal@gmail.com",
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        user = User.objects.get(email="student@student.ubuea.cm")
        assert user.role == "STUDENT"
        assert user.student_profile.student_number == "2026TST01"
        assert user.student_profile.department == dept
        assert user.student_profile.level == "300"

    def test_self_register_accepts_a_single_name_without_a_placeholder_surname(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CS", name="Computer Science")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "solo@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "Solo",
                "last_name": "",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026SOLO1",
                "level": "300",
                "personal_email": "solo.personal@gmail.com",
            },
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.content
        user = User.objects.get(email="solo@student.ubuea.cm")
        assert user.first_name == "Solo"
        assert user.last_name == ""
        assert user.get_full_name() == "Solo"

    def test_self_register_duplicate_matricule_returns_field_message(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        existing = User.objects.create_user(
            email="existing@student.ubuea.cm", password="pass12345", first_name="Old", last_name="Student",
            role="STUDENT",
        )
        StudentProfile.objects.create(
            user=existing, student_number="2026TST01", department=dept, level="300",
        )
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "another@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "Another",
                "last_name": "Student",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026tst01",
                "level": "300",
                "personal_email": "another.personal@gmail.com",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        message = body["error"]["details"]["matricule"][0]
        assert "matricule already has an account" in message

    def test_self_register_rejects_invalid_level(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "badlevel@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "New",
                "last_name": "Student",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026TST02",
                "level": "100",
                "personal_email": "badlevel.personal@gmail.com",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert not User.objects.filter(email="badlevel@student.ubuea.cm").exists()

    def test_self_register_lecturer_with_any_email(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "dr.teacher@gmail.com",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "Dr",
                "last_name": "Teacher",
                "department": str(dept.id),
                "role": "LECTURER",
                "staff_number": "STF0099",
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        user = User.objects.get(email="dr.teacher@gmail.com")
        assert user.role == "LECTURER"
        assert user.lecturer_profile.staff_number == "STF0099"

    def test_self_register_signs_the_new_user_in(self):
        from rest_framework.test import APIClient

        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = APIClient()
        resp = client.post(
            reverse("auth-self-register"),
            {
                "email": "auto.login@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "Auto",
                "last_name": "Login",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026AUTO1",
                "level": "300",
                "personal_email": "auto.login.personal@gmail.com",
            },
            format="json",
        )

        assert resp.status_code == 201, resp.content
        body = resp.json()["data"]
        assert body["email"] == "auto.login@student.ubuea.cm"
        assert body["full_name"] == "Auto Login"
        assert body["role"] == "STUDENT"
        assert resp.cookies.get("fet_access") is not None
        assert resp.cookies.get("fet_refresh") is not None
        assert resp.cookies["fet_access"]["httponly"] is True

        me = client.get(reverse("auth-me"))
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "auto.login@student.ubuea.cm"

        user = User.objects.get(email="auto.login@student.ubuea.cm")
        assert user.last_login_at is not None

    def test_self_register_requires_role_field(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "norole@ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "No",
                "last_name": "Role",
                "department": str(dept.id),
                "matricule": "2026TST99",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_self_register_student_requires_personal_email(self):
        fet = Faculty.objects.create(code="FET", name="Faculty of Engineering and Technology")
        dept = Department.objects.create(faculty=fet, code="CIV", name="Civil Engineering")
        client = Client()
        resp = client.post(
            reverse("auth-self-register"),
            data={
                "email": "student2@student.ubuea.cm",
                "password": "pass12345",
                "password_confirm": "pass12345",
                "first_name": "No",
                "last_name": "Personal",
                "department": str(dept.id),
                "role": "STUDENT",
                "matricule": "2026TST03",
                "level": "200",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400
