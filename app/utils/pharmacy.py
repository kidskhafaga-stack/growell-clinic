"""The counter: what the pharmacy is asked for, checks, and hands over.

``HOSPITAL_PLAN.md`` مرحلة ج بند ٧ names three things — *"الجرعة بالكيلو،
والتعارضات، ومراجعة الروشتة"* — and **two of them were already built and are
not rebuilt here**. The paediatric dose lives in :mod:`app.utils.dosing`, the
interactions and the allergy check in :mod:`app.utils.rx_safety`, and the
prescription writer has shown both to the doctor for a long time. A second
copy of either would be a second set of clinical numbers, which is the one
thing this program never does twice.

**What was missing is the third, and the act underneath it.** A prescription
was written, printed, and that was the end of it as far as the software was
concerned. Nobody reviewed it as a pharmacist reviews one, the box left the
shelf without the clinic's own stock knowing, and nothing was charged. So this
module is the counter: the queue, the check *shown to the person handing the
box over*, and the handing over itself.

**The check is the same check.** ``review`` calls ``rx_safety`` and adds
nothing to it. The pharmacist sees exactly what the doctor saw — which is the
point of a second pair of eyes, and would be defeated by a second rulebook.

**A query, never a veto.** A pharmacist who reads a dose they think is wrong
has one job: to say so, to the person who wrote it. Recording that as a
question and not a refusal is the honest shape — the doctor may have meant it,
and a pharmacy that can block a prescription is one prescriptions get written
around.

**And dispensing is opt-in twice over.** A line with no store item on it is
printed and handed to the family to fill outside, exactly as before: nothing
leaves the shelf and nothing is charged. That is the normal case for a clinic
and it stays untouched — the same rule as a ward order with no shelf behind
it, and a bed with no rate on it.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Prescription, PrescriptionItem


def queue(days=3, patient_id=None, limit=100):
    """Prescriptions with something still to hand over, newest first.

    Newest first and not oldest — the opposite of the lab's rack, and for the
    opposite reason: somebody is standing at the counter holding the paper
    that was written four minutes ago. The lab works through a backlog; a
    pharmacy works through a queue of people.

    Bounded to the last few days because a prescription from March is not
    waiting at the counter; it was filled somewhere else or never filled. The
    patient's own file is where an old one is looked up, not this list.
    """
    since = datetime.utcnow() - timedelta(days=max(1, days))
    query = (Prescription.query
             .filter(Prescription.created_at >= since)
             .order_by(Prescription.created_at.desc(), Prescription.id.desc()))
    if patient_id is not None:
        query = query.filter(Prescription.patient_id == patient_id)
    return [rx for rx in query.limit(limit).all() if pending(rx)]


def pending(prescription):
    """The lines this prescription still owes the counter.

    A line with no store item is not pending anything: it was never the
    pharmacy's to hand over. That is what keeps this list empty — and the
    module invisible — for a clinic whose families fill their prescriptions
    outside.
    """
    return [i for i in (prescription.items if prescription else [])
            if i.store_item_id is not None and i.dispensed_at is None]


def dispensed(prescription):
    return [i for i in (prescription.items if prescription else [])
            if i.dispensed_at is not None]


def review(prescription, lang="ar"):
    """What the pharmacist should see before handing anything over.

    **The same check the doctor was shown**, from ``rx_safety`` and nowhere
    else: the allergy, the paediatric dose against this child's own weight,
    and the interactions between the ingredients on the paper. A second
    rulebook here would defeat the whole purpose of a second pair of eyes.
    """
    from app.utils.rx_safety import check

    if prescription is None:
        return {"lines": [], "interactions": [], "by_item": {}}
    written = list(prescription.items or [])
    # The rows themselves: `rx_safety` already accepts a `PrescriptionItem`,
    # and rebuilding them as dicts here would be a second copy of what a
    # written line *is* — one that drifts the first time a field is added.
    found = check(written, patient=prescription.patient, lang=lang)
    # Keyed by the line it belongs to, so the screen never has to trust that
    # two lists came back in the same order — the kind of assumption that
    # holds until somebody filters one of them and puts a dose warning under
    # the wrong medicine.
    found["by_item"] = {row.id: line for row, line
                        in zip(written, found.get("lines") or [])}
    return found


def dispense(item, user=None, quantity=None, at=None):
    """Hand this line over. Returns the line.

    Refuses only two things, and both are a keystroke on the wrong row rather
    than a clinical decision: a line with nothing to give, and one that has
    already been given. Everything else the pharmacy may do and the program
    records — including handing over the last box when the count says the
    shelf is empty, which is a discrepancy for the store to reconcile and not
    a medicine to withhold from a child standing at the counter.
    """
    if item is None or item.store_item_id is None:
        raise ValueError("nothing to dispense")
    if item.dispensed_at is not None:
        raise ValueError("already dispensed")
    if quantity is not None:
        item.quantity = max(1, int(quantity or 1))
    if not item.quantity:
        item.quantity = 1
    item.dispensed_at = at or datetime.utcnow()
    item.dispensed_by = getattr(user, "id", None)
    return item


def query(item, note=None, user=None, at=None):
    """The pharmacist has a question about this line.

    Recorded and never a block: the line stays dispensable, because the answer
    is usually "yes, I meant it" and the family is standing there.
    """
    if item is None:
        raise ValueError("no line")
    text = (note or "").strip()[:255]
    if not text:
        # A question with no question in it would clear the flag and say
        # nothing, which reads on the doctor's screen as "the pharmacy looked
        # and was happy".
        raise ValueError("no note")
    item.query_note = text
    item.queried_at = at or datetime.utcnow()
    item.queried_by = getattr(user, "id", None)
    return item


def open_queries(days=7, limit=50):
    """Lines the pharmacy asked about and nobody has handed over yet.

    The doctor's half of the query. Without it a question asked at the counter
    reaches the doctor only if somebody walks round — which is the same gap
    the results inbox exists to close for a film that came back.
    """
    since = datetime.utcnow() - timedelta(days=max(1, days))
    return (PrescriptionItem.query
            .join(Prescription,
                  PrescriptionItem.prescription_id == Prescription.id)
            .filter(PrescriptionItem.queried_at.isnot(None),
                    PrescriptionItem.dispensed_at.is_(None),
                    Prescription.created_at >= since)
            .order_by(PrescriptionItem.queried_at.desc())
            .limit(limit).all())


# ------------------------------------------------------------- the money ---
def unbilled(patient_id=None, prescription_id=None):
    """Lines handed over that nobody has charged for.

    Handed over, not written: a prescription the family took away to fill
    outside costs the clinic nothing, and the moment something is owed is the
    moment a box leaves this shelf.
    """
    query_ = (PrescriptionItem.query
              .join(Prescription,
                    PrescriptionItem.prescription_id == Prescription.id)
              .filter(PrescriptionItem.dispensed_at.isnot(None),
                      PrescriptionItem.invoice_item_id.is_(None),
                      PrescriptionItem.store_item_id.isnot(None)))
    if patient_id is not None:
        query_ = query_.filter(Prescription.patient_id == patient_id)
    if prescription_id is not None:
        query_ = query_.filter(
            PrescriptionItem.prescription_id == prescription_id)
    return query_.order_by(PrescriptionItem.dispensed_at,
                           PrescriptionItem.id).all()


def take_off_shelf(rows, invoice, user=None, lang="ar"):
    """Move handed-over medicines out of stock. Returns how many.

    **The line on the bill is not made here.** The desk raises it, the same way
    it raises every other line a family pays for, and this posts the stock
    movement behind it — so the price on the paper the family holds and the
    box missing from the shelf are one act with one document.

    One issue document holds the whole handover and rides on the invoice, so
    the ledger picks up the cost of goods in the same posting the till already
    does for a service's consumables.

    **And a box is never refused for want of stock.** The pharmacy handed it
    over; that happened. Declining to record it because our own count says the
    shelf is empty replaces a true fact with a tidy one — the movement is
    posted, the stock is allowed to go negative, and the difference is the
    store's to reconcile rather than a medicine to unfeed a child.
    """
    from app.models import StockMovement
    from app.utils.costing import issue_unit_cost
    from app.utils.store_docs import open_document

    rows = [r for r in (rows or []) if r.store_item is not None]
    if not rows or invoice is None:
        return 0

    document = getattr(invoice, "_iss_doc", None)
    for line in rows:
        if document is None:
            document = open_document("issue", reference=invoice.invoice_number)
        movement = StockMovement(
            item_id=line.store_item_id, kind="out",
            qty=-abs(max(1, int(line.quantity or 1))),
            reason=_reason(line, lang),
            unit_cost=issue_unit_cost(line.store_item),
            created_by=getattr(user, "id", None), document_id=document.id)
        db.session.add(movement)
        db.session.flush()
        line.stock_movement_id = movement.id

    if document is not None:
        invoice._iss_doc = document
    return len(rows)


def _line_text(line, stock_item, lang):
    name = (stock_item.display_name(lang) if hasattr(stock_item, "display_name")
            else line.drug_name)
    parts = [name]
    if line.dose:
        parts.append(line.dose)
    return " · ".join(parts)[:200]


def _reason(line, lang):
    from app.i18n import t

    try:
        return t("pharm.issue_reason", drug=line.drug_name)[:160]
    except Exception:  # noqa: BLE001
        return (line.drug_name or "")[:160]
