"""The daily bed charge — counted from the stay, charged once per night.

The third of the three things ``HOSPITAL_PLAN.md`` says an inpatient ward
needs beyond a bed. Everything under it already existed: the stay knows its
hours, the bed knows where it is, and the price list knows what things cost.
What was missing is the sentence joining them — *this child has been in for
four nights and nobody has billed any of them.*

**A night, not a day.** Nights are counted from the local date of admission
to the local date of discharge, not including the day they leave, with a
floor of one. It is the rule hospitals bill on and the one a family expects:
in on Monday, out on Thursday, three nights. A child admitted and discharged
the same afternoon is one, because a bed was made up and taken again.

**The rate is a service.** Not a number typed onto a unit — a ``Service``, so
the night sits in the clinic's one price list where the discounts, the payer
rules, the doctor's commission and the tax item code already work. It is read
from the bed and falls back to the unit, because one nursery bay holds a cot,
an incubator and a transport capsule and they are not the same money.

**And the price is the switch.** A clinic that has set no service on any unit
is never charged for anything and never sees a figure, which is how this
feature stays absent for the clinics it is not for — the same rule as a module
that is off.

**Nothing is posted behind anybody's back.** The stay screen *shows* the
uncharged nights and somebody presses; the discharge posts them because a
discharge is already a deliberate act with a form in front of it. There is no
timer that quietly writes money onto a family's account overnight.

**And the bed a night is charged at is the bed at the end of that night.** A
child moved up to intensive care at four in the afternoon spends the night in
intensive care, and that is what the night cost.
"""
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models.bed_charge import BedDayCharge
from app.utils.clock import local_today, to_local, to_utc


def rate_for(bed):
    """The service a night in this bed is charged at, or ``None``.

    The bed first, the unit behind it. ``None`` is a complete answer and the
    common one: a clinic that does not bill by the night has set neither.
    """
    if bed is None:
        return None
    if bed.daily_service is not None:
        return bed.daily_service
    unit = bed.unit
    return unit.daily_service if unit is not None else None


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
    """The clinic dates this stay owes a night for, oldest first.

    ``upto`` is the last date that may be counted; it defaults to the
    clinic's today for an open stay, so an open stay is never billed for a
    night that has not finished. A closed one counts to the day before its
    discharge, with a floor of one.
    """
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


def charged_dates(admission_id):
    rows = (db.session.query(BedDayCharge.on_date)
            .filter(BedDayCharge.admission_id == admission_id).all())
    return {row[0] for row in rows}


def outstanding(admission, upto=None):
    """``[(date, bed, service)]`` — the nights nobody has billed yet.

    Nights with no rate behind them are left out entirely rather than added
    at zero: a clinic that does not bill by the night should see nothing at
    all, not a list of free days.
    """
    if admission is None:
        return []
    done = charged_dates(admission.id)
    out = []
    for day in nights(admission, upto):
        if day in done:
            continue
        bed = bed_on(admission, day)
        service = rate_for(bed)
        if service is None:
            continue
        out.append((day, bed, service))
    return out


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
    """Charge every night this stay owes and has not been charged for.

    Returns ``{"nights", "total", "invoice"}``. Safe to run again — the
    unique index on (stay, night) is what makes it so, rather than a flag
    somebody has to remember to set.
    """
    from app.models.invoice import InvoiceItem

    due = outstanding(admission, upto)
    if not due:
        return {"nights": 0, "total": 0.0, "invoice": None}

    invoice = invoice_for(admission, user)
    total = 0.0
    for day, bed, service in due:
        price = float(service.price or 0)
        item = InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            # The description carries the night and the bed, because the
            # question a family asks of this line is "which night, and why is
            # Tuesday more than Monday".
            description=_line(service, bed, day, lang),
            unit_price=price, quantity=1)
        db.session.add(item)
        db.session.flush()
        db.session.add(BedDayCharge(
            admission_id=admission.id, patient_id=admission.patient_id,
            on_date=day, bed_id=getattr(bed, "id", None),
            service_id=service.id,
            # Snapshotted beside the link, like every printed name here: a
            # price list edited in March must not rewrite February's bill.
            unit_price=price, invoice_item_id=item.id,
            posted_by=getattr(user, "id", None)))
        total += price
    return {"nights": len(due), "total": round(total, 2), "invoice": invoice}


def _line(service, bed, day, lang):
    name = service.display_name(lang) if hasattr(service, "display_name") \
        else service.name
    where = ""
    if bed is not None:
        unit = bed.unit
        where = f" — {unit.name} · {bed.name}" if unit else f" — {bed.name}"
    return f"{name} ({day.isoformat()}){where}"[:200]
