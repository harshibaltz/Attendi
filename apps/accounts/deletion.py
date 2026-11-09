"""Account closure: release the login and remove course/attendance activity."""
from django.db import transaction
from django.utils import timezone


def purge_course_and_attendance_data(user):
    """Delete the user's enrolments, attendance records, stations and points.

    Self-deletion releases the login identifiers, so keeping these rows would
    leave the closed account visible as an active student in class lists and
    attendance history. Returns a count summary for the audit log.
    """
    from apps.academics.models import Enrollment
    from apps.attendance.models import (
        AttendanceCheckpoint,
        AttendanceRecord,
        PointsLedger,
    )

    with transaction.atomic():
        records = AttendanceRecord.objects.filter(student=user).delete()[0]
        checkpoints = AttendanceCheckpoint.objects.filter(student=user).delete()[0]
        points = PointsLedger.objects.filter(student=user).delete()[0]
        enrollments = Enrollment.objects.filter(student=user).delete()[0]
    return {
        "attendance_records": records,
        "checkpoints": checkpoints,
        "points_entries": points,
        "enrollments": enrollments,
    }


def archive_account(user, *, reason, improvement=""):
    """Anonymise the account row, make the login unusable, and purge activity.

    The caller must hold a row lock inside a transaction. Original identifiers
    are copied to ``deleted_from_*`` so an administrator can identify (and
    optionally restore) the closed account after the email/matricule are freed.
    """
    student_profile = getattr(user, "student_profile", None)
    lecturer_profile = getattr(user, "lecturer_profile", None)

    user.deleted_at = timezone.now()
    user.deletion_reason = reason
    user.deletion_improvement = improvement
    user.deleted_from_email = user.email
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.is_active = False
    user.status = user.Status.ARCHIVED
    user.must_change_password = False
    user.reset_otp_hash = None
    user.reset_otp_expires = None
    user.reset_otp_attempts = 0
    user.set_unusable_password()

    if student_profile is not None:
        user.deleted_from_personal_email = student_profile.personal_email
        user.deleted_from_student_number = student_profile.student_number
        student_profile.student_number = None
        student_profile.personal_email = None
        student_profile.profile_image_reference = ""
        student_profile.profile_bio = ""
        student_profile.skills = []
        student_profile.achievements = []
        student_profile.save(
            update_fields=[
                "student_number",
                "personal_email",
                "profile_image_reference",
                "profile_bio",
                "skills",
                "achievements",
                "updated_at",
            ]
        )
    elif lecturer_profile is not None:
        user.deleted_from_staff_number = lecturer_profile.staff_number
        lecturer_profile.staff_number = None
        lecturer_profile.profile_image_reference = ""
        lecturer_profile.bio = ""
        lecturer_profile.save(
            update_fields=[
                "staff_number",
                "profile_image_reference",
                "bio",
                "updated_at",
            ]
        )

    purged = purge_course_and_attendance_data(user)
    user.save(
        update_fields=[
            "deleted_at",
            "deletion_reason",
            "deletion_improvement",
            "deleted_from_email",
            "deleted_from_personal_email",
            "deleted_from_student_number",
            "deleted_from_staff_number",
            "email",
            "is_active",
            "status",
            "must_change_password",
            "reset_otp_hash",
            "reset_otp_expires",
            "reset_otp_attempts",
            "password",
            "updated_at",
        ]
    )
    return purged
