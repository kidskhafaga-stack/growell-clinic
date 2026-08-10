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
                and (getattr(user, "is_admin", False) or user.can(CLEAR_CAPABILITY)))


def raise_flag(patient_id, level, reason, user_id=None):
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

    existing = active(patient_id)
    if existing is not None:
        # Escalating warn → block is a real event and is kept as one. Anything
        # else just updates the note in place.
        existing.level = level
        existing.reason = reason
        existing.raised_by = user_id or existing.raised_by
        existing.raised_at = datetime.utcnow()
        return existing

    flag = PatientFlag(patient_id=patient_id, level=level, reason=reason,
                       raised_by=user_id)
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
