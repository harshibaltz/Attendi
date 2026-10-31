from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.academics.models import CourseOffering, Department, Faculty

from .models import LecturerProfile, StudentProfile, User


class UserPublicSerializer(serializers.ModelSerializer):
    """Minimal public view - never leaks password or sensitive fields."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "status",
            "is_active",
            "last_login_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


class AdminUserSerializer(serializers.ModelSerializer):
    """Admin directory row, including the deleted-account archive.

    Only ``UserListView`` (``IsAdmin``) uses this. Original login identifiers
    are kept in ``deleted_from_*`` so an administrator can still identify a
    self-deleted account even though its email/matricule were released.
    """

    full_name = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()
    staff_number = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "status",
            "is_active",
            "last_login_at",
            "created_at",
            "student_number",
            "staff_number",
            "department",
            "level",
            "deleted_at",
            "deletion_reason",
            "deletion_improvement",
            "deleted_from_email",
            "deleted_from_personal_email",
            "deleted_from_student_number",
            "deleted_from_staff_number",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    @staticmethod
    def _profile(obj, name):
        return getattr(obj, name, None)

    def get_student_number(self, obj):
        if obj.deleted_at:
            return obj.deleted_from_student_number
        profile = self._profile(obj, "student_profile")
        return profile.student_number if profile else None

    def get_staff_number(self, obj):
        if obj.deleted_at:
            return obj.deleted_from_staff_number
        profile = self._profile(obj, "lecturer_profile")
        return profile.staff_number if profile else None

    def get_department(self, obj):
        profile = self._profile(obj, "student_profile") or self._profile(obj, "lecturer_profile")
        return profile.department.name if profile and profile.department else None

    def get_level(self, obj):
        profile = self._profile(obj, "student_profile")
        return profile.level if profile else None


class RegisterSerializer(serializers.Serializer):
    """Admin-only user creation."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower().strip()

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class AdminAssignmentSerializer(serializers.Serializer):
    """A system admin selects the role and its required academic boundary."""

    role = serializers.ChoiceField(choices=[User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN])
    faculty_id = serializers.PrimaryKeyRelatedField(
        source="admin_faculty", queryset=Faculty.objects.all(), required=False, allow_null=True,
    )
    department_id = serializers.PrimaryKeyRelatedField(
        source="admin_department", queryset=Department.objects.all(), required=False, allow_null=True,
    )

    def validate(self, attrs):
        role = attrs["role"]
        faculty = attrs.get("admin_faculty")
        department = attrs.get("admin_department")
        if role == User.Role.FACULTY_ADMIN and (faculty is None or department is not None):
            raise serializers.ValidationError("A faculty admin needs one faculty and no department.")
        if role == User.Role.DEPARTMENT_ADMIN and (department is None or faculty is not None):
            raise serializers.ValidationError("A department admin needs one department and no faculty.")
        return attrs


class AdminAccountCreateSerializer(AdminAssignmentSerializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("This email already has an account. Assign its role instead.")
        return value


# ---------------------------------------------------------------------------
# Self-registration
# ---------------------------------------------------------------------------

# Students register with University of Buea emails (@ubuea.cm).
# Lecturers may register with any valid email address.
STUDENT_REGISTRATION_DOMAINS = {"student.ubuea.cm"}


class SelfRegisterSerializer(serializers.Serializer):
    """Public self-registration. Role is chosen explicitly on the form.

    Students register with @student.ubuea.cm email + matricule + level.
    Lecturers register with any valid email + staff_number.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=100, trim_whitespace=True)
    last_name = serializers.CharField(max_length=100, trim_whitespace=True)
    department = serializers.UUIDField()
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    role = serializers.ChoiceField(choices=[("STUDENT", "Student"), ("LECTURER", "Lecturer")])
    matricule = serializers.CharField(max_length=30, required=False, allow_blank=True)
    staff_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
    level = serializers.CharField(max_length=20, required=False, allow_blank=True)
    personal_email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists. Sign in instead, or use "
                "\"Forgot password\" if you no longer remember the password."
            )
        return value

    def validate_personal_email(self, value):
        if not value:
            return None
        value = value.lower().strip()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "This personal email is already linked to another account. "
                "If it is yours, sign in or reset the password instead."
            )
        return value

    def validate_level(self, value):
        value = (value or "").strip()
        if value and value not in {"200", "300", "400", "500"}:
            raise serializers.ValidationError("Level must be one of: L200, L300, L400, L500.")
        return value

    def validate_department(self, value):
        department = Department.objects.filter(id=value).first()
        if department is None:
            raise serializers.ValidationError("Unknown department.")
        return department

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})

        role = attrs.get("role")

        if role == "STUDENT":
            matricule = (attrs.get("matricule") or "").strip()
            if not matricule:
                raise serializers.ValidationError({"matricule": "Matricule number is required for students."})
            # Login matches matricules case-insensitively, so uniqueness must
            # be checked the same way - otherwise the DB unique index would
            # reject the save as an unhandled IntegrityError (HTTP 500).
            if StudentProfile.objects.filter(student_number__iexact=matricule).exists():
                raise serializers.ValidationError({
                    "matricule": (
                        "This matricule already has an account. Sign in with your existing "
                        "account, or use \"Forgot password\" to get a reset code."
                    )
                })
            personal_email = (attrs.get("personal_email") or "").strip()
            if not personal_email:
                raise serializers.ValidationError({"personal_email": "Personal email is required for students."})
        elif role == "LECTURER":
            if not attrs.get("staff_number", "").strip():
                raise serializers.ValidationError({"staff_number": "Staff number is required for lecturers."})
        return attrs

    def create(self, validated_data):
        role = validated_data.pop("role")
        matricule = validated_data.pop("matricule", "").strip()
        staff_number = validated_data.pop("staff_number", "").strip()
        level = validated_data.pop("level", "").strip()
        personal_email = validated_data.pop("personal_email", None) or None
        department = validated_data.pop("department")  # resolved in validate_department()
        date_of_birth = validated_data.pop("date_of_birth", None)
        validated_data.pop("password_confirm")

        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data["first_name"],
            last_name=validated_data["last_name"],
            role=role,
            date_of_birth=date_of_birth,
        )

        if role == "STUDENT":
            StudentProfile.objects.create(
                user=user,
                student_number=matricule,
                department=department,
                level=level if level else "200",
                personal_email=personal_email,
            )
        else:
            LecturerProfile.objects.create(
                user=user,
                staff_number=staff_number,
                department=department,
            )
        return user


class DeleteAccountSerializer(serializers.Serializer):
    """Strong confirmation + exit feedback for self-deletion."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirm = serializers.CharField(write_only=True)
    reason = serializers.ChoiceField(choices=User.DeletionReason.choices)
    improvement = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, trim_whitespace=True
    )

    def validate_confirm(self, value):
        if value.strip().upper() != "DELETE":
            raise serializers.ValidationError('Type "DELETE" to confirm.')
        return value

    def validate(self, attrs):
        if attrs["reason"] == User.DeletionReason.OTHER and not attrs.get("improvement", "").strip():
            raise serializers.ValidationError(
                {"improvement": "Please tell us what went wrong or what we could improve."}
            )
        return attrs


class MeSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    student_profile = serializers.SerializerMethodField()
    lecturer_profile = serializers.SerializerMethodField()
    admin_scope = serializers.SerializerMethodField()
    delegations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "status",
            "date_of_birth",
            "must_change_password",
            "student_profile",
            "lecturer_profile",
            "admin_scope",
            "delegations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_admin_scope(self, obj):
        if obj.role == User.Role.FACULTY_ADMIN and obj.admin_faculty_id:
            return {"faculty_id": str(obj.admin_faculty_id), "faculty_name": obj.admin_faculty.name}
        if obj.role == User.Role.DEPARTMENT_ADMIN and obj.admin_department_id:
            return {
                "faculty_id": str(obj.admin_department.faculty_id),
                "faculty_name": obj.admin_department.faculty.name,
                "department_id": str(obj.admin_department_id),
                "department_name": obj.admin_department.name,
            }
        return None

    def get_delegations(self, obj):
        """Attendance delegation flags for students (null for other roles).

        The frontend uses this to show the attendance launcher; the backend
        still re-checks every launch with the same helper.
        """
        if obj.role != User.Role.STUDENT:
            return None
        from apps.attendance.permissions import launchable_offerings
        from apps.projects.models import ClassDelegate

        offerings = launchable_offerings(
            obj, CourseOffering.objects.filter(status="ACTIVE")
        )
        offering_ids = [str(pk) for pk in offerings.values_list("id", flat=True)]
        return {
            "is_class_delegate": ClassDelegate.objects.filter(student=obj).exists(),
            "is_department_delegate": obj.department_delegate_courses.exists(),
            "can_launch_attendance": bool(offering_ids),
            "offering_ids": offering_ids,
        }

    def get_student_profile(self, obj):
        profile = getattr(obj, "student_profile", None)
        if profile is None:
            return None
        department = profile.department
        return {
            "id": profile.id,
            "student_number": profile.student_number,
            "department_id": profile.department_id,
            "department": {
                "id": department.id,
                "name": department.name,
                "code": department.code,
            } if department else None,
            "level": profile.level,
            "admission_year": profile.admission_year,
            "personal_email": profile.personal_email,
            "profile_image_reference": profile.profile_image_reference,
            "bio": profile.profile_bio,
            "skills": profile.skills,
            "achievements": profile.achievements,
        }

    def get_lecturer_profile(self, obj):
        profile = getattr(obj, "lecturer_profile", None)
        if profile is None:
            return None
        department = profile.department
        return {
            "id": profile.id,
            "staff_number": profile.staff_number,
            "department_id": profile.department_id,
            "department": {
                "id": department.id,
                "name": department.name,
                "code": department.code,
            } if department else None,
            "title": profile.title,
            "bio": profile.bio,
            "profile_image_reference": profile.profile_image_reference,
        }


class ProfileUpdateSerializer(serializers.Serializer):
    """Self-service profile edits.

    Users may change their own name, contact details, bio and - with
    uniqueness checks - their institutional email and student/staff number.
    Department, role and account status remain administrator-managed.
    """

    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    email = serializers.EmailField(required=False)
    student_number = serializers.CharField(max_length=30, required=False)
    staff_number = serializers.CharField(max_length=30, required=False)
    level = serializers.CharField(max_length=20, required=False)
    bio = serializers.CharField(required=False, allow_blank=True)
    skills = serializers.ListField(child=serializers.CharField(), required=False)
    achievements = serializers.ListField(child=serializers.CharField(), required=False)
    personal_email = serializers.EmailField(required=False, allow_blank=True)
    admission_year = serializers.IntegerField(required=False, min_value=1990, max_value=2100,
                                              allow_null=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if value.endswith("@deleted.invalid"):
            raise serializers.ValidationError("That email address is reserved.")
        qs = User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_student_number(self, value):
        value = value.strip()
        qs = StudentProfile.objects.filter(student_number__iexact=value)
        profile = getattr(self.instance, "student_profile", None)
        if profile is not None:
            qs = qs.exclude(pk=profile.pk)
        if qs.exists():
            raise serializers.ValidationError("This matricule is already registered.")
        return value

    def validate_staff_number(self, value):
        value = value.strip()
        qs = LecturerProfile.objects.filter(staff_number__iexact=value)
        profile = getattr(self.instance, "lecturer_profile", None)
        if profile is not None:
            qs = qs.exclude(pk=profile.pk)
        if qs.exists():
            raise serializers.ValidationError("This staff number is already registered.")
        return value

    def validate_personal_email(self, value):
        if not value:
            return None
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if qs.exists():
            raise serializers.ValidationError("An account with this personal email already exists.")
        return value

    def validate_level(self, value):
        value = (value or "").strip()
        if value and value not in {"200", "300", "400", "500"}:
            raise serializers.ValidationError("Level must be one of: L200, L300, L400, L500.")
        return value

    def validate(self, attrs):
        role = self.instance.role
        if "student_number" in attrs:
            if role != User.Role.STUDENT:
                raise serializers.ValidationError(
                    {"student_number": "Only students can have a matricule."}
                )
            if getattr(self.instance, "student_profile", None) is None:
                raise serializers.ValidationError(
                    {"student_number": "This account has no student profile."}
                )
        if "staff_number" in attrs:
            if role != User.Role.LECTURER:
                raise serializers.ValidationError(
                    {"staff_number": "Only lecturers can have a staff number."}
                )
            if getattr(self.instance, "lecturer_profile", None) is None:
                raise serializers.ValidationError(
                    {"staff_number": "This account has no lecturer profile."}
                )
        return attrs

    def update(self, instance, validated_data):
        profile = getattr(instance, "student_profile", None) or getattr(
            instance, "lecturer_profile", None
        )
        profile_fields = {
            "level", "bio", "skills", "achievements", "personal_email", "admission_year",
            "student_number", "staff_number",
        }
        profile_data = {k: v for k, v in validated_data.items() if k in profile_fields}
        user_fields = {k: v for k, v in validated_data.items() if k not in profile_fields}

        try:
            with transaction.atomic():
                for k, v in user_fields.items():
                    setattr(instance, k, v)
                instance.save(
                    update_fields=[*user_fields.keys(), "updated_at"]
                    if user_fields else ["updated_at"]
                )

                if profile and profile_data:
                    def model_field(profile, key):
                        return "profile_bio" if key == "bio" and hasattr(profile, "profile_bio") else key

                    mapped_fields = [model_field(profile, k) for k in profile_data]
                    for k, v in profile_data.items():
                        setattr(profile, model_field(profile, k), v)
                    profile.save(update_fields=[*mapped_fields, "updated_at"])
        except IntegrityError as exc:
            # The serializer checks uniqueness first; this covers the race
            # between that check and the write.
            raise serializers.ValidationError(
                "That email or registration number is already in use."
            ) from exc
        return instance


class StudentListSerializer(serializers.ModelSerializer):
    """Admin-only directory listing (also powers User management).

    Only exposed through ``UserListView`` (``IsAdmin``), so account state is
    safe to include here -- the admin screen needs it to show who is blocked
    and to restore a soft-deleted account.
    """

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "status",
            "is_active",
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class RequestOtpSerializer(serializers.Serializer):
    """Accepts the account email. Existence is never revealed to the caller."""

    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class VerifyOtpSerializer(serializers.Serializer):
    """Validates the account email + the 6-digit OTP (no password yet)."""

    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)

    def validate_email(self, value):
        return value.strip().lower()

    def validate_otp(self, value):
        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be a 6-digit code.")
        return value


class ConfirmResetSerializer(serializers.Serializer):
    """Validates the emailed 6-digit OTP + the new password.

    The password is run through Django's configured validators here, so a weak
    password is rejected with a 400 before any OTP is consumed. ``newPassword``
    is accepted as an alias for ``new_password`` for API clients that use
    camelCase.
    """

    email = serializers.EmailField()
    otp = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def to_internal_value(self, data):
        if "new_password" not in data and "newPassword" in data:
            data = data.copy()
            data["new_password"] = data.get("newPassword")
        return super().to_internal_value(data)

    def validate_email(self, value):
        return value.strip().lower()

    def validate_otp(self, value):
        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError("OTP must be a 6-digit code.")
        return value

    def validate_new_password(self, value):
        validate_password(value)
        return value
