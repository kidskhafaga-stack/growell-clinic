"""Who is owed a reading, and how late it is.

The readings themselves are a table (``app/models/observation.py``). What a
station actually needs is the question the readings cannot answer: **which
child has not been measured for longer than the doctor asked.** A missing
observation leaves no row behind — the absence is the finding, and something
has to work it out from the order and the clock.

Everything here compares UTC with UTC. The stored times are naive UTC, the
"now" it measures against is ``datetime.utcnow()``, and nothing in this file
touches a local date — which is the rule four money reports were fixed for
breaking (see ``app/utils/clock.py``). The clinic's own timezone enters only
when a screen prints an hour to a human.
"""
from datetime import datetime

from app.extensions import db
from app.models.observation import Observation, ObservationOrder, due_at, \
    lateness_grace

# What a row on the board can be. Ordered worst-first on purpose: the board
# sorts by this and a nurse reads the top of it.
LATE, DUE, OK = "late", "due", "ok"


def state(order, last_taken, now=None):
    """Where one order stands right now.

    ``{"level", "due_at", "minutes_late"}``. ``minutes_late`` is negative
    while the next reading is still ahead, which lets a screen print "in 6
    minutes" and "12 minutes late" from one number instead of two branches.
    """
    if order is None or not order.is_running:
        return {"level": OK, "due_at": None, "minutes_late": 0}
    now = now or datetime.utcnow()
    when = due_at(order, last_taken)
    minutes = int((now - when).total_seconds() // 60)
    if minutes >= lateness_grace(order.every_minutes):
        level = LATE
    elif minutes >= 0:
        level = DUE
    else:
        level = OK
    return {"level": level, "due_at": when, "minutes_late": minutes}


def latest_for(order_ids):
    """``{order_id: newest Observation}`` for many orders, in two queries.

    Written this way rather than the obvious loop because this feeds a board
    that draws one row per child under observation, and a query per row is the
    one performance mistake that is invisible until a ward is full. There is a
    ceiling test that fails if this becomes a loop.

    Two readings sharing an order and an exact ``taken_at`` — the same nurse
    saving twice in the same second — leave one of the two here. They are
    interchangeable for the only thing this is used for, which is "when was
    the last reading and what did it say".
    """
    from sqlalchemy import and_, func

    ids = [i for i in order_ids if i]
    if not ids:
        return {}
    newest = (db.session.query(
        Observation.order_id.label("order_id"),
        func.max(Observation.taken_at).label("at"))
        .filter(Observation.order_id.in_(ids))
        .group_by(Observation.order_id).subquery())
    rows = (Observation.query
            .join(newest, and_(Observation.order_id == newest.c.order_id,
                               Observation.taken_at == newest.c.at))
            .all())
    return {row.order_id: row for row in rows}


def running_order(patient_id):
    """The observation order this child is under, or ``None``.

    The newest running one. More than one at a time is not a shape the screens
    offer — an interval is changed by stopping and re-ordering, so that the
    chart keeps both the old cadence and the moment it changed — but the
    database cannot promise that on its own, and a page that crashed because
    somebody's import created two would be a poor way to find out.
    """
    return (ObservationOrder.query
            .filter(ObservationOrder.patient_id == patient_id,
                    ObservationOrder.stopped_at.is_(None))
            .order_by(ObservationOrder.started_at.desc(),
                      ObservationOrder.id.desc()).first())


def board(now=None):
    """Every child currently under observation, worst first.

    Each row carries the order, the child, the last reading and how late the
    next one is — plus the program's own reading of that last set of numbers,
    which comes from ``red_flags`` and ``vital_bands`` rather than from
    anything invented here. A board that judged a temperature by its own rule
    would be a second copy of the clinic's thresholds, free to disagree with
    the visit screen about the same child.
    """
    from sqlalchemy.orm import selectinload

    from app.utils.red_flags import assess

    now = now or datetime.utcnow()
    orders = (ObservationOrder.query
              .options(selectinload(ObservationOrder.patient))
              .filter(ObservationOrder.stopped_at.is_(None))
              .order_by(ObservationOrder.started_at).all())
    latest = latest_for([o.id for o in orders])

    rows = []
    for order in orders:
        last = latest.get(order.id)
        rows.append({
            "order": order,
            "patient": order.patient,
            "last": last,
            "state": state(order, last.taken_at if last else None, now),
            "flag": assess(order.patient, last, ""),
        })
    rank = {LATE: 0, DUE: 1, OK: 2}
    rows.sort(key=lambda r: (rank[r["state"]["level"]],
                             -r["state"]["minutes_late"]))
    return rows


def chart(patient_id, limit=48):
    """This child's readings, newest first.

    Forty-eight is two days of hourly rounds, or twelve hours of
    quarter-hourly ones. A ward round reads the recent ones; anything older is
    history and belongs on a page that says so, rather than in a table that
    silently grows to four hundred rows on a tablet at the bedside.
    """
    return (Observation.query
            .filter(Observation.patient_id == patient_id)
            .order_by(Observation.taken_at.desc(), Observation.id.desc())
            .limit(limit).all())
