"""Where a newborn's bilirubin sits against the thresholds, by the hour.

Phase 4 of EMERGENCY_NEWBORN_PLAN.md, and the decision that shaped it was
taken before any of it was written: **this is a calculator, never the
assistant.**

The number decides phototherapy or an exchange transfusion. This program
already refuses to let a model give a drug dose, and the reason is written
down in `ai_discuss.py` — *a second, less careful road to the same number is
how a program ends up with two answers to "how much" and no way to know which
one a nurse read.* A bilirubin threshold is that same category. The assistant
may **explain** what comes out of here; it may not produce it.

**It refuses rather than guesses.** No hour of birth, no gestation, no
bilirubin — it says which one is missing and stops. A threshold read at the
wrong hour is a decision taken on somebody else's baby, and in the first days
these curves move fast enough that a day's error crosses them.

**And it will not answer at all until a clinician has signed off the table.**
The numbers in `app/data/jaundice_thresholds.json` were transcribed by hand
rather than read from a machine-readable source, and a transcribed clinical
table that a program presents as authoritative is the exact failure this
session has spent its time guarding against. So the table ships, the settings
screen shows it in full for review, and until somebody ticks the box this
returns "not confirmed" and no numbers. The same shape as the ICD-11 picker,
which does not offer a classification it has not loaded.
"""
import json
import os

CONFIRMED_KEY = "jaundice_table_confirmed"

# Gestational ages the table has curves for. A baby below the lowest is not
# extrapolated down to — preterm thresholds are not a straight line and the
# ones under 35 weeks belong to a unit, not a clinic.
LOWEST_WEEKS = 35
HIGHEST_ROW = 38

_cache = {}


def table():
    """The threshold table, read once."""
    if "data" not in _cache:
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "jaundice_thresholds.json")
        with open(path, encoding="utf-8") as fh:
            _cache["data"] = json.load(fh)
    return _cache["data"]


def confirmed():
    """Whether a clinician has reviewed the shipped table and accepted it."""
    from app.models import Setting

    try:
        return Setting.get(CONFIRMED_KEY) == "1"
    except Exception:  # noqa: BLE001 — settings table may not be ready
        return False


def _row(weeks):
    """Which curve applies. Rounded **down**, never up.

    A 37+6 baby is read on the 37-week curve, not the 38-week one: the
    thresholds rise with maturity, so rounding up would hand a less mature
    baby a more permissive number. Where a rule has to be wrong it is wrong
    towards treating.
    """
    if weeks is None or weeks < LOWEST_WEEKS:
        return None
    return str(min(int(weeks), HIGHEST_ROW))


def _at(curve, hours):
    """Linear interpolation along one curve, flat outside its ends."""
    if hours <= curve[0][0]:
        return curve[0][1]
    if hours >= curve[-1][0]:
        return curve[-1][1]
    for (h0, v0), (h1, v1) in zip(curve, curve[1:]):
        if h0 <= hours <= h1:
            if h1 == h0:
                return v1
            return v0 + (v1 - v0) * (hours - h0) / (h1 - h0)
    return curve[-1][1]


def limits(weeks, hours, has_risk=False):
    """``(phototherapy, exchange)`` for this baby, or ``(None, None)``."""
    row = _row(weeks)
    if row is None or hours is None or hours < 0:
        return (None, None)
    data = table()
    band = "risk" if has_risk else "no_risk"
    return (_at(data["phototherapy"][band][row], hours),
            _at(data["exchange"][band][row], hours))


def assess(patient, bilirubin, has_risk=False, hours=None):
    """Where this reading sits, or what is missing.

    ``{"ok": bool}`` plus, when it can answer: the two thresholds, the margin
    to each, what it points at, and when to repeat.

    ``hours`` may be passed in for a reading taken earlier — the value belongs
    to the moment blood was drawn, not to the moment somebody typed it in.
    """
    # Asked before anything else: a clinic that does not see newborns is not
    # withholding an answer here, it has no question. The table is not on
    # their settings screen either — see `offers`.
    from app.utils.facility import offers

    if not offers("newborn_care"):
        return {"ok": False, "reason": "not_offered"}
    if not confirmed():
        return {"ok": False, "reason": "table_not_confirmed"}

    weeks = getattr(patient, "gestation_weeks", None) if patient else None
    if weeks is None:
        return {"ok": False, "reason": "no_gestation"}
    if weeks < LOWEST_WEEKS:
        return {"ok": False, "reason": "too_preterm"}

    if hours is None:
        hours = getattr(patient, "age_hours", None) if patient else None
    if hours is None:
        return {"ok": False, "reason": "no_birth_time"}

    try:
        value = float(bilirubin)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "no_bilirubin"}

    photo, exchange = limits(weeks, hours, has_risk)
    if photo is None:
        return {"ok": False, "reason": "no_gestation"}

    if value >= exchange:
        points_at = "exchange"
    elif value >= photo:
        points_at = "phototherapy"
    elif value >= photo - 3:
        points_at = "close"
    else:
        points_at = "below"

    return {
        "ok": True,
        "value": value,
        "hours": round(hours, 1),
        "weeks": weeks,
        "risk": bool(has_risk),
        "phototherapy": round(photo, 1),
        "exchange": round(exchange, 1),
        "to_phototherapy": round(photo - value, 1),
        "points_at": points_at,
        "repeat_in": _repeat(points_at, hours),
        "source": table()["source"],
        "unit": table()["unit"],
    }


def _repeat(points_at, hours):
    """Hours until the next level, as an interval and not an appointment.

    Deliberately coarse. The precise answer depends on the rate of rise, which
    needs two readings and a judgement; what a clinic needs from a screen is
    "hours, not days" versus "tomorrow is soon enough".
    """
    if points_at in ("exchange", "phototherapy"):
        return 6
    if points_at == "close":
        return 12
    return 24 if hours < 72 else 48
