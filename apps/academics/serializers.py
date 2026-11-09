from rest_framework import serializers

from .models import (
    Semester,
    ClassDefinition,
    ClassSchedule,
    ClassSession,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    Faculty,
)


class FacultySerializer(serializers.ModelSerializer):
    class Meta:
        model = Faculty
        fields = ["id", "name", "code", "description", "status", "created_at"]


class DepartmentSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.name", read_only=True)

    class Meta:
        model = Department
        fields = ["id", "faculty", "faculty_name", "name", "code", "description", "status"]


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = [
            "id", "name", "academic_year", "number", "start_date", "end_date",
            "registration_deadline", "status", "is_active",
        ]
        # `is_active` is moved by Semester.save(), not by the client, and only one
        # semester may hold it. Clients read it to show which one is live.
        read_only_fields = ["is_active"]


class CourseSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Course
        fields = ["id", "department", "department_name", "code", "title", "description", "credit_units", "level", "status"]


class CourseOfferingSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course.code", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    lecturer_name = serializers.SerializerMethodField()
    co_lecturer_name = serializers.SerializerMethodField()
    department_names = serializers.SerializerMethodField()
    materials_count = serializers.SerializerMethodField()
    announcements_count = serializers.SerializerMethodField()
    assignments_count = serializers.SerializerMethodField()
    assessments_count = serializers.SerializerMethodField()
    enrolled_students = serializers.SerializerMethodField()

    class Meta:
        model = CourseOffering
        fields = [
            "id", "course", "course_code", "course_title", "semester", "semester_name",
            "department", "department_name", "departments", "department_names",
            "lecturer", "lecturer_name", "co_lecturer", "co_lecturer_name", "status",
            "registration_deadline", "materials_count", "announcements_count",
            "assignments_count", "assessments_count", "enrolled_students",
        ]

    def get_lecturer_name(self, obj):
        return obj.lecturer.get_full_name() if obj.lecturer else ""

    def get_co_lecturer_name(self, obj):
        return obj.co_lecturer.get_full_name() if obj.co_lecturer else ""

    def get_department_names(self, obj):
        return [d.name for d in obj.departments.all()]

    @staticmethod
    def _annotated(obj, name):
        value = getattr(obj, name, None)
        return value if value is not None else None

    def get_materials_count(self, obj):
        cached = self._annotated(obj, "materials_count")
        return cached if cached is not None else obj.materials.count()

    def get_announcements_count(self, obj):
        cached = self._annotated(obj, "announcements_count")
        return cached if cached is not None else obj.announcements.count()

    def get_assignments_count(self, obj):
        cached = self._annotated(obj, "assignments_count")
        return cached if cached is not None else obj.assignments.count()

    def get_assessments_count(self, obj):
        cached = self._annotated(obj, "assessments_count")
        return cached if cached is not None else obj.assessments.count()

    def get_enrolled_students(self, obj):
        cached = self._annotated(obj, "enrolled_students")
        if cached is not None:
            return cached
        return obj.enrollments.filter(status=Enrollment.Status.ACTIVE).count()


class EnrollmentSerializer(serializers.ModelSerializer):
    student_email = serializers.CharField(source="student.email", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    course_code = serializers.CharField(source="course_offering.course.code", read_only=True)
    course_title = serializers.CharField(source="course_offering.course.title", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id", "student", "student_email", "student_name", "student_number",
            "department", "level", "course_offering", "course_code", "course_title",
            "status", "enrolled_at", "dropped_at",
        ]
        read_only_fields = ["enrolled_at", "dropped_at"]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_student_number(self, obj):
        profile = getattr(obj.student, "student_profile", None)
        return profile.student_number if profile else ""

    def get_department(self, obj):
        profile = getattr(obj.student, "student_profile", None)
        if not profile or not profile.department:
            return ""
        return profile.department.name or profile.department.code

    def get_level(self, obj):
        profile = getattr(obj.student, "student_profile", None)
        return profile.level if profile else ""


class ClassDefinitionSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course_offering.course.code", read_only=True)
    offering_id = serializers.UUIDField(source="course_offering.id", read_only=True)
    lecturer_name = serializers.SerializerMethodField()

    class Meta:
        model = ClassDefinition
        fields = ["id", "course_offering", "offering_id", "course_code", "lecturer", "lecturer_name", "name", "class_type", "location", "recurrence_rule", "status"]

    def get_lecturer_name(self, obj):
        return obj.lecturer.get_full_name() if obj.lecturer else ""


class ClassSessionSerializer(serializers.ModelSerializer):
    class_name = serializers.CharField(source="class_definition.name", read_only=True)
    class_type = serializers.CharField(source="class_definition.class_type", read_only=True)
    course_code = serializers.SerializerMethodField()
    offering_id = serializers.SerializerMethodField()

    class Meta:
        model = ClassSession
        fields = ["id", "class_definition", "class_name", "class_type", "course_code", "offering_id", "starts_at", "ends_at", "status"]

    def get_course_code(self, obj):
        return obj.class_definition.course_offering.course.code

    def get_offering_id(self, obj):
        return obj.class_definition.course_offering.id


class StudentBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()

    class Meta:
        from apps.accounts.models import User
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "student_number"]

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_student_number(self, obj):
        profile = getattr(obj, "student_profile", None)
        return profile.student_number if profile else ""


class ClassScheduleSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source="course_offering.course.code", read_only=True)
    offering_id = serializers.CharField(source="course_offering.id", read_only=True)

    class Meta:
        model = ClassSchedule
        fields = [
            "id", "course_offering", "offering_id", "course_code", "lecturer", "class_type",
            "day_of_week", "start_time", "end_time", "location", "is_active", "created_at",
        ]
        read_only_fields = ["lecturer"]
