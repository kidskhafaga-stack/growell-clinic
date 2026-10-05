"""Recognising a child getting worse and answering — GAHAR ICD.22 / GSR.10.

What the program can hold of the standard's (أ)–(ز):

* **(أ) criteria, age specific** — the heart and breathing rate bands by age
  and the fixed temperature and oxygen limits (`vital_bands`), now the
  hospital's own wherever it writes them (`clinical_rules`); and the nurse's
  worry in words, which no band replaces;
* **(د) the codes** — the hospital's list of how it calls (`Lookup` domain
  ``emergency_code``), in its words;
* **(هـ) the time frame** — the hospital's number of minutes from the call to
  the responder at the bed (:data:`RESPONSE_SETTING`). Without it the
  program measures and does not judge: it invents no response time;
* **(و) uniform 24/7** — the report breaks the same figures down by weekday
  and by time of day, so "the night answers slower" is visible or disproved;
* **(ز) recording** — the call itself, on the child's record.

**Nothing here waits for the paperwork.** A call is two taps — the reading is
filled in from the chart — because the moment somebody is calling for help
is the worst moment to ask them to type.
"""
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models.deterioration import (OUTCOMES, RESUSCITATION,
                                      DeteriorationCall)

CODES_DOMAIN = "emergency_code"
RESPONSE_SETTING = "deterioration_response_minutes"


class CallError(ValueError):
    """A refusal with a key the screen can name (``deterioration.err_<key>``)."""


# ---------------------------------------------------------------- the codes --
def codes():
    from app.models import Lookup

    return (Lookup.query.filter_by(domain=CODES_DOMAIN, is_active=True)
            .order_by(Lookup.sort_order, Lookup.id).all())


def add_code(name):
    from app.models import Lookup
    from app.utils.lookups import make_key

    name = (name or "").strip()[:80]
    if not name:
        raise CallError("need_code")
    existing = (Lookup.query.filter_by(domain=CODES_DOMAIN)
                .filter(Lookup.name_ar == name).first())
    if existing is not None:
        existing.is_active = True
        return existing
    row = Lookup(domain=CODES_DOMAIN, key=make_key(name, CODES_DOMAIN),
                 name_ar=name, is_active=True)
    db.session.add(row)
    return row


def retire_code(row):
    if row is None or row.domain != CODES_DOMAIN:
        raise CallError("not_a_code")
    row.is_active = False
    return row


def code_label(key):
    from app.models import Lookup

    if not key:
        return ""
    row = Lookup.query.filter_by(domain=CODES_DOMAIN, key=key).first()
    return row.name_ar if row is not None else key


# ------------------------------------------------------------ the time frame --
def response_minutes():
    from app.models import Setting

    raw = (Setting.get(RESPONSE_SETTING) or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def set_response_minutes(value):
    from app.models import Setting

    raw = str(value or "").strip()
    number = int(raw) if raw.isdigit() and 0 < int(raw) <= 240 else None
    Setting.set(RESPONSE_SETTING, str(number) if number else "")
    return number


def late(call, now=None):
    """Past the hospital's time to the bed — ``None`` when it wrote none."""
    limit = response_minutes()
    if not limit or call is None or call.called_at is None:
        return None
    end = call.arrived_at or now or datetime.utcnow()
    return (end - call.called_at) > timedelta(minutes=limit)


# ---------------------------------------------------------------- the reading --
def describe(observation, patient):
    """«RR 70 · SpO2 88» — the readings of this observation outside the usual
    range for the child's age, as the chart coloured them."""
    from app.utils import vital_bands
    from app.utils.dosing import age_months_of

    if observation is None:
        return None
    labels = {"temp": "T", "hr": "HR", "rr": "RR", "spo2": "SpO2"}
    parts = []
    for kind, (value, level) in vital_bands.read(
            observation, age_months_of(patient)).items():
        if value is not None and level in (vital_bands.ABNORMAL,
                                           vital_bands.BORDERLINE):
            parts.append(f"{labels[kind]} {value:g}" if isinstance(value, float)
                         else f"{labels[kind]} {value}")
    if getattr(observation, "avpu", None) and observation.avpu != "A":
        parts.append(f"AVPU {observation.avpu}")
    return " · ".join(parts)[:200] or None


# ------------------------------------------------------------------- the call --
def open_call(patient, user, observation=None, concern=None, code_key=None,
              called_whom=None, at=None):
    """Noticed and called, in one press. The caller commits."""
    from app.utils import beds

    if patient is None:
        raise CallError("no_patient")
    concern = (concern or "").strip()[:255] or None
    reading = describe(observation, patient)
    if not reading and not concern:
        raise CallError("need_reason")
    key = (code_key or "").strip() or None
    if key is not None and key not in {c.key for c in codes()}:
        key = None
    whom = (called_whom or "").strip()[:120] or None
    if key is None and whom is None:
        raise CallError("need_whom")
    moment = at or datetime.utcnow()
    stay = beds.open_admission(patient.id)
    row = DeteriorationCall(
        patient_id=patient.id, admission_id=stay.id if stay else None,
        observation_id=getattr(observation, "id", None), reading=reading,
        concern=concern, noticed_at=moment, noticed_by=getattr(user, "id", None),
        code_key=key, called_whom=whom, called_at=moment)
    db.session.add(row)
    db.session.flush()
    return row


def arrive(call, user, at=None):
    """The responder is at the bed — pressed by the responder."""
    if call is None or not call.is_open:
        raise CallError("closed")
    if call.arrived_at is not None:
        raise CallError("already_arrived")
    call.arrived_at = at or datetime.utcnow()
    call.arrived_by = getattr(user, "id", None)
    return call


def close(call, user, actions, outcome, resuscitation_id=None, at=None):
    """What was done and how it ended. Needs somebody to have come — a call
    nobody answered is not closed, it is the finding."""
    if call is None or not call.is_open:
        raise CallError("closed")
    if call.arrived_at is None:
        raise CallError("nobody_came")
    actions = (actions or "").strip()
    if not actions:
        raise CallError("need_actions")
    if outcome not in OUTCOMES:
        raise CallError("need_outcome")
    call.actions = actions[:4000]
    call.outcome = outcome
    call.resuscitation_id = resuscitation_id if outcome == RESUSCITATION else None
    call.closed_at = at or datetime.utcnow()
    call.closed_by = getattr(user, "id", None)
    return call


# -------------------------------------------------------------- the readings --
def open_calls(limit=50):
    return (DeteriorationCall.query
            .filter(DeteriorationCall.closed_at.is_(None))
            .order_by(DeteriorationCall.called_at).limit(limit).all())


def for_patient(patient_id, limit=20):
    return (DeteriorationCall.query
            .filter(DeteriorationCall.patient_id == patient_id)
            .order_by(DeteriorationCall.noticed_at.desc()).limit(limit).all())


def report(start, end):
    """Evidence 4 and (و): ``{"rows", "count", "median", "late", "outcomes",
    "by_weekday", "by_block", "limit"}`` for calls between two clinic days.

    ``by_weekday`` (Monday first) and ``by_block`` (six-hour blocks of the
    clinic's day) carry the count and the median minutes to arrive — the same
    response at three in the morning on a Friday as at noon on a Tuesday is
    what (و) asks the hospital to show."""
    from app.utils.clock import to_local, to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (DeteriorationCall.query
            .filter(DeteriorationCall.called_at >= since,
                    DeteriorationCall.called_at <= until)
            .order_by(DeteriorationCall.called_at).all())

    def median(values):
        values = sorted(v for v in values if v is not None)
        return values[len(values) // 2] if values else None

    weekday = {i: [] for i in range(7)}
    block = {i: [] for i in range(4)}
    outcomes = {}
    for row in rows:
        local = to_local(row.called_at)
        weekday[local.weekday()].append(row.minutes_to_arrive())
        block[local.hour // 6].append(row.minutes_to_arrive())
        if row.outcome:
            outcomes[row.outcome] = outcomes.get(row.outcome, 0) + 1
    return {
        "rows": rows, "count": len(rows),
        "median": median([r.minutes_to_arrive() for r in rows]),
        "late": [r for r in rows if late(r) is True],
        "unanswered": [r for r in rows if r.arrived_at is None],
        "outcomes": outcomes, "limit": response_minutes(),
        "by_weekday": [{"day": i, "count": len(v), "median": median(v)}
                       for i, v in weekday.items()],
        "by_block": [{"block": i, "count": len(v), "median": median(v)}
                     for i, v in block.items()],
    }
