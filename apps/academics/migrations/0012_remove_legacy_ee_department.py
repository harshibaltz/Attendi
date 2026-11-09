"""Remove the old "EE / Electrical Engineering" department.

It is a duplicate of the real EEN department and has no courses or offerings.
Students who registered under it are moved to EEN, then the department is
deleted so it can never appear on the self-registration form again.
"""
from django.db import migrations


def remove_legacy_ee(apps, schema_editor):
    Department = apps.get_model("academics", "Department")
    StudentProfile = apps.get_model("accounts", "StudentProfile")
    LecturerProfile = apps.get_model("accounts", "LecturerProfile")
    User = apps.get_model("accounts", "User")
    CourseOffering = apps.get_model("academics", "CourseOffering")

    legacy = Department.objects.filter(code="EE", name="Electrical Engineering").first()
    if not legacy:
        return
    replacement = Department.objects.filter(code="EEN").first()
    if not replacement:
        return

    StudentProfile.objects.filter(department=legacy).update(department=replacement)
    LecturerProfile.objects.filter(department=legacy).update(department=replacement)
    User.objects.filter(admin_department=legacy).update(admin_department=replacement)
    for offering in CourseOffering.objects.filter(departments=legacy):
        offering.departments.remove(legacy)
    legacy.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0011_courseoffering_registration_deadline"),
        ("accounts", "0008_user_deleted_at_user_deleted_from_email_and_more"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_ee, migrations.RunPython.noop),
    ]
