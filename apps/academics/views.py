"""Academics views (API Spec doc 07 §§16-23).

Faculty, Department, Course, Offering, Enrollment, ClassDefinition, ClassSession.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db import models as db_models
from django.shortcuts import get_object_or_404
from django.utils import timezone as tz
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.permissions import IsAdmin, IsLecturerOrAdmin
from apps.core.scoping import (
    can_administer_department, can_administer_offering, is_admin,
    is_offering_teacher, scope_by_department, scope_users,
)
from apps.audit.services import audit
from apps.core.csv_export import csv_response
from apps.core.pdf_export import pdf_table_response
from apps.learning.models import Assessment, AssessmentMark, AssignmentSubmission

from .models import (
    Semester,
    CarryOverApplication,
    ClassDefinition,
    ClassSchedule,
    ClassSession,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Faculty,
)
from .services import (
    allowed_course_levels,
    effective_registration_deadline,
    enroll_cohort,
    registration_is_closed,
)
from .serializers import (
    SemesterSerializer,
    ClassDefinitionSerializer,
    ClassScheduleSerializer,
    ClassSessionSerializer,
    CourseOfferingSerializer,
    CourseSerializer,
    DepartmentSerializer,
    EnrollmentSerializer,
    FacultySerializer,
    StudentBriefSerializer,
)


class FacultyListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(FacultySerializer(Faculty.objects.all(), many=True).data)


class FacultyCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        if request.user.role != User.Role.SYSTEM_ADMIN:
            return Response(status=status.HTTP_403_FORBIDDEN)
        s = FacultySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        faculty = s.save()
        audit(user=request.user, action="FACULTY_CREATED", resource_type="Faculty", resource_id=faculty.id, request=request)
        return Response(FacultySerializer(faculty).data, status=status.HTTP_201_CREATED)


class FacultyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, faculty_id):
        faculty = get_object_or_404(Faculty, id=faculty_id)
        return Response(FacultySerializer(faculty).data)


class DepartmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Department.objects.select_related("faculty").all()
        faculty_id = request.query_params.get("faculty_id")
        if faculty_id:
            qs = qs.filter(faculty_id=faculty_id)
        return Response(DepartmentSerializer(qs, many=True).data)


class PublicDepartmentListView(APIView):
    """GET /api/v1/departments/public/ - used by the self-registration form."""

    permission_classes = [AllowAny]

    def get(self, request):
        from rest_framework.permissions import AllowAny as _AllowAny
        qs = Department.objects.select_related("faculty").filter(status="ACTIVE")
        return Response(DepartmentSerializer(qs, many=True).data)


class DepartmentCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        s = DepartmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not request.user.role == User.Role.SYSTEM_ADMIN and not (
            request.user.role == User.Role.FACULTY_ADMIN
            and s.validated_data["faculty"].id == request.user.admin_faculty_id
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)
        dept = s.save()
        audit(user=request.user, action="DEPARTMENT_CREATED", resource_type="Department", resource_id=dept.id, request=request)
        return Response(DepartmentSerializer(dept).data, status=status.HTTP_201_CREATED)


class DepartmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, department_id):
        dept = get_object_or_404(Department, id=department_id)
        return Response(DepartmentSerializer(dept).data)


class SemesterListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(SemesterSerializer(Semester.objects.all(), many=True).data)


class SemesterDetailView(APIView):
    """PATCH /api/v1/semesters/{id}/ - set the registration cut-off (system admin).

    Semesters are institution-wide, so only a SYSTEM_ADMIN may change these
    dates; faculty/department admins set per-course deadlines on the offering.
    """

    permission_classes = [IsAuthenticated]

    EDITABLE = {"registration_deadline", "start_date", "end_date"}

    def patch(self, request, semester_id):
        if request.user.role != User.Role.SYSTEM_ADMIN:
            return Response(status=status.HTTP_403_FORBIDDEN)
        semester = get_object_or_404(Semester, id=semester_id)
        data = {key: value for key, value in request.data.items() if key in self.EDITABLE}
        if not data:
            return Response(
                {"success": False, "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Send at least one of: registration_deadline, start_date, end_date.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = SemesterSerializer(semester, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit(
            user=request.user,
            action="SEMESTER_UPDATED",
            resource_type="Semester",
            resource_id=semester.id,
            request=request,
            metadata={key: str(value) for key, value in data.items()},
        )
        return Response(serializer.data)


class SemesterActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, semester_id):
        if request.user.role != User.Role.SYSTEM_ADMIN:
            return Response({"error": "Forbidden"}, status=403)
        semester = get_object_or_404(Semester, id=semester_id)
        semester.is_active = True
        semester.save()
        # Returned bare: SuccessRenderer already wraps it as {success, data}.
        return Response(SemesterSerializer(semester).data)


class AdminStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_admin(request.user):
            return Response({"error": "Forbidden"}, status=403)

        from apps.accounts.models import User, StudentProfile, LecturerProfile

        active_semester = Semester.objects.filter(is_active=True).first()
        stats = {
            "total_students": scope_users(User.objects.filter(role="STUDENT"), request.user).count(),
            "total_lecturers": scope_users(User.objects.filter(role="LECTURER"), request.user).count(),
            "total_departments": 0,
            "total_courses": 0,
            "total_offerings": 0,
            "total_enrollments": 0,
            "active_semester": None,
        }

        if active_semester:
            stats["active_semester"] = {
                "id": str(active_semester.id),
                "name": active_semester.name,
                "academic_year": active_semester.academic_year,
                "number": active_semester.number,
            }
            stats["total_offerings"] = scope_by_department(
                CourseOffering.objects.filter(semester=active_semester), request.user,
            ).count()
            stats["total_enrollments"] = scope_by_department(Enrollment.objects.filter(
                course_offering__semester=active_semester,
                status=Enrollment.Status.ACTIVE,
            ), request.user, "course_offering__department").count()

        stats["total_courses"] = scope_by_department(Course.objects.all(), request.user).count()
        stats["total_departments"] = scope_by_department(Department.objects.all(), request.user, "id").count()

        # Returned bare: SuccessRenderer already wraps it as {success, data}.
        return Response(stats)


class CourseListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Course.objects.select_related("department").all()
        department_id = request.query_params.get("department_id")
        level = request.query_params.get("level")
        search = request.query_params.get("search")
        if department_id:
            qs = qs.filter(
                db_models.Q(department_id=department_id)
                | db_models.Q(offerings__departments__id=department_id)
            ).distinct()
        if level:
            qs = qs.filter(level=level)
        if search:
            qs = qs.filter(db_models.Q(title__icontains=search) | db_models.Q(code__icontains=search))
        return Response(CourseSerializer(qs, many=True).data)

    def post(self, request):
        if not is_admin(request.user):
            return Response(status=status.HTTP_403_FORBIDDEN)
        s = CourseSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not can_administer_department(request.user, s.validated_data["department"]):
            return Response(status=status.HTTP_403_FORBIDDEN)
        course = s.save()
        audit(user=request.user, action="COURSE_CREATED", resource_type="Course", resource_id=course.id, request=request)
        return Response(CourseSerializer(course).data, status=status.HTTP_201_CREATED)


class CourseExportView(APIView):
    """GET /api/v1/courses/export/ - every course the admin can see, as CSV.

    Columns include the owning department/faculty, curriculum details and the
    live usage figures (number of offerings and active enrolments).
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    HEADER = [
        "Course code",
        "Course title",
        "Department",
        "Faculty",
        "Level",
        "Credit units",
        "Status",
        "Offerings",
        "Active enrolments",
    ]

    def get(self, request):
        from django.utils import timezone as tz

        qs = Course.objects.select_related("department__faculty").annotate(
            offering_count=db_models.Count("offerings", distinct=True),
            active_enrolments=db_models.Count(
                "offerings__enrollments",
                filter=db_models.Q(offerings__enrollments__status=Enrollment.Status.ACTIVE),
                distinct=True,
            ),
        )
        qs = scope_by_department(qs, request.user, "department")

        department_id = request.query_params.get("department_id")
        level = request.query_params.get("level")
        search = (request.query_params.get("search") or "").strip()
        if department_id:
            qs = qs.filter(department_id=department_id)
        if level:
            qs = qs.filter(level=level)
        if search:
            qs = qs.filter(
                db_models.Q(code__icontains=search) | db_models.Q(title__icontains=search)
            )
        qs = qs.order_by("department__code", "code")

        filename = f"courses-{tz.localdate().isoformat()}.csv"
        return csv_response(
            filename,
            self.HEADER,
            [
                [
                    course.code,
                    course.title,
                    course.department.name if course.department else "",
                    course.department.faculty.name if course.department and course.department.faculty else "",
                    course.level or "",
                    course.credit_units,
                    course.status,
                    course.offering_count,
                    course.active_enrolments,
                ]
                for course in qs
            ],
        )


class CourseDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        return Response(CourseSerializer(course).data)


class CourseOfferingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            CourseOffering.objects
            .select_related("course", "semester", "department", "lecturer", "co_lecturer")
            .prefetch_related("departments")
            .annotate(
                materials_count=db_models.Count("materials", distinct=True),
                announcements_count=db_models.Count("announcements", distinct=True),
                assignments_count=db_models.Count("assignments", distinct=True),
                assessments_count=db_models.Count("assessments", distinct=True),
                enrolled_students=db_models.Count(
                    "enrollments",
                    filter=db_models.Q(enrollments__status=Enrollment.Status.ACTIVE),
                    distinct=True,
                ),
            )
            .all()
        )
        for param in ("course_id", "semester_id"):
            val = request.query_params.get(param)
            if val:
                qs = qs.filter(**{param: val})
        department_id = request.query_params.get("department_id")
        if department_id:
            # A cross-department offering is listed for every department that
            # can register for it, not only its primary department.
            qs = qs.filter(
                db_models.Q(department_id=department_id)
                | db_models.Q(departments__id=department_id)
            ).distinct()
        return Response(CourseOfferingSerializer(qs, many=True).data)


class CourseOfferingCreateView(APIView):
    permission_classes = [IsAuthenticated, IsLecturerOrAdmin]

    def post(self, request):
        s = CourseOfferingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if s.validated_data["course"].department_id != s.validated_data["department"].id:
            return Response({"error": "The offering must belong to its course's department."},
                            status=status.HTTP_400_BAD_REQUEST)
        shared = s.validated_data.get("departments", [])
        if shared:
            primary = s.validated_data["department"]
            if request.user.role not in {User.Role.SYSTEM_ADMIN, User.Role.FACULTY_ADMIN} or not can_administer_department(request.user, primary):
                return Response(status=status.HTTP_403_FORBIDDEN)
            if any(department.faculty_id != primary.faculty_id for department in shared):
                return Response({"error": "Shared departments must belong to the course faculty."}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_department(
            request.user, s.validated_data["department"]
        ):
            return Response(status=status.HTTP_403_FORBIDDEN)
        lecturer = s.validated_data.get("lecturer")
        co_lecturer = s.validated_data.get("co_lecturer")
        if lecturer and co_lecturer and lecturer.id == co_lecturer.id:
            return Response(
                {"error": "The co-lecturer must be different from the lead lecturer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN}:
            for teacher in (lecturer, co_lecturer):
                if teacher and not scope_users(User.objects.filter(id=teacher.id), request.user).exists():
                    return Response(status=status.HTTP_403_FORBIDDEN)
        offering = s.save()
        return Response(CourseOfferingSerializer(offering).data, status=status.HTTP_201_CREATED)


class CourseOfferingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        return Response(CourseOfferingSerializer(offering).data)

    def patch(self, request, offering_id):
        if not IsAdmin().has_permission(request, self):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only administrators can manage course offerings."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        editable = {"lecturer", "co_lecturer", "departments", "registration_deadline"}
        if not editable.intersection(request.data):
            return Response(
                {"success": False, "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Send at least one of: lecturer, co_lecturer, departments, registration_deadline.",
                }},
                status=status.HTTP_400_BAD_REQUEST,
            )

        offering = get_object_or_404(CourseOffering, id=offering_id)
        if not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)

        def _resolve_teacher(key):
            """Validate one optional lecturer field; returns (sent, value)."""
            if key not in request.data:
                return False, None
            teacher_id = request.data.get(key)
            if not teacher_id:
                return True, None
            teacher = get_object_or_404(
                User, id=teacher_id, role="LECTURER", is_active=True, status=User.Status.ACTIVE
            )
            if request.user.role != User.Role.SYSTEM_ADMIN and not scope_users(
                User.objects.filter(id=teacher.id), request.user
            ).exists():
                raise PermissionError
            return True, teacher

        try:
            lecturer_sent, lecturer = _resolve_teacher("lecturer")
            co_sent, co_lecturer = _resolve_teacher("co_lecturer")
        except PermissionError:
            return Response(status=status.HTTP_403_FORBIDDEN)

        department_ids = None
        if "departments" in request.data:
            if request.user.role not in {User.Role.SYSTEM_ADMIN, User.Role.FACULTY_ADMIN} or not can_administer_department(request.user, offering.department):
                return Response(status=status.HTTP_403_FORBIDDEN)
            raw_ids = request.data.get("departments") or []
            if not isinstance(raw_ids, list):
                return Response(
                    {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "departments must be a list of department ids."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            departments = list(Department.objects.filter(id__in=raw_ids))
            requested_ids = {str(i) for i in raw_ids}
            if len(departments) != len(requested_ids):
                return Response(
                    {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "One or more departments do not exist."}},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if any(department.faculty_id != offering.department.faculty_id for department in departments):
                return Response({"error": "Shared departments must belong to the course faculty."}, status=status.HTTP_400_BAD_REQUEST)
            department_ids = [d.id for d in departments]

        deadline_sent = "registration_deadline" in request.data
        deadline = None
        if deadline_sent:
            raw_deadline = request.data.get("registration_deadline")
            if raw_deadline in (None, ""):
                deadline = None
            else:
                deadline = parse_date(str(raw_deadline))
                if deadline is None:
                    return Response(
                        {"success": False, "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "registration_deadline must be a date (YYYY-MM-DD) or null.",
                        }},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        final_lecturer_id = (lecturer.id if lecturer else None) if lecturer_sent else offering.lecturer_id
        final_co_id = (co_lecturer.id if co_lecturer else None) if co_sent else offering.co_lecturer_id
        if final_lecturer_id and final_co_id and final_lecturer_id == final_co_id:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "The co-lecturer must be different from the lead lecturer."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Assigning a lecturer must hand them a ready-to-use classroom: the
        # offering is theirs (so it shows on their panel and attendance works),
        # and an empty offering is primed with its cohort so there are students
        # to mark. Locked so a concurrent assignment cannot double-enroll.
        with transaction.atomic():
            offering = CourseOffering.objects.select_for_update().get(id=offering_id)
            previous_lecturer_id = offering.lecturer_id
            update_fields = []
            if lecturer_sent:
                offering.lecturer = lecturer
                update_fields.append("lecturer")
            if co_sent:
                offering.co_lecturer = co_lecturer
                update_fields.append("co_lecturer")
            if deadline_sent:
                offering.registration_deadline = deadline
                update_fields.append("registration_deadline")
            if update_fields:
                offering.save(update_fields=[*update_fields, "updated_at"])
            if lecturer_sent and lecturer is not None and not Enrollment.objects.filter(course_offering=offering).exists():
                enroll_cohort(offering)
            if department_ids is not None:
                removed_ids = set(offering.departments.values_list("id", flat=True)) - set(department_ids)
                offering.departments.set(department_ids)
                for enrollment in Enrollment.objects.filter(
                    course_offering=offering,
                    student__student_profile__department_id__in=removed_ids,
                    status=Enrollment.Status.ACTIVE,
                ):
                    enrollment.status = Enrollment.Status.DROPPED
                    enrollment.dropped_at = tz.now()
                    enrollment.save(update_fields=["status", "dropped_at", "updated_at"])
                if offering.lecturer_id:
                    enroll_cohort(offering)
        audit(
            user=request.user,
            action="COURSE_OFFERING_UPDATED",
            resource_type="CourseOffering",
            resource_id=offering.id,
            request=request,
            metadata={
                "previous_lecturer_id": str(previous_lecturer_id or ""),
                "lecturer_id": str(offering.lecturer_id or ""),
                "co_lecturer_id": str(offering.co_lecturer_id or ""),
                "shared_department_ids": [str(i) for i in (department_ids or [])],
            },
        )
        return Response(CourseOfferingSerializer(offering).data)


# ---------------------------------------------------------------------------
# Enrollment (API Spec doc 07 §20)
# ---------------------------------------------------------------------------

class EnrollmentListView(APIView):
    """GET enrolled students for a course offering."""

    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == User.Role.LECTURER and not is_offering_teacher(request.user, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You do not teach this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if request.user.role == "STUDENT":
            if not Enrollment.objects.filter(student=request.user, course_offering=offering, status=Enrollment.Status.ACTIVE).exists():
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not enrolled in this course."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        enrollments = (
            Enrollment.objects.filter(course_offering=offering)
            .select_related("student", "student__student_profile", "student__student_profile__department")
        )
        return Response(EnrollmentSerializer(enrollments, many=True).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if not offering.semester.is_active:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Enrollment is only open for the active semester."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only authorized staff can enroll students."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        student_id = request.data.get("student_id")
        student = get_object_or_404(User, id=student_id, role="STUDENT")
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not scope_users(
            User.objects.filter(id=student.id), request.user
        ).exists():
            return Response(status=status.HTTP_403_FORBIDDEN)
        if Enrollment.objects.filter(student=student, course_offering=offering, status=Enrollment.Status.ACTIVE).exists():
            return Response(
                {"success": False, "error": {"code": "CONFLICT", "message": "Student is already enrolled in this offering."}},
                status=status.HTTP_409_CONFLICT,
            )
        enrollment = Enrollment.objects.create(student=student, course_offering=offering)
        audit(user=request.user, action="STUDENT_ENROLLED", resource_type="Enrollment", resource_id=enrollment.id, request=request,
              metadata={"student_id": str(student.id), "offering_id": str(offering.id)})
        return Response(EnrollmentSerializer(enrollment).data, status=status.HTTP_201_CREATED)

    def delete(self, request, offering_id, student_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)

        if request.user.role == User.Role.STUDENT:
            # A student may withdraw from their own registration only.
            if str(request.user.id) != str(student_id):
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only drop your own courses."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not offering.semester.is_active:
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only drop courses in the active semester."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
                return Response(status=status.HTTP_403_FORBIDDEN)
            if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, offering):
                return Response(status=status.HTTP_403_FORBIDDEN)
            if request.user.role == User.Role.LECTURER and not is_offering_teacher(request.user, offering):
                return Response(status=status.HTTP_403_FORBIDDEN)

        enrollment = get_object_or_404(Enrollment, student_id=student_id, course_offering=offering, status=Enrollment.Status.ACTIVE)
        enrollment.status = Enrollment.Status.DROPPED
        from django.utils import timezone
        enrollment.dropped_at = timezone.now()
        enrollment.save(update_fields=["status", "dropped_at", "updated_at"])
        audit(user=request.user, action="STUDENT_DROPPED", resource_type="Enrollment", resource_id=enrollment.id, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EnrollmentExportView(APIView):
    """GET /api/v1/course-offerings/{id}/enrollments/export/ - class list CSV.

    Available to the course lecturer/co-lecturer and to administrators who can
    administer the offering. Only active enrolments are exported; withdrawn
    (``DROPPED``) records stay in the database for the academic history.
    """

    permission_classes = [IsAuthenticated]

    HEADER = [
        "Student name",
        "Matricule",
        "Department",
        "Level",
    ]

    SORT_FIELDS = {
        "name": ("student__first_name", "student__last_name"),
        "matricule": ("student__student_profile__student_number",),
        "email": ("student__email",),
        "department": ("student__student_profile__department__name",),
        "level": ("student__student_profile__level",),
        "status": ("status",),
        "enrolled": ("enrolled_at",),
    }

    def get(self, request, offering_id):
        offering = get_object_or_404(
            CourseOffering.objects.select_related("course", "semester"), id=offering_id
        )
        user = request.user
        allowed = (
            user.role == User.Role.SYSTEM_ADMIN
            or (user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN}
                and can_administer_offering(user, offering))
            or (user.role == User.Role.LECTURER and is_offering_teacher(user, offering))
        )
        if not allowed:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You cannot export this class list."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        sort = (request.query_params.get("sort") or "name").lower()
        order = (request.query_params.get("order") or "asc").lower()
        sort_fields = self.SORT_FIELDS.get(sort, self.SORT_FIELDS["name"])
        if order == "desc":
            sort_fields = tuple(f"-{field}" for field in sort_fields)

        enrollments = (
            Enrollment.objects.filter(
                course_offering=offering,
                status=Enrollment.Status.ACTIVE,
            )
            .select_related("student", "student__student_profile", "student__student_profile__department")
            .order_by(*sort_fields)
        )

        rows = []
        for enrollment in enrollments:
            student = enrollment.student
            profile = getattr(student, "student_profile", None)
            department = profile.department if profile else None
            rows.append([
                student.get_full_name(),
                profile.student_number if profile else "",
                department.name if department else "",
                profile.level if profile else "",
            ])

        code = "".join(
            ch if ch.isalnum() or ch in "-_" else "-" for ch in (offering.course.code or "course")
        )
        today = tz.localdate().isoformat()
        if (request.query_params.get("type") or "").lower() == "pdf":
            title = f"Enrolled students - {offering.course.code} {offering.course.title}"
            subtitle = f"{offering.semester.name} - generated {today}"
            pdf_header = ["No.", *self.HEADER]
            pdf_rows = [
                [number, *row]
                for number, row in enumerate(rows, start=1)
            ]
            return pdf_table_response(
                f"enrolled-students-{code}-{today}.pdf",
                title,
                subtitle,
                pdf_header,
                pdf_rows,
                column_weights=[0.05, 0.32, 0.15, 0.33, 0.15],
            )
        return csv_response(f"enrolled-students-{code}-{today}.csv", self.HEADER, rows)


class MyCoursesView(APIView):
    """GET /api/v1/students/me/courses - student's enrolled courses for current period."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_semester = Semester.objects.filter(is_active=True).first()
        if active_semester is None:
            return Response([])
        enrollments = Enrollment.objects.filter(
            student=request.user,
            course_offering__semester=active_semester,
            status=Enrollment.Status.ACTIVE,
        ).select_related("course_offering", "course_offering__course", "course_offering__department")
        # Delegates are students, so this is where the frontend learns which
        # of their enrolled courses they are allowed to launch attendance for.
        from apps.projects.models import ClassDelegate

        class_delegate_offerings = set(
            ClassDelegate.objects.filter(student=request.user).values_list(
                "course_offering_id", flat=True
            )
        )
        department_delegate_courses = set(
            request.user.department_delegate_courses.values_list("id", flat=True)
        )
        result = []
        for e in enrollments:
            off = e.course_offering
            is_class_delegate = off.id in class_delegate_offerings
            is_department_delegate = off.course_id in department_delegate_courses
            result.append({
                "enrollment_id": e.id,
                "offering_id": off.id,
                "course_code": off.course.code,
                "course_title": off.course.title,
                "department": off.department.name if off.department else "",
                "semester": off.semester.name,
                "lecturer_name": off.lecturer.get_full_name() if off.lecturer else "TBA",
                "materials_count": off.materials.count(),
                "announcements_count": off.announcements.count(),
                "assignments_count": off.assignments.count(),
                "is_class_delegate": is_class_delegate,
                "is_department_delegate": is_department_delegate,
                "can_launch_attendance": is_class_delegate or is_department_delegate,
            })
        return Response(result)


class DepartmentCourseDelegatesView(APIView):
    """GET/POST /api/v1/courses/{course_id}/department-delegates/

    Appoint the students who may launch attendance for every offering of a
    course. Open to scoped administrators of the course's department and to
    lecturers teaching an offering of the course.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _may_appoint(user, course):
        if can_administer_department(user, course.department):
            return True
        return CourseOffering.objects.filter(
            db_models.Q(lecturer=user) | db_models.Q(co_lecturer=user), course=course
        ).exists()

    @staticmethod
    def _payload(course):
        delegates = course.department_delegates.select_related("student_profile").order_by(
            "first_name", "last_name"
        )
        candidates = (
            User.objects.filter(
                role=User.Role.STUDENT,
                enrollments__course_offering__course=course,
                enrollments__status=Enrollment.Status.ACTIVE,
            )
            .select_related("student_profile")
            .distinct()
            .order_by("first_name", "last_name")
        )

        def row(user):
            profile = getattr(user, "student_profile", None)
            return {
                "id": str(user.id),
                "full_name": user.get_full_name(),
                "email": user.email,
                "student_number": getattr(profile, "student_number", "") or "",
            }

        return {
            "course_id": str(course.id),
            "course_code": course.code,
            "delegates": [row(u) for u in delegates],
            "candidates": [row(u) for u in candidates],
        }

    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        if not self._may_appoint(request.user, course):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the course lecturer or an administrator can manage delegates."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(self._payload(course))

    def post(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        if not self._may_appoint(request.user, course):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the course lecturer or an administrator can manage delegates."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        raw_ids = request.data.get("student_ids")
        if not isinstance(raw_ids, list):
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "student_ids must be a list."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            students = list(
                User.objects.filter(
                    id__in=raw_ids,
                    role=User.Role.STUDENT,
                    enrollments__course_offering__course=course,
                    enrollments__status=Enrollment.Status.ACTIVE,
                ).distinct()
            )
        except (ValidationError, ValueError, TypeError):
            students = []
        if len(students) != len({str(value) for value in raw_ids}):
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Every delegate must be an actively enrolled student of this course."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        course.department_delegates.set(students)
        audit(
            user=request.user, action="COURSE_DELEGATES_UPDATED",
            resource_type="Course", resource_id=course.id, request=request,
            metadata={"delegate_ids": [str(s.id) for s in students]},
        )
        return Response(self._payload(course))


class StudentRegistrationView(APIView):
    """GET /api/v1/students/me/available-courses - courses available for registration.
    POST /api/v1/students/me/register/ - register for selected courses."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != "STUDENT":
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only students can access this endpoint."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        profile = getattr(request.user, "student_profile", None)
        if not profile or not profile.department or not profile.level:
            return Response(
                {"success": False, "error": {"code": "INCOMPLETE_PROFILE", "message": "Your profile is missing department or level information."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        active_semester = Semester.objects.filter(is_active=True).first()
        if not active_semester:
            return Response(
                {"success": False, "error": {"code": "NO_ACTIVE_SEMESTER", "message": "No active semester found."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        available = CourseOffering.objects.filter(
            db_models.Q(department=profile.department)
            | db_models.Q(departments=profile.department),
            semester=active_semester,
            status="ACTIVE",
            course__level__in=allowed_course_levels(profile.level),
        ).select_related("course", "department", "semester", "lecturer", "co_lecturer").distinct()

        already_enrolled = set(
            Enrollment.objects.filter(
                student=request.user,
                course_offering__semester=active_semester,
                status=Enrollment.Status.ACTIVE,
            ).values_list("course_offering_id", flat=True)
        )
        today = tz.localdate()
        result = []
        for off in available:
            deadline = effective_registration_deadline(off)
            result.append({
                "offering_id": str(off.id),
                "course_code": off.course.code,
                "course_title": off.course.title,
                "credit_units": off.course.credit_units,
                "course_level": off.course.level,
                "lecturer_name": off.lecturer.get_full_name() if off.lecturer else "TBA",
                "is_enrolled": off.id in already_enrolled,
                "registration_deadline": deadline,
                "registration_closed": registration_is_closed(off, today),
            })
        semester_closed = (
            active_semester.registration_deadline is not None
            and today > active_semester.registration_deadline
        )
        return Response({
            "semester": active_semester.name,
            "registration_deadline": active_semester.registration_deadline,
            "registration_closed": semester_closed,
            "level": profile.level,
            "department": profile.department.name,
            "courses": result,
        })

    def post(self, request):
        if request.user.role != "STUDENT":
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only students can access this endpoint."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        profile = getattr(request.user, "student_profile", None)
        if not profile or not profile.department or not profile.level:
            return Response(
                {"success": False, "error": {"code": "INCOMPLETE_PROFILE", "message": "Your profile is missing department or level information."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        active_semester = Semester.objects.filter(is_active=True).first()
        if not active_semester:
            return Response(
                {"success": False, "error": {"code": "NO_ACTIVE_SEMESTER", "message": "No active semester found."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offering_ids = request.data.get("offering_ids", [])
        if not isinstance(offering_ids, list):
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "offering_ids must be a list."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not offering_ids:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "No courses selected."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        available = {
            offering.id: offering
            for offering in CourseOffering.objects.filter(
                db_models.Q(department=profile.department)
                | db_models.Q(departments=profile.department),
                semester=active_semester,
                status="ACTIVE",
                course__level__in=allowed_course_levels(profile.level),
            ).select_related("semester", "course")
        }
        created = []
        errors = []
        # One transaction for the batch: each course either fully registers
        # (enrollment + project-group membership) or not at all.
        with transaction.atomic():
            for oid in offering_ids:
                try:
                    import uuid
                    off_id = uuid.UUID(str(oid))
                except ValueError:
                    errors.append({"offering_id": str(oid), "error": "Invalid ID format"})
                    continue
                if off_id not in available:
                    errors.append({"offering_id": str(oid), "error": "Course not available for your department/level"})
                    continue
                if registration_is_closed(available[off_id]):
                    errors.append({"offering_id": str(oid), "error": "Registration is closed for this course"})
                    continue
                enrollment, was_created = Enrollment.objects.select_for_update().get_or_create(
                    student=request.user,
                    course_offering_id=off_id,
                    defaults={"status": Enrollment.Status.ACTIVE},
                )
                activated = was_created
                if not was_created and enrollment.status == Enrollment.Status.DROPPED:
                    enrollment.status = Enrollment.Status.ACTIVE
                    enrollment.dropped_at = None
                    enrollment.save(update_fields=["status", "dropped_at", "updated_at"])
                    activated = True
                if activated:
                    created.append(str(off_id))
                    from apps.projects.services import sync_student_memberships_for_offering

                    sync_student_memberships_for_offering(request.user, available[off_id])
        return Response({
            "success": True,
            "registered_count": len(created),
            "registered": created,
            "errors": errors if errors else None,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Class Definitions (API Spec doc 07 §22)
# ---------------------------------------------------------------------------

class ClassDefinitionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        return Response(ClassDefinitionSerializer(offering.class_definitions.all(), many=True).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["course_offering"] = offering.id
        s = ClassDefinitionSerializer(data=data)
        s.is_valid(raise_exception=True)
        cd = s.save()
        return Response(ClassDefinitionSerializer(cd).data, status=status.HTTP_201_CREATED)


class ClassDefinitionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, class_id):
        cd = get_object_or_404(ClassDefinition, id=class_id)
        return Response(ClassDefinitionSerializer(cd).data)


# ---------------------------------------------------------------------------
# Class Sessions (API Spec doc 07 §23)
# ---------------------------------------------------------------------------

class ClassSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, class_id):
        cd = get_object_or_404(ClassDefinition, id=class_id)
        return Response(ClassSessionSerializer(cd.sessions.all(), many=True).data)

    def post(self, request, class_id):
        cd = get_object_or_404(ClassDefinition, id=class_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, cd.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["class_definition"] = cd.id
        s = ClassSessionSerializer(data=data)
        s.is_valid(raise_exception=True)
        cs = s.save()
        return Response(ClassSessionSerializer(cs).data, status=status.HTTP_201_CREATED)


class ClassSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        cs = get_object_or_404(ClassSession, id=session_id)
        return Response(ClassSessionSerializer(cs).data)


class EligibleStudentsView(APIView):
    """GET eligible students for a class session (API Spec doc 07 §21).
    Determines eligibility from course enrollment (FR-002, BR-011)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        from apps.attendance.models import AttendanceSession
        from apps.attendance.permissions import can_launch_attendance

        cs = get_object_or_404(ClassSession, id=session_id)
        offering = cs.class_definition.course_offering
        # Whoever is actually running attendance for this class needs the roster,
        # even if they are not the class owner (e.g. a co-lecturer or a delegate).
        running = set(
            AttendanceSession.objects.filter(
                class_session=cs, lecturer=request.user
            ).values_list("lecturer_id", flat=True)
        )
        allowed = (
            request.user.role in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN"}
            or is_offering_teacher(request.user, offering)
            or cs.class_definition.lecturer_id == request.user.id
            or request.user.id in running
            or can_launch_attendance(request.user, offering)
        )
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN}:
            allowed = can_administer_offering(request.user, cs.class_definition.course_offering)
        if not allowed:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You can only view the roster of classes you teach."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        students = cs.eligible_students
        return Response(StudentBriefSerializer(students, many=True).data)


# ---------------------------------------------------------------------------
# Lecturer teaching courses & weekly timetable (ClassSchedule)
# ---------------------------------------------------------------------------

class LecturerMyCoursesView(APIView):
    """GET /api/v1/lecturers/me/courses - offerings the lecturer teaches,
    with enrollment counts, class definitions and weekly timetable slots."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        active_semester = Semester.objects.filter(is_active=True).first()
        # A lecturer always sees every offering assigned to them. Filtering to
        # the active semester used to hide a course the admin had just assigned
        # (when the offering sits in another semester) and left the lecturer
        # with an empty classroom list and no way to take attendance. Active
        # offerings are ordered first so the current term stays on top.
        qs = (
            CourseOffering.objects.select_related("course", "department", "semester", "lecturer", "co_lecturer")
            .filter(
                db_models.Q(lecturer=request.user) | db_models.Q(co_lecturer=request.user)
            )
            .order_by(
                db_models.Case(
                    db_models.When(semester=active_semester, then=0),
                    default=1,
                    output_field=db_models.IntegerField(),
                ),
                "course__code",
            )
        )
        result = []
        for off in qs:
            schedules = off.schedules.filter(is_active=True)
            # Work waiting on the lecturer, aggregated for the dashboard.
            ungraded = AssignmentSubmission.objects.filter(
                assignment__course_offering=off,
                status=AssignmentSubmission.Status.SUBMITTED,
            ).count()
            open_disputes = AssessmentMark.objects.filter(
                assessment__course_offering=off,
                dispute_status=AssessmentMark.DisputeStatus.OPEN,
            ).count()
            result.append({
                "offering_id": off.id,
                "course_code": off.course.code,
                "course_title": off.course.title,
                "department": off.department.name if off.department else "",
                "semester": off.semester.name,
                "is_active_semester": bool(active_semester and off.semester_id == active_semester.id),
                "lecturer_name": off.lecturer.get_full_name() if off.lecturer else "",
                "materials_count": off.materials.count(),
                "announcements_count": off.announcements.count(),
                "assignments_count": off.assignments.count(),
                "assessments_count": off.assessments.count(),
                "published_assessments_count": off.assessments.filter(status=Assessment.Status.PUBLISHED).count(),
                "ungraded_submissions": ungraded,
                "open_disputes": open_disputes,
                "enrolled_students": off.enrollments.filter(status=Enrollment.Status.ACTIVE).count(),
                "class_definitions": [
                    {"id": cd.id, "name": cd.name, "class_type": cd.class_type, "location": cd.location}
                    for cd in off.class_definitions.all()
                ],
                "schedules": ClassScheduleSerializer(schedules, many=True).data,
            })
        return Response(result)


class ScheduleListView(APIView):
    """GET/POST /api/v1/course-offerings/{offering_id}/schedules - weekly timetable slots."""

    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        return Response(ClassScheduleSerializer(offering.schedules.filter(is_active=True), many=True).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["course_offering"] = str(offering.id)
        s = ClassScheduleSerializer(data=data)
        s.is_valid(raise_exception=True)
        # `lecturer` is read-only on the serializer, so putting it in `data`
        # would be dropped and the insert would fail on a NOT NULL column.
        schedule = s.save(lecturer_id=offering.lecturer_id or request.user.id)
        audit(user=request.user, action="SCHEDULE_CREATED", resource_type="ClassSchedule", resource_id=schedule.id, request=request)
        return Response(ClassScheduleSerializer(schedule).data, status=status.HTTP_201_CREATED)


class ScheduleDetailView(APIView):
    """DELETE /api/v1/schedules/{schedule_id} - remove a timetable slot."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, schedule_id):
        schedule = get_object_or_404(ClassSchedule, id=schedule_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, schedule.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if schedule.lecturer_id != request.user.id and request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        schedule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Carry-over applications (BR-004)
# ---------------------------------------------------------------------------

class CarryOverApplyView(APIView):
    """POST /api/v1/carry-over/apply/ - student requests to register for a
    course they were not enrolled in (e.g. repeating a failed course)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != "STUDENT":
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only students can apply for carry-over registration."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        offering_id = request.data.get("course_offering_id")
        offering = get_object_or_404(CourseOffering, id=offering_id)
        reason = (request.data.get("reason") or "").strip()

        if Enrollment.objects.filter(student=request.user, course_offering=offering, status=Enrollment.Status.ACTIVE).exists():
            return Response(
                {"success": False, "error": {"code": "CONFLICT", "message": "You are already registered for this course."}},
                status=status.HTTP_409_CONFLICT,
            )
        app, created = CarryOverApplication.objects.get_or_create(
            student=request.user, course_offering=offering,
            defaults={"reason": reason, "status": CarryOverApplication.Status.PENDING},
        )
        if not created and app.status == CarryOverApplication.Status.APPROVED:
            return Response(
                {"success": False, "error": {"code": "CONFLICT", "message": "Your carry-over application was already approved."}},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({
            "id": app.id,
            "course_offering_id": str(offering.id),
            "course_code": offering.course.code,
            "course_title": offering.course.title,
            "status": app.status,
            "reason": app.reason,
            "created_at": app.created_at,
        }, status=status.HTTP_201_CREATED)


class CarryOverListView(APIView):
    """GET /api/v1/carry-over/ - staff see all applications, students see their own."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = CarryOverApplication.objects.select_related("student", "course_offering", "course_offering__course")
        if request.user.role == "STUDENT":
            qs = qs.filter(student=request.user)
        elif request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN}:
            qs = scope_by_department(qs, request.user, "course_offering__department")
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        result = [
            {
                "id": a.id,
                "student_id": str(a.student_id),
                "student_name": a.student.get_full_name(),
                "student_email": a.student.email,
                "matricule": getattr(getattr(a.student, "student_profile", None), "student_number", ""),
                "course_offering_id": str(a.course_offering_id),
                "course_code": a.course_offering.course.code,
                "course_title": a.course_offering.course.title,
                "reason": a.reason,
                "status": a.status,
                "review_note": a.review_note,
                "created_at": a.created_at,
            }
            for a in qs
        ]
        return Response(result)


class CarryOverReviewView(APIView):
    """POST /api/v1/carry-over/{id}/review/ {decision: APPROVED|REJECTED, note?}

    Approval creates the Enrollment - only then can attendance be
    confirmed for this student in this course (BR-031).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        if request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only staff can review applications."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        app = get_object_or_404(CarryOverApplication, id=application_id)
        if request.user.role in {User.Role.FACULTY_ADMIN, User.Role.DEPARTMENT_ADMIN} and not can_administer_offering(request.user, app.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        decision = (request.data.get("decision") or "").upper()
        if decision not in {CarryOverApplication.Status.APPROVED, CarryOverApplication.Status.REJECTED}:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "decision must be APPROVED or REJECTED."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        app.status = decision
        app.review_note = (request.data.get("note") or "").strip()
        app.reviewed_by = request.user
        app.reviewed_at = tz.now()
        app.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at", "updated_at"])

        enrollment = None
        if decision == CarryOverApplication.Status.APPROVED:
            enrollment, _ = Enrollment.objects.get_or_create(
                student=app.student, course_offering=app.course_offering,
                defaults={"status": Enrollment.Status.ACTIVE},
            )
            if enrollment.status != Enrollment.Status.ACTIVE:
                enrollment.status = Enrollment.Status.ACTIVE
                enrollment.save(update_fields=["status", "updated_at"])

        audit(user=request.user, action=f"CARRY_OVER_{decision}", resource_type="CarryOverApplication",
              resource_id=app.id, request=request, metadata={"student_id": str(app.student_id)})

        return Response({
            "id": app.id,
            "status": app.status,
            "review_note": app.review_note,
            "enrolled": enrollment is not None,
        })
