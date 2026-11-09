import re

from django.db import migrations

_USER_WORD = re.compile(r"(?i)(?:^|\s)user(?=\s|$)")


def _strip_placeholder(value):
    if not value:
        return value
    return re.sub(r"\s+", " ", _USER_WORD.sub(" ", value)).strip()


def strip_placeholder_names(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    updates = []
    for user in User.objects.only("id", "first_name", "last_name").iterator():
        first_name = _strip_placeholder(user.first_name)
        last_name = _strip_placeholder(user.last_name)
        if not first_name and not last_name:
            continue
        if first_name != user.first_name or last_name != user.last_name:
            user.first_name = first_name
            user.last_name = last_name
            updates.append(user)
    if updates:
        User.objects.bulk_update(updates, ["first_name", "last_name"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0010_admin_deletion_reason"),
    ]

    operations = [
        migrations.RunPython(strip_placeholder_names, migrations.RunPython.noop),
    ]
