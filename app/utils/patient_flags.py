"""Reading and writing a family's payment-conduct flag.

The rules live here rather than in the routes because three screens ask the
same questions — the booking form, the visit, the till — and a rule copied into
three places is a rule that will disagree with itself.

See :mod:`app.models.patient_flag` for why the flag is cleared rather than
deleted, why raising and clearing are different permissions, and why it never
prints.
"""
from datetime import datetime

from app.extensions import db
from app.models import PatientFlag

# Clearing is a financial decision, not a clerical one.
CLEAR_CAPABILITY = "finance_manage"
DUTY_CAPABILITY = "duty_manager"


def active(patient_id):
    """The open flag on this file, or None. Newest wins if several exist."""
    if not patient_id:
        return None
    return (PatientFlag.query
            .filter(PatientFlag.patient_id == patient_id,
                    PatientFlag.cleared_at.is_(None))
            .order_by(PatientFlag.raised_at.desc()).first())


def history(patient_id, limit=20):
    """Every flag this file has carried, open or closed, newest first.

    The cleared ones are the point: "this was raised twice last year and
    cleared both times" is a different fact from "there is nothing on file",
    and only one of them is visible if closed flags are hidden.
    """
    if not patient_id:
        return []
    return (PatientFlag.query.filter_by(patient_id=patient_id)
            .order_by(PatientFlag.raised_at.desc()).limit(limit).all())


def blocks_booking(patient_id):
    """Does this file currently stop a booking on its own?"""
    flag = active(patient_id)
    return bool(flag and flag.blocks)


def can_clear(user):
    """Whoever raised it is not who takes it off.

    Both directions matter: it stops a flag being lifted quietly by the person
    who put it there, and it stops one being lifted by somebody who does not
    know whether the money ever arrived.
    """
    return bool(user is not None
                and (getattr(user, "is_admin", False) or user.can(CLEAR_CAPABILITY)
                     or user.can(DUTY_CAPABILITY)))


def in_emergency(patient_id):
    """Whether this child is in the emergency department now, or was sent up
    from it in the last day. **A hold never stops that admission** — the
    emergency is treated first, by law and by sense; the hold is shown and
    the staff decide (`app/utils/patient_flags`, decree 1063/2014)."""
    from datetime import timedelta

    from app.models import EmergencyVisit

    since = datetime.utcnow() - timedelta(hours=24)
    rows = EmergencyVisit.query.filter(
        EmergencyVisit.patient_id == patient_id,
        db.or_(EmergencyVisit.departed_at.is_(None),
               EmergencyVisit.departed_at >= since)).all()
    return any(r.departed_at is None or r.disposition == "admitted" for r in rows)


def blocks_admission(patient_id):
    """A planned admission waits for a manager; one from the emergency never
    does."""
    return blocks_booking(patient_id) and not in_emergency(patient_id)


def raise_flag(patient_id, level, reason, user_id=None, kind=None):
    """Open a flag on a file. Returns the row, or None if it was refused.

    Refused when the reason is empty — a note nobody can judge, argue with or
    fairly clear — or when the file already carries an open one, which is
    raised in place instead of stacked: two open flags mean two different
    stories about the same family and nobody knows which is current.
    """
    reason = (reason or "").strip()
    if not patient_id or not reason:
        return None
    if level not in ("warn", "block"):
        level = "warn"
    if kind not in ("account", "family"):
        kind = "account"

    existing = active(patient_id)
    if existing is not None:
        # Escalating warn → block is a real event and is kept as one. Anything
        # else just updates the note in place.
        existing.level = level
        existing.kind = kind
        existing.reason = reason
        existing.raised_by = user_id or existing.raised_by
        existing.raised_at = datetime.utcnow()
        return existing

    flag = PatientFlag(patient_id=patient_id, level=level, kind=kind,
                       reason=reason, raised_by=user_id)
    db.session.add(flag)
    return flag


def clear_flag(patient_id, reason, user_id=None):
    """Close the open flag on a file. The row stays."""
    flag = active(patient_id)
    if flag is None:
        return None
    flag.cleared_at = datetime.utcnow()
    flag.cleared_by = user_id
    flag.clear_reason = (reason or "").strip() or None
    return flag


def open_holds():
    """Every open flag, holds first, newest first — the manager's list."""
    rows = PatientFlag.query.filter(PatientFlag.cleared_at.is_(None)).all()
    return sorted(rows, key=lambda f: (f.level != "block", -(f.raised_at.timestamp()
                                                            if f.raised_at else 0)))


def held_today():
    """Files on hold with a booking today or a bed now — the ones a manager
    may be asked about before the day is out."""
    from app.models import Admission, Appointment
    from app.utils.clock import local_today

    held = {f.patient_id for f in PatientFlag.query.filter(
        PatientFlag.cleared_at.is_(None), PatientFlag.level == "block").all()}
    if not held:
        return set()
    booked = {a.patient_id for a in Appointment.query.filter(
        Appointment.patient_id.in_(held), Appointment.appt_date == local_today(),
        Appointment.status.notin_(("cancelled", "no_show"))).all()}
    in_bed = {a.patient_id for a in Admission.query.filter(
        Admission.patient_id.in_(held), Admission.discharged_at.is_(None)).all()}
    return booked | in_bed
