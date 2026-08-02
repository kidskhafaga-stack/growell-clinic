"""What can be sold to this child today, and which dose it would be.

The clinic's own words for what was missing:

> "There should be a vaccination service and a service added with it called the
> vaccination fee. The vaccination service brings up the available vaccines,
> and you pick the trade name, and pick which dose — and if they have had a
> dose with me before, it tells you the doses **after** that, once you pick the
> patient. Even if they are coming for two vaccines."

The billing side already handled the other direction: a doctor gave a dose and
the cashier swept it up afterwards. There was no way to sell one *forward* —
the family paying at reception before the nurse gives it — which is how a
vaccination visit actually runs. So the only path to money was "give it first,
find it on the bill later", and anything the family declined after paying was a
correction rather than a choice.

Three things this has to get right, and each is a way of being quietly wrong:

**"The doses after that."** Offering dose 1 of a course the child is three
doses into is the mistake the request is about — and it is not a display
problem, because whichever dose is on the invoice is the one the record will
say was given. The next undone dose is preselected and the ones already had
are marked, not hidden: "the first was at a government unit" is a real thing
somebody needs to be able to say.

**Stock is the difference between selling and promising.** A vaccine with an
empty fridge shelf is not on the list, because taking money for it is taking
money for a phone call tomorrow.

**And the fee comes once**, however many vaccines are being given. Two vaccines
in one visit is ordinary, and charging the administration fee twice for one
administration is the kind of overcharge nobody spots until a parent does.
"""
from app.models import PatientVaccine, Vaccine
from app.utils.dose_labels import dose_choices


def _given_numbers(patient_id, vaccine_id):
    return {pv.dose_number for pv in PatientVaccine.query.filter_by(
        patient_id=patient_id, vaccine_id=vaccine_id, event_type="given").all()}


def _brand_offer(patient_id, vaccine, brand, lang):
    """One brand as a thing that can be put on an invoice, or None."""
    given = _given_numbers(patient_id, vaccine.id)
    doses = dose_choices(vaccine, brand, given, lang)
    remaining = [d for d in doses if not d["given"]]
    # Seasonal courses come round again every year, so "finished" never applies
    # to them — last year's dose does not mean this year's is unavailable.
    if not remaining and not vaccine.is_seasonal:
        return None
    if vaccine.is_seasonal and not remaining:
        nxt = max((d["number"] for d in doses), default=0) + 1
        remaining = [{"number": nxt, "label": f"#{nxt}", "age_months": None,
                      "given": False, "booster": False}]
    return {
        "brand": brand,
        "id": brand.id,
        "name": brand.display_name(lang),
        "price": brand.price or 0,
        "stock": brand.stock,
        "doses": doses,
        "remaining": remaining,
        # The one the screen should land on. Picking dose 1 for a child who is
        # three doses in is exactly the mistake this exists to prevent.
        "next": remaining[0]["number"] if remaining else None,
        "next_label": remaining[0]["label"] if remaining else None,
    }


def sellable(patient, lang="ar"):
    """Vaccines this child can be given and charged for, in schedule order.

    Government (mandatory) vaccines are excluded: they are free and never come
    off the clinic's own fridge, so putting them on a till screen invites
    somebody to charge for one.
    """
    if patient is None:
        return []
    out = []
    for vaccine in (Vaccine.query
                    .filter(Vaccine.is_mandatory.is_(False))
                    .order_by(Vaccine.sort_order, Vaccine.id).all()):
        if getattr(vaccine, "is_discontinued", False):
            continue
        brands = []
        for brand in vaccine.brands:
            if getattr(brand, "is_discontinued", False):
                continue
            # No stock, no sale. Taking the money for an empty shelf is taking
            # the money for a phone call tomorrow.
            if (brand.stock or 0) <= 0:
                continue
            offer = _brand_offer(patient.id, vaccine, brand, lang)
            if offer is not None:
                brands.append(offer)
        if brands:
            out.append({
                "vaccine": vaccine,
                "id": vaccine.id,
                "name": vaccine.display_name(lang),
                "brands": brands,
            })
    return out


def as_json(offers):
    """The offers with no model objects in them, for the till screen's script.

    Kept separate from :func:`sellable` rather than making that return plain
    data: the server-side callers want the brand itself to price and charge it,
    and a shape that serves both ends up carrying an id the template has to
    look back up.
    """
    return [{
        "id": offer["id"],
        "name": offer["name"],
        "brands": [{
            "id": b["id"],
            "name": b["name"],
            "price": b["price"],
            "stock": b["stock"],
            "next": b["next"],
            "next_label": b["next_label"],
            "doses": [{"number": d["number"], "label": d["label"],
                       "given": bool(d["given"])} for d in b["doses"]],
        } for b in offer["brands"]],
    } for offer in offers]


def fee_already_on(invoice):
    """Is the administration fee already on this invoice?

    Two vaccines in one visit is ordinary practice, and charging the fee twice
    for one administration is an overcharge nobody notices until a parent
    counts it.
    """
    if invoice is None:
        return False
    return any(it.service and it.service.category == "vaccination_fee"
               for it in invoice.items)


def sale_lines(patient, picks, lang="ar", doctor=None, invoice=None,
               fee_service=None):
    """Invoice lines for the vaccines picked on the till screen.

    ``picks`` is ``[{"brand_id": int, "dose_number": int}]`` — several, because
    a child coming for two vaccines is one visit and one bill.

    The vial and the fee are **two lines with two identities**: the vial is
    identified by its brand and carries no invoice commission (the doctor's
    share of a vial is the brand's ``doctor_fee``, credited on the dose), and
    the fee is the vaccination-fee service. They shared one service id once,
    and a discount aimed at the fee came off the vial with it.
    """
    lines = []
    fee_added = fee_already_on(invoice)
    for pick in picks or []:
        brand = pick.get("brand")
        if brand is None:
            continue
        vaccine = brand.vaccine
        name = vaccine.display_name(lang) if vaccine else ""
        lines.append({
            "service_id": "",
            "description": f"{name} — {brand.display_name(lang)}",
            "unit_price": brand.price or 0,
            "quantity": 1,
            "no_commission": "1",
            "brand_id": brand.id,
            "dose_number": pick.get("dose_number"),
        })
        if not fee_added and fee_service is not None:
            fee = fee_service.price_for(doctor)
            # A zero fee is a decision, not an absence: clinics that give the
            # vaccine at cost still want the line on the bill so the family can
            # see it was charged at nothing. It is added whenever the service
            # exists, and priced at whatever the clinic set — including zero.
            lines.append({
                "service_id": str(fee_service.id),
                "description": fee_service.display_name(lang),
                "unit_price": fee if fee is not None else 0,
                "quantity": 1,
            })
            fee_added = True
    return lines


def claim_prepaid(pv):
    """Link a dose being recorded to the invoice line that already paid for it.

    This is the half that makes selling forward safe. Without it the flow
    double-charges: reception sells dose 2, the nurse records it, and
    ``_uncharged_vaccines`` — which looks for doses with no ``invoice_id`` —
    finds it and puts it on the next bill. The family pays twice for one
    vaccine, and the second charge looks exactly like a normal one.

    Matched on **brand and dose number**, which is what was chosen at the desk.
    A line whose dose number was never recorded (a sale made before that column
    existed, or a dose billed the old way round) still matches on the brand
    alone, because refusing to match there would reintroduce the double charge
    for exactly the clinics that upgraded mid-course.

    A line is only claimed once: two doses of the same brand cannot both point
    at one payment, or selling one and giving two would go unnoticed.

    Returns the :class:`Invoice` it was matched to, or ``None``.
    """
    from app.models import Invoice, InvoiceItem, PatientVaccine

    if pv is None or pv.invoice_id or not pv.brand_id:
        return None
    rows = (InvoiceItem.query
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .filter(Invoice.patient_id == pv.patient_id,
                    InvoiceItem.vaccine_brand_id == pv.brand_id)
            .order_by(InvoiceItem.id).all())
    if not rows:
        return None

    # Which invoices already have a dose of this brand hanging off them.
    taken = {}
    for other in PatientVaccine.query.filter(
            PatientVaccine.patient_id == pv.patient_id,
            PatientVaccine.brand_id == pv.brand_id,
            PatientVaccine.invoice_id.isnot(None)).all():
        taken[other.invoice_id] = taken.get(other.invoice_id, 0) + 1

    exact = [r for r in rows if r.vaccine_dose_number == pv.dose_number]
    loose = [r for r in rows if r.vaccine_dose_number is None]
    for candidate in exact + loose:
        used = taken.get(candidate.invoice_id, 0)
        here = sum(1 for r in rows if r.invoice_id == candidate.invoice_id)
        if used >= here:
            continue          # every line on that invoice is already spoken for
        pv.invoice_id = candidate.invoice_id
        return candidate.invoice
    return None
