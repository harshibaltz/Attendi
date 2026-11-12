import pytest

from apps.accounts.models import StudentProfile, User
from apps.academics.models import Department, Enrollment, Faculty


@pytest.mark.django_db
def test_faculty_admin_shares_existing_offering_with_own_faculty(api_client, course, offering, cs_department):
    peer = Department.objects.create(code="PEER", name="Peer", faculty=cs_department.faculty)
    foreign_faculty = Faculty.objects.create(code="FOREIGN", name="Foreign")
    foreign = Department.objects.create(code="FDEPT", name="Foreign Department", faculty=foreign_faculty)
    student = User.objects.create_user(email="peer@test.edu", password="pass1234", role="STUDENT")
    StudentProfile.objects.create(user=student, department=peer, level="300")
    course.level = "300"
    course.save(update_fields=["level"])
    lecturer = User.objects.create_user(email="teacher-share@test.edu", password="pass1234", role="LECTURER")
    offering.lecturer = lecturer
    offering.save(update_fields=["lecturer"])
    admin = User.objects.create_user(email="share-admin@test.edu", password="pass1234", role="FACULTY_ADMIN", admin_faculty=cs_department.faculty)
    api_client.force_authenticate(user=admin)
    url = f"/api/v1/course-offerings/{offering.id}/"
    assert api_client.patch(url, {"departments": [str(foreign.id)]}, format="json").status_code == 400
    shared = api_client.patch(url, {"departments": [str(peer.id)]}, format="json")
    assert shared.status_code == 200, shared.content
    # Sharing a department does not auto-enroll that department's students.
    assert Enrollment.objects.filter(student=student, course_offering=offering).count() == 0

    # Once the student registers themselves, removing the shared department
    # still drops their enrollment.
    Enrollment.objects.create(
        student=student, course_offering=offering, status=Enrollment.Status.ACTIVE
    )
    assert api_client.patch(url, {"departments": []}, format="json").status_code == 200
    assert Enrollment.objects.filter(student=student, course_offering=offering).count() == 1
    assert Enrollment.objects.get(student=student, course_offering=offering).status == Enrollment.Status.DROPPED
