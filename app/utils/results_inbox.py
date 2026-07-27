"""Results that came back, and nobody has read yet.

The clinic asks for a chest film; two days later the mother photographs the
report and sends it. It is filed on the child's record and tied to the order
it answers — and then it waits, because the doctor only meets it by opening
that child's visit, and the child is not coming in today. That was the point
of ordering it in the program.

So the arrived-and-unread orders are a list of their own: the shortest list
in the clinic on a good day, and the one nobody should have to remember.

"Arrived" is `VisitInvestigation.result_state`: a file is attached and no
doctor has written what it says. Reading it and recording the result takes it
off this list — that is the only way off, because it is the only thing that
means the question was answered.
"""
from datetime import datetime


def arrived_unread(doctor_id=None, limit=100):
    """Orders whose answer is here and unread, longest-waiting first.

    Scoped to one doctor when asked: a paediatrician with four colleagues
    wants the films *they* asked for, not the clinic's whole pile.
    """
    from sqlalchemy.orm import selectinload

    from app.extensions import db
    from app.models import PatientAttachment, Visit, VisitInvestigation

    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.files),
                     selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.visit))
            .filter(VisitInvestigation.status == "requested")
            # Only the ones with something attached; the rest are still out
            # with the family and belong on nobody's list.
            .filter(VisitInvestigation.id.in_(
                db.session.query(PatientAttachment.investigation_id)
                .filter(PatientAttachment.investigation_id.isnot(None)))))
    if doctor_id:
        rows = rows.join(Visit, VisitInvestigation.visit_id == Visit.id) \
                   .filter(Visit.doctor_id == doctor_id)

    out = []
    for order in rows.limit(limit).all():
        # result_state does the real judging; this is the cheap pre-filter.
        if order.result_state != "arrived":
            continue
        out.append({"order": order, "patient": order.patient,
                    "arrived_at": order.arrived_at,
                    "waiting_hours": _hours_since(order.arrived_at),
                    "files": list(order.files or [])})
    out.sort(key=lambda row: -(row["waiting_hours"] or 0))
    return out


def arrived_count(doctor_id=None):
    """How many are waiting to be read — what the bell shows."""
    return len(arrived_unread(doctor_id=doctor_id, limit=200))


def _hours_since(moment):
    if moment is None:
        return 0
    return max((datetime.utcnow() - moment).total_seconds() / 3600.0, 0)


def closing_windows(hours=2):
    """Conversations whose free-reply window shuts within ``hours``.

    The inbox already prints how long is left. Nobody is looking at the inbox
    at eleven at night, which is exactly when a window quietly closes and the
    next reply starts costing money — so these get counted where people do
    look, and pushed to the top of the list where they don't.
    """
    from app.utils.inbox import conversations

    # ``conversations`` already works out each thread's window and sorts the
    # closing ones to the top; counting them here from a second copy of the
    # rule is how the bell and the list end up disagreeing.
    return [c for c in conversations(only_open=True, limit=200)
            if c.get("closing") and (c.get("hours_left") or 0) <= hours]
