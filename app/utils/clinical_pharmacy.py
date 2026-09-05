"""The ward pharmacist: whose chart has nobody been through today.

**Not the counter.** :mod:`app.utils.pharmacy` is the dispensing pharmacy — a
queue of people holding paper, a box off the shelf, money. This is the other
half of the same profession and the half a hospital is bought for: somebody
who reads the drug chart of every child in a bed, against that child's weight
and their kidneys and the four other things they are on, and says something to
the doctor before a dose is given rather than after.

``HOSPITAL_PLAN.md`` مرحلة ج بند ٧ names three things and **none of the
clinical rules are written here**: the paediatric dose lives in
:mod:`app.utils.dosing`, the interactions and allergies in
:mod:`app.utils.rx_safety`, and the ward already hands its chart to that check
through ``drug_round.safety``. The pharmacist sees exactly what the doctor and
the nurse see, which is the point of a third pair of eyes and would be
defeated by a third rulebook.

What is here is the **work**, and it has the shape of every other ward
question this program answers:

* **who has nobody been through today** — the same sentence as the ward
  round's, because a chart reviewed on Monday says nothing about the drug
  started on Wednesday;
* **a review is a row**, not a flag: a stay with no query on it looks exactly
  like a stay nobody has opened, and those are opposite facts;
* **and a query is a question, never a block.** The order goes on being given
  while it is open. The answer is usually "yes, I meant it", the child is in
  the bed, and a pharmacy that can stop a ward's drug is one the ward starts
  writing around.
"""
from datetime import datetime

from app.extensions import db
from app.models import ChartReview, MedicationOrder
from app.models.admission import Admission


def reviewed_today(admission_ids, on_date=None):
    """``{admission_id: ChartReview}`` for reviews done on the clinic's today.

    One query for the whole board, and the clinic's day rather than the
    server's — comparing a stored UTC moment against a local date is the
    mistake this program has already paid for in four money reports.
    """
    from app.utils.clock import local_today
    from app.utils.live import day_bounds

    if not admission_ids:
        return {}
    start, end = day_bounds(on_date or local_today())
    rows = (ChartReview.query
            .filter(ChartReview.admission_id.in_(admission_ids),
                    ChartReview.at >= start, ChartReview.at < end)
            .order_by(ChartReview.at).all())
    return {row.admission_id: row for row in rows}


def open_queries(admission_ids=None):
    """``{admission_id: [order]}`` — questions the doctor has not answered.

    Grouped by stay because that is how the board reads: a child with two
    unanswered questions is one row that needs somebody, not two.
    """
    query = MedicationOrder.query.filter(
        MedicationOrder.queried_at.isnot(None),
        MedicationOrder.answered_at.is_(None),
        MedicationOrder.stopped_at.is_(None))
    if admission_ids is not None:
        if not admission_ids:
            return {}
        query = query.filter(MedicationOrder.admission_id.in_(admission_ids))
    out = {}
    for row in query.order_by(MedicationOrder.queried_at).all():
        out.setdefault(row.admission_id, []).append(row)
    return out


def board(kind=None, on_date=None):
    """Every child in a bed, unreviewed first, with what they are on.

    Unreviewed first and not alphabetical: the whole reason to open this
    screen is to find who has been missed, and a list that buries them among
    the ones already done is a list that gets read from the top and abandoned.
    """
    from app.utils import drug_round
    from app.models.place import Bed, Space, Unit

    stays = (Admission.query
             .filter(Admission.discharged_at.is_(None))
             .order_by(Admission.admitted_at).all())
    if kind:
        stays = [s for s in stays
                 if s.bed is not None and s.bed.unit is not None
                 and s.bed.unit.kind == kind]
    if not stays:
        return []

    ids = [s.id for s in stays]
    done = reviewed_today(ids, on_date)
    asked = open_queries(ids)
    charts = drug_round.running_orders(ids)

    rows = []
    for stay in stays:
        orders = list(charts.get(stay.id) or [])
        rows.append({
            "admission": stay, "patient": stay.patient, "bed": stay.bed,
            "orders": orders, "drugs": len(orders),
            "review": done.get(stay.id),
            "queries": asked.get(stay.id) or [],
        })
    # Nobody has been to them, then whoever has the most on their chart —
    # which is the honest proxy for who is most worth a second pair of eyes.
    rows.sort(key=lambda r: (r["review"] is not None, -r["drugs"]))
    return rows


def counts(rows=None):
    """``{beds, unreviewed, queries}`` — the three numbers on the heading."""
    rows = board() if rows is None else rows
    return {"beds": len(rows),
            "unreviewed": sum(1 for r in rows if r["review"] is None),
            "queries": sum(len(r["queries"]) for r in rows)}


def chart(admission, lang="ar"):
    """This stay's drug chart with the clinic's own safety check over it.

    ``drug_round.safety`` and nothing else — the same call the ward screen
    makes. A clinical pharmacy with its own idea of an interaction would be a
    second copy of a clinical rule, free to disagree with the prescription
    screen about the same child on the same day.
    """
    from app.utils import drug_round

    if admission is None:
        return {"orders": [], "safety": None}
    return {"orders": list(drug_round.running_orders([admission.id])
                           .get(admission.id) or []),
            "safety": drug_round.safety(admission, lang=lang)}


def review(admission, user=None, note=None, at=None):
    """Record that somebody went through this chart. Returns the row.

    A second review on the same day is a second row rather than an update:
    two pharmacists looking at the same child four hours apart is two events,
    and the board only ever asks whether *any* of them happened today.
    """
    if admission is None:
        raise ValueError("no stay")
    from app.utils import drug_round

    row = ChartReview(
        admission_id=admission.id, patient_id=admission.patient_id,
        at=at or datetime.utcnow(), by_id=getattr(user, "id", None),
        drugs_seen=len(drug_round.running_orders([admission.id])
                       .get(admission.id) or []),
        note=(note or "").strip()[:255] or None)
    db.session.add(row)
    return row


def ask(order, note=None, user=None, at=None):
    """Ask the doctor about one order. Never stops it."""
    if order is None:
        raise ValueError("no order")
    text = (note or "").strip()[:255]
    if not text:
        # A question with no question in it would flag the order and say
        # nothing, which reads on the doctor's screen as somebody having
        # looked and been satisfied.
        raise ValueError("no note")
    order.query_note = text
    order.queried_at = at or datetime.utcnow()
    order.queried_by = getattr(user, "id", None)
    # Asking again reopens: a doctor answered, the pharmacist is still not
    # happy, and the second question is the one that matters.
    order.answer_note = None
    order.answered_at = None
    order.answered_by = None
    return order


def answer(order, note=None, user=None, at=None):
    """The doctor's reply. The question stays on the order afterwards.

    Clearing it would leave a changed dose with nothing saying why, and an
    unchanged one with nothing saying it was defended.
    """
    if order is None or order.queried_at is None:
        raise ValueError("nothing asked")
    order.answer_note = (note or "").strip()[:255] or None
    order.answered_at = at or datetime.utcnow()
    order.answered_by = getattr(user, "id", None)
    return order
