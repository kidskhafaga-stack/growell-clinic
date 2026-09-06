"""What has actually come in against a bill — from the family, and from the payer.

**Two doors, and the program only ever watched one of them.** A bill is settled
by money from two different places: what the family hands over at the desk,
which arrives as a ``Payment`` on the invoice, and what the payer sends against
a claim, which arrives on the ``Claim`` and never touches the invoice at all.
Every "collected" figure in the program read the first and none of them read
the second — so a fully covered visit showed as **paid in full the moment it
was raised**, because the family owed nothing, while the 200 the insurer was
billed had not been asked for yet, let alone sent.

That was survivable while the only question was "does this family still owe us
something". It stops being survivable the moment a doctor is paid on what was
collected, which is how contract work is settled almost everywhere:
*"التعاقد غالباً لما يتم التحصيل من الجهة"*.

**Proportional, because money does not arrive per line.** A family pays a
bill, not a row on it, and a payer pays a claim, not an invoice inside it. So
what a given line has been collected for is its share of what came in — the
same rule ``refunds.doctor_share_of`` has always used going the other way, and
one rule read in both directions is what stops a refund taking back more than
a payment brought in.

**A short-paid claim is short across its invoices**, for the same reason: the
payer said "this batch is worth 9,000, not 10,000" without saying which line
they knocked off, and picking one ourselves would be inventing the answer.
"""
from app.extensions import db


def payer_billed(invoice):
    """What the payer was billed on this invoice — 0 when there is no payer.

    Cover is stored as a line discount, so this is the invoice's discount
    total. That is not a tidy definition, but it is **the same one the claim
    builder uses**, and a doctor's "waiting on the insurer" that disagreed
    with the claim the insurer was actually sent would be worse than an
    untidy one.
    """
    if invoice is None or not invoice.payer_id:
        return 0.0
    return round(invoice.discount_total or 0, 2)


def payer_paid(invoice):
    """What has actually arrived from the payer against this invoice."""
    if invoice is None or not invoice.payer_id:
        return 0.0
    return payer_paid_many([invoice.id]).get(invoice.id, 0.0)


def payer_paid_many(invoice_ids):
    """``{invoice_id: money in from the payer}`` in one query.

    Batched because the payouts screen asks this about every doctor in the
    clinic, and a query per invoice on a hospital's month is the difference
    between a screen that opens and a screen that hangs.
    """
    from app.models.payer import Claim, ClaimItem

    ids = [i for i in (invoice_ids or []) if i]
    if not ids:
        return {}
    rows = (db.session.query(ClaimItem.invoice_id, ClaimItem.amount,
                             Claim.paid_amount, Claim.total_amount)
            .join(Claim, ClaimItem.claim_id == Claim.id)
            .filter(ClaimItem.invoice_id.in_(ids),
                    Claim.status == "paid").all())
    out = {}
    for invoice_id, amount, claim_paid, claim_total in rows:
        if not claim_total:
            continue
        share = (claim_paid or 0) * (amount or 0) / claim_total
        out[invoice_id] = round(out.get(invoice_id, 0.0) + share, 2)
    return out


def settled_fraction(invoice, payer_in=None):
    """How much of this bill has been collected, as a fraction of 0..1.

    Both doors together: the family's payments and the payer's claim money
    over everything the bill asked of either of them.

    **1.0 when the bill asked for nothing.** A visit priced at zero — a staff
    child, a free follow-up — is not "uncollected for ever"; there was nothing
    to collect, and leaving it at 0 would park the doctor's share of it in
    "waiting" permanently with nobody able to clear it.
    """
    if invoice is None:
        return 0.0
    patient_side = round(invoice.total or 0, 2)
    payer_side = payer_billed(invoice)
    asked = round(patient_side + payer_side, 2)
    if asked <= 0:
        return 1.0
    got = round(max(invoice.paid or 0, 0) +
                (payer_paid(invoice) if payer_in is None else payer_in), 2)
    return max(0.0, min(1.0, got / asked))


def split_for_doctor(doctor_id, date_from=None, date_to=None):
    """``{collected, from_family, from_payer}`` of one doctor's invoice shares.

    ``collected`` is what the clinic has actually been paid for; the other two
    are what is still out, split by **who owes it** — because chasing a family
    and chasing an insurer are two different jobs done by two different people,
    and one "outstanding" figure tells neither of them anything.

    Only the shares that sit on a bill. A shift and a vaccine fee are owed by
    the clinic itself with no third party in between, so they are not waiting
    on anybody and do not belong in a split about waiting. :func:`account`
    reports them beside this rather than inside it.
    """
    from app.models import Invoice, InvoiceItem

    query = (db.session.query(InvoiceItem, Invoice)
             .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
             .filter(InvoiceItem.earned_by(doctor_id),
                     InvoiceItem.commission_amount.isnot(None)))
    if date_from is not None:
        query = query.filter(Invoice.invoice_date >= date_from)
    if date_to is not None:
        query = query.filter(Invoice.invoice_date <= date_to)
    rows = query.all()
    if not rows:
        return {"collected": 0.0, "from_family": 0.0, "from_payer": 0.0}

    paid_in = payer_paid_many({inv.id for _, inv in rows})

    collected = family = payer = 0.0
    for line, invoice in rows:
        share = round(line.commission_amount or 0, 2)
        if not share:
            continue
        got = paid_in.get(invoice.id, 0.0)
        fraction = settled_fraction(invoice, payer_in=got)
        collected += share * fraction
        outstanding = share * (1 - fraction)
        if not outstanding:
            continue
        # Split what is still out by who owes it. Proportional again: a bill
        # half paid by the family and unclaimed from the insurer is owed by
        # both of them, and saying it is owed by one would send somebody to
        # ask the wrong person for it.
        due_family = max(round(invoice.total or 0, 2) - max(invoice.paid or 0, 0), 0)
        due_payer = max(payer_billed(invoice) - got, 0)
        both = due_family + due_payer
        if both <= 0:
            collected += outstanding
            continue
        family += outstanding * due_family / both
        payer += outstanding * due_payer / both

    return {"collected": round(collected, 2),
            "from_family": round(family, 2),
            "from_payer": round(payer, 2)}
