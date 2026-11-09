import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedUUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.SYSTEM_ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedUUIDModel):
    """Platform user. One unique account per academic identity (BR-001)."""

    class Role(models.TextChoices):
        STUDENT = "STUDENT", "Student"
        LECTURER = "LECTURER", "Lecturer"
        DEPARTMENT_ADMIN = "DEPARTMENT_ADMIN", "Department Administrator"
        FACULTY_ADMIN = "FACULTY_ADMIN", "Faculty Administrator"
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Administrator"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        ARCHIVED = "ARCHIVED", "Archived"

    class DeletionReason(models.TextChoices):
        NO_LONGER_NEEDED = "NO_LONGER_NEEDED", "I no longer need the account"
        GRADUATED = "GRADUATED", "I graduated or left the university"
        PRIVACY = "PRIVACY", "Privacy concerns"
        TOO_MANY_ISSUES = "TOO_MANY_ISSUES", "Problems or bugs with the platform"
        SWITCHING_ACCOUNT = "SWITCHING_ACCOUNT", "I want to create a new account"
        ADMIN_DELETED = "ADMIN_DELETED", "Deleted by an administrator"
        OTHER = "OTHER", "Other"

    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    admin_faculty = models.ForeignKey(
        "academics.Faculty", null=True, blank=True, on_delete=models.PROTECT,
        related_name="faculty_administrators",
    )
    admin_department = models.ForeignKey(
        "academics.Department", null=True, blank=True, on_delete=models.PROTECT,
        related_name="department_administrators",
    )
    date_of_birth = models.DateField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # Password reset via a 6-digit emailed OTP. Only the SHA-256 hash of the
    # code is stored, so a database leak cannot be used to reset a password.
    # All three fields are cleared once a reset succeeds (or the code burns).
    reset_otp_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    reset_otp_expires = models.DateTimeField(null=True, blank=True)
    reset_otp_attempts = models.PositiveIntegerField(default=0)

    # Self-deletion keeps the academic records but releases the identifiers so
    # the owner can register again. The original login identifiers are retained
    # here for administrators only; they are never used for authentication.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deletion_reason = models.CharField(
        max_length=30, choices=DeletionReason.choices, blank=True, default=""
    )
    deletion_improvement = models.TextField(blank=True, default="")
    deleted_from_email = models.EmailField(null=True, blank=True)
    deleted_from_personal_email = models.EmailField(null=True, blank=True)
    deleted_from_student_number = models.CharField(max_length=30, null=True, blank=True)
    deleted_from_staff_number = models.CharField(max_length=30, null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return f"{self.get_full_name()} <{self.email}>"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def clean(self):
        super().clean()
        if self.role == self.Role.FACULTY_ADMIN:
            if not self.admin_faculty_id or self.admin_department_id:
                raise ValidationError("Faculty administrators require exactly one faculty assignment.")
        elif self.role == self.Role.DEPARTMENT_ADMIN:
            if not self.admin_department_id or self.admin_faculty_id:
                raise ValidationError("Department administrators require exactly one department assignment.")
        elif self.admin_faculty_id or self.admin_department_id:
            raise ValidationError("Only faculty and department administrators may have an admin scope.")

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_lecturer(self):
        return self.role == self.Role.LECTURER

    @property
    def is_admin_role(self):
        return self.role in {self.Role.DEPARTMENT_ADMIN, self.Role.FACULTY_ADMIN, self.Role.SYSTEM_ADMIN}

    def record_login(self):
        self.last_login_at = timezone.now()
        self.save(update_fields=["last_login_at", "updated_at"])


class StudentProfile(TimeStampedUUIDModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    student_number = models.CharField(max_length=30, unique=True, null=True, blank=True, db_index=True)
    department = models.ForeignKey(
        "academics.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    admission_year = models.PositiveIntegerField(null=True, blank=True)
    level = models.CharField(max_length=20, blank=True, default="")
    personal_email = models.EmailField(null=True, blank=True)
    profile_bio = models.TextField(blank=True, default="")
    profile_image_reference = models.CharField(max_length=500, blank=True, default="")
    skills = models.JSONField(default=list, blank=True)
    achievements = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"StudentProfile({self.user.email})"


class LecturerProfile(TimeStampedUUIDModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="lecturer_profile")
    staff_number = models.CharField(max_length=30, unique=True, null=True, blank=True, db_index=True)
    department = models.ForeignKey(
        "academics.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="lecturers"
    )
    title = models.CharField(max_length=50, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    profile_image_reference = models.CharField(max_length=500, blank=True, default="")

    def __str__(self):
        return f"LecturerProfile({self.user.email})"
