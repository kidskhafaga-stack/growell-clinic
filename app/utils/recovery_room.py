"""SAS.19 — is the recovery room ready for the worst ten minutes of the day.

See :mod:`app.models.recovery_equipment` for what the standard asks and why
the list is the hospital's. This module answers the three questions a
surveyor walking the room asks:

* **Is there one, and is it big enough?** — :func:`capacity`, against the
  standard's own *"at least one bed for each operating room"*.
* **Is what it must hold written down?** — :func:`empty_categories`, one of
  the standard's five headings with nothing under it.
* **Was it checked, and what was found?** — :func:`record_check`,
  :func:`open_problems`, :func:`due`.

Nothing here refuses a case. A recovery room with a missing defibrillator is
a problem somebody has to go and fix, and the screen's job is to make sure
they know — not to stop a child who is already asleep from being woken up.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.recovery_equipment import (CATEGORIES, CHECK_HOURS_SETTING,
                                           FINDINGS, RecoveryCheck,
                                           RecoveryCheckLine, RecoveryItem)


def _clean(value, size):
    return (value or "").strip()[:size] or None


# ------------------------------------------------ is there one (EOC 1) ----
def units():
    """The hospital's recovery rooms, as it laid them out."""
    from app.models import Unit

    return (Unit.query.filter(Unit.kind == "recovery",
                              Unit.is_active.is_(True))
            .order_by(Unit.sort_order, Unit.id).all())


def beds_in(unit):
    """Beds in service in this recovery room."""
    if unit is None:
        return 0
    return sum(1 for space in unit.spaces if space.is_active
               for bed in space.beds if bed.is_active)


def capacity():
    """Operating rooms against recovery beds.

    ``{"rooms", "beds", "units", "enough"}`` — ``enough`` is the standard's
    own number, *"at least one bed for each operating room"*, and ``None``
    while the hospital has no operating room to count (nothing to measure).
    """
    from app.models import Theatre

    rooms = Theatre.query.filter(Theatre.is_active.is_(True)).count()
    found = units()
    beds = sum(beds_in(u) for u in found)
    return {"rooms": rooms, "beds": beds, "units": len(found),
            "enough": None if rooms == 0 else beds >= rooms}


# --------------------------------------------- the list (EOC 2, 3 a) ----
def items(unit, active_only=True):
    """What this room must hold, by the standard's headings in its order."""
    if unit is None:
        return []
    q = RecoveryItem.query.filter_by(unit_id=unit.id)
    if active_only:
        q = q.filter(RecoveryItem.is_active.is_(True))
    rows = q.all()
    return sorted(rows, key=lambda r: (CATEGORIES.index(r.category)
                                       if r.category in CATEGORIES else 99,
                                       r.sort_order, r.id))


def add_item(unit, category, name, quantity=None, note=None, user=None):
    """Put one thing on this room's list. The caller commits."""
    if unit is None or getattr(unit, "kind", None) != "recovery":
        raise ValueError("not a recovery room")
    if category not in CATEGORIES:
        raise ValueError("unknown heading")
    name = _clean(name, 160)
    if not name:
        raise ValueError("no name")
    same = [r for r in items(unit, active_only=False)
            if r.category == category and r.name.casefold() == name.casefold()]
    if same:
        # Brought back rather than listed twice: two rows for one thing
        # would let a check find one and miss the other.
        same[0].is_active = True
        same[0].quantity = _clean(quantity, 40)
        same[0].note = _clean(note, 200)
        return same[0]
    row = RecoveryItem(unit_id=unit.id, category=category, name=name,
                       quantity=_clean(quantity, 40), note=_clean(note, 200),
                       sort_order=len(items(unit, active_only=False)),
                       added_by=getattr(user, "id", None))
    db.session.add(row)
    return row


def retire_item(item):
    """Off the list. Never deleted — past checks still name it."""
    if item is None:
        return None
    item.is_active = False
    return item


def empty_categories(unit):
    """The standard's headings this room lists nothing under."""
    have = {r.category for r in items(unit)}
    return [c for c in CATEGORIES if c not in have]


# ------------------------------------------------- checking (EOC 3) ----
def check_hours():
    """How often the hospital checks its recovery rooms, or ``None``."""
    from app.models import Setting

    try:
        hours = int((Setting.get(CHECK_HOURS_SETTING) or "").strip())
    except ValueError:
        return None
    return hours if hours > 0 else None


def set_check_hours(value):
    """Blank clears it; otherwise a whole number of hours above zero."""
    from app.models import Setting

    raw = (str(value) if value is not None else "").strip()
    if not raw:
        Setting.set(CHECK_HOURS_SETTING, "")
        return None
    try:
        hours = int(raw)
    except ValueError:
        raise ValueError("not a number")
    if hours <= 0:
        raise ValueError("not positive")
    Setting.set(CHECK_HOURS_SETTING, str(hours))
    return hours


def record_check(unit, findings, user=None, note=None, now=None):
    """One walk round the room. The caller commits.

    ``findings`` is ``{item_id: (finding, note)}``. **Every item on the list
    must have an answer**: a check that skipped the defibrillator is not a
    check of the room, and recording it as one would put a date on the room
    that says it was looked at when part of it was not. Refused, naming how
    many were left.
    """
    listed = items(unit)
    if unit is None or not listed:
        raise ValueError("nothing to check")
    missing = []
    clean = {}
    for item in listed:
        finding, line_note = findings.get(item.id, (None, None))
        if finding not in FINDINGS:
            missing.append(item)
            continue
        clean[item.id] = (finding, _clean(line_note, 200))
    if missing:
        raise ValueError(f"{len(missing)} unanswered")
    row = RecoveryCheck(unit_id=unit.id, at=now or datetime.utcnow(),
                        by_id=getattr(user, "id", None),
                        note=_clean(note, 255))
    for item in listed:
        finding, line_note = clean[item.id]
        row.lines.append(RecoveryCheckLine(item_id=item.id, finding=finding,
                                           note=line_note))
    db.session.add(row)
    return row


def checks(unit, limit=None):
    if unit is None:
        return []
    q = (RecoveryCheck.query.filter_by(unit_id=unit.id)
         .order_by(RecoveryCheck.at.desc(), RecoveryCheck.id.desc()))
    return q.limit(limit).all() if limit else q.all()


def latest_check(unit):
    found = checks(unit, limit=1)
    return found[0] if found else None


def last_findings(unit):
    """``{item_id: line}`` — each item's most recent finding, from whichever
    check last looked at it."""
    out = {}
    for check in reversed(checks(unit)):
        for line in check.lines:
            out[line.item_id] = line
    return out


def open_problems(unit):
    """Items whose last finding was not ``ok``. A problem stays open until
    a later check finds the thing there and usable — fixing it is a fact a
    check records, not a box somebody ticks."""
    last = last_findings(unit)
    return [(item, last[item.id]) for item in items(unit)
            if item.id in last and last[item.id].finding != "ok"]


def never_checked(unit):
    """Items on the list no check has ever looked at — added since."""
    last = last_findings(unit)
    return [item for item in items(unit) if item.id not in last]


def due(unit, now=None):
    """Is a check due? ``None`` while the hospital has not said how often."""
    hours = check_hours()
    if hours is None:
        return None
    last = latest_check(unit)
    if last is None:
        return True
    return (now or datetime.utcnow()) > last.at + timedelta(hours=hours)


def state(unit, now=None):
    """Everything the board shows about one room, in one dict."""
    return {"unit": unit, "beds": beds_in(unit),
            "empty": empty_categories(unit),
            "problems": open_problems(unit),
            "unchecked": never_checked(unit),
            "last": latest_check(unit), "due": due(unit, now)}


def ready(unit, now=None):
    """Nothing outstanding: every heading listed, every item checked, the
    last finding for each one ``ok``, and no check overdue."""
    s = state(unit, now)
    return (not s["empty"] and not s["problems"] and not s["unchecked"]
            and s["due"] is not True and s["last"] is not None)
