from datetime import timedelta

import pytest
from django.utils import timezone

from apps.notifications.models import Notification, PlatformUpdate


@pytest.mark.django_db
def test_published_update_is_delivered_once(api_client, student_user):
    update = PlatformUpdate.objects.create(
        version="2026.10.28", title="Faster attendance", message="Stations now rotate faster."
    )
    api_client.force_authenticate(user=student_user)

    first = api_client.get("/api/v1/notifications/")
    assert first.status_code == 200, first.content
    rows = first.json()["data"]
    assert len(rows) == 1
    assert rows[0]["type"] == "PLATFORM_UPDATE"
    assert rows[0]["reference_id"] == str(update.id)

    # Reading again must not duplicate the notification.
    second = api_client.get("/api/v1/notifications/")
    assert second.status_code == 200
    assert len(second.json()["data"]) == 1
    assert Notification.objects.filter(user=student_user).count() == 1


@pytest.mark.django_db
def test_scheduled_or_inactive_update_is_not_delivered(api_client, student_user):
    PlatformUpdate.objects.create(
        version="future", title="Not yet", published_at=timezone.now() + timedelta(days=1)
    )
    PlatformUpdate.objects.create(version="old", title="Disabled", is_active=False)
    api_client.force_authenticate(user=student_user)

    response = api_client.get("/api/v1/notifications/")
    assert response.status_code == 200, response.content
    assert response.json()["data"] == []


@pytest.mark.django_db
def test_mark_all_read(api_client, student_user):
    PlatformUpdate.objects.create(version="v1", title="Hello")
    api_client.force_authenticate(user=student_user)
    api_client.get("/api/v1/notifications/")

    response = api_client.post("/api/v1/notifications/read-all/")
    assert response.status_code == 200, response.content
    assert response.json()["data"]["message"] == "All notifications marked as read."
    assert Notification.objects.filter(user=student_user, read_at__isnull=True).count() == 0
