"""A student can withdraw from a course they registered for."""
import pytest
from rest_framework.test import APIClient

from apps.academics.models import Enrollment

pytestmark = pytest.mark.django_db


def _delete(user, offering, student_id):
    client = APIClient()
    client.force_authenticate(user=user)
    return client.delete(
        f"/api/v1/course-offerings/{offering.id}/enrollments/{student_id}/"
    )


def test_student_can_drop_own_active_enrollment(enrolled_student, offering, academic_period):
    academic_period.is_active = True
    academic_period.save(update_fields=["is_active"])

    response = _delete(enrolled_student, offering, enrolled_student.id)

    assert response.status_code == 204, response.content
    enrollment = Enrollment.objects.get(student=enrolled_student, course_offering=offering)
    assert enrollment.status == Enrollment.Status.DROPPED
    assert enrollment.dropped_at is not None


def test_student_cannot_drop_another_students_course(enrolled_student, student2_user, offering, academic_period):
    academic_period.is_active = True
    academic_period.save(update_fields=["is_active"])

    response = _delete(student2_user, offering, enrolled_student.id)

    assert response.status_code == 403
    assert Enrollment.objects.get(student=enrolled_student, course_offering=offering).status == Enrollment.Status.ACTIVE


def test_student_cannot_drop_in_inactive_semester(enrolled_student, offering):
    response = _delete(enrolled_student, offering, enrolled_student.id)

    assert response.status_code == 403
    assert Enrollment.objects.get(student=enrolled_student, course_offering=offering).status == Enrollment.Status.ACTIVE


def test_lecturer_can_still_remove_a_student(enrolled_student, offering, lecturer_user, academic_period):
    academic_period.is_active = True
    academic_period.save(update_fields=["is_active"])
    offering.lecturer = lecturer_user
    offering.save(update_fields=["lecturer"])

    response = _delete(lecturer_user, offering, enrolled_student.id)

    assert response.status_code == 204
    assert Enrollment.objects.get(student=enrolled_student, course_offering=offering).status == Enrollment.Status.DROPPED
