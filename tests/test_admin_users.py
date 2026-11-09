"""User management: list + status changes by a SYSTEM_ADMIN.

Guards the reactivation contract that the soft delete depends on:
  * login requires both ``is_active`` and ``status == ACTIVE``,
  * restoring ``status`` must therefore restore ``is_active`` too,
  * admins cannot lock themselves out,
  * only SYSTEM_ADMIN can change another user's status.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import StudentProfile, User
from apps.academics.models import Enrollment

pytestmark = pytest.mark.django_db


def _user(role=User.Role.STUDENT, email="member@test.edu"):
    return User.objects.create_user(
        email=email, password="OldPass123", first_name="Mem", last_name="Ber", role=role
    )


def _admin(email="admin@test.edu"):
    return _user(role=User.Role.SYSTEM_ADMIN, email=email)


def _patch_status(actor, target, new_status):
    client = APIClient()
    client.force_authenticate(user=actor)
    return client.patch(
        reverse("user-detail", kwargs={"user_id": target.id}),
        {"status": new_status},
        format="json",
    )


def test_user_list_includes_account_state_for_admins():
    admin = _admin()
    student = _user()
    client = APIClient()
    client.force_authenticate(user=admin)

    resp = client.get(reverse("user-list"))
    assert resp.status_code == 200

    rows = {row["email"]: row for row in resp.json()["data"]}
    row = rows[student.email]
    assert row["role"] == "STUDENT"
    assert row["status"] == "ACTIVE"
    assert row["is_active"] is True
    assert row["full_name"] == "Mem Ber"


def test_user_list_includes_suspended_and_archived_accounts():
    admin = _admin()
    suspended = _user(email="suspended@test.edu")
    archived = _user(email="archived@test.edu")
    User.objects.filter(pk=suspended.pk).update(status=User.Status.SUSPENDED, is_active=False)
    User.objects.filter(pk=archived.pk).update(status=User.Status.ARCHIVED, is_active=False)

    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.get(reverse("user-list"))
    assert resp.status_code == 200

    rows = {row["email"]: row for row in resp.json()["data"]}
    assert rows["suspended@test.edu"]["status"] == "SUSPENDED"
    assert rows["archived@test.edu"]["status"] == "ARCHIVED"


def test_students_cannot_list_users():
    student = _user()
    client = APIClient()
    client.force_authenticate(user=student)

    assert client.get(reverse("user-list")).status_code == 403


def test_archived_account_is_restored_and_can_sign_in():
    admin = _admin()
    student = _user(email="deleted@test.edu")
    User.objects.filter(pk=student.pk).update(is_active=False, status=User.Status.ARCHIVED)

    resp = _patch_status(admin, student, User.Status.ACTIVE)
    assert resp.status_code == 200

    student.refresh_from_db()
    assert student.status == User.Status.ACTIVE
    assert student.is_active is True

    login = APIClient().post(
        reverse("auth-login"),
        {"email": "deleted@test.edu", "password": "OldPass123"},
        format="json",
    )
    assert login.status_code == 200


def test_deactivating_a_user_blocks_sign_in():
    admin = _admin()
    student = _user(email="blocked@test.edu")

    resp = _patch_status(admin, student, User.Status.SUSPENDED)
    assert resp.status_code == 200

    student.refresh_from_db()
    assert student.status == User.Status.SUSPENDED
    assert student.is_active is False

    login = APIClient().post(
        reverse("auth-login"),
        {"email": "blocked@test.edu", "password": "OldPass123"},
        format="json",
    )
    assert login.status_code == 403


def test_admin_cannot_deactivate_own_account():
    admin = _admin()

    resp = _patch_status(admin, admin, User.Status.SUSPENDED)
    assert resp.status_code == 400

    admin.refresh_from_db()
    assert admin.status == User.Status.ACTIVE
    assert admin.is_active is True


def test_admin_can_still_edit_own_profile():
    admin = _admin()
    client = APIClient()
    client.force_authenticate(user=admin)

    resp = client.patch(
        reverse("user-detail", kwargs={"user_id": admin.id}),
        {"first_name": "Renamed"},
        format="json",
    )
    assert resp.status_code == 200
    admin.refresh_from_db()
    assert admin.first_name == "Renamed"


def test_faculty_admin_cannot_change_another_users_status():
    actor = _user(role=User.Role.FACULTY_ADMIN, email="faculty@test.edu")
    target = _user(email="target@test.edu")

    resp = _patch_status(actor, target, User.Status.SUSPENDED)
    assert resp.status_code == 403

    target.refresh_from_db()
    assert target.status == User.Status.ACTIVE


def test_deactivating_revokes_every_refresh_token():
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    from apps.accounts.authentication import get_token_pair_for_user

    admin = _admin()
    student = _user(email="sessions@test.edu")
    get_token_pair_for_user(student)  # an outstanding refresh token
    assert OutstandingToken.objects.filter(user=student).exists()

    assert _patch_status(admin, student, User.Status.SUSPENDED).status_code == 200

    outstanding = OutstandingToken.objects.filter(user=student)
    assert outstanding.exists()
    blacklisted = BlacklistedToken.objects.filter(token__in=outstanding).count()
    assert blacklisted == outstanding.count()


def test_invalid_status_is_rejected():
    admin = _admin()
    student = _user(email="student@test.edu")

    resp = _patch_status(admin, student, "DELETED")
    assert resp.status_code == 400

    student.refresh_from_db()
    assert student.status == User.Status.ACTIVE


def _delete_user(actor, target):
    client = APIClient()
    client.force_authenticate(user=actor)
    return client.delete(reverse("user-detail", kwargs={"user_id": target.id}))


def test_admin_can_delete_another_account_and_its_activity(
    student_user, offering
):
    admin = _admin()
    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )

    resp = _delete_user(admin, student_user)
    assert resp.status_code == 200, resp.content

    student_user.refresh_from_db()
    assert student_user.deleted_at is not None
    assert student_user.status == User.Status.ARCHIVED
    assert student_user.is_active is False
    assert student_user.email == f"deleted-{student_user.id}@deleted.invalid"
    assert student_user.deleted_from_email == "student@test.edu"
    assert student_user.deleted_from_student_number == "STU001"
    assert not Enrollment.objects.filter(student=student_user).exists()
    profile = StudentProfile.objects.get(user=student_user)
    assert profile.student_number is None

    row = resp.json()["data"]
    assert row["deleted_at"] is not None
    assert row["deleted_from_email"] == "student@test.edu"


def test_non_system_admin_cannot_delete_an_account(student_user):
    actor = _user(role=User.Role.FACULTY_ADMIN, email="faculty@test.edu")

    assert _delete_user(actor, student_user).status_code == 403

    student_user.refresh_from_db()
    assert student_user.deleted_at is None


def test_admin_cannot_delete_their_own_account_through_the_user_endpoint():
    admin = _admin()

    resp = _delete_user(admin, admin)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SELF_DELETION"

    admin.refresh_from_db()
    assert admin.deleted_at is None
