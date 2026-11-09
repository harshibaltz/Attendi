"""Tests for Google-Classroom-style classroom creation (Phase 2).

A lecturer opens a classroom for one of their own department's courses and
every student registered for that course (same department + level) is
enrolled automatically.
"""
import pytest

from apps.academics.models import Course, CourseOffering, Enrollment, Semester
from apps.accounts.models import LecturerProfile, StudentProfile, User


@pytest.fixture
def active_semester(db):
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.now().date()
    return Semester.objects.create(
        name="2026/2027 Semester 1",
        academic_year="2026/2027",
        number="1",
        start_date=now - timedelta(days=7),
        end_date=now + timedelta(days=120),
        is_active=True,
    )


@pytest.fixture
def dept_lecturer(cs_department, db):
    user = User.objects.create_user(
        email="owner.lecturer@test.edu", password="test1234",
        first_name="Owning", last_name="Lecturer", role="LECTURER",
    )
    LecturerProfile.objects.create(
        user=user, staff_number="STF900", department=cs_department, title="Dr."
    )
    return user


@pytest.fixture
def other_dept(faculty, db):
    from apps.academics.models import Department

    return Department.objects.create(code="EE", name="Electrical Engineering", faculty=faculty)


@pytest.fixture
def other_lecturer(other_dept, db):
    user = User.objects.create_user(
        email="ee.lecturer@test.edu", password="test1234",
        first_name="Other", last_name="Lecturer", role="LECTURER",
    )
    LecturerProfile.objects.create(
        user=user, staff_number="STF901", department=other_dept, title="Mr."
    )
    return user


def make_cohort(department, level, count, prefix="S"):
    students = []
    for i in range(count):
        s = User.objects.create_user(
            email=f"{prefix.lower()}{i}@test.edu", password="test1234",
            first_name=f"{prefix}{i}", last_name="Test", role="STUDENT",
        )
        StudentProfile.objects.create(
            user=s, student_number=f"{prefix}{i:03d}", department=department, level=level
        )
        students.append(s)
    return students


@pytest.mark.django_db
class TestClassroomCreation:
    def test_student_cannot_create_classroom(self, api_client, cs_department, student_user, active_semester, db):
        course = Course.objects.create(code="CSC901", title="X", department=cs_department, level="300")
        api_client.force_authenticate(user=student_user)
        resp = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert resp.status_code == 403

    def test_available_courses_scoped_to_own_department(
        self, api_client, cs_department, other_dept, dept_lecturer, other_lecturer, active_semester, db
    ):
        Course.objects.create(code="CSC901", title="Mine", department=cs_department, level="300")
        Course.objects.create(code="EE901", title="Theirs", department=other_dept, level="300")
        api_client.force_authenticate(user=dept_lecturer)
        resp = api_client.get("/api/v1/classrooms/available-courses/")
        assert resp.status_code == 200
        codes = {c["course_code"] for c in resp.json()["data"]["courses"]}
        assert "CSC901" in codes
        assert "EE901" not in codes

    def test_create_classroom_auto_enrolls_cohort(
        self, api_client, cs_department, dept_lecturer, active_semester, db
    ):
        course = Course.objects.create(code="CSC902", title="Auto Enrol", department=cs_department, level="300")
        cohort = make_cohort(cs_department, "300", 3)
        # A different level must NOT be pulled in.
        make_cohort(cs_department, "200", 2, prefix="L")

        api_client.force_authenticate(user=dept_lecturer)
        resp = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert resp.status_code == 201, resp.content
        data = resp.json()["data"]
        assert data["auto_enrolled"] == 3
        assert data["cohort_size"] == 3

        offering = CourseOffering.objects.get(course=course, semester=active_semester)
        enrolled_ids = set(
            offering.enrollments.filter(status=Enrollment.Status.ACTIVE).values_list("student_id", flat=True)
        )
        assert enrolled_ids == {s.id for s in cohort}

    def test_lecturer_cannot_create_for_other_department_course(
        self, api_client, other_dept, dept_lecturer, active_semester, db
    ):
        course = Course.objects.create(code="EE902", title="Not Mine", department=other_dept, level="300")
        api_client.force_authenticate(user=dept_lecturer)
        resp = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert resp.status_code == 404

    def test_duplicate_classroom_conflicts(
        self, api_client, cs_department, dept_lecturer, active_semester, db
    ):
        course = Course.objects.create(code="CSC903", title="Dup", department=cs_department, level="300")
        api_client.force_authenticate(user=dept_lecturer)
        first = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert first.status_code == 201
        second = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert second.status_code == 409

    def test_enrollment_is_not_duplicated(
        self, api_client, cs_department, dept_lecturer, active_semester, db
    ):
        course = Course.objects.create(code="CSC904", title="Idem", department=cs_department, level="300")
        cohort = make_cohort(cs_department, "300", 3)
        api_client.force_authenticate(user=dept_lecturer)
        resp = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert resp.status_code == 201
        assert resp.json()["data"]["auto_enrolled"] == 3

        offering = CourseOffering.objects.get(course=course, semester=active_semester)
        # Exactly one enrollment per cohort member - no duplicates.
        assert offering.enrollments.count() == 3
        for student in cohort:
            assert offering.enrollments.filter(student=student).count() == 1

    def test_course_id_required(self, api_client, dept_lecturer, active_semester, db):
        api_client.force_authenticate(user=dept_lecturer)
        resp = api_client.post("/api/v1/classrooms/", {}, format="json")
        assert resp.status_code == 400

    def test_admin_may_create_for_any_department(
        self, api_client, other_dept, active_semester, db
    ):
        from apps.accounts.models import User as U

        admin = U.objects.create_user(
            email="sysadmin@test.edu", password="test1234",
            first_name="Sys", last_name="Admin", role="SYSTEM_ADMIN", is_staff=True,
        )
        course = Course.objects.create(code="EE903", title="Admin Made", department=other_dept, level="300")
        api_client.force_authenticate(user=admin)
        resp = api_client.post("/api/v1/classrooms/", {"course_id": str(course.id)}, format="json")
        assert resp.status_code == 201


@pytest.mark.django_db
def test_offering_list_returns_actual_classroom_counts(
    api_client, cs_department, dept_lecturer, student_user, active_semester, db
):
    from apps.announcements.models import Announcement
    from apps.learning.models import Assessment, Assignment, LearningMaterial

    course = Course.objects.create(code="CSC905", title="Counted", department=cs_department, level="300")
    offering = CourseOffering.objects.create(
        course=course, semester=active_semester, department=cs_department, lecturer=dept_lecturer,
    )
    Enrollment.objects.create(student=student_user, course_offering=offering)
    Enrollment.objects.create(
        student=make_cohort(cs_department, "300", 1, prefix="D")[0],
        course_offering=offering,
        status=Enrollment.Status.DROPPED,
    )
    LearningMaterial.objects.create(
        course_offering=offering, uploaded_by=dept_lecturer, title="Slides",
    )
    Assignment.objects.create(
        course_offering=offering, created_by=dept_lecturer, title="Task",
    )
    Assessment.objects.create(
        course_offering=offering, created_by=dept_lecturer, title="CA",
    )
    Announcement.objects.create(
        created_by=dept_lecturer, scope_type=Announcement.ScopeType.COURSE,
        course_offering=offering, title="Notice", content="Hello",
    )

    api_client.force_authenticate(user=dept_lecturer)
    resp = api_client.get("/api/v1/course-offerings/")
    assert resp.status_code == 200, resp.content
    rows = resp.json()["data"] if isinstance(resp.json(), dict) else resp.json()
    row = next(r for r in rows if r["id"] == str(offering.id))
    assert row["materials_count"] == 1
    assert row["announcements_count"] == 1
    assert row["assignments_count"] == 1
    assert row["assessments_count"] == 1
    assert row["enrolled_students"] == 1
