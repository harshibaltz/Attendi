"""Who may run attendance for an offering.

Three groups, in addition to scoped admins:
  * the assigned lecturer (lead or co-lecturer),
  * departmental course delegates (``Course.department_delegates`` - a student
    appointed for the course, covering every section/offering of it),
  * the class delegate of the offering (``projects.ClassDelegate`` - the
    existing per-class representative model).

This module is the single source of truth: API views and the `/auth/me/`
payload both call it, so the button the frontend renders and the permission
the backend enforces cannot drift apart.
"""
from django.db.models import Q

from apps.academics.models import CourseOffering
from apps.core.scoping import can_administer_offering, is_admin, is_offering_teacher
from apps.projects.models import ClassDelegate


def is_class_delegate(user, offering):
    if not getattr(user, "is_authenticated", False) or offering is None:
        return False
    return ClassDelegate.objects.filter(course_offering=offering, student=user).exists()


def is_department_delegate(user, course):
    if not getattr(user, "is_authenticated", False) or course is None:
        return False
    return course.department_delegates.filter(pk=user.pk).exists()


def can_launch_attendance(user, offering):
    """True when `user` may open an attendance session for this offering."""
    if not getattr(user, "is_authenticated", False) or offering is None:
        return False
    if is_admin(user):
        return can_administer_offering(user, offering)
    if is_offering_teacher(user, offering):
        return True
    return (
        is_department_delegate(user, offering.course)
        or is_class_delegate(user, offering)
    )


def launchable_offerings(user, queryset=None):
    """Offerings the user can launch attendance for, as a queryset."""
    qs = queryset if queryset is not None else CourseOffering.objects.all()
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if is_admin(user):
        if user.role == "SYSTEM_ADMIN":
            return qs
        if user.role == "FACULTY_ADMIN":
            return qs.filter(
                Q(department__faculty_id=user.admin_faculty_id)
                | Q(departments__faculty_id=user.admin_faculty_id)
            ).distinct()
        return qs.filter(
            Q(department_id=user.admin_department_id)
            | Q(departments=user.admin_department_id)
        ).distinct()
    return qs.filter(
        Q(lecturer=user)
        | Q(co_lecturer=user)
        | Q(class_delegate__student=user)
        | Q(course__department_delegates=user)
    ).distinct()
