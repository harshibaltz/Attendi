"""Station auto-selection and points awarding (FR-047/048 + gamification).

Points (settings-overridable):
  AUTO_STATION       5 - station picked by the system (the student is also
                         marked present as soon as they are selected)
  STUDENT_OF_CLASS  10 - algorithm-picked star of the session (once per
                         student per course - never repeated for the same
                         course, still eligible for other courses)
  TEACHER_STATION    5 - station picked by the lecturer
  STATION_SCAN       4 - regular QR scan (projector or a classmate's station)
  MANUAL             0 - added manually after the session (discouraged)

Special day (birthday): every award the student earns that day is DOUBLED.
"""
import random

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.academics.models import Enrollment

from .models import AttendanceCheckpoint, AttendanceRecord, AttendanceSession, PointsLedger

POINTS = {
    "AUTO_STATION": getattr(settings, "ATTENDANCE_POINTS_AUTO_STATION", 5),
    "TEACHER_STATION": getattr(settings, "ATTENDANCE_POINTS_TEACHER_STATION", 5),
    "STATION_SCAN": getattr(settings, "ATTENDANCE_POINTS_STATION_SCAN", 4),
    "SCAN": getattr(settings, "ATTENDANCE_POINTS_SCAN", 4),
    "MANUAL": getattr(settings, "ATTENDANCE_POINTS_MANUAL", 0),
    "STUDENT_OF_CLASS": getattr(settings, "ATTENDANCE_POINTS_STUDENT_OF_CLASS", 10),
}
SPECIAL_DAY_MULTIPLIER = getattr(settings, "ATTENDANCE_SPECIAL_DAY_MULTIPLIER", 2)
# Auto-selection is capped: only 3 stations in the entire class per session.
MAX_AUTO_STATIONS = getattr(settings, "ATTENDANCE_MAX_AUTO_STATIONS", 3)
# Each station serves at most this many classmates (choose wisely!).
SCANS_PER_STATION = getattr(settings, "ATTENDANCE_SCANS_PER_STATION", 2)


def _notify_points(user, title, message, session=None, ntype="ATTENDANCE"):
    """Fire an in-app notification so students feel every point land."""
    try:
        from apps.notifications.models import Notification

        Notification.objects.create(
            user=user,
            type=ntype,
            title=title,
            message=message,
            reference_type="AttendanceSession",
            reference_id=session.id if session else None,
        )
    except Exception:
        pass  # notifications must never break attendance


def _celebrate(user, base: int, category: str, session=None, when=None) -> int:
    """Apply the special-day multiplier, persist nothing, and return final points."""
    special = is_special_day(user, when=when)
    final = base * SPECIAL_DAY_MULTIPLIER if special else base
    course = ""
    if session is not None:
        try:
            course = session.class_session.class_definition.course_offering.course.code
        except Exception:
            course = ""
    if category == PointsLedger.Category.SCAN:
        _notify_points(
            user,
            f"+{final} points - attendance recorded! 🎉",
            (f"Happy Birthday! 🎂 Your scan earned DOUBLE points ({base} x{SPECIAL_DAY_MULTIPLIER})." if special
             else f"Your attendance for {course} was confirmed. Keep showing up to earn more!"),
            session=session,
        )
    elif category == PointsLedger.Category.STATION_SCAN:
        _notify_points(
            user,
            f"+{final} points - station scan! ⚡",
            (f"Happy Birthday! 🎂 Doubled ({base} x{SPECIAL_DAY_MULTIPLIER})." if special
             else f"You scanned at a classmate's station in {course} - station scans earn {base} pts. Nice and fast!"),
            session=session,
        )
    elif category == PointsLedger.Category.AUTO_STATION:
        _notify_points(
            user,
            f"⭐ Station points locked in: +{final} points!",
            (f"Happy Birthday! 🎂 Your station bonus is DOUBLED ({base} x{SPECIAL_DAY_MULTIPLIER})." if special
             else f"The system picked you as a station in {course}. Your attendance is confirmed and your {base} station points are locked in - classmates can still scan your QR."),
            session=session,
        )
    elif category == PointsLedger.Category.TEACHER_STATION:
        _notify_points(
            user,
            f"Station points locked in: +{final} points",
            (f"Happy Birthday! 🎂 Doubled ({base} x{SPECIAL_DAY_MULTIPLIER})." if special
             else f"Your lecturer picked you as a station in {course}. Your attendance is confirmed and your {base} station points are locked in."),
            session=session,
        )
    elif category == PointsLedger.Category.STUDENT_OF_CLASS:
        _notify_points(
            user,
            f"🌟 Student of the Class! +{final} points",
            (f"Happy Birthday AND Student of the Class in {course} - points DOUBLED ({base} x{SPECIAL_DAY_MULTIPLIER})! 🎂" if special
             else f"The algorithm chose you as the star of {course} today. One per course - see you at the next one!"),
            session=session,
        )
    return final


def is_special_day(user, when=None) -> bool:
    """True on the user's birthday (Feb 29 birthdays celebrate Feb 28)."""
    dob = getattr(user, "date_of_birth", None)
    if dob is None:
        return False
    when = timezone.localtime(when) if when is not None else timezone.localtime()
    try:
        return (when.month, when.day) == (dob.month, dob.day)
    except ValueError:  # e.g. Feb 29 in a non-leap year
        return (when.month, when.day) == (2, 28)


def _final_points(base: int, user) -> int:
    return base * SPECIAL_DAY_MULTIPLIER if is_special_day(user) else base


def attendance_rate_for_students(offering, student_ids):
    """Map student_id -> attendance rate (0.0-1.0) across the offering's sessions."""
    total_sessions = AttendanceSession.objects.filter(
        class_session__class_definition__course_offering=offering
    ).count()
    if total_sessions == 0 or not student_ids:
        return {}
    records = AttendanceRecord.objects.filter(
        attendance_session__class_session__class_definition__course_offering=offering,
        student_id__in=student_ids,
    ).values_list("student_id", flat=True)
    counts = {}
    for sid in records:
        counts[sid] = counts.get(sid, 0) + 1
    return {sid: counts.get(sid, 0) / total_sessions for sid in student_ids}


@transaction.atomic
def auto_select_stations(attendance_session: AttendanceSession, count: int = 3):
    """Pick stations ONLY from students verified present in THIS session (FR-047).

    The candidate pool is the set of students who already checked in for this
    exact attendance session (they scanned a QR). Historical attendance is
    used only as a tie-breaker WITHIN that verified-present pool, so an
    absentee (no matter how consistent in the past) can never be picked.

    Hard cap: only MAX_AUTO_STATIONS (3) auto-selected stations exist in
    the entire class per session. A picked student is marked present and
    receives their station points immediately, whether or not anyone scans
    their QR. Their station serves the first SCANS_PER_STATION (2)
    classmates, who each earn bonus points - so they share the QR wisely,
    not just with their closest friends.

    The session row is locked so two concurrent selections cannot both read
    the same checkpoint count and together exceed MAX_AUTO_STATIONS.
    """
    # Row-lock the session so concurrent requests cannot all pass the cap
    # check and over-create stations (or collide on checkpoint numbers).
    attendance_session = AttendanceSession.objects.select_for_update().get(id=attendance_session.id)
    existing_auto = attendance_session.checkpoints.filter(
        selection_method=AttendanceCheckpoint.SelectionMethod.AUTO
    ).count()
    if existing_auto >= MAX_AUTO_STATIONS:
        return []
    count = min(count, MAX_AUTO_STATIONS - existing_auto)
    if count <= 0:
        return []

    # Presence gate: candidates must have recorded THIS session (proven present).
    pool = set(
        AttendanceRecord.objects.filter(attendance_session=attendance_session)
        .values_list("student_id", flat=True)
    )
    existing = set(attendance_session.checkpoints.values_list("student_id", flat=True))
    candidates = [sid for sid in pool if sid not in existing]
    if not candidates:
        return []

    # Within the present pool, prefer the most consistent attendees (FR-047 spirit).
    offering = attendance_session.course_offering
    rates = attendance_rate_for_students(offering, candidates)
    candidates.sort(key=lambda sid: rates.get(sid, 0), reverse=True)
    top_pool = candidates[: max(1, len(candidates) // 2 + 1)]
    chosen = random.sample(top_pool, min(count, len(top_pool)))

    next_number = attendance_session.checkpoints.count()
    created = []
    for sid in chosen:
        next_number += 1
        cp = AttendanceCheckpoint.objects.create(
            attendance_session=attendance_session,
            student_id=sid,
            checkpoint_number=next_number,
            selection_method=AttendanceCheckpoint.SelectionMethod.AUTO,
        )
        created.append(cp)
        # Being picked as a station confirms attendance and locks in the
        # station points immediately - it must not depend on classmates scanning.
        award_station_points(attendance_session, cp)
        _notify_points(
            cp.student,
            "🎯 You have been selected as a station!",
            (f"You are one of only {MAX_AUTO_STATIONS} auto-selected stations in class today. "
             f"Your attendance is confirmed and you have {POINTS['AUTO_STATION']} station points. "
             f"Show your QR from the Attendance page - the first {SCANS_PER_STATION} classmates to scan "
             f"earn {POINTS['STATION_SCAN']} pts each. "
             f"Share it fairly - your station locks after {SCANS_PER_STATION} scans!"),
            session=attendance_session,
        )
    return created


@transaction.atomic
def award_station_points(attendance_session: AttendanceSession, checkpoint: AttendanceCheckpoint, when=None):
    """Confirm the station student present and award their points (FR-048).

    Called as soon as a station is assigned and again on scans; the ledger
    unique constraint makes it idempotent, so the station student keeps
    attendance and points even if nobody scans their QR.

    AUTO- and TEACHER-selected student stations earn the same base points.
    Projector "stations" (lecturer-owned checkpoints) earn nothing.
    Doubled on the student's birthday.

    The session row is locked so the exists-check and the ledger insert are
    one atomic step (the unique(student, session) constraint is the backstop).
    """
    attendance_session = AttendanceSession.objects.select_for_update().get(id=attendance_session.id)
    if checkpoint.student.role != "STUDENT":
        return
    is_student_station = checkpoint.student.role == "STUDENT"
    is_auto = checkpoint.selection_method in {
        AttendanceCheckpoint.SelectionMethod.AUTO,
        AttendanceCheckpoint.SelectionMethod.SCAN,
    }
    category = (
        PointsLedger.Category.AUTO_STATION if is_auto else PointsLedger.Category.TEACHER_STATION
    )
    AttendanceRecord.objects.get_or_create(
        attendance_session=attendance_session,
        student=checkpoint.student,
        defaults={
            "checkpoint": checkpoint,
            "verification_method": AttendanceRecord.VerificationMethod.QR_STATION,
            "status": "PRESENT",
        },
    )
    entry = PointsLedger.objects.select_for_update().filter(
        student=checkpoint.student, attendance_session=attendance_session,
    ).first()
    if entry is not None and entry.category in {
        PointsLedger.Category.AUTO_STATION,
        PointsLedger.Category.TEACHER_STATION,
        PointsLedger.Category.STUDENT_OF_CLASS,
    }:
        return
    base = POINTS["AUTO_STATION" if is_auto else "TEACHER_STATION"]
    final = _celebrate(checkpoint.student, base, category, session=attendance_session, when=when)
    if entry is not None:
        # Auto stations must already have checked in, so they normally hold a
        # scan entry (4 pts). Station duty replaces it with the station award
        # instead of adding a second ledger row (one row per session).
        entry.category = category
        entry.points = final
        entry.save(update_fields=["category", "points", "updated_at"])
        return
    PointsLedger.objects.create(
        student=checkpoint.student,
        attendance_session=attendance_session,
        category=category,
        points=final,
    )


def activate_scanned_station(attendance_session, student):
    """Promote a checked-in student while the scan caller holds the session lock."""
    if attendance_session.mode != AttendanceSession.SessionMode.STATIONS or student.role != "STUDENT":
        return None
    checkpoint, _created = AttendanceCheckpoint.objects.get_or_create(
        attendance_session=attendance_session,
        student=student,
        defaults={
            "checkpoint_number": attendance_session.checkpoints.count() + 1,
            "selection_method": AttendanceCheckpoint.SelectionMethod.SCAN,
        },
    )
    return checkpoint


@transaction.atomic
def award_scan_points(attendance_session: AttendanceSession, student, checkpoint=None, when=None) -> int:
    """Scanner points: 5 at a student station (bonus), 3 at the projector.
    Doubled on the student's birthday."""
    attendance_session = AttendanceSession.objects.select_for_update().get(id=attendance_session.id)
    if PointsLedger.objects.filter(student=student, attendance_session=attendance_session).exists():
        return 0
    at_station = checkpoint is not None and checkpoint.student.role == "STUDENT"
    category = PointsLedger.Category.STATION_SCAN if at_station else PointsLedger.Category.SCAN
    points = _celebrate(
        student, POINTS["STATION_SCAN" if at_station else "SCAN"],
        category, session=attendance_session, when=when,
    )
    ledger = PointsLedger.objects.create(
        student=student,
        attendance_session=attendance_session,
        category=category,
        points=points,
    )
    return ledger.points


@transaction.atomic
def award_manual_points(attendance_session: AttendanceSession, student) -> int:
    """Manual entries earn zero points to discourage bypassing QR (FR-048).

    ``student`` may be a User instance or a raw primary key.
    """
    attendance_session = AttendanceSession.objects.select_for_update().get(id=attendance_session.id)
    student_id = getattr(student, "pk", student)
    ledger, _ = PointsLedger.objects.get_or_create(
        student_id=student_id,
        attendance_session=attendance_session,
        defaults={"category": PointsLedger.Category.MANUAL, "points": POINTS["MANUAL"]},
    )
    return ledger.points


@transaction.atomic
def award_student_of_class(attendance_session: AttendanceSession):
    """Algorithm-picked star of the session (+10, birthday-doubled).

    Candidates: students who attended this session.
    Excluded: anyone already named Student of the Class in ANY earlier
    session of the SAME course - one star per course per lifetime.
    They remain fully eligible for other courses.

    The session row is locked so two concurrent calls cannot both pass the
    "no existing star" check and award two stars.
    """
    # Row-lock the session: without it two concurrent calls can both pass
    # the "no winner yet" check below and crown two different students.
    attendance_session = AttendanceSession.objects.select_for_update().get(id=attendance_session.id)
    existing = PointsLedger.objects.filter(
        attendance_session=attendance_session, category=PointsLedger.Category.STUDENT_OF_CLASS
    ).select_related("student").first()
    if existing:
        return existing

    offering = attendance_session.course_offering
    prior_winners = set(
        PointsLedger.objects.filter(
            category=PointsLedger.Category.STUDENT_OF_CLASS,
            attendance_session__class_session__class_definition__course_offering=offering,
        ).values_list("student_id", flat=True)
    )
    attendees = list(
        AttendanceRecord.objects.filter(
            attendance_session=attendance_session,
            student__role="STUDENT",
        ).select_related("student")
    )
    already_rewarded = set(
        PointsLedger.objects.filter(attendance_session=attendance_session)
        .values_list("student_id", flat=True)
    )

    # Prefer someone who has not earned anything this session - spreads the joy.
    fresh = [r.student for r in attendees
             if r.student_id not in prior_winners and r.student_id not in already_rewarded]
    if fresh:
        winner = random.choice(fresh)
        points = _celebrate(winner, POINTS["STUDENT_OF_CLASS"], PointsLedger.Category.STUDENT_OF_CLASS, session=attendance_session)
        return PointsLedger.objects.create(
            student=winner,
            attendance_session=attendance_session,
            category=PointsLedger.Category.STUDENT_OF_CLASS,
            points=points,
        )

    # Everyone already earned something this session: upgrade one of them
    # (never a prior winner of this course).
    upgradable = [r.student for r in attendees if r.student_id not in prior_winners]
    if not upgradable:
        return None
    winner = random.choice(upgradable)
    entry = PointsLedger.objects.get(student=winner, attendance_session=attendance_session)
    bonus = _final_points(POINTS["STUDENT_OF_CLASS"], winner)
    entry.category = PointsLedger.Category.STUDENT_OF_CLASS
    entry.points = max(entry.points, bonus)
    entry.save(update_fields=["category", "points", "updated_at"])
    _notify_points(
        winner,
        f"🌟 Student of the Class! +{bonus} points",
        f"The algorithm chose you as the star of {offering.course.code} today. One per course - see you at the next one!",
        session=attendance_session,
    )
    return entry
