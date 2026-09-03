"""Who is in which bed, and which beds are free — all of it counted, none of it stored.

The one rule this file exists to keep: **a bed is free when no stay is open on
it.** There is no ``is_occupied`` column anywhere, and there must never be one.
A flag is one forgotten discharge away from a ward that reports itself full
with three beds standing empty, and the ward staff learn within a week to
stop believing the screen — which costs more than the feature was worth. Same
reasoning as the rule already written down for `Measurement` and corrected
age: *المحسوب أحسن من المتخزّن*.

Everything here is UTC against UTC, like the observations. The clinic's own
clock enters only when a screen prints an hour to a person.
"""
from datetime import datetime

from app.extensions import db
from app.models.admission import Admission, BedStay
from app.models.place import Bed, Space, Unit


class BedTaken(Exception):
    """Somebody else got there first.

    Raised rather than returned because every caller has to handle it and a
    boolean is too easy to ignore: two people admitting two children from two
    screens in the same minute is not a rare event on a busy morning, it is
    the normal way a ward fills up.
    """


def occupied_bed_ids():
    """The ids of every bed with a stay open on it, as a set.

    One query for the whole hospital. The board draws every bed and asks this
    once, rather than asking per bed — which is the shape the query ceilings
    exist to catch.
    """
    rows = (db.session.query(BedStay.bed_id)
            .filter(BedStay.until.is_(None)).all())
    return {row[0] for row in rows}


def open_stays_by_bed():
    """``{bed_id: BedStay}`` for every occupied bed, with the child loaded.

    The board prints the name of whoever is in each bed, so the patient comes
    with the stay rather than being fetched per row.
    """
    from sqlalchemy.orm import selectinload

    rows = (BedStay.query
            .options(selectinload(BedStay.admission)
                     .selectinload(Admission.patient))
            .filter(BedStay.until.is_(None)).all())
    return {row.bed_id: row for row in rows}


def board(unit_id=None):
    """The whole place, unit by unit, with what is in every bed.

    Four queries whatever the size of the hospital: the units, their spaces,
    their beds, and the open stays. A ward with sixty beds costs the same as
    one with four.
    """
    from sqlalchemy.orm import selectinload

    units = (Unit.query
             .options(selectinload(Unit.spaces).selectinload(Space.beds))
             .filter(Unit.is_active.is_(True))
             .order_by(Unit.sort_order, Unit.id))
    if unit_id:
        units = units.filter(Unit.id == unit_id)
    units = units.all()

    stays = open_stays_by_bed()
    out = []
    for unit in units:
        spaces = []
        free = taken = 0
        for space in unit.spaces:
            if not space.is_active:
                continue
            beds = []
            for bed in space.beds:
                stay = stays.get(bed.id)
                if bed.is_active:
                    taken += 1 if stay else 0
                    free += 0 if stay else 1
                beds.append({"bed": bed, "stay": stay,
                             "patient": (stay.admission.patient
                                         if stay else None)})
            spaces.append({"space": space, "beds": beds})
        out.append({"unit": unit, "spaces": spaces,
                    "free": free, "taken": taken})
    return out


def free_beds(unit_id=None, isolation=None, kind=None):
    """Beds nobody is in, narrowest first by the filters given.

    ``isolation=True`` is the question asked at the worst possible moment —
    an infectious child at the door — and it is answered from the space,
    never from the bed. See ``models/place.py``.
    """
    query = (Bed.query.join(Space, Bed.space_id == Space.id)
             .join(Unit, Space.unit_id == Unit.id)
             .filter(Bed.is_active.is_(True), Space.is_active.is_(True),
                     Unit.is_active.is_(True)))
    if unit_id:
        query = query.filter(Unit.id == unit_id)
    if isolation is not None:
        query = query.filter(Space.is_isolation.is_(bool(isolation)))
    if kind:
        query = query.filter(Bed.kind == kind)
    taken = occupied_bed_ids()
    ordered = query.order_by(Unit.sort_order, Space.sort_order,
                             Bed.sort_order, Bed.id).all()
    return [bed for bed in ordered if bed.id not in taken]


def open_admission(patient_id):
    """The stay this child is currently in, or ``None``."""
    return (Admission.query
            .filter(Admission.patient_id == patient_id,
                    Admission.discharged_at.is_(None))
            .order_by(Admission.admitted_at.desc(), Admission.id.desc())
            .first())


def admit(patient, bed, user=None, visit=None, doctor_id=None, reason=None,
          when=None):
    """Put a child in a bed and open their stay.

    Refuses a bed that already has somebody in it — checked here rather than
    trusted from the screen, because the screen's list of free beds was drawn
    seconds ago and a ward fills up between a page loading and a button being
    pressed.

    Refuses a second admission for a child who is already admitted, for the
    same reason a second one would be wrong: they are in a bed, and two open
    stays would make both beds look occupied by the same child and neither of
    them wrong.
    """
    if bed is None:
        raise BedTaken("no bed")
    if not bed.is_active:
        raise BedTaken("out of service")
    if bed.id in occupied_bed_ids():
        raise BedTaken("occupied")
    if open_admission(patient.id) is not None:
        raise BedTaken("already admitted")

    now = when or datetime.utcnow()
    admission = Admission(
        patient_id=patient.id,
        visit_id=visit.id if visit is not None else None,
        doctor_id=doctor_id,
        admitted_at=now,
        admitted_by=getattr(user, "id", None),
        reason=(reason or "").strip()[:200] or None)
    db.session.add(admission)
    db.session.flush()
    db.session.add(BedStay(admission_id=admission.id, bed_id=bed.id,
                           since=now, moved_by=getattr(user, "id", None)))
    return admission


def move(admission, bed, user=None, note=None, when=None):
    """Move a child to another bed, closing the old stay and opening a new one.

    The old row keeps its hours. Overwriting ``bed_id`` in place would answer
    "where is this child now" and silently rewrite every earlier day of the
    stay to say they had always been there — which is exactly the question
    infection control asks afterwards.
    """
    if admission is None or not admission.is_open:
        raise BedTaken("not admitted")
    if bed is None or not bed.is_active:
        raise BedTaken("out of service")
    current = admission.current_stay
    if current is not None and current.bed_id == bed.id:
        return current
    if bed.id in occupied_bed_ids():
        raise BedTaken("occupied")

    now = when or datetime.utcnow()
    if current is not None:
        current.until = now
    stay = BedStay(admission_id=admission.id, bed_id=bed.id, since=now,
                   moved_by=getattr(user, "id", None),
                   note=(note or "").strip()[:120] or None)
    db.session.add(stay)
    return stay


def discharge(admission, outcome, user=None, note=None, when=None):
    """End the stay, and free the bed with it.

    The bed is freed by closing the stay, not by clearing a flag — so a
    discharge that is recorded is a bed that is free, in one place, with
    nothing to keep in step.
    """
    from app.models.admission import OUTCOMES

    if admission is None or not admission.is_open:
        return admission
    now = when or datetime.utcnow()
    admission.discharged_at = now
    admission.discharged_by = getattr(user, "id", None)
    admission.outcome = outcome if outcome in OUTCOMES else "home"
    admission.discharge_note = (note or "").strip() or None
    current = admission.current_stay
    if current is not None:
        current.until = now
    return admission


def counts():
    """``{"free", "taken", "total"}`` across every active bed.

    For the dashboard line and nothing else. Derived from the same two facts
    as everything above, so it cannot disagree with the board.
    """
    total = (Bed.query.join(Space, Bed.space_id == Space.id)
             .join(Unit, Space.unit_id == Unit.id)
             .filter(Bed.is_active.is_(True), Space.is_active.is_(True),
                     Unit.is_active.is_(True)).count())
    taken = len(occupied_bed_ids())
    return {"free": max(0, total - taken), "taken": taken, "total": total}
