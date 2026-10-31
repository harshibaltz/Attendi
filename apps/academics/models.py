import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedUUIDModel


class Faculty(TimeStampedUUIDModel):
    """FET - Faculty of Engineering and Technology (and others)."""
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Department(TimeStampedUUIDModel):
    """Academic department within a faculty."""
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        ordering = ["faculty__code", "code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Semester(TimeStampedUUIDModel):
    """e.g. 2026/2027 Semester 1."""
    name = models.CharField(max_length=100)
    academic_year = models.CharField(max_length=10, db_index=True)
    number = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    registration_deadline = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default="ACTIVE")
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-academic_year", "number"]
        unique_together = [("academic_year", "number")]
        constraints = [
            # At most one semester may be active at a time. The partial unique
            # index makes this a hard DB guarantee (the save() demotion alone
            # is racy under concurrent activation).
            models.UniqueConstraint(
                fields=["is_active"],
                condition=Q(is_active=True),
                name="unique_active_semester",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                Semester.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
            super().save(*args, **kwargs)


class Course(TimeStampedUUIDModel):
    """Academic subject/module. Code must be unique within institution (BR-001)."""
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="courses")
    code = models.CharField(max_length=20, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    credit_units = models.PositiveIntegerField(default=3)
    level = models.CharField(max_length=10, blank=True, default="")
    status = models.CharField(max_length=20, default="ACTIVE")
    # Students appointed to run attendance for this course across every
    # offering/section of it (departmental course delegates).
    department_delegates = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="department_delegate_courses",
        help_text="Students who may launch attendance for any offering of this course.",
    )

    class Meta:
        ordering = ["department__code", "code"]

    def __str__(self):
        return f"{self.code} - {self.title}"


class CourseOffering(TimeStampedUUIDModel):
    """A course taught during a specific semester.
    Distinguishes the course definition from semester-specific offerings."""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="offerings")
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="course_offerings")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="course_offerings")
    lecturer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="offering_lectures"
    )
    co_lecturer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="co_offering_lectures",
        help_text="Optional second lecturer when the course is co-taught.",
    )
    # Extra departments whose students may register for this offering. The
    # primary `department` above always applies as well; this M2M only extends
    # the audience for cross-department courses.
    departments = models.ManyToManyField(
        Department, blank=True, related_name="shared_course_offerings",
        help_text="Additional departments allowed to register for this offering.",
    )
    status = models.CharField(max_length=20, default="ACTIVE")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-semester__academic_year", "course__code"]
        unique_together = [("course", "semester")]

    def clean(self):
        super().clean()
        # The denormalised department drives admin scoping, so it must never
        # diverge from the course it belongs to - a mismatch would hand the
        # offering to the wrong department's administrators.
        if self.course_id and self.department_id and self.course.department_id != self.department_id:
            raise ValidationError(
                {"department": "The offering department must match the course's department."}
            )
        if self.lecturer_id and self.co_lecturer_id and self.lecturer_id == self.co_lecturer_id:
            raise ValidationError(
                {"co_lecturer": "The co-lecturer must be a different person from the lead lecturer."}
            )

    @property
    def lecturer_ids(self):
        return {pk for pk in (self.lecturer_id, self.co_lecturer_id) if pk}

    def is_taught_by(self, user):
        """True when `user` is the lead or co-lecturer of this offering."""
        return bool(getattr(user, "is_authenticated", False) and user.id in self.lecturer_ids)

    @property
    def all_department_ids(self):
        """Primary department plus every shared department."""
        extra = set(self.departments.values_list("id", flat=True)) if self.pk else set()
        return ({self.department_id} if self.department_id else set()) | extra

    def __str__(self):
        return f"{self.course.code} - {self.semester.name}"


class Enrollment(TimeStampedUUIDModel):
    """Student-course enrollment (Core relationship - Functional Req FR-001/002).

    Enrollment is the primary academic relationship.
    Students enroll in COURSE OFFERINGS, not individual classes.
    The system determines class eligibility from enrollment (BR-011).
    """
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DROPPED = "DROPPED", "Dropped"
        COMPLETED = "COMPLETED", "Completed"
        SUSPENDED = "SUSPENDED", "Suspended"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course_offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    enrolled_at = models.DateTimeField(default=timezone.now)
    dropped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(fields=["student", "course_offering"], name="unique_enrollment"),
        ]

    def __str__(self):
        return f"{self.student.email} -> {self.course_offering}"


class CarryOverApplication(TimeStampedUUIDModel):
    """A student applying to take a course they were not enrolled in
    (e.g. repeating a failed course from a previous level - carry over).

    Approved applications create an Enrollment, which is what gates
    attendance confirmation (BR-031).
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="carry_over_applications"
    )
    course_offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="carry_over_applications")
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_carry_overs"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["student", "course_offering"], name="unique_carry_over_application"),
        ]

    def __str__(self):
        return f"CarryOver({self.student.email} -> {self.course_offering}, {self.status})"


class ClassDefinition(TimeStampedUUIDModel):
    """Teaching context (lecture, practical, tutorial) under a course offering.
    Distinguished from ClassSession for attendance tracking."""

    class ClassType(models.TextChoices):
        LECTURE = "LECTURE", "Lecture"
        PRACTICAL = "PRACTICAL", "Practical"
        TUTORIAL = "TUTORIAL", "Tutorial"
        LAB = "LAB", "Laboratory"
        OTHER = "OTHER", "Other"

    course_offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="class_definitions")
    lecturer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="class_definitions"
    )
    name = models.CharField(max_length=200)
    class_type = models.CharField(max_length=20, choices=ClassType.choices, default=ClassType.LECTURE)
    location = models.CharField(max_length=100, blank=True, default="")
    recurrence_rule = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        ordering = ["course_offering__course__code", "name"]

    def __str__(self):
        return f"{self.name} ({self.class_type})"


class ClassSchedule(TimeStampedUUIDModel):
    """Weekly recurring teaching slot (the lecturer's timetable).

    e.g. "CSC301 Lecture, Monday 10:00-12:00, Room 204".
    Used to prefill attendance sessions; lecturers can still start a
    session at a custom time when periods are swapped (FR-040 note).
    """

    class DayOfWeek(models.TextChoices):
        MONDAY = "MONDAY", "Monday"
        TUESDAY = "TUESDAY", "Tuesday"
        WEDNESDAY = "WEDNESDAY", "Wednesday"
        THURSDAY = "THURSDAY", "Thursday"
        FRIDAY = "FRIDAY", "Friday"
        SATURDAY = "SATURDAY", "Saturday"
        SUNDAY = "SUNDAY", "Sunday"

    course_offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="schedules")
    lecturer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teaching_schedules")
    class_type = models.CharField(max_length=20, choices=ClassDefinition.ClassType.choices, default=ClassDefinition.ClassType.LECTURE)
    day_of_week = models.CharField(max_length=10, choices=DayOfWeek.choices, db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["course_offering__course__code", "day_of_week", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["course_offering", "day_of_week", "start_time"],
                name="unique_offering_day_start",
            ),
        ]

    def __str__(self):
        return f"{self.course_offering} {self.day_of_week} {self.start_time}-{self.end_time}"


class ClassSession(TimeStampedUUIDModel):
    """An actual occurrence of a class (e.g. Monday 08:00).

    For attendance, we track the session not the definition.
    """
    class_definition = models.ForeignKey(ClassDefinition, on_delete=models.CASCADE, related_name="sessions")
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="SCHEDULED", db_index=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.class_definition.name} @ {self.starts_at}"

    @property
    def course_offering(self):
        return self.class_definition.course_offering

    @property
    def eligible_students(self):
        """Students with active enrollment in the offering (BR-011/BR-012)."""
        return get_user_model().objects.filter(
            enrollments__course_offering=self.class_definition.course_offering,
            enrollments__status="ACTIVE",
        ).select_related("student_profile")
