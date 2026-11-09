"""User management endpoints (API Spec doc 07 §14)."""
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.csv_export import csv_response

from apps.core.permissions import IsAdmin
from apps.audit.services import audit
from apps.core.scoping import can_view_user, scope_users

from .deletion import archive_account
from .models import LecturerProfile, StudentProfile, User
from .serializers import AdminUserSerializer, MeSerializer


class MyCoursesView(APIView):
    """GET /api/v1/users/me/courses - delegated to academics.urls"""
    pass


def _user_directory(request):
    """The scoped, filtered, ordered account directory used by list + export."""
    role = request.query_params.get("role")
    qs = scope_users(User.objects.select_related("student_profile", "lecturer_profile"), request.user)
    if role:
        qs = qs.filter(role=role.upper())
    deleted = request.query_params.get("deleted")
    if deleted == "1":
        qs = qs.filter(deleted_at__isnull=False)
    elif deleted == "0":
        qs = qs.filter(deleted_at__isnull=True)
    search = (request.query_params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(email__icontains=search)
            | Q(deleted_from_email__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(deleted_from_student_number__icontains=search)
            | Q(deleted_from_staff_number__icontains=search)
            | Q(student_profile__student_number__icontains=search)
            | Q(lecturer_profile__staff_number__icontains=search)
        )
    return qs.order_by("email")


class UserListView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        return Response(AdminUserSerializer(_user_directory(request), many=True).data)


class UserExportView(APIView):
    """GET /api/v1/users/export/ - the account directory as CSV.

    Honours the same role/deleted/search filters as the list, and the same
    scoping (system admin = everyone, faculty/department admin = their unit).
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    HEADER = [
        "Full name",
        "Email",
        "Role",
        "Account status",
        "Is active",
        "Matricule",
        "Staff number",
        "Department",
        "Level",
        "Last login",
        "Created at",
        "Deleted at",
        "Deletion reason",
        "Original email (deleted account)",
        "Original matricule (deleted account)",
    ]

    def get(self, request):
        from django.utils import timezone as tz

        rows = AdminUserSerializer(_user_directory(request), many=True).data
        filename = f"users-{tz.localdate().isoformat()}.csv"
        return csv_response(
            filename,
            self.HEADER,
            [
                [
                    row.get("full_name"),
                    row.get("email"),
                    row.get("role"),
                    row.get("status"),
                    "Yes" if row.get("is_active") else "No",
                    row.get("student_number") or "",
                    row.get("staff_number") or "",
                    row.get("department") or "",
                    row.get("level") or "",
                    row.get("last_login_at") or "",
                    row.get("created_at") or "",
                    row.get("deleted_at") or "",
                    row.get("deletion_reason") or "",
                    row.get("deleted_from_email") or "",
                    row.get("deleted_from_student_number") or "",
                ]
                for row in rows
            ],
        )



def _restore_deleted_account(user):
    """Reclaim a self-deleted account's login identifiers.

    The account's courses and attendance were deleted when it was closed, so a
    restore only brings back the login. Identifiers are released for reuse, so
    the original email or matricule may already belong to a new account; in
    that case restoring would silently hijack the wrong identity, so refuse.
    """
    original_email = (user.deleted_from_email or "").strip()
    original_matricule = user.deleted_from_student_number
    original_staff = user.deleted_from_staff_number
    original_personal = user.deleted_from_personal_email

    if not original_email:
        return (
            "MISSING_IDENTIFIERS",
            "This deleted account has no saved original email and cannot be restored.",
        )
    if User.objects.filter(email__iexact=original_email).exclude(pk=user.pk).exists():
        return (
            "RESTORE_CONFLICT",
            "The original email is now used by another account. Rename or remove that account before restoring this one.",
        )
    student_profile = getattr(user, "student_profile", None)
    if (
        student_profile
        and original_matricule
        and StudentProfile.objects.filter(student_number=original_matricule)
        .exclude(pk=student_profile.pk)
        .exists()
    ):
        return (
            "RESTORE_CONFLICT",
            "The original matricule is now used by another student. Restore cannot continue.",
        )
    lecturer_profile = getattr(user, "lecturer_profile", None)
    if (
        lecturer_profile
        and original_staff
        and LecturerProfile.objects.filter(staff_number=original_staff)
        .exclude(pk=lecturer_profile.pk)
        .exists()
    ):
        return (
            "RESTORE_CONFLICT",
            "The original staff number is now used by another lecturer. Restore cannot continue.",
        )

    user.email = original_email
    user.deleted_at = None
    user.deletion_reason = ""
    user.deletion_improvement = ""
    user.deleted_from_email = None
    user.deleted_from_personal_email = None
    user.deleted_from_student_number = None
    user.deleted_from_staff_number = None
    user.status = User.Status.ACTIVE
    user.is_active = True
    # The old password was made unusable at deletion. The restored owner must
    # request an OTP and choose a fresh password before signing in.
    user.must_change_password = True

    if student_profile:
        update_fields = ["updated_at"]
        if original_matricule:
            student_profile.student_number = original_matricule
            update_fields.append("student_number")
        if original_personal:
            student_profile.personal_email = original_personal
            update_fields.append("personal_email")
        student_profile.save(update_fields=update_fields)
    elif lecturer_profile:
        update_fields = ["updated_at"]
        if original_staff:
            lecturer_profile.staff_number = original_staff
            update_fields.append("staff_number")
        lecturer_profile.save(update_fields=update_fields)
    return None


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        from django.shortcuts import get_object_or_404

        user = get_object_or_404(User, id=user_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_view_user(request.user, user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == User.Role.LECTURER and request.user.id != user.id:
            from apps.academics.models import Enrollment

            if not (user.role == User.Role.STUDENT and Enrollment.objects.filter(
                student=user,
                status=Enrollment.Status.ACTIVE,
            ).filter(
                Q(course_offering__lecturer=request.user) | Q(course_offering__co_lecturer=request.user)
            ).exists()):
                return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.id != user.id and request.user.role not in {
            "DEPARTMENT_ADMIN", "FACULTY_ADMIN", "SYSTEM_ADMIN", "LECTURER"
        }:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You cannot view this profile."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(MeSerializer(user).data)

    def patch(self, request, user_id):
        from django.shortcuts import get_object_or_404

        user = get_object_or_404(User, id=user_id)
        restoring = (
            bool(user.deleted_at) and request.data.get("status") == User.Status.ACTIVE
        )
        if user.deleted_at and not restoring:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "ACCOUNT_DELETED",
                        "message": "This account was deleted by its owner. Restore it to reactivate the login.",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "role" in request.data:
            return Response({"error": "Use the admin account assignment endpoint to change roles."},
                            status=status.HTTP_400_BAD_REQUEST)
        is_system_admin = request.user.role == User.Role.SYSTEM_ADMIN
        if request.user.id != user.id and not is_system_admin:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You cannot update this user."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Account status is administrative state: a user must not be able to
        # suspend or archive their own account, so only a system admin may
        # change it - including on their own account.
        if "status" in request.data and not is_system_admin:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only a system admin can change account status."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if "status" in request.data and request.data["status"] not in User.Status.values:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid status value."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (
            "status" in request.data
            and user.id == request.user.id
            and request.data["status"] != User.Status.ACTIVE
        ):
            return Response(
                {"success": False, "error": {"code": "SELF_DEACTIVATION", "message": "You cannot deactivate your own account."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if restoring:
            error = _restore_deleted_account(user)
            if error:
                code, message = error
                return Response(
                    {"success": False, "error": {"code": code, "message": message}},
                    status=(
                        status.HTTP_409_CONFLICT
                        if code == "RESTORE_CONFLICT"
                        else status.HTTP_400_BAD_REQUEST
                    ),
                )
        for field in ("first_name", "last_name", "status"):
            if field in request.data:
                old_val = getattr(user, field)
                new_val = request.data[field]
                if old_val != new_val:
                    setattr(user, field, new_val)
                    if field == "status":
                        # Login requires BOTH ``is_active`` and ``status == ACTIVE``.
                        # Soft-delete sets both, so restoring one without the
                        # other would leave the account locked out.
                        user.is_active = new_val == User.Status.ACTIVE
                    audit(
                        user=request.user, action=f"USER_{field.upper()}_CHANGED",
                        resource_type="User", resource_id=user.id,
                        request=request, metadata={"old": str(old_val), "new": str(new_val)},
                    )
        user.save()
        if restoring:
            audit(
                user=request.user,
                action="ACCOUNT_RESTORED",
                resource_type="User",
                resource_id=user.id,
                request=request,
            )
        if not user.is_active:
            # Access tokens are short-lived JWTs, but a live refresh token would
            # keep minting new ones for up to a week -- kill every session now.
            from .views_auth import _revoke_all_refresh_tokens

            _revoke_all_refresh_tokens(user)
        return Response(MeSerializer(user).data)

    def delete(self, request, user_id):
        """DELETE /api/v1/users/{id}/ - close another account (SYSTEM_ADMIN).

        Same archive + purge as self-deletion, but no target password is needed.
        The account remains restorable from this screen; its courses and
        attendance history do not.
        """
        from django.shortcuts import get_object_or_404

        if request.user.role != User.Role.SYSTEM_ADMIN:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only a system administrator can delete accounts."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        user = get_object_or_404(User, id=user_id)
        if user.id == request.user.id:
            return Response(
                {"success": False, "error": {"code": "SELF_DELETION", "message": "Use your Profile danger zone to delete your own account."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.deleted_at:
                return Response(
                    {"success": False, "error": {"code": "ACCOUNT_DELETED", "message": "This account is already deleted."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if locked.role == User.Role.SYSTEM_ADMIN:
                other_admins = User.objects.filter(
                    role=User.Role.SYSTEM_ADMIN,
                    is_active=True,
                    status=User.Status.ACTIVE,
                    deleted_at__isnull=True,
                ).exclude(pk=locked.pk)
                if not other_admins.exists():
                    return Response(
                        {
                            "success": False,
                            "error": {
                                "code": "LAST_SYSTEM_ADMIN",
                                "message": "You are the last active system administrator. Promote another administrator before deleting this account.",
                            },
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            purged = archive_account(
                locked, reason=User.DeletionReason.ADMIN_DELETED
            )
            from .views_auth import _revoke_all_refresh_tokens

            _revoke_all_refresh_tokens(locked)

        audit(
            user=request.user,
            action="ACCOUNT_DELETED_BY_ADMIN",
            resource_type="User",
            resource_id=locked.id,
            request=request,
            metadata={"role": locked.role, "purged": purged},
        )
        locked.refresh_from_db()
        return Response(AdminUserSerializer(locked).data)
