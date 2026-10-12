"""Environmental cleaning — see ``models/cleaning``.

The board says, per area, what each task needs today: a daily task done
today or not, a shift task with each time it was done today, and a deep
clean with when it was last done and when it falls due by the hospital's own
interval. Recording only; the schedule is infection control's.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.cleaning import (FREQUENCIES, RISKS, CleaningArea, CleaningDone,
                                 CleaningTask)


class CleaningError(ValueError):
    """A refusal with a locale key (``clean.err_<key>``)."""


def _text(raw, limit):
    s = (raw or "").strip()
    return s[:limit] or None


def may_record(user):
    """Whoever cleans, or supervises it: the ward, or infection control."""
    from app.utils import ipc

    return bool(ipc.may_review(user) or (user is not None and user.can_access("beds")))


def add_area(form):
    name = _text(form.get("name"), 120)
    if not name:
        raise CleaningError("name")
    risk = form.get("risk")
    if risk not in RISKS:
        raise CleaningError("risk")
    row = CleaningArea(name=name, risk=risk, unit_id=form.get("unit_id", type=int) or None)
    db.session.add(row)
    db.session.flush()
    return row


def add_task(area, form):
    activity = _text(form.get("activity"), 200)
    if not activity:
        raise CleaningError("activity")
    freq = form.get("frequency")
    if freq not in FREQUENCIES:
        raise CleaningError("frequency")
    every = form.get("every_days", type=int)
    if freq == "deep" and not (every and every > 0):
        raise CleaningError("every_days")
    area.tasks.append(CleaningTask(activity=activity, frequency=freq,
                                   every_days=every if freq == "deep" else None,
                                   disinfectant=_text(form.get("disinfectant"), 160),
                                   method=_text(form.get("method"), 255)))
    db.session.flush()
    return area


def record(task, form, user):
    if not task.is_active:
        raise CleaningError("stopped")
    row = CleaningDone(task_id=task.id, done_by=getattr(user, "id", None),
                       note=_text(form.get("note"), 255))
    db.session.add(row)
    db.session.flush()
    return row


def _day_bounds(day):
    from app.utils.clock import to_utc

    start = to_utc(datetime.combine(day, datetime.min.time()))
    return start, to_utc(datetime.combine(day + timedelta(days=1), datetime.min.time()))


def board(today):
    """``[{area, rows: [{task, today: [done], last, due, late}]}]``."""
    from app.utils.clock import to_local

    start, end = _day_bounds(today)
    out = []
    areas = (CleaningArea.query.filter_by(is_active=True)
             .order_by(CleaningArea.risk.desc(), CleaningArea.name).all())
    order = {r: i for i, r in enumerate(RISKS)}
    areas.sort(key=lambda a: (order.get(a.risk, 9), a.name))
    for a in areas:
        rows = []
        for task in a.tasks:
            if not task.is_active:
                continue
            todays = (task.done.filter(CleaningDone.done_at >= start,
                                       CleaningDone.done_at < end).all())
            last = task.done.first()
            due = late = None
            if task.frequency == "deep":
                last_day = to_local(last.done_at).date() if last else None
                due = (last_day + timedelta(days=task.every_days)) if last_day else today
                late = due <= today and not todays
            elif task.frequency == "daily":
                late = not todays
            rows.append({"task": task, "today": todays, "last": last, "due": due,
                         "late": late})
        out.append({"area": a, "rows": rows})
    return out


__all__ = ["CleaningError", "add_area", "add_task", "board", "may_record", "record"]
