"""Shared academic provisioning helpers.

Kept out of the views so that opening a classroom and assigning a lecturer to an
offering prime the offering the same way: the same cohort, the same enrollment
semantics.
"""
from django.utils import timezone

from apps.accounts.models import StudentProfile, User

from .models import Course, Enrollment


def _level_rank(value):
    """Numeric rank for a level label ("300" -> 300), or None if not numeric."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def allowed_course_levels(student_level):
    """Course levels a student may take: their own level and every lower level.

    Levels are stored as short strings ("100".."500"), so compare them as
    numbers when possible and fall back to an exact match for custom labels.
    """
    normalized = str(student_level or "").strip()
    rank = _level_rank(normalized)
    if rank is None:
        return {normalized} if normalized else set()
    levels = set(Course.objects.exclude(level="").values_list("level", flat=True).distinct())
    levels.add(normalized)
    return {
        level for level in levels
        if _level_rank(level) is not None and _level_rank(level) <= rank
    }


def levels_for_course(course_level):
    """Student levels that may take a course: its own level and every higher level."""
    normalized = str(course_level or "").strip()
    rank = _level_rank(normalized)
    if rank is None:
        return {normalized} if normalized else set()
    levels = set(
        StudentProfile.objects.exclude(level="").values_list("level", flat=True).distinct()
    )
    levels.add(normalized)
    return {
        level for level in levels
        if _level_rank(level) is not None and _level_rank(level) >= rank
    }


def effective_registration_deadline(offering):
    """The offering's own deadline, falling back to the semester-wide one."""
    return offering.registration_deadline or offering.semester.registration_deadline


def registration_is_closed(offering, today=None):
    deadline = effective_registration_deadline(offering)
    if deadline is None:
        return False
    return (today or timezone.localdate()) > deadline


def cohort_queryset(offering):
    """Students who belong in any participating department of an offering.

    Uses active students in the primary and shared departments, narrowed to
    the course level when the course declares one.
    """
    course = offering.course
    qs = User.objects.filter(
        role=User.Role.STUDENT,
        is_active=True,
        student_profile__department_id__in=offering.all_department_ids,
    )
    if course.level:
        # A higher-level student may take a lower-level course, so the cohort
        # is "this level or above" rather than an exact match.
        qs = qs.filter(student_profile__level__in=levels_for_course(course.level))
    return qs


def enroll_cohort(offering):
    """Idempotently enroll the offering's cohort.

    Returns the number of *new* enrollments created; students already enrolled
    are left untouched.
    """
    created = 0
    for student in cohort_queryset(offering):
        _enrollment, was_created = Enrollment.objects.get_or_create(
            student=student,
            course_offering=offering,
            defaults={"status": Enrollment.Status.ACTIVE},
        )
        if was_created:
            created += 1
    return created
