"""The breathing machine's settings (DOCTOR_EASE ٤-ج ع-٢; rows in
``models/ventilation``).

The doctor writes the mode and the numbers; each change is a row, the latest
one is what the machine is on now. The program checks only that a number is a
number a machine can be set to — it suggests nothing.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.ventilation import VentSetting

#: (field, type, low, high) — what a machine can physically be set to.
FIELDS = (("fio2", int, 21, 100), ("peep", float, 0, 30), ("rate", int, 0, 150),
          ("pip", int, 0, 80), ("tidal_ml", int, 1, 1500),
          ("pressure_support", int, 0, 60), ("ti", float, 0.1, 5), ("flow", float, 0, 80))


class VentError(ValueError):
    """A refusal with a key (``vent.err_<key>``)."""


def record(admission, form, user=None, at=None, now=None):
    """One change. ``form`` is a mapping of the fields. The caller commits."""
    if admission is None or not admission.is_open:
        raise VentError("closed")
    now = now or datetime.utcnow()
    at = at or now
    if at > now + timedelta(minutes=5) or at < admission.admitted_at - timedelta(minutes=5):
        raise VentError("at")
    stopped = bool(form.get("stopped"))
    mode = (form.get("mode") or "").strip()[:30]
    if not mode and not stopped:
        raise VentError("mode")
    values = {}
    for field, cast, low, high in FIELDS:
        raw = (form.get(field) or "").strip()
        if not raw:
            continue
        try:
            value = cast(float(raw))
        except ValueError:
            raise VentError("number")
        if not low <= value <= high:
            raise VentError("number")
        values[field] = value
    row = VentSetting(admission_id=admission.id, patient_id=admission.patient_id, at=at,
                      mode=mode or "—", stopped=stopped,
                      note=(form.get("note") or "").strip()[:160] or None,
                      by_id=getattr(user, "id", None), recorded_at=now, **values)
    db.session.add(row)
    db.session.flush()
    return row


def history(admission):
    """Newest first."""
    return sorted(admission.vent_settings or [], key=lambda r: (r.at, r.id), reverse=True)


def current(admission):
    """What the machine is on now, or ``None`` (never on one, or taken off)."""
    rows = history(admission)
    if not rows or rows[0].stopped:
        return None
    return rows[0]


def shown(admission):
    """The card belongs on a stay in intensive care or the incubators, and on
    any stay that has ever had a setting written."""
    if admission.vent_settings:
        return True
    unit = getattr(getattr(admission, "bed", None), "unit", None)
    return getattr(unit, "kind", None) in ("icu", "nicu")
