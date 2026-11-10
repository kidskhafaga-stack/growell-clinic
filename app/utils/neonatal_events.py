"""Apnoea, bradycardia and desaturation episodes (DOCTOR_EASE ٤-ج ح-٢; rows in
``models/neonatal_event``). The nurse records each one; the stay and the
incubator board show how many in the last 24 hours. No limit of ours.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.neonatal_event import RECOVERIES, NeonatalEvent

WINDOW_HOURS = 24


class EventError(ValueError):
    """A refusal with a key (``abd.err_<key>``)."""


def _int(raw, low, high):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw in (None, ""):
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        raise EventError("number")
    if not low <= value <= high:
        raise EventError("number")
    return value


def record(admission, form, user=None, at=None, now=None):
    """One episode. The caller commits."""
    if admission is None or not admission.is_open:
        raise EventError("closed")
    kinds = {k: bool(form.get(k)) for k in ("apnoea", "brady", "desat")}
    if not any(kinds.values()):
        raise EventError("kind")
    now = now or datetime.utcnow()
    at = at or now
    if at > now + timedelta(minutes=5) or at < admission.admitted_at - timedelta(minutes=5):
        raise EventError("at")
    recovery = (form.get("recovery") or "").strip()
    row = NeonatalEvent(admission_id=admission.id, patient_id=admission.patient_id, at=at,
                        seconds=_int(form.get("seconds"), 1, 3600),
                        lowest_hr=_int(form.get("lowest_hr"), 10, 250),
                        lowest_spo2=_int(form.get("lowest_spo2"), 10, 100),
                        recovery=recovery if recovery in RECOVERIES else None,
                        note=(form.get("note") or "").strip()[:160] or None,
                        by_id=getattr(user, "id", None), recorded_at=now, **kinds)
    db.session.add(row)
    db.session.flush()
    return row


def recent(admission, now=None, hours=WINDOW_HOURS):
    since = (now or datetime.utcnow()) - timedelta(hours=hours)
    return sorted([e for e in (admission.neonatal_events or []) if e.at >= since],
                  key=lambda e: (e.at, e.id), reverse=True)


def count_last_day(admission_ids, now=None):
    """``{admission_id: n}`` in the last 24 hours — one query for a board."""
    if not admission_ids:
        return {}
    since = (now or datetime.utcnow()) - timedelta(hours=WINDOW_HOURS)
    rows = (NeonatalEvent.query.filter(NeonatalEvent.admission_id.in_(list(admission_ids)),
                                       NeonatalEvent.at >= since).all())
    out = {}
    for r in rows:
        out[r.admission_id] = out.get(r.admission_id, 0) + 1
    return out


def shown(admission):
    if admission.neonatal_events:
        return True
    unit = getattr(getattr(admission, "bed", None), "unit", None)
    return getattr(unit, "kind", None) == "nicu"
