"""Phototherapy sessions (DOCTOR_EASE ٤-ج ح-٣; rows in ``models/phototherapy``).
On, off, what kind, and the hours — on the stay and on the incubator board."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.phototherapy import KINDS, PhotoSession


class PhotoError(ValueError):
    """A refusal with a key (``photo.err_<key>``)."""


def running(admission):
    return next((s for s in (admission.photo_sessions or []) if s.is_on), None)


def start(admission, kind=None, user=None, at=None, note=None, now=None):
    if admission is None or not admission.is_open:
        raise PhotoError("closed")
    if running(admission) is not None:
        raise PhotoError("already_on")
    now = now or datetime.utcnow()
    at = at or now
    if at > now + timedelta(minutes=5) or at < admission.admitted_at - timedelta(minutes=5):
        raise PhotoError("at")
    row = PhotoSession(admission_id=admission.id, patient_id=admission.patient_id,
                       kind=kind if kind in KINDS else None, started_at=at,
                       started_by=getattr(user, "id", None),
                       note=(note or "").strip()[:160] or None)
    db.session.add(row)
    db.session.flush()
    return row


def stop(admission, user=None, at=None, now=None):
    row = running(admission)
    if row is None:
        raise PhotoError("not_on")
    now = now or datetime.utcnow()
    at = at or now
    if at < row.started_at or at > now + timedelta(minutes=5):
        raise PhotoError("at")
    row.stopped_at = at
    row.stopped_by = getattr(user, "id", None)
    return row


def sessions(admission):
    return sorted(admission.photo_sessions or [], key=lambda s: s.started_at, reverse=True)


def total_hours(admission, now=None):
    return round(sum(s.hours(now) for s in (admission.photo_sessions or [])), 1)


def on_now(admission_ids):
    """``{admission_id: session}`` running now — one query for a board."""
    if not admission_ids:
        return {}
    rows = PhotoSession.query.filter(PhotoSession.admission_id.in_(list(admission_ids)),
                                     PhotoSession.stopped_at.is_(None)).all()
    return {r.admission_id: r for r in rows}


def shown(admission):
    if admission.photo_sessions:
        return True
    unit = getattr(getattr(admission, "bed", None), "unit", None)
    return getattr(unit, "kind", None) == "nicu"
