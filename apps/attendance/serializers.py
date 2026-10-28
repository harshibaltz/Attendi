from django.conf import settings
from rest_framework import serializers

from .models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession


class AttendanceSessionSerializer(serializers.ModelSerializer):
    total_present = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    course_code = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceSession
        fields = [
            "id", "class_session", "lecturer", "started_at", "expires_at", "effective_end_at",
            "status", "mode", "total_present", "class_name", "course_code",
            "expected_headcount", "headcount_reached_at",
        ]

    def get_total_present(self, obj):
        counts = self.context.get("present_by_session")
        if counts is not None:
            return counts.get(obj.id, 0)
        return obj.records.filter(status__in=["PRESENT", "LATE"]).count()

    def get_class_name(self, obj):
        return obj.class_session.class_definition.name

    def get_course_code(self, obj):
        return obj.class_session.class_definition.course_offering.course.code


class AttendanceCheckpointSerializer(serializers.ModelSerializer):
    student_email = serializers.CharField(source="student.email", read_only=True)
    student_name = serializers.SerializerMethodField()
    selection_method = serializers.CharField(read_only=True)
    scans_at_station = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceCheckpoint
        fields = ["id", "student", "student_email", "student_name", "checkpoint_number", "selection_method", "scans_at_station"]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_scans_at_station(self, obj):
        return obj.records.filter(verification_method="QR_SCAN").count()


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_email = serializers.CharField(source="student.email", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_number = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = [
            "id", "attendance_session", "student", "student_email", "student_name",
            "student_number", "department", "level",
            "recorded_at", "updated_at", "verification_method", "status",
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def _profile(self, obj):
        # A student may not have a profile yet (roster import race, admin-only
        # accounts). Reading through the reverse OneToOne can raise, so guard it.
        return getattr(obj.student, "student_profile", None)

    def get_student_number(self, obj):
        profile = self._profile(obj)
        return getattr(profile, "student_number", None) or ""

    def get_department(self, obj):
        profile = self._profile(obj)
        department = getattr(profile, "department", None) if profile else None
        if not department:
            return ""
        return department.name or department.code or ""

    def get_level(self, obj):
        profile = self._profile(obj)
        return getattr(profile, "level", "") or ""


class ScanRequestSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)


class OfflineCaptureSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)
    captured_at_client = serializers.DateTimeField(required=False)
    checkpoint_id = serializers.UUIDField(required=False, allow_null=True)
    verification_method = serializers.ChoiceField(choices=["QR_SCAN"], default="QR_SCAN")


class OfflineSyncSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    captures = OfflineCaptureSerializer(
        many=True, allow_empty=False,
        max_length=settings.ATTENDANCE_OFFLINE_SYNC_MAX_CAPTURES,
    )

    def validate_captures(self, captures):
        if len(captures) > settings.ATTENDANCE_OFFLINE_SYNC_MAX_CAPTURES:
            raise serializers.ValidationError("Too many captures in one batch.")
        return captures


class CredentialBundleSerializer(serializers.Serializer):
    session_id = serializers.UUIDField()
    checkpoint_id = serializers.UUIDField(allow_null=True)
    hmac_key_id = serializers.CharField()
    hmac_key = serializers.CharField()
    session_started_at = serializers.DateTimeField()
    session_expires_at = serializers.DateTimeField()
    slot_origin_ts = serializers.IntegerField()
    slot_duration_seconds = serializers.IntegerField()
    max_slots = serializers.IntegerField()
