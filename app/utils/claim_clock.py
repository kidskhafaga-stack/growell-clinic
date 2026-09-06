"""Two deadlines a claims desk lives by, and the money sitting past them.

**A payer agreement is a price list and two dates**, and this program only
ever held the price list. The dates are the ones the desk argues about: *by
when must the claim be sent*, and *by when must the money come*. Both were in
the paper agreement and in nobody's screen, so the program could not say the
two sentences that make a claims desk a job rather than a filing cabinet —
"this one closes on Thursday" and "this payer is sixty days late".

**The window is the sharp one.** A filing window is a contractual deadline
counted from the date of service, and past it an otherwise payable claim is
refused — in most agreements it cannot be billed to the family either, so it
converts straight into a write-off. Windows run from about 90 days to a year
depending on the payer, which is exactly why **the program never guesses one**:
a number we invented would either raise alarms about claims that are fine or
stay silent about claims that are already dead. No term typed, no deadline
shown.

**Aged by when it was submitted, not by when it was billed**, because the
payer's clock starts when the claim reaches them. The buckets are the ordinary
30 / 60 / 90 ones the trade uses, and the reason they are worth drawing is
that what sits past 90 days is roughly half-collectable — the point of the
screen is to make that visible while it is still 40.
"""
from datetime import timedelta

from app.extensions import db
from app.utils.clock import local_today

# The ordinary ageing buckets, oldest last. Days since submission.
BUCKETS = ((0, 30), (31, 60), (61, 90), (91, None))


def terms(payer, on_date=None):
    """``(filing_days, payment_days, cycle_day)`` in force — Nones when unset.

    Read off the contract in force on the date, because a renewal may change
    them: a claim raised in March is judged by March's agreement.
    """
    if payer is None:
        return (None, None, None)
    contract = None
    if getattr(payer, "contracts", None):
        contract = payer.active_contract(on_date or local_today())
    if contract is None:
        return (None, None, None)
    return (contract.filing_days, contract.payment_days, contract.cycle_day)


def filing_due(invoice):
    """The last day this invoice can still be claimed, or ``None``.

    ``None`` means "no term typed", which is a different thing from "no time
    left" and must never be shown as a deadline.
    """
    if invoice is None or not invoice.payer_id or not invoice.invoice_date:
        return None
    days = terms(invoice.payer, invoice.invoice_date)[0]
    if not days:
        return None
    return invoice.invoice_date + timedelta(days=int(days))


def days_to_file(invoice, today=None):
    """Days left to send this claim. Negative once the window has closed."""
    due = filing_due(invoice)
    if due is None:
        return None
    return (due - (today or local_today())).days


def payment_due(claim):
    """The day this claim's money is due, or ``None`` when nothing says.

    Counted from **submission** and not from the date of service: the payer's
    clock starts when the claim reaches them, which is also the only date they
    would accept being held to.
    """
    if claim is None or claim.submitted_at is None:
        return None
    days = terms(claim.payer, claim.date_from or local_today())[1]
    if not days:
        return None
    return claim.submitted_at.date() + timedelta(days=int(days))


def days_overdue(claim, today=None):
    """How many days past its due date this claim's money is. 0 when not."""
    due = payment_due(claim)
    if due is None:
        return 0
    return max(((today or local_today()) - due).days, 0)


def closing_soon(within=14, payer_id=None, today=None):
    """Covered invoices whose filing window is closing, soonest first.

    Includes the ones already past it, and says so with a negative number of
    days rather than hiding them: a claim that can no longer be sent is the
    most important row on the screen, because somebody has to decide to write
    it off rather than discover it at the audit.

    Empty for every clinic that has typed no filing term — the switch.
    """
    from app.models import Invoice
    from app.models.payer import Claim, ClaimItem

    today = today or local_today()
    taken = {row[0] for row in
             db.session.query(ClaimItem.invoice_id)
             .join(Claim, ClaimItem.claim_id == Claim.id)
             .filter(Claim.status != "rejected").all()}

    query = Invoice.query.filter(Invoice.payer_id.isnot(None))
    if payer_id is not None:
        query = query.filter(Invoice.payer_id == payer_id)

    rows = []
    for invoice in query.all():
        if invoice.id in taken or invoice.discount_total <= 0:
            continue
        left = days_to_file(invoice, today)
        if left is None or left > within:
            continue
        rows.append({"invoice": invoice, "days": left,
                     "due": filing_due(invoice),
                     "amount": round(invoice.discount_total, 2)})
    rows.sort(key=lambda r: r["days"])
    return rows


def outstanding(payer_id=None, today=None):
    """Claims sent and not paid, with how long they have been out.

    Submitted **and** approved: an approved claim is a payer saying "yes, we
    owe this", and money that has been agreed and not sent is exactly the
    money worth chasing. A draft is not out at all — it is still on our desk.
    """
    from app.models.payer import Claim

    today = today or local_today()
    query = Claim.query.filter(Claim.status.in_(("submitted", "approved")))
    if payer_id is not None:
        query = query.filter(Claim.payer_id == payer_id)

    rows = []
    for claim in query.order_by(Claim.submitted_at).all():
        sent = claim.submitted_at.date() if claim.submitted_at else None
        age = (today - sent).days if sent else None
        rows.append({"claim": claim, "age": age,
                     "due": payment_due(claim),
                     "overdue": days_overdue(claim, today),
                     "amount": round(claim.approved_amount
                                     if claim.approved_amount is not None
                                     else (claim.total_amount or 0), 2)})
    return rows


def aging(payer_id=None, today=None):
    """``[{label, days, count, amount}]`` — the money out, by how long.

    One row per bucket, **including the empty ones**: a table that drops the
    90+ row when it is empty and grows it when it is not is a table nobody
    reads the shape of. The buckets are fixed; what moves is the money in them.
    """
    rows = outstanding(payer_id, today)
    out = []
    for low, high in BUCKETS:
        inside = [r for r in rows
                  if r["age"] is not None and r["age"] >= low
                  and (high is None or r["age"] <= high)]
        out.append({"low": low, "high": high,
                    "count": len(inside),
                    "amount": round(sum(r["amount"] for r in inside), 2)})
    # A claim submitted with no date on it belongs somewhere, and inventing an
    # age for it would file it in a bucket it may not be in.
    undated = [r for r in rows if r["age"] is None]
    if undated:
        out.append({"low": None, "high": None, "count": len(undated),
                    "amount": round(sum(r["amount"] for r in undated), 2)})
    return out
