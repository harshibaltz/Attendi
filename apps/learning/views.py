"""Learning materials & file management (API Spec doc 07 §§34-36).

MVP: local file storage in MEDIA_ROOT. Production should use S3-compatible
object storage with signed URLs (Tech Stack doc 12 §13).
"""
import csv
import os
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Course, CourseOffering, Enrollment, Semester
from apps.academics.services import levels_for_course
from apps.accounts.models import User
from apps.audit.services import audit
from apps.core.permissions import ADMIN_ROLES
from apps.core.scoping import (
    can_administer_offering,
    is_admin,
    is_offering_teacher,
    scope_by_department,
    scope_users,
)

from .models import (
    Assessment,
    AssessmentGroup,
    AssessmentMark,
    Assignment,
    AssignmentSubmission,
    LearningMaterial,
    UploadedFile,
)
from .scales import group_shares, is_converted, marking_scale, to_reported
from .serializers import (
    AssessmentGroupDetailSerializer,
    AssessmentGroupSerializer,
    AssessmentMarkInputSerializer,
    AssessmentMarkSerializer,
    AssessmentSerializer,
    AssignmentSerializer,
    AssignmentSubmissionSerializer,
    LearningMaterialSerializer,
    UploadedFileSerializer,
)

STAFF_ROLES = {"SYSTEM_ADMIN", "FACULTY_ADMIN", "DEPARTMENT_ADMIN", "LECTURER"}


def _is_staff(user):
    return user.role == "LECTURER" or is_admin(user)


def _can_view_material(user, material):
    """Enrollment gate for materials (BR-070, BR-071). Staff manage all, students
    only see materials of offerings they are actively enrolled in."""
    if user.role in ADMIN_ROLES:
        return can_administer_offering(user, material.course_offering)
    if user.role != "STUDENT":
        return True
    return Enrollment.objects.filter(
        student=user, course_offering=material.course_offering, status=Enrollment.Status.ACTIVE
    ).exists()


def _can_manage_offering(request, offering):
    """BR-072: lecturers may only manage offerings assigned to them; admins broad."""
    if request.user.role in ADMIN_ROLES:
        return can_administer_offering(request.user, offering)
    return request.user.role == "LECTURER" and is_offering_teacher(request.user, offering)


def _is_enrolled(user, offering):
    return Enrollment.objects.filter(student=user, course_offering=offering, status=Enrollment.Status.ACTIVE).exists()


def _can_access_file(user, uploaded_file):
    """File access is context-aware (FR-052, BR-181): uploader always allowed,
    staff allowed for management, students allowed when the file belongs to a
    course they are enrolled in or a project they belong to."""
    if user.role in ADMIN_ROLES:
        if not is_admin(user):
            return False
        from apps.projects.models import ProjectDocument
        scoped_offerings = scope_by_department(CourseOffering.objects.all(), user)
        return (
            LearningMaterial.objects.filter(file=uploaded_file, course_offering__in=scoped_offerings).exists()
            or Assignment.objects.filter(attachment=uploaded_file, course_offering__in=scoped_offerings).exists()
            or AssignmentSubmission.objects.filter(file=uploaded_file, assignment__course_offering__in=scoped_offerings).exists()
            or Assessment.objects.filter(attachment=uploaded_file, course_offering__in=scoped_offerings).exists()
            or ProjectDocument.objects.filter(file=uploaded_file, project__course_offering__in=scoped_offerings).exists()
            or (uploaded_file.uploaded_by_id == user.id and not (
                LearningMaterial.objects.filter(file=uploaded_file).exists()
                or Assignment.objects.filter(attachment=uploaded_file).exists()
                or AssignmentSubmission.objects.filter(file=uploaded_file).exists()
                or Assessment.objects.filter(attachment=uploaded_file).exists()
                or ProjectDocument.objects.filter(file=uploaded_file).exists()
            ))
        )
    if uploaded_file.uploaded_by_id == user.id:
        return True
    from apps.projects.models import ProjectDocument

    material_offering_ids = LearningMaterial.objects.filter(file=uploaded_file).values_list(
        "course_offering_id", flat=True
    )
    if user.role == "LECTURER":
        if CourseOffering.objects.filter(
            Q(lecturer=user) | Q(co_lecturer=user), id__in=material_offering_ids
        ).exists():
            return True
        if AssignmentSubmission.objects.filter(
            Q(assignment__course_offering__lecturer=user)
            | Q(assignment__course_offering__co_lecturer=user),
            file=uploaded_file,
        ).exists():
            return True
        if Assessment.objects.filter(
            Q(course_offering__lecturer=user) | Q(course_offering__co_lecturer=user),
            attachment=uploaded_file,
        ).exists():
            return True
        return ProjectDocument.objects.filter(file=uploaded_file, project__supervisor=user).exists()
    if user.role == "STUDENT":
        if Enrollment.objects.filter(
            student=user, course_offering_id__in=material_offering_ids, status=Enrollment.Status.ACTIVE
        ).exists():
            return True
        if Assignment.objects.filter(
            attachment=uploaded_file, course_offering__enrollments__student=user,
            course_offering__enrollments__status=Enrollment.Status.ACTIVE,
        ).exists():
            return True
        if Assessment.objects.filter(
            attachment=uploaded_file, status=Assessment.Status.PUBLISHED,
            course_offering__enrollments__student=user,
            course_offering__enrollments__status=Enrollment.Status.ACTIVE,
        ).exists():
            return True
        if AssignmentSubmission.objects.filter(file=uploaded_file, student=user).exists():
            return True
        return ProjectDocument.objects.filter(file=uploaded_file, project__members__student=user).exists()
    return False


def _validate_upload(uploaded_file):
    """BR-182 allowed types + BR-183 max size. Returns (error_message, None) on failure."""
    name = uploaded_file.name or "file"
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    if uploaded_file.size > settings.FILE_MAX_SIZE_BYTES:
        return f"File exceeds the maximum size of {settings.FILE_MAX_SIZE_MB} MB."
    if not ext or ext not in settings.ALLOWED_FILE_EXTENSIONS:
        return "File type not allowed. Permitted types: " + ", ".join(sorted(settings.ALLOWED_FILE_EXTENSIONS)) + "."
    return None


class MaterialListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == "STUDENT":
            if not Enrollment.objects.filter(student=request.user, course_offering=offering, status=Enrollment.Status.ACTIVE).exists():
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "Not enrolled in this course."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return Response(LearningMaterialSerializer(offering.materials.all(), many=True).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if not _can_manage_offering(request, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only staff can upload materials."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["course_offering"] = offering.id
        data["uploaded_by"] = request.user.id
        s = LearningMaterialSerializer(data=data)
        s.is_valid(raise_exception=True)
        material = s.save()
        audit(user=request.user, action="MATERIAL_CREATED", resource_type="LearningMaterial",
              resource_id=material.id, request=request, metadata={"offering_id": str(offering.id)})
        return Response(LearningMaterialSerializer(material).data, status=status.HTTP_201_CREATED)


class MaterialDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, material_id):
        material = get_object_or_404(LearningMaterial, id=material_id)
        if not _can_view_material(request.user, material):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized to view this material."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(LearningMaterialSerializer(material).data)

    def patch(self, request, material_id):
        material = get_object_or_404(LearningMaterial, id=material_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, material.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.id != material.uploaded_by_id and request.user.role not in {"SYSTEM_ADMIN", "FACULTY_ADMIN"}:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        s = LearningMaterialSerializer(material, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, material_id):
        material = get_object_or_404(LearningMaterial, id=material_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, material.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.id != material.uploaded_by_id and request.user.role not in ADMIN_ROLES:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        material.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FileUploadView(APIView):
    """POST /api/v1/files/ - single-file upload (FR-050, API Spec doc 07 §35).

    Accepts multipart form data with a ``file`` field. File bytes are stored in
    private MEDIA_ROOT; only metadata is kept in the DB (BR-180).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "No file provided."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        error = _validate_upload(upload)
        if error:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": error}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = upload.name or "file"
        storage_key = f"uploaded/{uuid.uuid4()}/{uuid.uuid4()}-{os.path.basename(name)[:120]}"
        destination = os.path.join(settings.MEDIA_ROOT, storage_key)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        with open(destination, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        uploaded_file = UploadedFile.objects.create(
            uploaded_by=request.user,
            original_name=name,
            storage_key=storage_key,
            mime_type=upload.content_type or "",
            size_bytes=upload.size,
        )
        audit(user=request.user, action="FILE_UPLOADED", resource_type="UploadedFile",
              resource_id=uploaded_file.id, request=request,
              metadata={"name": name, "mime_type": upload.content_type, "size_bytes": upload.size})
        return Response(UploadedFileSerializer(uploaded_file).data, status=status.HTTP_201_CREATED)


class FileDownloadView(APIView):
    """GET /api/v1/files/{file_id} - authorized file download (FR-052, BR-181)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, file_id):
        uploaded_file = get_object_or_404(UploadedFile, id=file_id)
        if not _can_access_file(request.user, uploaded_file):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not authorized to access this file."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        file_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.storage_key)
        if not os.path.exists(file_path):
            raise Http404("File not found on storage.")
        return FileResponse(
            open(file_path, "rb"),
            as_attachment=True,
            filename=uploaded_file.original_name,
        )


# ---------------------------------------------------------------------------
# Assignments (Google-Classroom style; teacher-controlled submission policy)
# ---------------------------------------------------------------------------

class AssignmentListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == "STUDENT" and not _is_enrolled(request.user, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not enrolled in this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        ctx = {"request": request}
        return Response(AssignmentSerializer(offering.assignments.all(), many=True, context=ctx).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if not _can_manage_offering(request, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the lecturer (or an admin) can create assignments."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["course_offering"] = offering.id
        data["created_by"] = request.user.id
        s = AssignmentSerializer(data=data)
        s.is_valid(raise_exception=True)
        assignment = s.save()
        audit(user=request.user, action="ASSIGNMENT_CREATED", resource_type="Assignment",
              resource_id=assignment.id, request=request, metadata={"offering_id": str(offering.id)})
        return Response(AssignmentSerializer(assignment, context={"request": request}).data, status=status.HTTP_201_CREATED)


class AssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, assignment_id):
        assignment = get_object_or_404(Assignment, id=assignment_id)
        if request.user.role in ADMIN_ROLES and not can_administer_offering(request.user, assignment.course_offering):
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.role == "STUDENT" and not _is_enrolled(request.user, assignment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not enrolled in this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(AssignmentSerializer(assignment, context={"request": request}).data)

    def patch(self, request, assignment_id):
        assignment = get_object_or_404(Assignment, id=assignment_id)
        if not _can_manage_offering(request, assignment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        s = AssignmentSerializer(assignment, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, assignment_id):
        assignment = get_object_or_404(Assignment, id=assignment_id)
        if not _can_manage_offering(request, assignment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        assignment.status = Assignment.Status.ARCHIVED
        assignment.save(update_fields=["status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentSubmissionListView(APIView):
    """POST - student turns in work. GET - list submissions (staff: all, student: own)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, assignment_id):
        assignment = get_object_or_404(Assignment, id=assignment_id)
        if request.user.role == "STUDENT":
            qs = assignment.submissions.filter(student=request.user)
        else:
            if not _can_manage_offering(request, assignment.course_offering):
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            qs = assignment.submissions.all()
        return Response(AssignmentSubmissionSerializer(qs.select_related("student", "file"), many=True).data)

    def post(self, request, assignment_id):
        # Lock the assignment row for the whole check + create so two parallel
        # submissions cannot both pass the max_submissions check.
        with transaction.atomic():
            assignment = get_object_or_404(
                Assignment.objects.select_for_update(), id=assignment_id
            )
            if request.user.role != "STUDENT":
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "Only students can submit work."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not _is_enrolled(request.user, assignment.course_offering):
                return Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not enrolled in this course."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if assignment.status != Assignment.Status.ACTIVE:
                return Response(
                    {"success": False, "error": {"code": "CONFLICT", "message": "This assignment is no longer accepting submissions."}},
                    status=status.HTTP_409_CONFLICT,
                )
            now = timezone.now()
            if assignment.due_at and now > assignment.due_at and not assignment.allow_late:
                return Response(
                    {"success": False, "error": {"code": "MISSED_DEADLINE", "message": "The submission deadline has passed."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
            consumed = AssignmentSubmission.objects.filter(
                assignment=assignment, student=request.user
            ).exclude(status=AssignmentSubmission.Status.RETURNED).count()
            if assignment.max_submissions and consumed >= assignment.max_submissions:
                return Response(
                    {"success": False, "error": {
                        "code": "SUBMISSION_LIMIT_REACHED",
                        "message": f"Submission limit of {assignment.max_submissions} reached. Contact your lecturer.",
                    }},
                    status=status.HTTP_403_FORBIDDEN,
                )
            submission = AssignmentSubmission.objects.create(
                assignment=assignment,
                student=request.user,
                file_id=request.data.get("file") or None,
                note=request.data.get("note", ""),
                is_late=bool(assignment.due_at and now > assignment.due_at),
            )
        audit(user=request.user, action="ASSIGNMENT_SUBMITTED", resource_type="AssignmentSubmission",
              resource_id=submission.id, request=request, metadata={"assignment_id": str(assignment.id)})
        return Response(AssignmentSubmissionSerializer(submission).data, status=status.HTTP_201_CREATED)


class AssignmentSubmissionDetailView(APIView):
    """PATCH by lecturer/admin: return (resubmission frees an attempt) or grade."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, submission_id):
        submission = get_object_or_404(
            AssignmentSubmission.objects.select_related("assignment", "student", "file"), id=submission_id
        )
        if not _can_manage_offering(request, submission.assignment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not authorized."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        action = request.data.get("status")
        if action == AssignmentSubmission.Status.RETURNED:
            submission.status = AssignmentSubmission.Status.RETURNED
            submission.grade = None
            submission.feedback = ""
            submission.graded_by = None
            submission.graded_at = None
            submission.save()
            audit(user=request.user, action="ASSIGNMENT_RETURNED", resource_type="AssignmentSubmission",
                  resource_id=submission.id, request=request)
        elif "grade" in request.data or "feedback" in request.data:
            if request.data.get("grade") not in (None, ""):
                try:
                    grade = Decimal(str(request.data.get("grade")))
                except (InvalidOperation, TypeError):
                    return Response(
                        {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Invalid grade value."}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                submission.grade = grade
                submission.status = AssignmentSubmission.Status.GRADED
                submission.graded_by = request.user
                submission.graded_at = timezone.now()
            if "feedback" in request.data:
                submission.feedback = request.data.get("feedback", "")
            submission.save()
            audit(user=request.user, action="ASSIGNMENT_GRADED", resource_type="AssignmentSubmission",
                  resource_id=submission.id, request=request)
        else:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Send status=RETURNED or grade/feedback."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(AssignmentSubmissionSerializer(submission).data)


def _lecturer_department(user):
    from apps.accounts.models import LecturerProfile

    profile = LecturerProfile.objects.filter(user=user).select_related("department").first()
    return profile.department if profile else None


def _classroom_courses(user):
    """Courses this lecturer may open a classroom for: their own department
    (their teaching assignment scope). Admins may use any department."""
    qs = Course.objects.filter(status="ACTIVE").select_related("department")
    if user.role in ADMIN_ROLES:
        return scope_by_department(qs, user)
    if user.role not in ADMIN_ROLES:
        dept = _lecturer_department(user)
        if dept is None:
            return qs.none()
        qs = qs.filter(department=dept)
    return qs


class AvailableClassroomCoursesView(APIView):
    """GET /api/v1/classrooms/available-courses/?semester_id=...

    Courses the lecturer may open a classroom for, with a cohort preview and
    whether a classroom already exists in the requested (or active) semester.
    Students are never enrolled by this endpoint; registration is their choice.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_staff(request.user):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only staff can create classrooms."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        semester_id = request.query_params.get("semester_id")
        if semester_id:
            semester = get_object_or_404(Semester, id=semester_id)
        else:
            semester = Semester.objects.filter(is_active=True).first() or Semester.objects.filter(
                status="ACTIVE"
            ).order_by("-academic_year", "number").first()
        result = []
        for course in _classroom_courses(request.user).order_by("code"):
            cohort = User.objects.filter(
                role="STUDENT",
                is_active=True,
                student_profile__department=course.department,
            )
            if course.level:
                cohort = cohort.filter(student_profile__level__in=levels_for_course(course.level))
            existing = None
            if semester:
                off = CourseOffering.objects.filter(course=course, semester=semester).select_related(
                    "lecturer"
                ).first()
                if off:
                    existing = {
                        "offering_id": str(off.id),
                        "lecturer_name": off.lecturer.get_full_name() if off.lecturer else "TBA",
                        "status": off.status,
                    }
            result.append({
                "course_id": str(course.id),
                "course_code": course.code,
                "course_title": course.title,
                "department": course.department.name,
                "level": course.level,
                "credit_units": course.credit_units,
                "cohort_size": cohort.count() if course.level else 0,
                "existing_classroom": existing,
            })
        return Response({
            "semester_id": str(semester.id) if semester else None,
            "semester_name": semester.name if semester else None,
            "courses": result,
        })


class ClassroomCreateView(APIView):
    """POST /api/v1/classrooms/

    Opens a classroom for one of the lecturer's own courses. No students are
    enrolled automatically; each student decides whether to register for the
    offering. Administrators may open a classroom in any semester and assign
    a lecturer now or later.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_staff(request.user):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only staff can create classrooms."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        course_id = request.data.get("course_id")
        if not course_id:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "course_id is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        course = get_object_or_404(_classroom_courses(request.user), id=course_id)

        semester = None
        semester_id = request.data.get("semester_id")
        if semester_id:
            semester = get_object_or_404(Semester, id=semester_id)
        else:
            semester = Semester.objects.filter(is_active=True).first() or Semester.objects.filter(
                status="ACTIVE"
            ).order_by("-academic_year", "number").first()
        if semester is None:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "No active semester to open a classroom in."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if request.user.role not in ADMIN_ROLES and not semester.is_active:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR",
                 "message": "Lecturers can only open classrooms in the active semester."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lecturer = request.user if request.user.role == "LECTURER" else None
        lecturer_id = request.data.get("lecturer_id")
        if request.user.role in ADMIN_ROLES and lecturer_id:
            lecturer_qs = scope_users(
                User.objects.filter(role=User.Role.LECTURER, is_active=True),
                request.user,
            )
            lecturer = get_object_or_404(lecturer_qs, id=lecturer_id)

        # Atomic: get_or_create lets the unique(course, semester) constraint
        # decide the winner when two requests race, so the loser gets a 409.
        with transaction.atomic():
            offering, created = CourseOffering.objects.get_or_create(
                course=course,
                semester=semester,
                defaults={
                    "department": course.department,
                    "lecturer": lecturer,
                    "status": "ACTIVE",
                },
            )
            if not created:
                return Response(
                    {"success": False, "error": {"code": "CONFLICT",
                     "message": f"A classroom for {course.code} already exists in {semester.name}."}},
                    status=status.HTTP_409_CONFLICT,
                )

        cohort_qs = User.objects.filter(
            role="STUDENT",
            is_active=True,
            student_profile__department=course.department,
        )
        if course.level:
            cohort_qs = cohort_qs.filter(student_profile__level__in=levels_for_course(course.level))

        audit(user=request.user, action="CLASSROOM_CREATED", resource_type="CourseOffering",
              resource_id=offering.id, request=request,
              metadata={"course_code": course.code, "self_registration": True,
                        "lecturer_id": str(offering.lecturer_id or "")})

        return Response({
            "offering_id": str(offering.id),
            "course_code": course.code,
            "course_title": course.title,
            "semester": semester.name,
            "lecturer": offering.lecturer.get_full_name() if offering.lecturer else "",
            "auto_enrolled": 0,
            "cohort_size": cohort_qs.count(),
            "enrollment_mode": "SELF_REGISTRATION",
        }, status=status.HTTP_201_CREATED)


class AssessmentListView(APIView):
    """GET  /api/v1/course-offerings/{offering_id}/assessments/
    POST /api/v1/course-offerings/{offering_id}/assessments/  (teaching lecturer)

    Students only ever see PUBLISHED sheets; lecturers see drafts too.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if _can_manage_offering(request, offering):
            qs = offering.assessments.all()
        elif _is_enrolled(request.user, offering):
            qs = offering.assessments.filter(status=Assessment.Status.PUBLISHED)
        else:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not enrolled in this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(AssessmentSerializer(qs, many=True, context={"request": request}).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if not _can_manage_offering(request, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can create assessments."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data.copy()
        data["course_offering"] = offering.id
        serializer = AssessmentSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        # `created_by` is read-only on the serializer, so putting it in `data`
        # would be dropped and the assessment would end up with no author.
        assessment = serializer.save(created_by=request.user)
        # Seed a mark row per enrolled student so the lecturer can type straight away.
        for student in _active_students(offering):
            AssessmentMark.objects.get_or_create(assessment=assessment, student=student)
        audit(user=request.user, action="ASSESSMENT_CREATED", resource_type="Assessment",
              resource_id=assessment.id, request=request)
        return Response(AssessmentSerializer(assessment, context={"request": request}).data, status=status.HTTP_201_CREATED)


def _active_students(offering):
    return User.objects.filter(
        enrollments__course_offering=offering,
        enrollments__status=Enrollment.Status.ACTIVE,
        role="STUDENT",
        is_active=True,
    ).distinct()


class AssessmentDetailView(APIView):
    """GET/PATCH/DELETE /api/v1/assessments/{assessment_id}/

    PATCH is how a lecturer publishes (status=PUBLISHED) or edits the sheet.
    """

    permission_classes = [IsAuthenticated]

    def _get(self, request, assessment_id):
        assessment = get_object_or_404(Assessment.objects.select_related("course_offering"), id=assessment_id)
        if not _can_manage_offering(request, assessment.course_offering):
            if assessment.status != Assessment.Status.PUBLISHED or not _is_enrolled(request.user, assessment.course_offering):
                return None, Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You cannot view this assessment."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return assessment, None

    def get(self, request, assessment_id):
        assessment, error = self._get(request, assessment_id)
        if error:
            return error
        data = AssessmentSerializer(assessment, context={"request": request}).data
        # Include full mark list for the lecturer, single mark for a student.
        if _can_manage_offering(request, assessment.course_offering):
            data["marks"] = AssessmentMarkSerializer(assessment.marks.select_related("student"), many=True).data
        return Response(data)

    def patch(self, request, assessment_id):
        assessment = get_object_or_404(Assessment, id=assessment_id)
        if not _can_manage_offering(request, assessment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can update this assessment."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        new_status = request.data.get("status")
        if new_status == Assessment.Status.PUBLISHED and assessment.status != Assessment.Status.PUBLISHED:
            assessment.published_at = timezone.now()
        data = request.data.copy()
        data.pop("status", None) if new_status is None else None
        serializer = AssessmentSerializer(assessment, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        assessment = serializer.save()
        if new_status:
            assessment.status = new_status
            if new_status == Assessment.Status.PUBLISHED and assessment.published_at is None:
                assessment.published_at = timezone.now()
            assessment.save(update_fields=["status", "published_at"])
        audit(user=request.user, action="ASSESSMENT_UPDATED", resource_type="Assessment",
              resource_id=assessment.id, request=request, metadata={"status": assessment.status})
        return Response(AssessmentSerializer(assessment, context={"request": request}).data)

    def delete(self, request, assessment_id):
        assessment = get_object_or_404(Assessment, id=assessment_id)
        if not _can_manage_offering(request, assessment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can delete this assessment."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        assessment.delete()
        audit(user=request.user, action="ASSESSMENT_DELETED", resource_type="Assessment",
              resource_id=assessment_id, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssessmentMarksView(APIView):
    """PUT /api/v1/assessments/{assessment_id}/marks/

    Bulk mark entry by the teaching lecturer:
    {"marks": [{"student": "<uuid>", "score": "18.5", "comment": "..."}]}
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, assessment_id):
        assessment = get_object_or_404(Assessment, id=assessment_id)
        if not _can_manage_offering(request, assessment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can enter marks."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = AssessmentMarkInputSerializer(data=request.data.get("marks", []), many=True)
        payload.is_valid(raise_exception=True)

        enrolled_ids = set(_active_students(assessment.course_offering).values_list("id", flat=True))
        entry_max = marking_scale(assessment)
        max_score = entry_max
        saved = 0
        errors = []
        for row in payload.validated_data:
            student_id = row["student"]
            if student_id not in enrolled_ids:
                errors.append(f"{student_id} is not enrolled in this course.")
                continue
            score = row.get("score")
            if score is not None and score > max_score:
                errors.append(f"{student_id}: score {score} exceeds the marking scale of {max_score}.")
                continue
            mark, _created = AssessmentMark.objects.get_or_create(assessment=assessment, student_id=student_id)
            mark.score = score
            mark.comment = row.get("comment", "") or ""
            mark.save(update_fields=["score", "comment", "updated_at"])
            saved += 1
        audit(user=request.user, action="ASSESSMENT_MARKS_SAVED", resource_type="Assessment",
              resource_id=assessment.id, request=request, metadata={"saved": saved})
        return Response({
            "saved": saved,
            "errors": errors,
            "marks": AssessmentMarkSerializer(assessment.marks.select_related("student"), many=True).data,
        })


class AssessmentMarkDetailView(APIView):
    """PATCH /api/v1/assessment-marks/{mark_id}/

    Student: raise or withdraw a dispute on a published mark.
    Lecturer: resolve a dispute with a response.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, mark_id):
        mark = get_object_or_404(AssessmentMark.objects.select_related("assessment", "student"), id=mark_id)
        assessment = mark.assessment
        manages = _can_manage_offering(request, assessment.course_offering)
        is_owner = mark.student_id == request.user.id

        if not manages and not is_owner:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Not your mark."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not manages and assessment.status != Assessment.Status.PUBLISHED:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "This assessment has not been published yet."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        if manages:
            old_response = mark.dispute_response
            response_text = request.data.get("dispute_response", old_response)
            mark.dispute_response = response_text
            if request.data.get("resolve") or response_text != old_response:
                mark.dispute_status = AssessmentMark.DisputeStatus.RESOLVED
                mark.resolved_at = timezone.now()
            mark.save(update_fields=["dispute_response", "dispute_status", "resolved_at", "updated_at"])
            audit(user=request.user, action="ASSESSMENT_DISPUTE_RESOLVED", resource_type="AssessmentMark",
                  resource_id=mark.id, request=request)
            return Response(AssessmentMarkSerializer(mark).data)

        reason = (request.data.get("dispute_reason") or "").strip()
        if not reason:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "Tell us what is wrong with this mark."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mark.dispute_reason = reason
        mark.dispute_status = AssessmentMark.DisputeStatus.OPEN
        mark.disputed_at = timezone.now()
        mark.dispute_response = ""
        mark.resolved_at = None
        mark.save(update_fields=["dispute_reason", "dispute_status", "disputed_at", "dispute_response", "resolved_at", "updated_at"])
        audit(user=request.user, action="ASSESSMENT_DISPUTE_RAISED", resource_type="AssessmentMark",
              resource_id=mark.id, request=request)
        return Response(AssessmentMarkSerializer(mark).data)


class AssessmentExportView(APIView):
    """GET /api/v1/assessments/{assessment_id}/export.csv

    Lecturer downloads the mark sheet as CSV to load into other software.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, assessment_id):
        assessment = get_object_or_404(Assessment.objects.select_related("course_offering__course"), id=assessment_id)
        if not _can_manage_offering(request, assessment.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can export marks."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        response = HttpResponse(content_type="text/csv")
        filename = f"{assessment.course_offering.course.code}-{assessment.title}".replace(" ", "_")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response)
        entry_max = marking_scale(assessment)
        writer.writerow([
            "student_number", "student_name", "email",
            f"raw_score", f"marking_scale_{entry_max}", f"reported_score", f"reported_out_of_{assessment.maximum_score}",
            "comment", "dispute_status", "dispute_reason", "dispute_response",
        ])
        for mark in assessment.marks.select_related("student").order_by("student__last_name", "student__first_name"):
            profile = getattr(mark.student, "student_profile", None)
            reported = to_reported(mark.score, assessment)
            writer.writerow([
                profile.student_number if profile else "",
                mark.student.get_full_name(),
                mark.student.email,
                mark.score if mark.score is not None else "",
                entry_max,
                reported if reported is not None else "",
                assessment.maximum_score,
                mark.comment,
                mark.dispute_status,
                mark.dispute_reason,
                mark.dispute_response,
            ])
        audit(user=request.user, action="ASSESSMENT_EXPORTED", resource_type="Assessment",
              resource_id=assessment.id, request=request)
        return response


class MyAssessmentsView(APIView):
    """GET /api/v1/students/me/assessments/ - published sheets with the student's own mark."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        offering_ids = list(Enrollment.objects.filter(
            student=request.user, status=Enrollment.Status.ACTIVE
        ).values_list("course_offering_id", flat=True))
        qs = Assessment.objects.filter(
            course_offering_id__in=offering_ids,
            status=Assessment.Status.PUBLISHED,
        )
        data = {"assessments": AssessmentSerializer(qs, many=True, context={"request": request}).data}

        # Combined grades (e.g. all CAs into one CA out of 30).
        groups = AssessmentGroup.objects.filter(
            course_offering_id__in=offering_ids, status="PUBLISHED"
        ).prefetch_related("assessments")
        data["groups"] = AssessmentGroupDetailSerializer(
            groups, many=True, context={"request": request}
        ).data
        return Response(data)


class AssessmentGroupListView(APIView):
    """GET/POST /api/v1/course-offerings/{offering_id}/assessment-groups/

    A group combines several assessments into one reported grade
    (e.g. all CAs into one CA out of 30).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if _can_manage_offering(request, offering):
            qs = offering.assessment_groups.all()
        elif _is_enrolled(request.user, offering):
            qs = offering.assessment_groups.filter(status="PUBLISHED")
        else:
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "You are not enrolled in this course."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(AssessmentGroupSerializer(qs, many=True).data)

    def post(self, request, offering_id):
        offering = get_object_or_404(CourseOffering, id=offering_id)
        if not _can_manage_offering(request, offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can create assessment groups."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AssessmentGroupSerializer(
            data={**request.data, "course_offering": offering.id}
        )
        serializer.is_valid(raise_exception=True)
        # `created_by` is read-only, so it has to be passed to save().
        group = serializer.save(created_by=request.user)
        audit(user=request.user, action="ASSESSMENT_GROUP_CREATED", resource_type="AssessmentGroup",
              resource_id=group.id, request=request)
        return Response(AssessmentGroupSerializer(group).data, status=status.HTTP_201_CREATED)


class AssessmentGroupDetailView(APIView):
    """GET/PATCH/DELETE /api/v1/assessment-groups/{group_id}/"""

    permission_classes = [IsAuthenticated]

    def _get(self, request, group_id):
        group = get_object_or_404(AssessmentGroup.objects.select_related("course_offering"), id=group_id)
        if not _can_manage_offering(request, group.course_offering):
            if group.status != "PUBLISHED" or not _is_enrolled(request.user, group.course_offering):
                return None, Response(
                    {"success": False, "error": {"code": "FORBIDDEN", "message": "You cannot view this grade."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        return group, None

    def get(self, request, group_id):
        group, error = self._get(request, group_id)
        if error:
            return error
        return Response(AssessmentGroupDetailSerializer(group, context={"request": request}).data)

    def patch(self, request, group_id):
        group = get_object_or_404(AssessmentGroup, id=group_id)
        if not _can_manage_offering(request, group.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can update this grade."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        new_status = request.data.get("status")
        data = {k: v for k, v in request.data.items() if k != "status"}
        serializer = AssessmentGroupSerializer(group, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        group = serializer.save()
        if new_status and new_status != group.status:
            group.status = new_status
            if new_status == "PUBLISHED" and group.published_at is None:
                group.published_at = timezone.now()
            group.save(update_fields=["status", "published_at"])
        return Response(AssessmentGroupDetailSerializer(group, context={"request": request}).data)

    def delete(self, request, group_id):
        group = get_object_or_404(AssessmentGroup, id=group_id)
        if not _can_manage_offering(request, group.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can delete this grade."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssessmentGroupExportView(APIView):
    """GET /api/v1/assessment-groups/{group_id}/export.csv"""

    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(AssessmentGroup.objects.select_related("course_offering__course"), id=group_id)
        if not _can_manage_offering(request, group.course_offering):
            return Response(
                {"success": False, "error": {"code": "FORBIDDEN", "message": "Only the teaching lecturer can export this grade."}},
                status=status.HTTP_403_FORBIDDEN,
            )
        response = HttpResponse(content_type="text/csv")
        filename = f"{group.course_offering.course.code}-{group.title}".replace(" ", "_")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        detail = AssessmentGroupDetailSerializer(group, context={"request": request}).data
        shares = group_shares(group)
        members = list(group.assessments.all())
        writer = csv.writer(response)
        writer.writerow(
            ["student_number", "student_name", "total", f"out_of_{group.maximum_score}"]
            + [f"{m.title} ({m.maximum_score})" for m in members]
        )
        for row in detail["students"]:
            by_assessment = {b["assessment_id"]: b["points"] for b in row["breakdown"]}
            writer.writerow(
                [row["student_number"], row["student_name"], row["total"] if row["total"] is not None else "", group.maximum_score]
                + [by_assessment.get(m.id, "") for m in members]
            )
        _ = shares
        return response
