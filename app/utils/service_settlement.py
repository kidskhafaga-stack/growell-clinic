"""When the bill says one thing and the visit turned out to be another.

Reception books and collects at the desk; the decision is taken later, inside
the room. A child booked for a paid consultation is seen for free. A check-up
turns out to need the longer visit. The doctor gives a discount nobody entered.
Each of those leaves the invoice describing something that did not happen, and
until now the program did nothing about any of it — cancelling an appointment
touches the reminders, the reason and the log, and never once looks at the
money. So a cancelled visit sat on the board marked **Paid**, with the clinic
holding cash for something that was not going to happen and no screen saying
so.

**This is the vaccine settlement, generalised.** That module already answers
this exact question for one kind of line, and the rule it established is the
one thing here worth copying:

    "Applying it rewrites the invoice line to reality — the refund/collection
    then follows from the invoice balance like any other, so nothing here
    invents its own money path."

So nothing in this file moves money. It works out **what the line should have
said**, and the difference falls out of arithmetic that already exists:

    difference = what was collected − what is owed once the line is corrected

Negative hands money back, positive collects it, zero is a visit that changed
shape without changing price. Reception is never asked to work that out.

**Commission needs no special case, and must not get one.** ``commission_amount``
is a snapshot of ``service.doctor_share(item.net, doctor)``, so correcting the
line to a free consultation makes it a share of nothing, and correcting it to a
dearer service makes it that service's share — both without a line of code
about commission. The vaccine version *zeroes* it, which is right for a vaccine
(they carry none) and would quietly rob a doctor of their cut of a consultation.
Recompute, never zero.

**Priced the way the till prices it** (`MONEY_SAFETY_PLAN.md` ف-٨). The
first version charged the new service at its list price, so the doctor's own
price, the clinic's cash price list, the insurer's share and the family's
named discount all fell off the corrected line: a covered child was suddenly
paying the whole consultation and the claim still read the old figure. A
service change now goes through :func:`reprice` — the till's own functions,
on that one line — and the proposal is the same rewrite done inside a
savepoint and rolled back, so the figure the desk agrees to and the figure
that is written are one computation, not two that can drift.
"""
from app.extensions import db

#: What the program is proposing. The screen renders these; reception picks
#: none of them, it presses the one button the verdict names.
VERDICTS = (
    "refund",       # money goes back
    "collect",      # money still to come
    "settled",      # the change costs nothing either way
    "nothing",      # the correction changes the bill not at all
    "unbilled",     # nothing was ever charged for this
)


def _round(value):
    return round(value or 0, 2)


class Proposal:
    """What the program suggests, and everything needed to check it.

    Deliberately not a database row. A proposal is a *reading* of the current
    invoice, so storing it would create a second copy of a number the invoice
    already holds — and the two would part company the moment anything else
    touched the bill. It is computed when somebody looks.
    """

    def __init__(self, item, was, becomes, collected, verdict, amount,
                 description=None, before=None, after=None, blocked=False):
        self.item = item
        #: The line before and after, for the screen: price, payer's share,
        #: discount, and what the family pays. Empty for a price-only
        #: proposal.
        self.before = before or {}
        self.after = after or {}
        #: The bill sits in a closed accounting period — nothing may change.
        self.blocked = blocked
        self.was = was                  # what the line is worth now
        self.becomes = becomes          # what it should be worth
        self.collected = collected      # what the family has actually paid
        self.verdict = verdict
        self.amount = amount            # always positive; the verdict says which way
        self.description = description  # the corrected line's wording

    @property
    def invoice(self):
        return self.item.invoice if self.item is not None else None

    def __repr__(self):
        return f"<Proposal {self.verdict} {self.amount}>"


def line_for(appointment):
    """The invoice line this appointment was billed on, or ``None``.

    An appointment with no line was never charged for, which is a different
    thing from one charged at zero — the first has nothing to settle and the
    second is a decision somebody made.
    """
    from app.models import Invoice

    if appointment is None:
        return None
    from app.utils.pricing import service_for_visit_type

    invoice = (Invoice.query
               .filter_by(appointment_id=appointment.id)
               .order_by(Invoice.id.desc()).first())
    if invoice is None:
        # One bill per family per day: a second booking the same day is
        # collected onto the bill the first one opened, which keeps the first
        # booking's number. That booking was billed all the same.
        invoice = (Invoice.query
                   .filter(Invoice.patient_id == appointment.patient_id,
                           Invoice.invoice_date == appointment.appt_date,
                           Invoice.status != "refunded")
                   .order_by(Invoice.id.desc()).first())
    if invoice is None or not invoice.items:
        return None
    # The visit's own charge is the line this booking is about. Anything else
    # on the bill — a vaccine, a dressing — was a separate decision and is not
    # this appointment's to rewrite. The booking has no service of its own, so
    # the visit type is what says which charge is the visit's; the same
    # mapping the till used to put the line there in the first place.
    base = service_for_visit_type(getattr(appointment, "appt_type", None))
    if base is not None:
        mine = [i for i in invoice.items if i.service_id == base.id]
        # Two of the same visit on one bill: the one for this booking's
        # doctor, and the last one if that still leaves two.
        theirs = [i for i in mine
                  if (i.doctor_id or invoice.doctor_id) == appointment.doctor_id]
        if theirs or mine:
            return (theirs or mine)[-1]
    # Nothing marks the visit's line. One line is the visit; on a bill with
    # several, guessing would rewrite somebody else's charge — the wizard asks.
    return invoice.items[0] if len(invoice.items) == 1 else None


def price_of(service, patient=None):
    """What a service costs, as the billing side would charge it."""
    return _round(getattr(service, "price", 0) if service is not None else 0)


def propose(item, new_price, description=None):
    """What should happen if this line becomes worth ``new_price``.

    The single calculation behind every case reception meets — a discount, a
    swap to a cheaper or dearer service, a free consultation, a cancellation
    (which is this with ``new_price`` of zero).
    """
    if item is None:
        return Proposal(None, 0.0, 0.0, 0.0, "unbilled", 0.0)

    invoice = item.invoice
    was = _round(item.net)
    becomes = _round(new_price)
    collected = _round(invoice.paid if invoice is not None else 0)

    if invoice is None:
        return Proposal(item, was, becomes, 0.0, "unbilled", 0.0, description)

    # What the whole bill would owe once this one line is corrected. The other
    # lines are somebody else's decisions and stay exactly as they are.
    owed_after = _round(_round(invoice.total) - was + becomes)
    difference = _round(collected - owed_after)

    if was == becomes:
        verdict = "nothing"
    elif difference > 0:
        verdict = "refund"
    elif difference < 0:
        verdict = "collect"
    else:
        # The line changed and the money did not: a free consultation on a
        # bill that had not been paid, or a swap that happens to cost the
        # same. Worth its own word — "nothing to do" and "nothing changed"
        # are different sentences to read on a screen.
        verdict = "settled"

    return Proposal(item, was, becomes, collected, verdict,
                    abs(difference), description)


def propose_service_change(appointment, service, description=None):
    """The proposal for turning this booking into a different service."""
    return propose_line_change(line_for(appointment), service,
                               description=description)


def _doctor_of(item):
    invoice = item.invoice
    return item.doctor or (invoice.doctor if invoice is not None else None)


def reprice(item, service, description=None, doctor=None):
    """Make ``item`` the line the till would have written for ``service``.

    The doctor's own price (`case_rates.price_for`), then — for this line
    only — the payer's tariff and cover or the clinic's cash price list
    (`billing.apply_coverage`), then the bill's named discount, then the
    doctor's share. Anything typed by hand on the old line goes: it was a
    decision about the old service.
    """
    from app.utils import billing, case_rates

    invoice = item.invoice
    doctor = doctor or _doctor_of(item)
    item.service = service
    item.service_id = service.id
    item.description = (description or getattr(service, "name", None)
                        or item.description)
    item.quantity = 1
    item.discount_value = 0
    item.discount_is_percent = False
    item.payer_amount = None
    item.group_discount = None
    item.cover_note = None
    item.cover_cut = None
    item.contract_group_id = None
    item.unit_price = round(case_rates.price_for(service, doctor) or 0, 2)
    db.session.flush()

    def named(inv, _patient):
        from app.models import NamedDiscount

        disc = (db.session.get(NamedDiscount, inv.discount_id)
                if inv.discount_id else None)
        amount = billing.named_discount_on_line(item, disc)
        if amount > 0:
            item.discount_value = amount
            item.discount_is_percent = False

    billing.apply_coverage(invoice, invoice.patient, then=named, only=[item])
    if not (item.payer_amount or 0) > 0:
        # A covered line's share was written by the cover, on the price; any
        # other line's is on what the family pays.
        item.commission_amount = case_rates.share_for(service, item.net, doctor)
    db.session.flush()
    invoice.recalc_status()
    return item


def _state(item):
    return {"description": item.description,
            "price": _round(item.gross),
            "payer": _round(item.payer_amount),
            "discount": _round(_round(item.gross) - _round(item.net)
                               - _round(item.payer_amount)),
            "family": _round(item.net)}


def _blocked(invoice):
    from app.utils.periods import period_blocked

    return bool(invoice is not None and invoice.invoice_date is not None
                and period_blocked(invoice.invoice_date, flash_it=False))


def propose_line_change(item, service, description=None):
    """What changing ``item`` to ``service`` would do — worked out by doing it
    inside a savepoint and rolling it back, so nothing is changed by asking."""
    if item is None or item.invoice is None or service is None:
        return Proposal(None, 0.0, 0.0, 0.0, "unbilled", 0.0)
    invoice = item.invoice
    before = _state(item)
    collected = _round(invoice.paid)
    savepoint = db.session.begin_nested()
    try:
        reprice(item, service, description)
        after = _state(item)
        owed_after = _round(invoice.total)
    finally:
        savepoint.rollback()
    difference = _round(collected - owed_after)
    same = all(before[k] == after[k] for k in ("price", "payer", "family"))
    if same:
        verdict = "nothing"
    elif difference > 0:
        verdict = "refund"
    elif difference < 0:
        verdict = "collect"
    else:
        verdict = "settled"
    return Proposal(item, before["family"], after["family"], collected,
                    verdict, abs(difference), after["description"],
                    before=before, after=after, blocked=_blocked(invoice))


def propose_cancellation(appointment):
    """The proposal for a booking that is not going to happen at all."""
    return propose(line_for(appointment), 0.0)


def apply(proposal, doctor=None, service=None, user_id=None):
    """Rewrite the line to what actually happened, and hand back the invoice.

    Nothing is collected or refunded here. The caller reads the invoice's own
    balance afterwards and uses the money paths that already exist — which is
    what keeps one way of taking money in this program and one way of giving
    it back.
    """
    item = proposal.item if proposal is not None else None
    if item is None or item.invoice is None or proposal.verdict == "unbilled":
        return None
    # A closed month is closed for money — the same rule as editing a line
    # from the bill (`periods.period_blocked`).
    if _blocked(item.invoice):
        return None

    if service is not None and proposal.after:
        reprice(item, service, proposal.description, doctor=doctor)
        return item.invoice

    item.unit_price = proposal.becomes
    item.quantity = 1
    # A correction replaces the price outright, so a discount that was part of
    # the old price would otherwise be taken off the new one as well.
    item.discount_value = 0
    item.discount_is_percent = False
    if service is not None:
        item.service_id = service.id
    if proposal.description:
        item.description = proposal.description

    # Recomputed, never zeroed — see the module docstring.
    earner = doctor or item.doctor or item.invoice.doctor
    priced = service if service is not None else item.service
    item.commission_amount = (priced.doctor_share(item.net, earner)
                              if priced is not None else 0.0)

    db.session.flush()
    item.invoice.recalc_status()
    return item.invoice
