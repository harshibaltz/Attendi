"""Authentication endpoints (API Spec doc 07 §13).

Cookie-based JWT. Returns tokens both in cookies AND body for dev flexibility.
"""
import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError

from apps.audit.services import audit

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from .deletion import archive_account
from .authentication import (
    clear_jwt_cookies,
    get_token_pair_for_user,
    set_jwt_cookie_values,
    set_jwt_cookies,
)
from .emails import send_password_changed_email, send_password_reset_otp_email
from .serializers import (
    ConfirmResetSerializer,
    DeleteAccountSerializer,
    MeSerializer,
    RegisterSerializer,
    RequestOtpSerializer,
    SelfRegisterSerializer,
    VerifyOtpSerializer,
)
from .throttling import PasswordResetThrottle

User = get_user_model()
logger = logging.getLogger(__name__)


class RegisterView(APIView):
    """Admin-only user creation.

    Public self-registration is disabled: student accounts come from the
    department roster upload, so outsiders cannot create accounts and
    nobody can sign up with someone else's matricule.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.Role.SYSTEM_ADMIN:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only administrators can create accounts."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        audit(user=request.user, action="ACCOUNT_CREATED", resource_type="User", resource_id=user.id, request=request,
              metadata={"created_email": user.email, "role": user.role})
        return Response(MeSerializer(user).data, status=status.HTTP_201_CREATED)


class SelfRegisterView(APIView):
    """POST /api/v1/auth/self-register/

    Public self-registration. Role is chosen explicitly on the registration form:
      STUDENT  -> must provide matricule + level + department (@student.ubuea.cm recommended)
      LECTURER -> must provide staff_number + department (any valid email)
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = SelfRegisterSerializer(data=request.data)
        if not serializer.is_valid():
            # Keep the reason visible in Vercel logs; field names and messages
            # only (never the submitted values), so this stays PII-free.
            logger.info("self-register rejected: %s", serializer.errors)
            raise ValidationError(serializer.errors)
        user = serializer.save()
        user.record_login()
        refresh = get_token_pair_for_user(user)
        audit(user=user, action="SELF_REGISTERED", resource_type="User", resource_id=user.id, request=request,
              metadata={"email": user.email, "role": user.role})
        audit(user=user, action="LOGGED_IN", resource_type="User", resource_id=user.id, request=request,
              metadata={"via": "self_register"})
        resp = Response(MeSerializer(user).data, status=status.HTTP_201_CREATED)
        return set_jwt_cookies(resp, refresh)


class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/

    Requires the current password. Clears must_change_password so roster
    accounts become fully usable after first login (BR-002).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        current = request.data.get("current_password", "")
        new = request.data.get("new_password", "")
        if not current or not new:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Current and new password are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(new) < 8:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "New password must be at least 8 characters."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not check_password(current, request.user.password):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Current password is incorrect."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if check_password(new, request.user.password):
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "New password must be different from the current one."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        request.user.set_password(new)
        request.user.must_change_password = False
        request.user.save(update_fields=["password", "must_change_password", "updated_at"])
        audit(user=request.user, action="PASSWORD_CHANGED", resource_type="User", resource_id=request.user.id, request=request)
        return Response({"message": "Password changed successfully."})


@method_decorator(csrf_exempt, name='dispatch')
class LoginView(APIView):
    """POST /api/v1/auth/login/

    Accepts either:
      - email + password  (lecturers, admins)
      - matricule + password  (students — matricule is looked up in StudentProfile)
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        identifier = request.data.get("email", "").strip().lower()
        matricule = request.data.get("matricule", "").strip()
        password = request.data.get("password", "")

        if not password:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Password is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = None

        # Student login via matricule
        if matricule and not identifier:
            from .models import StudentProfile
            profile = StudentProfile.objects.select_related("user").filter(
                student_number__iexact=matricule
            ).first()
            if profile:
                user = profile.user

        # Email login (lecturer / admin / student)
        elif identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Email or matricule and password are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user is None:
            # Hash the supplied password even when no account matched, exactly
            # as Django's ModelBackend does: without it, a missing email or
            # matricule returns measurably faster and the timing difference
            # can be used to enumerate registered accounts.
            User().set_password(password)
        if user is None or not check_password(password, user.password):
            return Response(
                {"success": False, "error": {"code": "UNAUTHENTICATED", "message": "Invalid credentials."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_active or user.status != User.Status.ACTIVE:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Your account is not active."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        from apps.core.scoping import is_admin
        if user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not is_admin(user):
            return Response(
                {"success": False, "error": {"code": "ADMIN_SCOPE_REQUIRED", "message": "Ask a system admin to assign your faculty or department."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        user.record_login()
        refresh = get_token_pair_for_user(user)
        audit(user=user, action="LOGGED_IN", resource_type="User", resource_id=user.id, request=request)
        # JWT lives exclusively in httpOnly cookies (never exposed to JS).
        resp = Response(MeSerializer(user).data, status=status.HTTP_200_OK)
        return set_jwt_cookies(resp, refresh)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_cookie = request.COOKIES.get("fet_refresh")
        if refresh_cookie:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken

                RefreshToken(refresh_cookie).blacklist()
            except Exception:
                pass
        audit(user=request.user, action="LOGGED_OUT", resource_type="User", resource_id=request.user.id, request=request)
        resp = Response(status=status.HTTP_204_NO_CONTENT)
        clear_jwt_cookies(resp)
        return resp


class TokenRefreshView(APIView):
    """POST /api/v1/auth/refresh/ — rotate the refresh cookie, mint a new access.

    Delegates to SimpleJWT's own serializer rather than hand-rolling rotation.
    The previous implementation called ``RefreshToken.rotate()``, which does not
    exist in SimpleJWT: every refresh raised AttributeError and returned a 500.
    The axios interceptor treats any failed refresh as a dead session, so once
    the 2h access token expired, *every* user was silently signed out.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer

        refresh_cookie = request.COOKIES.get(settings.COOKIE_NAME_REFRESH)
        body_refresh = request.data.get("refresh")
        token_str = refresh_cookie or body_refresh
        if refresh_cookie:
            from .authentication import enforce_cookie_csrf

            enforce_cookie_csrf(request)
        if not token_str:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Refresh token required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # An invalid, expired, or already-blacklisted refresh token raises a
        # bare TokenError (SimpleJWT does not wrap it in a DRF exception), which
        # would otherwise escape as an unhandled HTTP 500. AuthenticationFailed,
        # by contrast, is handled by DRF and already renders as a 401.
        serializer = TokenRefreshSerializer(data={"refresh": token_str})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "UNAUTHENTICATED",
                        "message": "Invalid or expired refresh token.",
                    },
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        data = serializer.validated_data
        # With ROTATE_REFRESH_TOKENS the serializer returns a replacement refresh
        # and blacklists the old one; the fallback only applies if rotation is off.
        resp = Response({"message": "Token refreshed."})
        return set_jwt_cookie_values(
            resp, str(data["access"]), str(data.get("refresh") or token_str)
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        from .serializers import ProfileUpdateSerializer

        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)


class DeleteAccountView(APIView):
    """DELETE /api/v1/auth/account/ — delete the signed-in user's own account.

    Available to every role (student, lecturer, admin). Requires the current
    password, the literal confirmation ``DELETE``, and an exit reason.

    The account is deactivated and archived, every refresh token is revoked,
    and the login identifiers are released:
      * the row gets a tombstone email so the real email is free to register
        again,
      * the matricule/staff number is moved to the admin-only archive fields
        and cleared from the profile.
    Course enrolments, attendance records/history and attendance points are
    deleted permanently. An administrator can still restore the account and
    its identifiers, but not that activity.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request):
        serializer = DeleteAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        if not check_password(data["password"], user.password):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Current password is incorrect."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Row lock + atomic so the revoke/anonymise happens as one step even if
        # the request is retried or races another session for the same account.
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=user.pk)
            if locked.deleted_at:
                return Response(
                    {"success": False, "error": {"code": "ACCOUNT_DELETED", "message": "This account is already deleted."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Never let the last active system administrator lock everyone out.
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
                locked,
                reason=data["reason"],
                improvement=data.get("improvement", ""),
            )
            _revoke_all_refresh_tokens(locked)

        audit(
            user=user,
            action="ACCOUNT_DELETED",
            resource_type="User",
            resource_id=user.id,
            request=request,
            metadata={"reason": data["reason"], "role": user.role, "purged": purged},
        )
        resp = Response(
            {
                "message": "Your account has been deleted. Your course enrolments and attendance history have been permanently removed."
            },
            status=status.HTTP_200_OK,
        )
        clear_jwt_cookies(resp)
        return resp


def _hash_otp(raw_otp):
    """SHA-256 hex digest. The DB only ever stores this, never the raw code."""
    return hashlib.sha256(raw_otp.encode("utf-8")).hexdigest()


def _generate_otp():
    """A cryptographically secure 6-digit code (never use the ``random`` module)."""
    return f"{secrets.randbelow(900000) + 100000}"


def _invalid_otp():
    return {
        "success": False,
        "error": {"code": "INVALID_OTP", "message": "Invalid OTP code."},
    }


def _too_many_attempts():
    return {
        "success": False,
        "error": {
            "code": "TOO_MANY_ATTEMPTS",
            "message": "Too many failed attempts. Request a new OTP.",
        },
    }


def _burn_otp(user):
    """Clear the OTP fields so a spent/exhausted code can never be reused.

    Uses a single UPDATE (not read-modify-write) so two concurrent callers
    cannot resurrect a burned code.
    """
    User.objects.filter(pk=user.pk).update(
        reset_otp_hash=None,
        reset_otp_expires=None,
        reset_otp_attempts=0,
    )
    user.reset_otp_hash = None
    user.reset_otp_expires = None
    user.reset_otp_attempts = 0


def _lock_user(email):
    """Fetch the user row under ``SELECT ... FOR UPDATE``.

    Serializes concurrent verify/confirm requests for the same account so the
    OTP attempt budget and single-use guarantee hold under parallel guesses.
    Degrades to a plain read on backends without row locking (e.g. SQLite).
    """
    return User.objects.select_for_update().filter(email__iexact=email).first()


def _otp_precheck(user):
    """Return a Response if the stored OTP is missing/expired/exhausted, else None."""
    if (
        user is None
        or not user.reset_otp_hash
        or user.reset_otp_expires is None
        or user.reset_otp_expires <= timezone.now()
    ):
        return Response(_invalid_otp(), status=status.HTTP_400_BAD_REQUEST)
    if user.reset_otp_attempts >= settings.PASSWORD_RESET_OTP_MAX_ATTEMPTS:
        _burn_otp(user)
        return Response(_too_many_attempts(), status=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def _otp_matches(user, otp):
    return secrets.compare_digest(_hash_otp(otp), user.reset_otp_hash or "")


def _record_failed_attempt(user):
    """Atomically bump the wrong-guess counter (no lost updates under load)."""
    User.objects.filter(pk=user.pk).update(reset_otp_attempts=F("reset_otp_attempts") + 1)
    user.refresh_from_db(fields=["reset_otp_attempts"])


def _revoke_all_refresh_tokens(user):
    """Blacklist every outstanding refresh token so all sessions are killed.

    Runs after a successful reset: if an attacker knew the old password and
    held a live session, that session dies the moment the victim resets.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


class RequestOtpView(APIView):
    """POST /api/v1/auth/forgot-password/request-otp/  { "email": "..." }

    Always returns the same generic 200, whether or not the email is registered,
    so the endpoint cannot be used to enumerate accounts.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PasswordResetThrottle]

    GENERIC_MESSAGE = "If an account exists with this email, an OTP has been sent."

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is not None:
            otp = _generate_otp()
            user.reset_otp_hash = _hash_otp(otp)
            user.reset_otp_expires = timezone.now() + timedelta(
                minutes=settings.PASSWORD_RESET_OTP_TTL_MINUTES
            )
            user.reset_otp_attempts = 0
            user.save(
                update_fields=[
                    "reset_otp_hash",
                    "reset_otp_expires",
                    "reset_otp_attempts",
                    "updated_at",
                ]
            )
            send_password_reset_otp_email(user, otp)
            audit(
                user=user,
                action="PASSWORD_RESET_REQUESTED",
                resource_type="User",
                resource_id=user.id,
                request=request,
            )

        return Response({"message": self.GENERIC_MESSAGE}, status=status.HTTP_200_OK)


class VerifyOtpView(APIView):
    """POST /api/v1/auth/reset-password/verify-otp/

    { "email": "...", "otp": "123456" }

    Confirms the code is correct without consuming it, so the SPA can advance to
    the "choose a new password" step. Wrong guesses still count toward the
    brute-force budget so this cannot be used to probe codes.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]

        # Row lock: concurrent verifies for one account run one at a time, so a
        # wrong guess can never be lost between the read and the increment.
        with transaction.atomic():
            user = _lock_user(email)
            failure = _otp_precheck(user)
            if failure is not None:
                return failure
            if not _otp_matches(user, otp):
                _record_failed_attempt(user)
                return Response(_invalid_otp(), status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": "OTP verified."}, status=status.HTTP_200_OK)


class ConfirmResetView(APIView):
    """POST /api/v1/auth/reset-password/confirm/

    { "email": "...", "otp": "123456", "new_password": "..." }

    The OTP is single-use, expires after a short window, and is burned after a
    handful of wrong guesses so a 6-digit code cannot be brute-forced.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AnonRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        serializer = ConfirmResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        new_password = serializer.validated_data["new_password"]

        # Row lock makes check + burn + password-set a single atomic step, so
        # the OTP is genuinely single-use even under concurrent requests.
        with transaction.atomic():
            user = _lock_user(email)
            failure = _otp_precheck(user)
            if failure is not None:
                return failure
            if not _otp_matches(user, otp):
                _record_failed_attempt(user)
                return Response(_invalid_otp(), status=status.HTTP_400_BAD_REQUEST)

            user.set_password(new_password)
            user.reset_otp_hash = None
            user.reset_otp_expires = None
            user.reset_otp_attempts = 0
            user.must_change_password = False
            user.save(
                update_fields=[
                    "password",
                    "reset_otp_hash",
                    "reset_otp_expires",
                    "reset_otp_attempts",
                    "must_change_password",
                    "updated_at",
                ]
            )
            _revoke_all_refresh_tokens(user)
        send_password_changed_email(user)
        audit(
            user=user,
            action="PASSWORD_RESET_COMPLETED",
            resource_type="User",
            resource_id=user.id,
            request=request,
        )
        return Response({"message": "Password successfully updated."}, status=status.HTTP_200_OK)
