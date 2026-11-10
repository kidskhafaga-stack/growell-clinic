"""Fluid balance on the ward — in and out in millilitres, and what they add up
to (DOCTOR_EASE ٤-ب د-٥; the rows are ``models/fluid_balance``).

* **The last 24 hours** — what went in, what came out, each by kind, and the
  difference; and urine as millilitres per kilo per hour, from the child's
  latest weight. That last one is arithmetic, not a judgement: the program
  says no number is too low or too high — that reading is the doctor's.
* **Day by day** for the whole stay, by the clinic's own calendar day.

A wrong amount is struck through, never deleted: the chart keeps that it was.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

from app.extensions import db
from app.models.fluid_balance import (DIRECTIONS, IN, KINDS_IN, KINDS_OUT, OUT,
                                      FluidEntry)

MAX_ML = 5000
WINDOW_HOURS = 24


class FluidError(ValueError):
    """A refusal with a key (``fluid.err_<key>``)."""


def direction_of(kind):
    return IN if kind in KINDS_IN else OUT if kind in KINDS_OUT else None


def record(admission, kind, ml, user=None, at=None, note=None, now=None):
    """One amount. The caller commits."""
    if admission is None or not admission.is_open:
        raise FluidError("closed")
    direction = direction_of(kind)
    if direction is None:
        raise FluidError("kind")
    try:
        ml = int(ml)
    except (TypeError, ValueError):
        raise FluidError("ml")
    if not 1 <= ml <= MAX_ML:
        raise FluidError("ml")
    now = now or datetime.utcnow()
    at = at or now
    if at > now + timedelta(minutes=5) or at < admission.admitted_at - timedelta(minutes=5):
        raise FluidError("at")
    row = FluidEntry(admission_id=admission.id, patient_id=admission.patient_id,
                     at=at, direction=direction, kind=kind, ml=ml,
                     note=(note or "").strip()[:160] or None,
                     by_id=getattr(user, "id", None), recorded_at=now)
    db.session.add(row)
    db.session.flush()
    return row


def strike(entry, user=None, now=None):
    if entry.struck_at is None:
        entry.struck_at = now or datetime.utcnow()
        entry.struck_by = getattr(user, "id", None)
    return entry


def _live(admission):
    return [e for e in (admission.fluid_entries or []) if e.struck_at is None]


def summary(admission, now=None):
    """The last 24 hours (or since admission, if shorter): ``in``, ``out``,
    ``net``, ``by_kind``, ``hours``, ``urine``, ``weight``, ``urine_ml_kg_h``
    (``None`` without a weight or without any urine written)."""
    from app.utils.dosing import latest_weight

    now = now or datetime.utcnow()
    end = min(now, admission.discharged_at) if admission.discharged_at else now
    start = max(end - timedelta(hours=WINDOW_HOURS), admission.admitted_at)
    rows = [e for e in _live(admission) if start <= e.at <= end]
    by_kind = OrderedDict((k, 0) for k in KINDS_IN + KINDS_OUT)
    for e in rows:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + e.ml
    total_in = sum(e.ml for e in rows if e.direction == IN)
    total_out = sum(e.ml for e in rows if e.direction == OUT)
    hours = max((end - start).total_seconds() / 3600, 0)
    weight = latest_weight(admission.patient)
    urine = by_kind.get("urine", 0)
    rate = (round(urine / weight / hours, 1)
            if weight and hours >= 1 and any(e.kind == "urine" for e in rows) else None)
    return {"in": total_in, "out": total_out, "net": total_in - total_out,
            "by_kind": {k: v for k, v in by_kind.items() if v},
            "hours": round(hours, 1), "urine": urine, "weight": weight,
            "urine_ml_kg_h": rate, "count": len(rows)}


def by_day(admission):
    """``[(local date, in, out, net)]`` for the stay, newest first."""
    from app.utils.clock import to_local

    days = OrderedDict()
    for e in sorted(_live(admission), key=lambda e: e.at):
        day = to_local(e.at).date()
        got = days.setdefault(day, [0, 0])
        got[0 if e.direction == IN else 1] += e.ml
    return [(d, i, o, i - o) for d, (i, o) in reversed(list(days.items()))]


def recent(admission, now=None, hours=WINDOW_HOURS):
    """The entries of the last 24 hours, struck ones included, newest first."""
    now = now or datetime.utcnow()
    since = now - timedelta(hours=hours)
    return sorted([e for e in (admission.fluid_entries or []) if e.at >= since],
                  key=lambda e: (e.at, e.id), reverse=True)


__all__ = ["DIRECTIONS", "FluidError", "KINDS_IN", "KINDS_OUT", "by_day", "record",
           "recent", "strike", "summary"]
