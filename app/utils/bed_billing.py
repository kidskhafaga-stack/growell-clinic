"""What a stay costs — a night on a ward, an hour in emergency.

The third of the three things ``HOSPITAL_PLAN.md`` says an inpatient ward
needs beyond a bed. Everything under it already existed: the stay knows its
hours, the bed knows where it is, and the price list knows what things cost.
What was missing is the sentence joining them — *this child has been in for
four nights and nobody has billed any of them.*

**Two bases, because two of them are real.** A ward, the incubators and
intensive care are charged by the **night**. Emergency is charged by the
**hour**: a child on a trolley for three hours who goes home has not spent a
night anywhere, and billing one is not a rounding difference — it is a bill
for something that did not happen. Recovery after theatre is the same shape,
shorter. Which of the two a department runs on is ``Unit.billing_basis``, set
from the bed setup and preset by the kind of unit rather than decided here.

**A night, not a day.** Nights run from the local date of admission to the
local date of discharge, not counting the day they leave, with a floor of one
once the stay has ended. In on Monday, out on Thursday is three nights; in and
out the same afternoon is one, because a bed was made up and taken again. An
*open* stay owes up to yesterday and never tonight, and a stay that started
this afternoon owes nothing at all yet.

**An hour is charged when the stay ends, and only then.** How many hours it
was is not known until the child leaves, and charging in instalments would put
two lines on one bill for one visit. Part-hours round up with a floor of one:
twenty minutes on a trolley is an hour of a trolley.

**The rate hangs off all three levels: bed, then room, then department.** A
clinic prices where it prices. Most price the room — a single and a double are
two prices for the same bed, and what differs is the walls. The nursery prices
the bed, because one bay holds a cot, an incubator and a transport capsule.
Emergency prices the department. So the nearest rate that is set wins, and the
answer to *"هي الفاتورة تفصيلية للسرير ولا الغرف؟"* is: by whichever of them
the clinic actually charges, and the invoice line names the bed either way.

**The rate is a service.** Not a number typed onto a unit — a ``Service``, so
it sits in the clinic's one price list where the discounts, the payer rules,
the doctor's commission and the tax item code already work.

**And the price is the switch.** A clinic that has set no rate anywhere is
never charged for anything and never sees a figure, which is how this feature
stays absent for the clinics it is not for — the same rule as a module that is
off.

**Nothing is posted behind anybody's back.** The stay screen *shows* what is
uncharged and somebody presses; the discharge posts it because a discharge is
already a deliberate act with a form in front of it. There is no timer that
quietly writes money onto a family's account overnight.

**And a night is charged at the bed they were in at the end of it.** A child
moved up to intensive care at four in the afternoon spends the night in
intensive care, and that is what the night cost.
"""
import math
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models.bed_charge import BedCharge
from app.utils.clock import local_today, to_local, to_utc

# The two units a stay can be sold in. Not a free string: the invoice line,
# the screen and the charge row all read it, and a third value would be a
# price nothing knows how to count.
NIGHT, HOUR = "night", "hour"
BASES = (NIGHT, HOUR)

# What a department of each kind is charged by when one is first built. A
# preset and not a rule — every one of them is editable from the bed setup
# afterwards, the same way the facility wizard presets capabilities. What it
# buys is that nobody has to know emergency is hourly *before* their first
# emergency bill comes out wrong.
BASIS_BY_KIND = {
    "emergency": HOUR,
    "recovery": HOUR,
    "day_care": HOUR,
    "ward": NIGHT,
    "icu": NIGHT,
    "nicu": NIGHT,
}


def default_basis(kind):
    return BASIS_BY_KIND.get(kind, NIGHT)


def basis_for(bed):
    """Night or hour, from the department this bed stands in.

    On the unit rather than on the bed because it is a fact about how the
    place works, not about the furniture: every trolley in an emergency is
    charged by the hour and every bed on a ward by the night.
    """
    unit = bed.unit if bed is not None else None
    basis = getattr(unit, "billing_basis", None)
    return basis if basis in BASES else NIGHT


def rate_for(bed):
    """The service this bed is charged at, or ``None``.

    Bed, then room, then department — the nearest one that is set. ``None`` is
    a complete answer and the common one: a clinic that does not bill for a
    bed has set none of the three.
    """
    if bed is None:
        return None
    if bed.rate_service is not None:
        return bed.rate_service
    space = bed.space
    if space is not None and space.rate_service is not None:
        return space.rate_service
    unit = bed.unit
    return unit.rate_service if unit is not None else None


def bed_on(admission, on_date):
    """Which bed this stay was in at the end of ``on_date``.

    The end of the night rather than the start of it, because a child moved
    into intensive care at four in the afternoon spends that night in
    intensive care — and because the last night of a stay would otherwise be
    charged at a bed they had already left.
    """
    edge = to_utc(datetime.combine(on_date, time.max))
    if admission.discharged_at and admission.discharged_at < edge:
        edge = admission.discharged_at
    covering = [s for s in admission.stays
                if s.since <= edge and (s.until is None or s.until >= edge)]
    if covering:
        return covering[-1].bed
    # Nothing covers that instant — a gap between two stays, or a date
    # outside the admission. The nearest earlier stay is the honest answer.
    earlier = [s for s in admission.stays if s.since <= edge]
    return earlier[-1].bed if earlier else (
        admission.stays[0].bed if admission.stays else None)


def nights(admission, upto=None):
    """The clinic dates this stay owes a night for, oldest first."""
    if admission is None or not admission.admitted_at:
        return []
    first = to_local(admission.admitted_at).date()
    if admission.discharged_at:
        last = to_local(admission.discharged_at).date() - timedelta(days=1)
        # In and out the same afternoon is still one night: a bed was made up
        # and taken again, and every hospital in the world charges for it.
        if last < first:
            last = first
    else:
        # An open stay owes up to yesterday. Charging tonight before it has
        # happened is how a family is billed for a night they went home in.
        #
        # **And the floor of one does not apply here**, which is the whole
        # difference between the two branches. A stay that ended the same
        # afternoon owes a night — a bed was made up and taken again. A stay
        # that *started* this afternoon owes nothing yet: the child is still
        # in the bed, and nobody knows whether tonight will happen in it.
        # Written the other way once, and the test that found it is the one
        # about a stay admitted today.
        last = (upto or local_today()) - timedelta(days=1)
        if last < first:
            return []
    if upto is not None and last > upto:
        last = upto

    out, day = [], first
    while day <= last:
        out.append(day)
        day += timedelta(days=1)
    return out


def hours_so_far(admission, now=None):
    """How long this child has been in, in hours, rounded up, floor of one.

    Shown while an hourly stay is running, so somebody can tell a family what
    it is coming to. **Not** what is charged — see :func:`billable_hours`.
    """
    if admission is None or not admission.admitted_at:
        return 0
    end = admission.discharged_at or (now or datetime.utcnow())
    # **Whole minutes, then hours.** Measured to the microsecond, a stay of
    # exactly three hours bills four — the discharge is written a fraction of
    # a second after the boundary and any part-hour rounds up. That is an
    # artefact of the clock, not a fact about the child, and it is the family
    # who would pay for it. A ward measures a stay to the minute.
    minutes = int((end - admission.admitted_at).total_seconds() // 60)
    # And then any part-hour is an hour: twenty minutes on a trolley is an
    # hour of a trolley. Rounding down would make the first hour of every
    # emergency free, and most emergency stays are one hour.
    return max(1, int(math.ceil(minutes / 60.0)))


def billable_hours(admission):
    """The hours to charge, or ``0`` while the stay is still open.

    An hourly stay is charged **when it ends**. How many hours it was is not
    known until the child leaves; charging in instalments would put two lines
    on one bill for one visit, and would need a second row for the same date,
    which the unique index rightly refuses.
    """
    if admission is None or admission.discharged_at is None:
        return 0
    return hours_so_far(admission)


def charged_dates(admission_id):
    rows = (db.session.query(BedCharge.on_date)
            .filter(BedCharge.admission_id == admission_id).all())
    return {row[0] for row in rows}


def outstanding(admission, upto=None):
    """What this stay owes and nobody has billed.

    A list of ``{"on", "bed", "service", "quantity", "basis", "amount"}``,
    oldest first. Periods with no rate behind them are left out entirely
    rather than added at zero: a clinic that does not bill for a bed should
    see nothing at all, not a list of free days.
    """
    if admission is None:
        return []
    done = charged_dates(admission.id)
    where = admission.bed or bed_on(admission, local_today())

    if basis_for(where) == HOUR:
        return _hourly(admission, done)

    out = []
    for day in nights(admission, upto):
        if day in done:
            continue
        at = bed_on(admission, day)
        service = rate_for(at)
        if service is None:
            continue
        out.append(_line(day, at, service, 1, NIGHT))
    return out


def _hourly(admission, done):
    """One period, written at the end, for a stay sold by the hour."""
    hours = billable_hours(admission)
    if not hours:
        return []
    day = to_local(admission.discharged_at).date()
    if day in done:
        return []
    at = bed_on(admission, day)
    service = rate_for(at)
    if service is None:
        return []
    return [_line(day, at, service, hours, HOUR)]


def _line(day, bed, service, quantity, basis):
    price = float(service.price or 0)
    return {"on": day, "bed": bed, "service": service, "quantity": quantity,
            "basis": basis, "amount": round(price * quantity, 2)}


def invoice_for(admission, user=None):
    """The stay's own invoice, made if it is not there yet.

    One invoice for the whole stay. Without it the nights would either raise
    a bill each — eleven for eleven days — or fall into the outpatient
    one-invoice-per-day rule and land on whichever bill the desk happened to
    open that morning.
    """
    from app.models.invoice import Invoice
    from app.utils.finance import generate_invoice_number

    existing = (Invoice.query
                .filter(Invoice.admission_id == admission.id)
                .order_by(Invoice.id).first())
    if existing is not None:
        return existing
    invoice = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=admission.patient_id,
                      doctor_id=admission.doctor_id,
                      admission_id=admission.id,
                      created_by=getattr(user, "id", None))
    db.session.add(invoice)
    db.session.flush()
    return invoice


def post(admission, user=None, upto=None, lang="ar"):
    """Charge everything this stay owes and has not been charged for.

    Returns ``{"periods", "total", "invoice"}``. Safe to run again — the
    unique index on (stay, date) is what makes it so, rather than a flag
    somebody has to remember to set.
    """
    from app.models.invoice import InvoiceItem

    due = outstanding(admission, upto)
    if not due:
        return {"periods": 0, "total": 0.0, "invoice": None}

    invoice = invoice_for(admission, user)
    added = []
    for row in due:
        price = float(row["service"].price or 0)
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=row["service"].id,
            # The description carries the period and the bed, because the
            # questions a family asks of this line are "which night" and "why
            # is Tuesday more than Monday".
            description=describe(row, lang),
            unit_price=price, quantity=row["quantity"])
        # The doctor's share of this line, snapshotted like every other
        # chargeable line in the program. Left off at first, so a clinic that
        # had set a commission on "a night on the ward" was quietly paying
        # nothing on the one service its inpatients buy most of.
        item.commission_amount = row["service"].doctor_share(item.net,
                                                             invoice.doctor)
        db.session.add(item)
        db.session.flush()
        db.session.add(BedCharge(
            admission_id=admission.id, patient_id=admission.patient_id,
            on_date=row["on"], bed_id=getattr(row["bed"], "id", None),
            service_id=row["service"].id,
            quantity=row["quantity"], basis=row["basis"],
            # Snapshotted beside the link, like every printed name here: a
            # price list edited in March must not rewrite February's bill.
            unit_price=price, invoice_item_id=item.id,
            posted_by=getattr(user, "id", None)))
        added.append(item)

    # **And then through the same door every other invoice goes through.**
    # The insurance, the contract tariff, the cash price list and the family's
    # own discount all live in `utils/billing`, and a bed bill raised outside
    # them was a covered child billed the cash rate for eleven nights with
    # nothing claimable at the end of it.
    from app.utils import billing

    billing.apply_coverage(invoice, admission.patient)
    db.session.flush()
    # **The ledger is not posted here** — see `charge` below, which is what a
    # screen should call. It matters, and it cost a suite run to find out: a
    # journal failure rolls the session back, and rolling back before the bill
    # is committed takes the bill with it. A family would have been discharged
    # with no invoice at all because the bookkeeping hiccupped.
    return {"periods": len(due),
            # The lines *this* call added, after coverage — not the whole
            # bill, which on the second posting of a long stay would report
            # last week's nights again as if they had just been charged.
            "total": round(sum(i.net for i in added), 2),
            "gross": round(sum(i.gross for i in added), 2),
            "invoice": invoice}


def charge(admission, user=None, upto=None, lang="ar"):
    """Post the outstanding periods, commit them, and then journal them.

    **The order is the point.** ``post`` builds the lines and ``post_to_ledger``
    is best-effort — and "best effort" means it rolls the session back when the
    ledger refuses. Called before the commit, that rollback discards the
    invoice it was trying to journal, and a family goes home with no bill at
    all because the chart of accounts was in a bad way. The till has always
    done it in this order; the wards do it here so nobody has to remember.
    """
    result = post(admission, user=user, upto=upto, lang=lang)
    db.session.commit()
    if result["invoice"] is not None:
        billing_module().post_to_ledger("invoice", result["invoice"],
                                        user_id=getattr(user, "id", None))
    return result


def billing_module():
    from app.utils import billing

    return billing


def describe(row, lang="ar"):
    """The invoice line, as a family reads it.

    The bed is named on every line, whichever level the price came from: a
    clinic that charges by the room still has somebody asking which room, and
    the bed answers it without a second lookup.
    """
    service = row["service"]
    name = (service.display_name(lang) if hasattr(service, "display_name")
            else service.name)
    when = row["on"].isoformat()
    if row["basis"] == HOUR:
        when = f"{when} · {row['quantity']}h"
    where = ""
    bed = row["bed"]
    if bed is not None:
        unit = bed.unit
        where = f" — {unit.name} · {bed.name}" if unit else f" — {bed.name}"
    return f"{name} ({when}){where}"[:200]
