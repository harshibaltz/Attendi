"""Remove courses and attendance left behind by already-deleted accounts.

New deletions purge this data immediately. This backfill applies the same
rule to accounts that were deleted before that change, so they no longer show
up in class rosters, exports or attendance history.
"""
from django.db import migrations


def purge_deleted_account_activity(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Enrollment = apps.get_model("academics", "Enrollment")
    AttendanceRecord = apps.get_model("attendance", "AttendanceRecord")
    AttendanceCheckpoint = apps.get_model("attendance", "AttendanceCheckpoint")
    PointsLedger = apps.get_model("attendance", "PointsLedger")

    deleted_ids = list(
        User.objects.filter(deleted_at__isnull=False).values_list("id", flat=True)
    )
    if not deleted_ids:
        return
    AttendanceRecord.objects.filter(student_id__in=deleted_ids).delete()
    AttendanceCheckpoint.objects.filter(student_id__in=deleted_ids).delete()
    PointsLedger.objects.filter(student_id__in=deleted_ids).delete()
    Enrollment.objects.filter(student_id__in=deleted_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_user_deleted_at_user_deleted_from_email_and_more"),
        ("academics", "0012_remove_legacy_ee_department"),
        ("attendance", "0006_checkpoint_scan_selection"),
    ]

    operations = [
        migrations.RunPython(purge_deleted_account_activity, migrations.RunPython.noop),
    ]
