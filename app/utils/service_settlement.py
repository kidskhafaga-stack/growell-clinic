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
                 description=None):
        self.item = item
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
    from app.models import Invoice, InvoiceItem

    if appointment is None:
        return None
    from app.utils.pricing import service_for_visit_type

    invoice = (Invoice.query
               .filter_by(appointment_id=appointment.id)
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
        for item in invoice.items:
            if item.service_id == base.id:
                return item
    return invoice.items[0]


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
    item = line_for(appointment)
    label = description
    if label is None and service is not None:
        label = getattr(service, "name", None)
    return propose(item, price_of(service), label)


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
