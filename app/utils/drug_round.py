"""Who is owed a drug, how late it is, and what actually happened.

The orders are a table (``app/models/medication.py``). What a ward needs from
them is the question the table cannot answer on its own: **which dose is due
now, and which one has gone past.** A dose that was not given leaves no row
behind — the absence is the finding — so something has to work it out from the
order, the last dose and the clock. That is the same shape as a late
observation, and this file is deliberately the same shape as
``utils/observations.py``.

**Nothing is scheduled ahead.** No rows exist for doses that have not
happened. A table of future doses has to be kept in step with an order that
changed at midnight, and the first thing it does when it drifts is claim a
child was given something they were not.

**A held dose moves the clock exactly as a given one does.** The round
happened; somebody stood at the bed and decided. What must not move the clock
is silence — which is the whole point of the board.

Everything here is UTC against UTC, like the observations and the beds. The
clinic's own clock enters only where a screen prints an hour to a person.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.medication import (DOSE_OUTCOMES, GIVEN, ROUTES,
                                   MedicationDose, MedicationOrder, due_at,
                                   lateness_grace)

# What a row on the board can be. Ordered worst-first: the board sorts by this
# and a nurse reads the top of it.
LATE, DUE, OK = "late", "due", "ok"

# A PRN dose asked for before its floor. Raised rather than returned for the
# same reason ``BedTaken`` is: every caller has to deal with it, and the two
# people who might press the button in the same ten minutes are a nurse and
# the nurse relieving them.
class TooSoon(Exception):
    pass


class NoReason(Exception):
    """A hold or a refusal with nothing said about why.

    Refused because a hold with no reason is indistinguishable from a dose
    somebody forgot, and it silences the board either way — which is the one
    failure the board exists to prevent.
    """


def state(order, last_dose_at, now=None):
    """Where one order stands right now.

    ``{"level", "due_at", "minutes_late"}``. ``minutes_late`` is negative
    while the next dose is still ahead, so a screen prints "in 40 minutes" and
    "25 minutes late" from one number rather than from two branches.

    A PRN order is never late — there is no hour it was owed at. What it has
    instead is ``not_before``: the earliest it may be repeated.
    """
    if order is None or not order.is_running:
        return {"level": OK, "due_at": None, "minutes_late": 0,
                "not_before": None}
    now = now or datetime.utcnow()
    if order.is_prn:
        floor = None
        if last_dose_at and order.min_gap_hours:
            floor = last_dose_at + timedelta(hours=order.min_gap_hours)
        return {"level": OK, "due_at": None, "minutes_late": 0,
                "not_before": floor if floor and floor > now else None}

    when = due_at(order, last_dose_at)
    if when is None:
        return {"level": OK, "due_at": None, "minutes_late": 0,
                "not_before": None}
    minutes = int((now - when).total_seconds() // 60)
    if minutes >= lateness_grace(order.every_hours):
        level = LATE
    elif minutes >= 0:
        level = DUE
    else:
        level = OK
    return {"level": level, "due_at": when, "minutes_late": minutes,
            "not_before": None}


def running_orders(admission_ids):
    """``{admission_id: [MedicationOrder]}`` for the orders still standing.

    One query for the whole ward, with the catalogue row loaded because the
    safety check reads it. A stopped order is left out here and kept for ever
    in the file — an order that was stopped is not an order that never was.
    """
    from sqlalchemy.orm import selectinload

    ids = [i for i in admission_ids if i]
    if not ids:
        return {}
    rows = (MedicationOrder.query
            .options(selectinload(MedicationOrder.drug))
            .filter(MedicationOrder.admission_id.in_(ids),
                    MedicationOrder.stopped_at.is_(None))
            .order_by(MedicationOrder.started_at, MedicationOrder.id).all())
    out = {}
    for row in rows:
        out.setdefault(row.admission_id, []).append(row)
    return out


def latest_dose_for(order_ids):
    """``{order_id: newest MedicationDose}`` in two queries.

    Newest by ``at`` — when the dose was dealt with — because that is what the
    next one is counted from. Two doses sharing an order and an exact ``at``
    leave one of the two here; they are interchangeable for the only thing
    this answers, which is when the last one was.
    """
    from sqlalchemy import and_, func

    ids = [i for i in order_ids if i]
    if not ids:
        return {}
    newest = (db.session.query(
        MedicationDose.order_id.label("order_id"),
        func.max(MedicationDose.at).label("at"))
        .filter(MedicationDose.order_id.in_(ids))
        .group_by(MedicationDose.order_id).subquery())
    rows = (MedicationDose.query
            .join(newest, and_(MedicationDose.order_id == newest.c.order_id,
                               MedicationDose.at == newest.c.at)).all())
    return {row.order_id: row for row in rows}


_RANK = {LATE: 0, DUE: 1, OK: 2}


def for_admissions(admission_ids, now=None):
    """``{admission_id: {"orders", "level", "late", "due"}}``.

    Everything a ward screen prints about the drugs, gathered in a fixed
    number of queries so a template asks the database nothing. The
    department's level is its worst order — one late drug on a child is what
    the row has to say, not an average of five.
    """
    now = now or datetime.utcnow()
    orders = running_orders(admission_ids)
    flat = [o for rows in orders.values() for o in rows]
    latest = latest_dose_for([o.id for o in flat])

    out = {}
    for admission_id in [i for i in admission_ids if i]:
        rows, worst = [], OK
        for order in orders.get(admission_id, []):
            last = latest.get(order.id)
            standing = state(order, last.at if last else None, now)
            rows.append({"order": order, "last": last, "state": standing})
            if _RANK[standing["level"]] < _RANK[worst]:
                worst = standing["level"]
        rows.sort(key=lambda r: (_RANK[r["state"]["level"]],
                                 -(r["state"]["minutes_late"] or 0)))
        out[admission_id] = {
            "orders": rows,
            "level": worst,
            "late": sum(1 for r in rows if r["state"]["level"] == LATE),
            "due": sum(1 for r in rows if r["state"]["level"] == DUE),
        }
    return out


def board(kind=None, now=None):
    """Every child on a drug right now, the most overdue at the top.

    ``kind`` narrows to one sort of department; without it, the whole
    hospital — which is what the station board wants at three in the morning,
    when whoever is on covers more than one ward.
    """
    from app.utils.department import _open_admissions

    now = now or datetime.utcnow()
    if kind:
        admissions = _open_admissions(kind)
    else:
        from app.models.admission import Admission
        from sqlalchemy.orm import selectinload

        admissions = (Admission.query
                      .options(selectinload(Admission.patient))
                      .filter(Admission.discharged_at.is_(None))
                      .order_by(Admission.admitted_at).all())

    drugs = for_admissions([a.id for a in admissions], now)
    rows = []
    for admission in admissions:
        entry = drugs.get(admission.id) or {}
        if not entry.get("orders"):
            # A child on nothing is not a row on a drug round. They are on
            # every other ward screen; putting them here too would bury the
            # four children who are actually owed something.
            continue
        rows.append({"admission": admission, "patient": admission.patient,
                     "bed": admission.bed, **entry})
    rows.sort(key=lambda r: (_RANK[r["level"]],
                             -max((o["state"]["minutes_late"] or 0)
                                  for o in r["orders"])))
    return rows


def order(admission, drug_name, user=None, drug=None, dose=None, route="oral",
          every_hours=None, is_prn=False, min_gap_hours=None, note=None,
          when=None):
    """Write a standing order, or refuse.

    Refuses a nameless drug, and refuses a regular order with no interval —
    "give amoxicillin" with no *how often* is not an instruction anybody can
    carry out, and storing it would put a line on the chart that can never be
    due and therefore can never be late.
    """
    if admission is None or not admission.is_open:
        raise ValueError("not admitted")
    name = (drug_name or "").strip()[:200]
    if not name:
        raise ValueError("no drug")
    is_prn = bool(is_prn)
    if not is_prn and not every_hours:
        raise ValueError("no interval")

    row = MedicationOrder(
        admission_id=admission.id, patient_id=admission.patient_id,
        drug_id=getattr(drug, "id", None), drug_name=name,
        dose=(dose or "").strip()[:80] or None,
        route=route if route in ROUTES else "oral",
        every_hours=None if is_prn else int(every_hours),
        is_prn=is_prn,
        min_gap_hours=int(min_gap_hours) if is_prn and min_gap_hours else None,
        started_at=when or datetime.utcnow(),
        ordered_by=getattr(user, "id", None),
        note=(note or "").strip()[:255] or None)
    db.session.add(row)
    return row


def stop(order_row, user=None, reason=None, when=None):
    """Stop an order. The doses it already has stay where they are — an order
    that was stopped is not an order that never existed, and the file has to
    be able to say what a child was on last Tuesday."""
    if order_row is None or not order_row.is_running:
        return order_row
    order_row.stopped_at = when or datetime.utcnow()
    order_row.stopped_by = getattr(user, "id", None)
    order_row.stop_reason = (reason or "").strip()[:200] or None
    return order_row


def give(order_row, outcome=GIVEN, user=None, at=None, reason=None, note=None,
         now=None):
    """Record what happened at this hour: given, held or refused.

    Three refusals, and each of them is a real ward failure:

    * a dose on a stopped order — the order was stopped for a reason, and a
      chart that accepts one afterwards is a chart that cannot be trusted to
      say what a child is on;
    * a hold or a refusal with nothing said about why — indistinguishable
      from a dose somebody forgot, and it silences the board either way;
    * a PRN repeated inside its own floor — the one safety number a "when
      needed" order carries, and the only place the program can enforce it.
    """
    if order_row is None or not order_row.is_running:
        raise ValueError("not running")
    if outcome not in DOSE_OUTCOMES:
        raise ValueError("no outcome")
    said = (reason or "").strip()
    if outcome != GIVEN and not said:
        raise NoReason(outcome)

    now = now or datetime.utcnow()
    when = at or now
    last = latest_dose_for([order_row.id]).get(order_row.id)
    if order_row.is_prn and order_row.min_gap_hours and last is not None:
        floor = last.at + timedelta(hours=order_row.min_gap_hours)
        if when < floor:
            raise TooSoon(floor)

    row = MedicationDose(
        order_id=order_row.id, patient_id=order_row.patient_id,
        # The hour it was owed at, stored beside the hour it happened. "The
        # eight o'clock dose, given at nine twenty" is a fact about a ward,
        # and the two halves say different things.
        due_at=due_at(order_row, last.at if last else None),
        at=when, recorded_at=now, outcome=outcome,
        reason=said[:200] or None,
        note=(note or "").strip()[:255] or None,
        by_id=getattr(user, "id", None))
    db.session.add(row)
    return row


def safety(admission, extra=None, lang="ar"):
    """What the clinic's own safety check makes of everything this child is on.

    Not a second check. ``rx_safety.check`` is the one the prescription screen
    uses — the dose ceilings, the allergies, the interaction pairs — and an
    inpatient order is handed to it unchanged, because ``MedicationOrder``
    names its fields the way a written line does. A ward with its own idea of
    an interaction would be a second copy of a clinical rule, free to disagree
    with the prescription screen about the same child on the same day.

    **The child's existing medicines are not added here**, and the first
    version of this function added them. They were already in: ``check``
    pulls them off the patient itself, precisely so that every caller gets the
    carbamazepine somebody else wrote months ago without having to remember
    to fetch it. Passing them again put the same ingredient in twice. Found
    by breaking the line and watching nothing fail — the second copy could
    not change the answer, which is what a second copy usually cannot, right
    up until the day it can.
    """
    from app.utils import rx_safety

    if admission is None:
        return None
    lines = list(running_orders([admission.id]).get(admission.id) or [])
    if extra is not None:
        lines = lines + [extra]
    return rx_safety.check(lines, patient=admission.patient, lang=lang)
