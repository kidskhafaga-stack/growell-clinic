"""SAS.11 — the system around the implant: the list, the events, the recall.

The two halves a case touches live in :mod:`app.utils.theatres` (confirmed
in the room; implanted with its batch). This module is the rest of the
standard's eight parts — see :mod:`app.models.implant` for which is which.

**Nothing here refuses a case.** An implant named by hand instead of from
the list is recorded and shown as not from the list; an event nobody has
reported yet stays on the screen until somebody does; a family nobody has
reached is named, not hidden. The gap is the thing a surveyor and the
theatre manager both need to see.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.implant import (CONTACT_OUTCOMES, EVENT_KINDS,
                                RECALL_HOURS_SETTING, ImplantDevice,
                                ImplantEvent, ImplantRecall,
                                ImplantRecallContact)


def _clean(value, size):
    return (value or "").strip()[:size] or None


# ------------------------------------------------------ (a)+(b) the list ----
def catalogue(active_only=True):
    """The hospital's list of implantable devices, by name."""
    q = ImplantDevice.query
    if active_only:
        q = q.filter(ImplantDevice.is_active.is_(True))
    return q.order_by(ImplantDevice.name, ImplantDevice.id).all()


def add_device(name, manufacturer=None, supplier=None, instructions=None,
               note=None, user=None, now=None):
    """Put one device on the list. The caller commits.

    The person adding it is the approval (a): the screen that calls this is
    an administrator's. Refused without a name. A name already on the list
    from the same manufacturer is brought back rather than listed twice — two
    rows for one device split its children between them, and a recall reads
    one.
    """
    name = _clean(name, 160)
    if not name:
        raise ValueError("no name")
    maker = _clean(manufacturer, 120)
    for row in catalogue(active_only=False):
        if (row.name.casefold() == name.casefold()
                and (row.manufacturer or "").casefold() == (maker or "").casefold()):
            row.is_active = True
            return row
    row = ImplantDevice(name=name, manufacturer=maker,
                        supplier=_clean(supplier, 160),
                        instructions=(instructions or "").strip() or None,
                        note=_clean(note, 200),
                        approved_at=now or datetime.utcnow(),
                        approved_by=getattr(user, "id", None))
    db.session.add(row)
    return row


def update_device(device, supplier=None, instructions=None, note=None):
    """Change what the hospital says about a device. The name and maker are
    not changed here: children already point at this row by them."""
    if device is None:
        return None
    device.supplier = _clean(supplier, 160)
    device.instructions = (instructions or "").strip() or None
    device.note = _clean(note, 200)
    return device


def retire_device(device):
    """Off the list for new cases. Never deleted — see the model."""
    if device is None:
        return None
    device.is_active = False
    return device


def off_list(implant):
    """Named by hand rather than taken from the hospital's list."""
    return implant is not None and implant.device_id is None


# ------------------------------------------------------------- (c) who ----
def record_technician(implant, name, external=None):
    """Who fitted it, and whether they were the company's representative.

    ``external`` is tri-state: ``True`` the company's representative,
    ``False`` the hospital's own staff, ``None`` nobody said.
    """
    if implant is None:
        return None
    implant.technician = _clean(name, 120)
    implant.technician_external = external if implant.technician else None
    return implant


# ------------------------------------------------ (h) going home with it ----
def instructions_for(implant):
    """The hospital's discharge instructions for this device, or ``None``."""
    device = getattr(implant, "device", None)
    return (device.instructions or None) if device is not None else None


def give_instructions(implant, user=None, at=None):
    """The instructions were given to the family.

    Only for an implant that is in the child, and only once: the first
    moment is the fact, and a second click on a slow screen must not move
    it.
    """
    if implant is None or not implant.implanted_at:
        raise ValueError("not implanted")
    if implant.instructions_given_at is None:
        implant.instructions_given_at = at or datetime.utcnow()
        implant.instructions_given_by = getattr(user, "id", None)
    return implant


def instructions_missing(implant):
    """In the child, and nobody has recorded giving the family the
    instructions."""
    return bool(implant is not None and implant.implanted_at
                and implant.instructions_given_at is None)


# ------------------------------------------------ (e)+(g) events ----
def record_event(implant, kind, description, user=None, now=None):
    """An adverse event or a malfunction, against an implant in a child."""
    if implant is None or not implant.implanted_at:
        raise ValueError("not implanted")
    if kind not in EVENT_KINDS:
        raise ValueError("unknown kind")
    text = (description or "").strip()
    if not text:
        raise ValueError("no description")
    row = ImplantEvent(implant_id=implant.id, kind=kind, description=text,
                       noted_at=now or datetime.utcnow(),
                       noted_by=getattr(user, "id", None))
    db.session.add(row)
    return row


def report_event(event, reported_to, at=None, reference=None, user=None,
                 now=None):
    """Where it was reported, when, and the reference. The caller commits.

    Refused without somebody reported to, and with a moment in the future
    or before the event was noted — a report cannot precede what it reports.
    """
    now = now or datetime.utcnow()
    if event is None:
        raise ValueError("no event")
    to = _clean(reported_to, 160)
    if not to:
        raise ValueError("reported to nobody")
    when = at or now
    if when > now + timedelta(minutes=5):
        raise ValueError("future")
    if when < event.noted_at - timedelta(minutes=5):
        raise ValueError("before the event")
    event.reported_to = to
    event.reported_at = when
    event.reference = _clean(reference, 80)
    event.reported_by = getattr(user, "id", None)
    return event


def unreported():
    """Every event noted and not yet reported, oldest first."""
    return (ImplantEvent.query.filter(ImplantEvent.reported_at.is_(None))
            .order_by(ImplantEvent.noted_at, ImplantEvent.id).all())


# ------------------------------------------------------------ recall ----
def recall_hours():
    """The hospital's time frame for reaching every child, or ``None``."""
    from app.models import Setting

    raw = (Setting.get(RECALL_HOURS_SETTING) or "").strip()
    try:
        hours = int(raw)
    except ValueError:
        return None
    return hours if hours > 0 else None


def set_recall_hours(value):
    """Write the time frame. Blank clears it; anything else must be a
    whole number of hours above zero."""
    from app.models import Setting

    raw = (str(value) if value is not None else "").strip()
    if not raw:
        Setting.set(RECALL_HOURS_SETTING, "")
        return None
    try:
        hours = int(raw)
    except ValueError:
        raise ValueError("not a number")
    if hours <= 0:
        raise ValueError("not positive")
    Setting.set(RECALL_HOURS_SETTING, str(hours))
    return hours


def open_recall(notice, user=None, now=None, **terms):
    """Start a recall from what a notice names. The caller commits.

    Refused without the notice's words and without at least one thing to
    search on: a recall of "everything" is not a recall.
    """
    text = _clean(notice, 255)
    if not text:
        raise ValueError("no notice")
    clean = {"name": _clean(terms.get("name"), 160),
             "lot": _clean(terms.get("lot"), 60),
             "serial": _clean(terms.get("serial"), 60),
             "manufacturer": _clean(terms.get("manufacturer"), 120)}
    if not any(clean.values()):
        raise ValueError("no terms")
    row = ImplantRecall(notice=text, opened_at=now or datetime.utcnow(),
                        opened_by=getattr(user, "id", None), **clean)
    db.session.add(row)
    return row


def affected(recall):
    """The implants in children this recall names — found again each time,
    so a child whose implant was recorded after the recall opened is not
    missed."""
    from app.utils import theatres as theatre

    if recall is None:
        return []
    return theatre.recall(**recall.terms)


def record_contact(recall, implant, outcome, note=None, user=None, now=None):
    """One attempt to reach one family. The caller commits."""
    if recall is None or implant is None:
        raise ValueError("nothing to record")
    if recall.closed_at is not None:
        raise ValueError("closed")
    if outcome not in CONTACT_OUTCOMES:
        raise ValueError("unknown outcome")
    if implant.id not in {i.id for i in affected(recall)}:
        raise ValueError("not on this recall")
    row = ImplantRecallContact(recall_id=recall.id, implant_id=implant.id,
                               outcome=outcome, note=_clean(note, 255),
                               at=now or datetime.utcnow(),
                               by_id=getattr(user, "id", None))
    db.session.add(row)
    return row


def deadline(recall):
    """When every child should have been reached, or ``None`` while the
    hospital has not set a time frame."""
    hours = recall_hours()
    if recall is None or hours is None:
        return None
    return recall.opened_at + timedelta(hours=hours)


def contact_state(recall, implant, now=None):
    """``reached`` · ``not_reached`` · ``not_tried`` · ``late``.

    ``reached`` is final once any attempt reached the family. ``late`` is a
    child still not reached after the hospital's time frame — or reached
    only after it, which the audit has to be able to see too.
    """
    now = now or datetime.utcnow()
    rows = [c for c in (recall.contacts if recall else [])
            if c.implant_id == implant.id]
    reached = [c for c in rows if c.outcome == "reached"]
    due = deadline(recall)
    if reached:
        first = min(c.at for c in reached)
        return "late" if due is not None and first > due else "reached"
    if due is not None and now > due:
        return "late"
    return "not_reached" if rows else "not_tried"


def board(recall, now=None):
    """Each affected implant with its child, its state and its attempts."""
    out = []
    for implant in affected(recall):
        out.append({"implant": implant,
                    "state": contact_state(recall, implant, now),
                    "attempts": [c for c in recall.contacts
                                 if c.implant_id == implant.id]})
    return out


def outstanding(recall, now=None):
    """Children on the recall nobody has reached yet."""
    return [r for r in board(recall, now)
            if not any(c.outcome == "reached" for c in r["attempts"])]


def close_recall(recall, user=None, note=None, now=None):
    """Close it. Allowed with families still unreached — sometimes a family
    cannot be found — but the note is then required, so the record says
    why the hospital stopped looking."""
    if recall is None or recall.closed_at is not None:
        return None
    text = _clean(note, 255)
    if outstanding(recall, now) and not text:
        raise ValueError("unreached families need a note")
    recall.closed_at = now or datetime.utcnow()
    recall.closed_by = getattr(user, "id", None)
    recall.close_note = text
    return recall


def recalls(open_only=False):
    q = ImplantRecall.query
    if open_only:
        q = q.filter(ImplantRecall.closed_at.is_(None))
    return q.order_by(ImplantRecall.opened_at.desc(), ImplantRecall.id.desc()).all()
