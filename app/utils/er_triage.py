"""Triage on the hospital's own levels — DOCTOR_EASE_PLAN ٤-أ ط-٤.

The level and the scale were typed by hand at every triage («أحمر — طارئ»,
«أصفر»), so one department wrote the same level five ways and nothing could
say a child had waited past what their level allows. Now:

* **the hospital writes its levels once** — the name, the colour, urgent or
  not, and the most minutes a child of that level waits for the doctor —
  **in its own numbers**: the program ships no triage scale and no times
  (:data:`KEY`; with none written, triage is typed by hand exactly as before);
* **triage is one press** on a level, and the vitals taken at the door are
  kept as a reading (``Observation``) with the weight;
* **the age bands already in the program** (``vital_bands``) can only
  **raise** «urgent» — a reading outside them marks the child urgent and says
  which reading; they never lower what the nurse decided;
* **the board says when a child has waited past their level's minutes**.
"""
import json
from datetime import datetime

from app.extensions import db

KEY = "er_triage_levels"
MAX_LEVELS = 8


class LevelError(ValueError):
    """A refusal with a key (``er_triage.err_<key>``)."""


def levels():
    """``[{"key", "name", "color", "urgent", "minutes"}]`` — the hospital's,
    in its order; empty when it wrote none."""
    from app.models import Setting

    try:
        rows = json.loads(Setting.get(KEY) or "[]")
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


def level(key):
    return next((r for r in levels() if r.get("key") == key), None)


def save_levels(rows):
    """Write the hospital's levels. ``rows``: dicts with name, color, urgent
    (bool), minutes (text, empty for none), delete (bool). The caller commits."""
    import re

    from app.models import Setting

    out, seen = [], set()
    for r in rows:
        if r.get("delete"):
            continue
        name = (r.get("name") or "").strip()[:40]
        if not name:
            continue
        minutes = (r.get("minutes") or "").strip()
        if minutes and (not minutes.isdigit() or int(minutes) > 24 * 60):
            raise LevelError("minutes")
        color = (r.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#64748b"
        key = (r.get("key") or "").strip()[:20] or f"l{len(out) + 1}"
        while key in seen:
            key = f"{key}_"
        seen.add(key)
        out.append({"key": key, "name": name, "color": color,
                    "urgent": bool(r.get("urgent")),
                    "minutes": int(minutes) if minutes else None})
    if len(out) > MAX_LEVELS:
        raise LevelError("too_many")
    Setting.set(KEY, json.dumps(out, ensure_ascii=False))
    return out


# ------------------------------------------------------- vitals at the door --
VITALS = (("temperature_c", float, 30, 44), ("pulse_bpm", int, 20, 300),
          ("resp_rate", int, 5, 150), ("spo2", int, 30, 100))


def door_vitals(attendance, form, user, at=None):
    """The readings taken at triage, kept as an observation (and the weight
    as a growth record). Returns ``(observation or None, flags)`` where
    ``flags`` are the readings outside the age band — ``[(kind, value)]``."""
    from app.models.observation import Observation
    from app.models import GrowthRecord
    from app.utils import vital_bands
    from app.utils.clock import local_today
    from app.utils.dosing import age_months_of

    values = {}
    for field, cast, low, high in VITALS:
        raw = (form.get(field) or "").strip()
        if not raw:
            continue
        try:
            value = cast(float(raw))
        except ValueError:
            continue
        if low <= value <= high:
            values[field] = value
    kg = (form.get("weight_kg") or "").strip()
    try:
        kg = float(kg) if kg else None
    except ValueError:
        kg = None
    if kg is not None and 0.3 <= kg <= 200:
        db.session.add(GrowthRecord(patient_id=attendance.patient_id,
                                    visit_id=attendance.visit_id,
                                    record_date=local_today(), weight_kg=round(kg, 2),
                                    source="emergency"))
    if not values:
        return None, []
    obs = Observation(patient_id=attendance.patient_id, visit_id=attendance.visit_id,
                      taken_at=at or datetime.utcnow(), recorded_by=getattr(user, "id", None),
                      **values)
    db.session.add(obs)
    db.session.flush()
    age = age_months_of(attendance.patient)
    field_of = dict(vital_bands.READINGS)
    flags = [(field_of[kind], value) for kind, (value, band) in vital_bands.read(obs, age).items()
             if band == vital_bands.ABNORMAL]
    return obs, flags


# ----------------------------------------------------------- the waiting --
def over_time(attendance, now=None):
    """Minutes past the level's time to the doctor, or ``None`` — a child
    not yet seen whose level the hospital gave minutes to."""
    if attendance.seen_at or attendance.departed_at or not attendance.level:
        return None
    lvl = next((r for r in levels() if r["name"] == attendance.level), None)
    if lvl is None or lvl.get("minutes") is None:
        return None
    since = attendance.triaged_at or attendance.arrived_at
    waited = ((now or datetime.utcnow()) - since).total_seconds() / 60
    over = int(waited - lvl["minutes"])
    return over if over > 0 else None


def color_of(attendance):
    lvl = next((r for r in levels() if r["name"] == attendance.level), None)
    return lvl["color"] if lvl else None
