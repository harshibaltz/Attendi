"""Delete-own-account endpoint.

Guards the self-deletion contract:
  * strong confirmation (password + typed DELETE + reason) is required,
  * any role may delete, but the last system admin may not,
  * login identifiers are released for re-registration while the account row
    stays for the administrator archive,
  * course enrolments, attendance records/history and attendance points are
    permanently deleted, so the closed account disappears from class data,
  * an administrator may restore the account and its identifiers, but not the
    deleted course/attendance activity,
  * every refresh token is revoked and the archived account cannot sign in.
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.authentication import get_token_pair_for_user
from apps.accounts.models import LecturerProfile, StudentProfile, User
from apps.academics.models import ClassDefinition, ClassSession, CourseOffering, Enrollment
from apps.attendance.models import (
    AttendanceCheckpoint,
    AttendanceRecord,
    AttendanceSession,
    PointsLedger,
)

pytestmark = pytest.mark.django_db

PASSWORD = "OldPass123"


def _user(role=User.Role.STUDENT, email="delete.me@test.edu"):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="De", last_name="Lete", role=role
    )


def _delete(client, **overrides):
    payload = {
        "password": PASSWORD,
        "confirm": "DELETE",
        "reason": User.DeletionReason.NO_LONGER_NEEDED,
    }
    payload.update(overrides)
    return client.delete(reverse("auth-delete-account"), payload, format="json")


def test_student_delete_releases_identifiers_and_keeps_the_row():
    user = _user()
    old_id = user.id
    StudentProfile.objects.create(
        user=user, student_number="UB12345", personal_email="personal@test.edu"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    resp = _delete(client, improvement="The mobile layout was hard to use.")
    assert resp.status_code == 200

    user.refresh_from_db()
    assert user.id == old_id
    assert user.is_active is False
    assert user.status == User.Status.ARCHIVED
    assert user.deleted_at is not None
    assert user.email == f"deleted-{old_id}@deleted.invalid"
    assert user.deleted_from_email == "delete.me@test.edu"
    assert user.deleted_from_student_number == "UB12345"
    assert user.deleted_from_personal_email == "personal@test.edu"
    assert user.deletion_reason == User.DeletionReason.NO_LONGER_NEEDED
    assert user.deletion_improvement == "The mobile layout was hard to use."

    profile = StudentProfile.objects.get(user=user)
    assert profile.student_number is None
    assert profile.personal_email is None

    login = APIClient().post(
        reverse("auth-login"),
        {"email": "delete.me@test.edu", "password": PASSWORD},
        format="json",
    )
    assert login.status_code in (401, 403)


def test_same_email_and_matricule_can_register_again(cs_department):
    user = _user()
    StudentProfile.objects.create(
        user=user, student_number="UB12345", personal_email="personal@test.edu"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    assert _delete(client).status_code == 200

    resp = APIClient().post(
        reverse("auth-self-register"),
        {
            "email": "delete.me@test.edu",
            "password": "NewPass123",
            "password_confirm": "NewPass123",
            "first_name": "New",
            "last_name": "Student",
            "department": str(cs_department.id),
            "role": "STUDENT",
            "matricule": "UB12345",
            "level": "300",
            "personal_email": "new.personal@test.edu",
        },
        format="json",
    )
    assert resp.status_code == 201

    new_user = User.objects.get(email="delete.me@test.edu")
    assert new_user.id != user.id
    assert new_user.student_profile.student_number == "UB12345"
    assert new_user.student_profile.department_id == cs_department.id


def test_student_delete_purges_courses_and_attendance(
    student_user, student2_user, offering, lecturer_user, class_def, class_session
):
    Enrollment.objects.create(
        student=student_user, course_offering=offering, status=Enrollment.Status.ACTIVE
    )
    session = AttendanceSession.objects.create(
        class_session=class_session,
        lecturer=lecturer_user,
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    AttendanceRecord.objects.create(attendance_session=session, student=student_user)
    other_record = AttendanceRecord.objects.create(
        attendance_session=session, student=student2_user
    )
    AttendanceCheckpoint.objects.create(
        attendance_session=session, student=student_user, checkpoint_number=1
    )
    PointsLedger.objects.create(
        student=student_user,
        attendance_session=session,
        category=PointsLedger.Category.SCAN,
        points=4,
    )

    client = APIClient()
    client.force_authenticate(user=student_user)
    assert _delete(client, password="test1234").status_code == 200

    assert not Enrollment.objects.filter(student=student_user).exists()
    assert not AttendanceRecord.objects.filter(student=student_user).exists()
    assert not AttendanceCheckpoint.objects.filter(student=student_user).exists()
    assert not PointsLedger.objects.filter(student=student_user).exists()
    # Only the deleted account's activity is removed.
    assert AttendanceRecord.objects.filter(pk=other_record.pk).exists()
    # The archive row and profile remain available to administrators.
    student_user.refresh_from_db()
    assert student_user.deleted_at is not None
    assert StudentProfile.objects.filter(user=student_user).exists()


def test_wrong_password_does_not_delete_anything():
    user = _user()
    client = APIClient()
    client.force_authenticate(user=user)

    resp = _delete(client, password="WrongPass123")
    assert resp.status_code == 403

    user.refresh_from_db()
    assert user.deleted_at is None
    assert user.email == "delete.me@test.edu"
    assert user.is_active is True


def test_confirmation_phrase_is_required():
    user = _user()
    client = APIClient()
    client.force_authenticate(user=user)

    resp = _delete(client, confirm="delete my account")
    assert resp.status_code == 400

    user.refresh_from_db()
    assert user.deleted_at is None


def test_reason_is_required_and_other_needs_an_explanation():
    user = _user()
    client = APIClient()
    client.force_authenticate(user=user)

    assert _delete(client, reason="").status_code == 400
    assert _delete(client, reason=User.DeletionReason.OTHER).status_code == 400
    assert _delete(
        client,
        reason=User.DeletionReason.OTHER,
        improvement="Please add dark mode.",
    ).status_code == 200


def test_lecturer_delete_keeps_classes_and_sessions(
    lecturer_user, class_def, class_session, offering
):
    LecturerProfile.objects.create(user=lecturer_user, staff_number="STAFF-1")
    CourseOffering.objects.filter(pk=offering.pk).update(lecturer=lecturer_user)
    client = APIClient()
    client.force_authenticate(user=lecturer_user)

    assert _delete(client, password="test1234").status_code == 200

    lecturer_user.refresh_from_db()
    assert lecturer_user.deleted_at is not None
    assert lecturer_user.deleted_from_staff_number == "STAFF-1"
    assert lecturer_user.lecturer_profile.staff_number is None
    assert ClassDefinition.objects.filter(pk=class_def.pk).exists()
    assert ClassSession.objects.filter(pk=class_session.pk).exists()
    assert CourseOffering.objects.get(pk=offering.pk).lecturer_id == lecturer_user.id


def test_admin_can_delete_when_another_system_admin_remains():
    admin = _user(role=User.Role.SYSTEM_ADMIN, email="admin@test.edu")
    _user(role=User.Role.SYSTEM_ADMIN, email="admin2@test.edu")
    client = APIClient()
    client.force_authenticate(user=admin)

    assert _delete(client).status_code == 200
    admin.refresh_from_db()
    assert admin.deleted_at is not None


def test_last_system_admin_cannot_delete_themselves():
    admin = _user(role=User.Role.SYSTEM_ADMIN, email="admin@test.edu")
    client = APIClient()
    client.force_authenticate(user=admin)

    resp = _delete(client)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "LAST_SYSTEM_ADMIN"

    admin.refresh_from_db()
    assert admin.deleted_at is None
    assert admin.is_active is True


def test_unauthenticated_cannot_delete():
    resp = APIClient().delete(reverse("auth-delete-account"))
    assert resp.status_code in (401, 403)


def test_deleting_revokes_every_refresh_token():
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    user = _user(email="revoke.me@test.edu")
    get_token_pair_for_user(user)  # mints an outstanding refresh token
    assert OutstandingToken.objects.filter(user=user).exists()

    client = APIClient()
    client.force_authenticate(user=user)
    assert _delete(client).status_code == 200

    outstanding = OutstandingToken.objects.filter(user=user)
    assert outstanding.exists()
    blacklisted = BlacklistedToken.objects.filter(token__in=outstanding).count()
    assert blacklisted == outstanding.count()


def test_admin_still_sees_deleted_account_data_and_feedback():
    user = _user(email="gone@test.edu")
    StudentProfile.objects.create(
        user=user, student_number="UB777", personal_email="old@test.edu"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    assert _delete(
        client,
        reason=User.DeletionReason.TOO_MANY_ISSUES,
        improvement="The attendance page reloaded too often.",
    ).status_code == 200

    admin = _user(role=User.Role.SYSTEM_ADMIN, email="admin@test.edu")
    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)

    resp = admin_client.get(reverse("user-list"), {"search": "gone@test.edu"})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["deleted_at"] is not None
    assert row["deleted_from_email"] == "gone@test.edu"
    assert row["deleted_from_student_number"] == "UB777"
    assert row["deletion_reason"] == User.DeletionReason.TOO_MANY_ISSUES
    assert row["deletion_improvement"] == "The attendance page reloaded too often."


def test_admin_can_restore_a_deleted_account_and_its_identifiers():
    user = _user()
    StudentProfile.objects.create(
        user=user, student_number="UB777", personal_email="old@test.edu"
    )
    client = APIClient()
    client.force_authenticate(user=user)
    assert _delete(client).status_code == 200
    user.refresh_from_db()
    assert user.email == f"deleted-{user.id}@deleted.invalid"

    admin = _user(role=User.Role.SYSTEM_ADMIN, email="admin@test.edu")
    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    resp = admin_client.patch(
        reverse("user-detail", kwargs={"user_id": user.id}),
        {"status": User.Status.ACTIVE},
        format="json",
    )
    assert resp.status_code == 200, resp.content

    user.refresh_from_db()
    assert user.deleted_at is None
    assert user.email == "delete.me@test.edu"
    assert user.status == User.Status.ACTIVE
    assert user.is_active is True
    assert user.must_change_password is True
    assert user.deleted_from_email is None
    profile = StudentProfile.objects.get(user=user)
    assert profile.student_number == "UB777"
    assert profile.personal_email == "old@test.edu"


def test_restore_refuses_when_the_original_email_was_reused():
    user = _user()
    client = APIClient()
    client.force_authenticate(user=user)
    assert _delete(client).status_code == 200

    _user(email="delete.me@test.edu")
    admin = _user(role=User.Role.SYSTEM_ADMIN, email="admin@test.edu")
    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    resp = admin_client.patch(
        reverse("user-detail", kwargs={"user_id": user.id}),
        {"status": User.Status.ACTIVE},
        format="json",
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "RESTORE_CONFLICT"


def test_self_deletion_cannot_claim_the_admin_reason():
    user = _user(email="self@test.edu")
    client = APIClient()
    client.force_authenticate(user=user)

    resp = _delete(client, reason=User.DeletionReason.ADMIN_DELETED)
    assert resp.status_code == 400

    user.refresh_from_db()
    assert user.deleted_at is None
    assert user.is_active is True
