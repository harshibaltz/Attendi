"""Class-list export for lecturers and administrators.

The CSV is a plain HttpResponse (not the JSON envelope) and only includes
active enrolments, so withdrawn records stay out of the attendance/class list.
"""
import csv
from io import StringIO

import pytest

from apps.academics.models import Course, CourseOffering, Department, Enrollment
from apps.accounts.models import LecturerProfile, StudentProfile, User


@pytest.fixture
def offering_with_teacher(course, academic_period, cs_department, lecturer_user):
    return CourseOffering.objects.create(
        course=course,
        semester=academic_period,
        department=cs_department,
        lecturer=lecturer_user,
    )


@pytest.fixture
def enrolled_pair(offering_with_teacher, cs_department):
    active = User.objects.create_user(
        email="active@test.edu", password="test1234",
        first_name="Ada", last_name="Active", role="STUDENT",
    )
    StudentProfile.objects.create(
        user=active, student_number="EXP001", department=cs_department, level="300",
    )
    dropped = User.objects.create_user(
        email="dropped@test.edu", password="test1234",
        first_name="Dee", last_name="Dropped", role="STUDENT",
    )
    StudentProfile.objects.create(
        user=dropped, student_number="EXP002", department=cs_department, level="300",
    )
    Enrollment.objects.create(
        student=active, course_offering=offering_with_teacher,
        status=Enrollment.Status.ACTIVE,
    )
    Enrollment.objects.create(
        student=dropped, course_offering=offering_with_teacher,
        status=Enrollment.Status.DROPPED,
    )
    return active, dropped


@pytest.mark.django_db
class TestEnrollmentExport:
    def test_lecturer_downloads_active_class_list(self, api_client, offering_with_teacher, enrolled_pair):
        active, _dropped = enrolled_pair
        api_client.force_authenticate(user=offering_with_teacher.lecturer)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
        )
        assert resp.status_code == 200, resp.content
        assert resp["Content-Type"].startswith("text/csv")
        assert "attachment; filename=" in resp["Content-Disposition"]
        body = resp.content.decode("utf-8-sig")
        assert "Ada Active" in body
        assert "EXP001" in body
        assert "Computer Science" in body
        assert "Dee Dropped" not in body
        assert "EXP002" not in body
        assert "active@test.edu" not in body
        assert "ACTIVE" not in body
        assert "Enrolled on" not in body

    def test_lecturer_downloads_pdf_class_list(self, api_client, offering_with_teacher, enrolled_pair):
        api_client.force_authenticate(user=offering_with_teacher.lecturer)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/?type=pdf"
        )
        assert resp.status_code == 200, resp.content
        assert resp["Content-Type"] == "application/pdf"
        assert "attachment; filename=" in resp["Content-Disposition"]
        assert resp["Content-Disposition"].endswith('.pdf"')
        assert resp.content.startswith(b"%PDF")

    def test_export_respects_sort_and_order(
        self, api_client, offering_with_teacher, enrolled_pair, cs_department
    ):
        active, _dropped = enrolled_pair
        maths = Department.objects.create(
            code="MATH", name="Mathematics", faculty=cs_department.faculty
        )
        zoe = User.objects.create_user(
            email="zoe@test.edu", password="test1234",
            first_name="Zoe", last_name="Zulu", role="STUDENT",
        )
        StudentProfile.objects.create(
            user=zoe, student_number="EXP003", department=maths, level="200",
        )
        Enrollment.objects.create(
            student=zoe, course_offering=offering_with_teacher,
            status=Enrollment.Status.ACTIVE,
        )

        api_client.force_authenticate(user=offering_with_teacher.lecturer)

        def names(sort, order):
            resp = api_client.get(
                f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
                f"?sort={sort}&order={order}"
            )
            assert resp.status_code == 200
            body = resp.content.decode("utf-8-sig")
            return [row["Student name"] for row in csv.DictReader(StringIO(body))]

        assert names("name", "desc")[0] == "Zoe Zulu"
        assert names("matricule", "desc")[0] == "Zoe Zulu"
        assert names("department", "desc")[0] == "Zoe Zulu"
        assert names("level", "asc")[0] == "Zoe Zulu"
        assert names("email", "asc")[0] == "Ada Active"

    def test_name_sort_matches_the_displayed_full_name(
        self, api_client, offering_with_teacher, enrolled_pair, cs_department
    ):
        aaron = User.objects.create_user(
            email="aaron@test.edu", password="test1234",
            first_name="Aaron", last_name="Zulu", role="STUDENT",
        )
        StudentProfile.objects.create(
            user=aaron, student_number="EXP004", department=cs_department, level="300",
        )
        Enrollment.objects.create(
            student=aaron, course_offering=offering_with_teacher,
            status=Enrollment.Status.ACTIVE,
        )
        api_client.force_authenticate(user=offering_with_teacher.lecturer)

        def rows(sort, order):
            resp = api_client.get(
                f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
                f"?sort={sort}&order={order}"
            )
            assert resp.status_code == 200
            body = resp.content.decode("utf-8-sig")
            return [row["Student name"] for row in csv.DictReader(StringIO(body))]

        # Displayed as "First Last": Aaron sorts before Ada by first name,
        # even though "Active" would sort before "Zulu" by surname.
        assert rows("name", "asc")[:2] == ["Aaron Zulu", "Ada Active"]
        assert rows("name", "desc")[:2] == ["Ada Active", "Aaron Zulu"]

    def test_roster_department_uses_the_full_name(
        self, api_client, offering_with_teacher, enrolled_pair
    ):
        active, _dropped = enrolled_pair
        api_client.force_authenticate(user=active)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/"
        )
        assert resp.status_code == 200
        row = next(r for r in resp.json()["data"] if r["student_number"] == "EXP001")
        assert row["department"] == "Computer Science"

    def test_pdf_numbers_rows_and_uses_the_full_department_name(
        self, api_client, offering_with_teacher, enrolled_pair, monkeypatch
    ):
        from django.http import HttpResponse

        captured = {}

        def fake_pdf(filename, title, subtitle, header, rows, column_weights=None):
            captured.update(
                header=header, rows=rows, column_weights=column_weights
            )
            return HttpResponse(b"%PDF", content_type="application/pdf")

        monkeypatch.setattr("apps.academics.views.pdf_table_response", fake_pdf)
        api_client.force_authenticate(user=offering_with_teacher.lecturer)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/?type=pdf"
        )
        assert resp.status_code == 200

        assert captured["header"] == [
            "No.", "Student name", "Matricule", "Department", "Level",
        ]
        assert len(captured["column_weights"]) == len(captured["header"])
        row = captured["rows"][0]
        assert len(row) == len(captured["header"])
        assert row[0] == 1
        assert row[3] == "Computer Science"
        assert row[4] == "300"

    def test_co_lecturer_can_download(self, api_client, offering_with_teacher, enrolled_pair, db):
        co = User.objects.create_user(
            email="co@test.edu", password="test1234",
            first_name="Co", last_name="Teacher", role="LECTURER",
        )
        offering_with_teacher.co_lecturer = co
        offering_with_teacher.save(update_fields=["co_lecturer"])
        api_client.force_authenticate(user=co)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
        )
        assert resp.status_code == 200

    def test_other_lecturer_cannot_download(self, api_client, offering_with_teacher, enrolled_pair, db):
        other = User.objects.create_user(
            email="other@test.edu", password="test1234",
            first_name="Other", last_name="Lecturer", role="LECTURER",
        )
        api_client.force_authenticate(user=other)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
        )
        assert resp.status_code == 403

    def test_department_admin_can_download(self, api_client, offering_with_teacher, enrolled_pair, cs_department):
        admin = User.objects.create_user(
            email="deptadmin@test.edu", password="test1234",
            first_name="Dept", last_name="Admin", role="DEPARTMENT_ADMIN",
            admin_department=cs_department,
        )
        api_client.force_authenticate(user=admin)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
        )
        assert resp.status_code == 200

    def test_student_cannot_download_but_can_read_own_list(
        self, api_client, offering_with_teacher, enrolled_pair
    ):
        active, _dropped = enrolled_pair
        api_client.force_authenticate(user=active)
        export = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/export/"
        )
        assert export.status_code == 403
        listing = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/"
        )
        assert listing.status_code == 200
        numbers = {row["student_number"] for row in listing.json()["data"]}
        assert "EXP001" in numbers

    def test_other_lecturer_cannot_read_roster(self, api_client, offering_with_teacher, enrolled_pair, db):
        other = User.objects.create_user(
            email="other2@test.edu", password="test1234",
            first_name="Other2", last_name="Lecturer", role="LECTURER",
        )
        api_client.force_authenticate(user=other)
        resp = api_client.get(
            f"/api/v1/course-offerings/{offering_with_teacher.id}/enrollments/"
        )
        assert resp.status_code == 403
