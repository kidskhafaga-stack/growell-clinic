"""Safe working hours — GAHAR WFM.17 ev. 3–4, *"When working hours exceed
the approved limits, measures are taken"*.

The limit is the hospital's (``LIMIT_SETTING``, hours a week); the rota's
shifts are counted by their slot's hours, a night that crosses midnight
counted whole. Without a limit, nothing is judged.
"""
from datetime import datetime

LIMIT_SETTING = "max_weekly_hours"


def limit():
    from app.models import Setting

    try:
        value = float((Setting.get(LIMIT_SETTING) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def slot_hours(slot):
    if slot is None or slot.start_time is None or slot.end_time is None:
        return 0.0
    start = datetime.combine(datetime(2000, 1, 1), slot.start_time)
    end = datetime.combine(datetime(2000, 1, 1), slot.end_time)
    hours = (end - start).total_seconds() / 3600.0
    return hours if hours > 0 else hours + 24


def over_limit(start, end):
    """``[(person, hours)]`` rostered more than the hospital's weekly limit
    in ``[start, end]``; ``None`` while no limit is set."""
    from app.models.duty import Duty

    cap = limit()
    if cap is None:
        return None
    totals = {}
    for d in (Duty.query.filter(Duty.on_date >= start, Duty.on_date <= end,
                                Duty.status != "absent").all()):
        if d.cover != "present":
            continue
        person = d.doctor
        totals[person] = totals.get(person, 0.0) + slot_hours(d.slot)
    return sorted([(p, h) for p, h in totals.items() if h > cap], key=lambda x: -x[1])


__all__ = ["LIMIT_SETTING", "limit", "over_limit", "slot_hours"]
