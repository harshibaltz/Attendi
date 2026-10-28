"""Signed QR capture, delayed sync, credentials, and legacy transition."""

import base64
import hashlib
import hmac
from datetime import timedelta

import pytest
from django.core.checks import run_checks
from django.test import override_settings
from django.utils import timezone

from apps.academics.models import Enrollment
from apps.attendance.models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession, PointsLedger
from apps.attendance.token_store import (
    TOKEN_HEADER, TOKEN_TTL, TokenVerificationError, credential_bundle, decode_token_version, generate_hmac_token,
    generate_session_token, verify_hmac_token,
)


def make_session(class_session, lecturer_user, *, started=None, seconds=150):
    started = started or timezone.now() - timedelta(seconds=2)
    return AttendanceSession.objects.create(
        class_session=class_session, lecturer=lecturer_user,
        started_at=started, expires_at=started + timedelta(seconds=seconds),
    )


def sync(api_client, student, session, *tokens, **capture_fields):
    api_client.force_authenticate(user=student)
    response = api_client.post(
        "/api/v1/attendance/offline-sync/",
        {"session_id": str(session.id), "captures": [
            {"token": token, **capture_fields} for token in tokens
        ]},
        format="json",
    )
    return response, response.json().get("data", {})


@pytest.mark.django_db
def test_hmac_token_roundtrip_and_device_key(class_session, lecturer_user):
    session = make_session(class_session, lecturer_user)
    token = generate_hmac_token(session, slot_index=0)
    claims = verify_hmac_token(token)
    assert claims["session_id"] == session.id
    assert claims["checkpoint_id"] is None
    assert claims["slot_index"] == 0
    bundle = credential_bundle(session)
    raw = base64.urlsafe_b64decode(token + "===")
    device_key = base64.urlsafe_b64decode(bundle["hmac_key"] + "===")
    assert hmac.compare_digest(
        hmac.new(device_key, raw[:TOKEN_HEADER.size], hashlib.sha256).digest(),
        raw[TOKEN_HEADER.size:],
    )
    assert len(device_key) == 32
    broken = bytearray(raw)
    broken[20] ^= 1
    with pytest.raises(TokenVerificationError):
        verify_hmac_token(base64.urlsafe_b64encode(broken).rstrip(b"=").decode())


@pytest.mark.django_db
def test_capture_window_rejects_late_slot(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(class_session, lecturer_user, started=timezone.now() - timedelta(seconds=30), seconds=150)
    session.effective_end_at = timezone.now() - timedelta(seconds=11)
    session.save(update_fields=["effective_end_at"])
    response, data = sync(api_client, enrolled_student, session, generate_hmac_token(session, slot_index=3))
    assert response.status_code == 200
    assert data["results"][0]["code"] == "CAPTURE_WINDOW_EXPIRED"
    assert not AttendanceRecord.objects.filter(attendance_session=session).exists()


@pytest.mark.django_db
def test_grace_period_accepts_late_sync(api_client, class_session, lecturer_user, enrolled_student):
    started = timezone.now() - timedelta(hours=1)
    session = make_session(class_session, lecturer_user, started=started, seconds=40)
    token = generate_hmac_token(session, slot_index=0)
    response, data = sync(
        api_client, enrolled_student, session, token,
        captured_at_client=(timezone.now() + timedelta(days=30)).isoformat(),
    )
    assert response.status_code == 200
    assert data["results"][0]["status"] == "ACCEPTED"
    record = AttendanceRecord.objects.get(attendance_session=session, student=enrolled_student)
    assert record.capture_slot_index == 0
    assert record.capture_verified_at is not None
    assert record.sync_batch_id is not None
    assert record.offline_idempotency_key
    assert PointsLedger.objects.filter(attendance_session=session, student=enrolled_student).count() == 1


@pytest.mark.django_db
def test_grace_period_expires(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(
        class_session, lecturer_user,
        started=timezone.now() - timedelta(hours=25), seconds=40,
    )
    response, data = sync(api_client, enrolled_student, session, generate_hmac_token(session, slot_index=0))
    assert response.status_code == 200
    assert data["results"][0]["code"] == "SYNC_GRACE_EXPIRED"
    assert not AttendanceRecord.objects.filter(attendance_session=session).exists()


@pytest.mark.django_db
def test_idempotent_sync_does_not_double_award(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(class_session, lecturer_user)
    token = generate_hmac_token(session, slot_index=0)
    first, first_data = sync(api_client, enrolled_student, session, token)
    second, second_data = sync(api_client, enrolled_student, session, token)
    assert first.status_code == second.status_code == 200
    assert first_data["results"][0]["status"] == "ACCEPTED"
    assert second_data["results"][0]["status"] == "DUPLICATE"
    assert first_data["results"][0]["record_id"] == second_data["results"][0]["record_id"]
    assert AttendanceRecord.objects.filter(attendance_session=session, student=enrolled_student).count() == 1
    assert PointsLedger.objects.filter(attendance_session=session, student=enrolled_student).count() == 1


@pytest.mark.django_db
def test_manual_close_sets_effective_end_and_rejects_future_slot(
    api_client, class_session, lecturer_user, enrolled_student,
):
    session = make_session(class_session, lecturer_user, started=timezone.now() - timedelta(seconds=30))
    api_client.force_authenticate(user=lecturer_user)
    closed = api_client.post(f"/api/v1/attendance/{session.id}/close/", {}, format="json")
    assert closed.status_code == 200
    session.refresh_from_db()
    assert session.effective_end_at is not None
    assert session.effective_end_at < session.expires_at
    response, data = sync(api_client, enrolled_student, session, generate_hmac_token(session, slot_index=4))
    assert response.status_code == 200
    assert data["results"][0]["code"] == "CAPTURE_WINDOW_EXPIRED"


@pytest.mark.django_db
def test_credentials_are_scoped_and_private(
    api_client, class_session, lecturer_user, enrolled_student, student2_user,
):
    session = make_session(class_session, lecturer_user)
    checkpoint = AttendanceCheckpoint.objects.create(
        attendance_session=session, student=enrolled_student, checkpoint_number=1,
    )
    station_url = f"/api/v1/attendance/{session.id}/station-credential/"
    projector_url = f"/api/v1/attendance/{session.id}/projector-credential/"
    api_client.force_authenticate(user=student2_user)
    assert api_client.get(station_url).status_code == 403
    api_client.force_authenticate(user=enrolled_student)
    station = api_client.get(station_url)
    assert station.status_code == 200
    assert station.json()["data"]["checkpoint_id"] == str(checkpoint.id)
    assert station["Cache-Control"] == "private, no-store"
    assert api_client.get(projector_url).status_code == 403
    api_client.force_authenticate(user=lecturer_user)
    projector = api_client.get(projector_url)
    assert projector.status_code == 200
    assert projector.json()["data"]["checkpoint_id"] is None
    assert projector.json()["data"]["hmac_key"] != station.json()["data"]["hmac_key"]


@pytest.mark.django_db
def test_two_students_can_sync_same_station_token(
    api_client, class_session, lecturer_user, enrolled_student, student2_user,
):
    session = make_session(class_session, lecturer_user)
    Enrollment.objects.create(
        student=student2_user, course_offering=session.course_offering,
        status=Enrollment.Status.ACTIVE,
    )
    checkpoint = AttendanceCheckpoint.objects.create(
        attendance_session=session, student=enrolled_student, checkpoint_number=1,
    )
    token = generate_hmac_token(session, checkpoint.id, slot_index=0)
    a, a_data = sync(api_client, enrolled_student, session, token, checkpoint_id=str(checkpoint.id))
    b, b_data = sync(api_client, student2_user, session, token, checkpoint_id=str(checkpoint.id))
    assert a.status_code == b.status_code == 200
    assert a_data["results"][0]["status"] == b_data["results"][0]["status"] == "ACCEPTED"
    assert AttendanceRecord.objects.filter(attendance_session=session).count() == 2


@pytest.mark.django_db
def test_legacy_v1_scan_still_works(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(class_session, lecturer_user)
    token = generate_session_token(session)["token"]
    api_client.force_authenticate(user=enrolled_student)
    response = api_client.post("/api/v1/attendance/scan/", {"token": token}, format="json")
    assert response.status_code == 201
    assert AttendanceRecord.objects.filter(attendance_session=session, student=enrolled_student).exists()


@pytest.mark.django_db
def test_live_v2_scan_and_partial_batch(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(class_session, lecturer_user)
    token = generate_hmac_token(session, slot_index=0)
    api_client.force_authenticate(user=enrolled_student)
    live = api_client.post("/api/v1/attendance/scan/", {"token": token}, format="json")
    assert live.status_code == 201
    assert AttendanceRecord.objects.get(attendance_session=session).capture_slot_index == 0

    other = make_session(class_session, lecturer_user)
    response, data = sync(api_client, enrolled_student, other, "legacy-token", generate_hmac_token(other, slot_index=0))
    assert response.status_code == 200
    assert [item["status"] for item in data["results"]] == ["REJECTED", "ACCEPTED"]


@pytest.mark.django_db
def test_signed_token_cannot_cross_sessions(api_client, class_session, lecturer_user, enrolled_student):
    source = make_session(class_session, lecturer_user)
    target = make_session(class_session, lecturer_user)
    response, data = sync(api_client, enrolled_student, target, generate_hmac_token(source, slot_index=0))
    assert response.status_code == 200
    assert data["results"][0]["code"] == "TOKEN_INVALID"
    assert not AttendanceRecord.objects.filter(attendance_session=target).exists()


@pytest.mark.django_db
def test_qr_endpoint_preserves_v1_default_and_allows_v2_opt_in(api_client, class_session, lecturer_user):
    session = make_session(class_session, lecturer_user)
    api_client.force_authenticate(user=lecturer_user)
    url = f"/api/v1/attendance/{session.id}/tokens/"
    legacy = api_client.post(url, {}, format="json")
    signed = api_client.post(url + "?token_version=2", {}, format="json")
    assert legacy.status_code == signed.status_code == 200
    assert decode_token_version(legacy.json()["data"]["tokens"][0]["token"]) == 1
    assert decode_token_version(signed.json()["data"]["tokens"][0]["token"]) == 2


@pytest.mark.django_db
def test_qr_endpoint_does_not_issue_unusable_final_slot(api_client, class_session, lecturer_user):
    session = make_session(
        class_session, lecturer_user,
        started=timezone.now() - timedelta(seconds=TOKEN_TTL * 4 + 1),
        seconds=TOKEN_TTL * 4 + 3,
    )
    api_client.force_authenticate(user=lecturer_user)
    response = api_client.post(
        f"/api/v1/attendance/{session.id}/tokens/?token_version=2", {}, format="json",
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "TOKEN_WINDOW_EXPIRED"


@pytest.mark.django_db
@override_settings(ATTENDANCE_OFFLINE_SYNC_MAX_CAPTURES=1)
def test_sync_batch_size_is_bounded(api_client, class_session, lecturer_user, enrolled_student):
    session = make_session(class_session, lecturer_user)
    token = generate_hmac_token(session, slot_index=0)
    response, _data = sync(api_client, enrolled_student, session, token, token)
    assert response.status_code == 400
    assert not AttendanceRecord.objects.filter(attendance_session=session).exists()


@pytest.mark.django_db
@override_settings(DEBUG=False, ATTENDANCE_TOKEN_HMAC_KEY="short")
def test_production_check_rejects_weak_hmac_key():
    assert "fet.E008" in {message.id for message in run_checks()}
