"""Attendance services - QR tokens, rotation, scan validation.

Token storage uses Django cache (Redis in production, LocMem in dev).
This satisfies the spec's requirement for temporary QR storage in Redis
while remaining functional without a Redis server during development.

Refs: Tech Stack doc 12 §6-8, Business Rules doc 04 §7-8, API Spec doc 07 §§24-32.
"""
import base64
import binascii
import hashlib
import hmac
import json
import math
import secrets
import struct
from datetime import datetime, timedelta, timezone as datetime_timezone
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession

TOKEN_TTL = getattr(settings, "ATTENDANCE_TOKEN_TTL_SECONDS", 10)
TOKEN_V2 = 2
PROJECTOR_ID = UUID(int=0)
TOKEN_HEADER = struct.Struct(">B16s16sII")
TOKEN_BYTES = TOKEN_HEADER.size + hashlib.sha256().digest_size


class TokenVerificationError(ValueError):
    """A malformed or incorrectly signed attendance token."""


def _decode_b64url(value):
    """Use the exact padding required by strict decoders (including Python 3.14)."""
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True,
    )


def configured_hmac_key():
    """Decode a 32-byte key from hex, base64url, or 32 raw UTF-8 bytes."""
    value = getattr(settings, "ATTENDANCE_TOKEN_HMAC_KEY", "")
    if isinstance(value, bytes):
        key = value
    elif isinstance(value, str):
        try:
            if value.startswith("hex:"):
                key = bytes.fromhex(value[4:])
            elif len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value):
                key = bytes.fromhex(value)
            elif value.startswith("base64:"):
                key = _decode_b64url(value[7:])
            else:
                key = value.encode("utf-8")
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid attendance HMAC key encoding") from exc
    else:
        raise ValueError("Invalid attendance HMAC key type")
    if len(key) < 32:
        raise ValueError("Attendance HMAC key must contain at least 32 bytes")
    return key


def derive_signing_key(session_id, checkpoint_id=None):
    """Scope signing material to one session and one station or projector."""
    session_uuid = UUID(str(session_id))
    checkpoint_uuid = UUID(str(checkpoint_id)) if checkpoint_id else PROJECTOR_ID
    context = b"fet-attendance-v2\x00" + session_uuid.bytes + checkpoint_uuid.bytes
    return hmac.new(configured_hmac_key(), context, hashlib.sha256).digest()


def slot_origin_ts(attendance_session):
    # Whole UTC seconds make the device and server agree on exact 10s slots.
    return math.ceil(attendance_session.started_at.timestamp())


def credential_bundle(attendance_session, checkpoint_id=None):
    """Material a permitted device needs to mint only its own QR tokens."""
    origin = slot_origin_ts(attendance_session)
    duration = TOKEN_TTL
    max_slots = max(0, int((attendance_session.effective_end.timestamp() - origin) // duration))
    key = derive_signing_key(attendance_session.id, checkpoint_id)
    return {
        "session_id": str(attendance_session.id),
        "checkpoint_id": str(checkpoint_id) if checkpoint_id else None,
        "hmac_key_id": "v2",
        "hmac_key": base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii"),
        "session_started_at": attendance_session.started_at,
        "session_expires_at": attendance_session.effective_end,
        "slot_origin_ts": origin,
        "slot_duration_seconds": duration,
        "max_slots": max_slots,
    }


def generate_hmac_token(attendance_session, checkpoint_id=None, slot_index=None, at=None):
    """Sign a compact v2 token for a fixed slot and station."""
    origin = slot_origin_ts(attendance_session)
    current_slot = slot_index is None
    if slot_index is None:
        slot_index = max(0, int(((at or timezone.now()).timestamp() - origin) // TOKEN_TTL))
    if not 0 <= slot_index <= 0xFFFFFFFF:
        raise ValueError("Token slot is outside the supported range")
    expiry_ts = origin + (slot_index + 1) * TOKEN_TTL
    if current_slot and expiry_ts > attendance_session.expires_at.timestamp():
        raise ValueError("No full v2 QR slot remains in this attendance session")
    if expiry_ts > 0xFFFFFFFF:
        raise ValueError("Token expiry is outside the supported range")
    checkpoint_uuid = UUID(str(checkpoint_id)) if checkpoint_id else PROJECTOR_ID
    header = TOKEN_HEADER.pack(
        TOKEN_V2, UUID(str(attendance_session.id)).bytes,
        checkpoint_uuid.bytes, slot_index, expiry_ts,
    )
    signature = hmac.new(
        derive_signing_key(attendance_session.id, checkpoint_id), header, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(header + signature).rstrip(b"=").decode("ascii")


def decode_token_version(token):
    """Identify the fixed-size v2 envelope; opaque legacy tokens remain v1."""
    if not isinstance(token, str) or len(token) != 98:
        return 1
    try:
        raw = _decode_b64url(token)
    except (ValueError, binascii.Error):
        return 1
    return TOKEN_V2 if len(raw) == TOKEN_BYTES and raw[0] == TOKEN_V2 else 1


def verify_hmac_token(token):
    """Verify token integrity without reading Redis or PostgreSQL."""
    try:
        raw = _decode_b64url(token)
        if len(raw) != TOKEN_BYTES:
            raise TokenVerificationError("Invalid v2 token size")
        version, session_bytes, checkpoint_bytes, slot_index, expiry_ts = TOKEN_HEADER.unpack(
            raw[:TOKEN_HEADER.size]
        )
        if version != TOKEN_V2:
            raise TokenVerificationError("Unsupported token version")
        session_id = UUID(bytes=session_bytes)
        checkpoint_uuid = UUID(bytes=checkpoint_bytes)
        checkpoint_id = None if checkpoint_uuid == PROJECTOR_ID else checkpoint_uuid
        expected = hmac.new(
            derive_signing_key(session_id, checkpoint_id), raw[:TOKEN_HEADER.size], hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected, raw[TOKEN_HEADER.size:]):
            raise TokenVerificationError("Invalid token signature")
    except (ValueError, binascii.Error, struct.error) as exc:
        raise TokenVerificationError("Invalid attendance token") from exc
    return {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "slot_index": slot_index,
        "expiry_ts": expiry_ts,
    }


def token_slot_bounds(attendance_session, claims):
    """Recompute slot timing from the database session, never client input."""
    if claims["session_id"] != attendance_session.id:
        raise TokenVerificationError("Session mismatch")
    start_ts = slot_origin_ts(attendance_session) + claims["slot_index"] * TOKEN_TTL
    end_ts = start_ts + TOKEN_TTL
    if claims["expiry_ts"] != end_ts:
        raise TokenVerificationError("Token slot expiry mismatch")
    start = datetime.fromtimestamp(start_ts, tz=datetime_timezone.utc)
    end = datetime.fromtimestamp(end_ts, tz=datetime_timezone.utc)
    return start, end


def generate_token_key(session_id: str, token: str) -> str:
    return f"att:{session_id}:token:{token}"


def generate_token_for_checkpoint(attendance_session: AttendanceSession, checkpoint, version=1) -> dict:
    """Create a single fresh short-lived token for one checkpoint (FR-043)."""
    if version == TOKEN_V2:
        return {
            "checkpoint_id": str(checkpoint.id),
            "checkpoint_number": checkpoint.checkpoint_number,
            "token": generate_hmac_token(attendance_session, checkpoint.id),
        }
    token = secrets.token_urlsafe(32)
    value = json.dumps({
        "attendance_session_id": str(attendance_session.id),
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_number": checkpoint.checkpoint_number,
        "student_email": checkpoint.student.email,
    })
    cache.set(generate_token_key(str(attendance_session.id), token), value, timeout=TOKEN_TTL)
    # Reverse lookup so a scan can find its session in O(1).
    cache.set(f"att:token:{token}", value, timeout=TOKEN_TTL)
    return {
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_number": checkpoint.checkpoint_number,
        "token": token,
    }


def generate_session_token(attendance_session: AttendanceSession, version=1) -> dict:
    """Create a single networked QR token for the whole session (projector mode).

    Not tied to any student station; scans against it are regular QR_SCAN
    entries earning standard scan points (BR-035 fallback when no stations
    have been selected yet).
    """
    if version == TOKEN_V2:
        return {
            "checkpoint_id": None,
            "checkpoint_number": 0,
            "token": generate_hmac_token(attendance_session),
        }
    token = secrets.token_urlsafe(32)
    value = json.dumps({
        "attendance_session_id": str(attendance_session.id),
        "checkpoint_id": None,
        "checkpoint_number": None,
        "student_email": "",
    })
    cache.set(generate_token_key(str(attendance_session.id), token), value, timeout=TOKEN_TTL)
    cache.set(f"att:token:{token}", value, timeout=TOKEN_TTL)
    return {
        "checkpoint_id": None,
        "checkpoint_number": 0,
        "token": token,
    }


def generate_tokens_for_session(attendance_session: AttendanceSession, checkpoints=None, version=1):
    """Generate cryptographically random tokens for each checkpoint (FR-042).

    Each token is short-lived (BR-035, default 10 seconds) and rotated by
    requesting fresh tokens periodically. Tokens are stored in cache,
    NOT in PostgreSQL.

    In projector mode (or before any stations are selected) a single
    session-level token is returned instead.
    """
    if checkpoints is None:
        checkpoints = list(attendance_session.checkpoints.select_related("student").all())
    if not checkpoints or attendance_session.mode == AttendanceSession.SessionMode.PROJECTOR:
        tokens = [generate_session_token(attendance_session, version=version)]
    else:
        tokens = [generate_token_for_checkpoint(attendance_session, cp, version=version) for cp in checkpoints]
    return {
        "expires_in_seconds": TOKEN_TTL,
        "tokens": tokens,
    }


def station_qr_payload(session, checkpoint, version=1):
    """Initial QR for a newly promoted station; subsequent rotations use the token API."""
    try:
        token = generate_token_for_checkpoint(session, checkpoint, version=version)["token"]
    except ValueError:
        return None
    return {
        "attendance_session_id": str(session.id),
        "checkpoint_id": str(checkpoint.id),
        "selection_method": checkpoint.selection_method,
        "token": token,
        "expires_in_seconds": TOKEN_TTL,
    }


def validate_and_record_scan(token: str, requesting_user) -> dict:
    """Validate a scanned token and record attendance if valid (FR-045, API Spec §30).

    Returns a dict with status info and HTTP status code.
    """
    if decode_token_version(token) == TOKEN_V2:
        try:
            claims = verify_hmac_token(token)
        except TokenVerificationError:
            return {"success": False, "error_code": "TOKEN_INVALID", "message": "Invalid QR code.", "http_status": 400}
        from .offline import record_v2_scan

        with transaction.atomic():
            session = AttendanceSession.objects.select_for_update().filter(id=claims["session_id"]).first()
            if session is None:
                return {"success": False, "error_code": "TOKEN_INVALID", "message": "Invalid QR code.", "http_status": 400}
            return record_v2_scan(session, requesting_user, claims)

    key = None
    matched_session_id = None
    token_data = None

    # Search cache for matching token across active sessions
    # We store tokens with known keys, so we iterate the token directly
    # Actually we need to find which session this token belongs to.
    # Strategy: list all att:{session_id}:token: keys is expensive.
    # Instead: when generating tokens, we also store a reverse lookup:
    # att:token:{token} -> session_id
    # Let's implement both directions for O(1) lookup.
    reverse_key = f"att:token:{token}"
    token_data_raw = cache.get(reverse_key)
    if token_data_raw:
        token_data = json.loads(token_data_raw)
        matched_session_id = token_data["attendance_session_id"]
        cache_key = generate_token_key(matched_session_id, token)
        cache_data = cache.get(cache_key)
        if cache_data is None:
            # Token expired
            return {"success": False, "error_code": "TOKEN_EXPIRED", "message": "QR code has expired. Please scan the current QR code.", "http_status": 410}
        token_data = json.loads(cache_data)
    else:
        return {"success": False, "error_code": "TOKEN_INVALID", "message": "Invalid QR code.", "http_status": 400}

    attendance_session_id = token_data["attendance_session_id"]

    with transaction.atomic():
        session = AttendanceSession.objects.select_for_update().get(id=attendance_session_id)

        # BR-030: Attendance requires active session
        if not session.is_active:
            return {"success": False, "error_code": "SESSION_EXPIRED", "message": "Attendance is closed.", "http_status": 410}

        # BR-031: Student must be eligible for the course
        offering = session.course_offering
        from apps.academics.models import Enrollment
        is_enrolled = Enrollment.objects.filter(
            student=requesting_user,
            course_offering=offering,
            status=Enrollment.Status.ACTIVE,
        ).exists()
        if not is_enrolled:
            return {"success": False, "error_code": "NOT_ENROLLED", "message": "You are not enrolled in this course.", "http_status": 403}

        # BR-040: One attendance record per session
        already_attended = AttendanceRecord.objects.filter(
            attendance_session=session,
            student=requesting_user,
        ).exists()
        if already_attended:
            return {"success": False, "error_code": "ALREADY_ATTENDED", "message": "Attendance already recorded for this session.", "http_status": 409}

        # BR-063: Attendance must be for the authenticated student
        checkpoint_id = token_data.get("checkpoint_id")

        # Station capacity: ONLY auto-selected student stations serve at most
        # SCANS_PER_STATION classmates (FR-047). Teacher-selected stations and
        # projector checkpoints are unlimited.
        from .points import POINTS, SCANS_PER_STATION, activate_scanned_station, award_scan_points, award_station_points
        from apps.notifications.models import Notification

        checkpoint = None
        if checkpoint_id:
            checkpoint = AttendanceCheckpoint.objects.select_for_update().select_related("student").filter(
                id=checkpoint_id, attendance_session=session,
            ).first()
            if checkpoint is None:
                return {"success": False, "error_code": "TOKEN_INVALID", "message": "Invalid QR code.", "http_status": 400}

        is_station = (
            checkpoint is not None
            and checkpoint.student.role == "STUDENT"
        )
        is_capped_station = is_station and checkpoint.selection_method in {
            AttendanceCheckpoint.SelectionMethod.AUTO,
            AttendanceCheckpoint.SelectionMethod.SCAN,
        }
        if is_capped_station:
            scans_served = AttendanceRecord.objects.filter(
                checkpoint=checkpoint, verification_method=AttendanceRecord.VerificationMethod.QR_SCAN
            ).count()
            if scans_served >= SCANS_PER_STATION:
                return {
                    "success": False,
                    "error_code": "STATION_FULL",
                    "message": f"This station already served {SCANS_PER_STATION} classmates. Please scan another station or the projector.",
                    "http_status": 409,
                }

        record = AttendanceRecord.objects.create(
            attendance_session=session,
            student=requesting_user,
            checkpoint_id=checkpoint_id,
            verification_method="QR_SCAN",
        )
        station = activate_scanned_station(session, requesting_user)

        # Points: scanners earn 4 pts (projector or student station); the
        # station owner earns 5 pts when their QR is first scanned.
        award_scan_points(session, requesting_user, checkpoint=checkpoint)
        is_student_station = checkpoint is not None and checkpoint.student.role == "STUDENT"
        if is_student_station:
            award_station_points(session, checkpoint)
            # Notify when a station reaches its scan cap.
            if is_capped_station:
                served_now = AttendanceRecord.objects.filter(
                    checkpoint=checkpoint, verification_method=AttendanceRecord.VerificationMethod.QR_SCAN
                ).count()
                if served_now == SCANS_PER_STATION:
                    Notification.objects.create(
                        user=checkpoint.student,
                        type="ATTENDANCE",
                        title="✅ Station complete - all scans used!",
                        message=(f"All {SCANS_PER_STATION} classmates have scanned your station in "
                                 f"{session.class_session.class_definition.course_offering.course.code}. "
                                 f"Your {POINTS['AUTO_STATION']} station points are locked in."),
                        reference_type="AttendanceSession",
                        reference_id=session.id,
                    )

        # Headcount: auto-close session if expected_headcount is set and reached.
        if session.expected_headcount is not None:
            checked_in = AttendanceRecord.objects.filter(attendance_session=session).count()
            if checked_in >= session.expected_headcount and session.headcount_reached_at is None:
                session.headcount_reached_at = timezone.now()
                session.status = AttendanceSession.Status.CLOSED
                session.save(update_fields=["headcount_reached_at", "status", "updated_at"])
                Notification.objects.create(
                    user=session.lecturer,
                    type="ATTENDANCE",
                    title="🎯 Headcount reached - session closed!",
                    message=(f"All {session.expected_headcount} expected students have checked in for "
                             f"{session.class_session.class_definition.course_offering.course.code}."),
                    reference_type="AttendanceSession",
                    reference_id=session.id,
                )

    # Clean up token (cannot be reused - BR-038)
    cache.delete(generate_token_key(attendance_session_id, token))
    cache.delete(reverse_key)

    result = {
        "success": True,
        "attendance_record_id": str(record.id),
        "message": "Attendance recorded.",
        "http_status": 201,
    }
    if station and session.is_active:
        qr = station_qr_payload(session, station)
        if qr:
            result["station_qr"] = qr
    return result
