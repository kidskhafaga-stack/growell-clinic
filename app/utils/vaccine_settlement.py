"""Settling a paid vaccine against what the doctor actually did.

Reception collects the vaccine when the visit is booked/checked out, but the
decision is taken later, inside the room:

* the child is feverish and the doctor **refuses** the dose → the vaccine's
  price has to go back to the parent;
* the doctor **swaps** the brand (RotaRix → RotaTeq) → only the *difference*
  moves, in either direction.

Both cases used to leave an invoice describing something that never happened.
Now every vaccine line carries the brand it billed (``InvoiceItem.
vaccine_brand_id``); when the clinical record for the day disagrees with it, a
``VaccineSettlement`` is raised and shows up on the cashier screen with the
exact amount to hand back or collect. Applying it rewrites the invoice line to
reality — the refund/collection then follows from the invoice balance like any
other, so nothing here invents its own money path.
"""
from datetime import date, datetime

from app.extensions import db
from app.models import (Invoice, PatientVaccine, VaccineBrand,
                        VaccineSettlement)
from app.utils.clock import local_today


def _not_given_label(lang):
    """"not given" for the corrected invoice line. Falls back to a literal when
    called outside a request (the settlement engine also runs from the CLI)."""
    try:
        from app.i18n import t
        return t("vaccinations.not_given")
    except Exception:
        return "not given" if lang == "en" else "لم يُعطَ"


def _brand_price(brand):
    return round((brand.price or 0) if brand is not None else 0, 2)


def _todays_vaccine_items(patient_id, on_date):
    """Invoice lines that charged a vaccine product on ``on_date``."""
    invoices = (Invoice.query
                .filter(Invoice.patient_id == patient_id,
                        Invoice.invoice_date == on_date).all())
    return [(inv, item) for inv in invoices for item in inv.items
            if item.vaccine_brand_id]


def _dose_events(patient_id, on_date):
    """The day's dose records, newest first (a later record supersedes)."""
    return (PatientVaccine.query
            .filter(PatientVaccine.patient_id == patient_id,
                    PatientVaccine.given_date == on_date,
                    PatientVaccine.event_type.in_(["given", "refused", "delayed"]))
            .order_by(PatientVaccine.id.desc()).all())


def _outcome_for(billed_brand, events):
    """What actually happened to the vaccine this line billed.

    Returns ``(reason, actual_brand, dose)``: ``(None, ...)`` when the record
    matches the bill or the doctor hasn't decided yet — nothing to settle.
    """
    vaccine_id = billed_brand.vaccine_id
    same_vaccine = [e for e in events if e.vaccine_id == vaccine_id]
    if not same_vaccine:
        return None, None, None
    given = next((e for e in same_vaccine if e.event_type == "given"), None)
    if given is not None:
        if given.brand_id == billed_brand.id:
            return None, None, given          # billed exactly what was given
        return "swapped", given.brand, given
    # No dose given, but the doctor documented a refusal/delay for it.
    return "refused", None, same_vaccine[0]


def sync_for_patient(patient_id, on_date=None):
    """Re-derive the day's pending settlements for one patient.

    Idempotent: called after every dose record, it creates what is now owed,
    updates an amount that changed, and cancels a pending settlement the doctor
    has since undone (e.g. the refused dose was given after all).
    """
    on_date = on_date or local_today()
    events = _dose_events(patient_id, on_date)
    pending = {s.item_id: s for s in VaccineSettlement.query.filter_by(
        patient_id=patient_id, status="pending").all()}
    touched = set()
    out = []
    for invoice, item in _todays_vaccine_items(patient_id, on_date):
        billed = db.session.get(VaccineBrand, item.vaccine_brand_id)
        if billed is None:
            continue
        reason, actual, dose = _outcome_for(billed, events)
        row = pending.get(item.id)
        if reason is None:
            if row is not None:                # the disagreement went away
                row.status = "cancelled"
            continue
        # + collect the difference, − refund it. A refusal refunds the line as
        # billed (its discount included, so a discounted dose refunds what was
        # actually paid for it).
        if reason == "refused":
            amount = -item.net
        else:
            amount = round(_brand_price(actual) - item.net, 2)
        if row is None:
            row = VaccineSettlement(
                patient_id=patient_id, invoice_id=invoice.id, item_id=item.id,
                billed_brand_id=billed.id, reason=reason)
            db.session.add(row)
        row.actual_brand_id = actual.id if actual is not None else None
        row.dose_id = dose.id if dose is not None else None
        row.reason = reason
        row.amount = amount
        touched.add(item.id)
        out.append(row)
    # A line that no longer exists (invoice edited) can't be settled.
    for item_id, row in pending.items():
        if item_id not in touched and row.item is None:
            row.status = "cancelled"
    return out


def apply_settlement(settlement, lang="ar", user_id=None):
    """Rewrite the invoice line to what actually happened.

    Refused → the line stays for the audit trail but drops to zero; swapped →
    the line becomes the brand that was really given, at its price. The money
    then falls out of the invoice balance: negative = refund the parent,
    positive = collect the difference.
    """
    item, invoice = settlement.item, settlement.invoice
    if settlement.status != "pending" or item is None or invoice is None:
        return None
    if settlement.reason == "refused":
        item.unit_price = 0
        item.quantity = 1
        item.discount_value = 0
        item.discount_is_percent = False
        item.commission_amount = 0
        item.vaccine_brand_id = None
        label = _not_given_label(lang)
        if label not in (item.description or ""):
            item.description = f"{item.description} — {label}"
    else:
        actual = settlement.actual_brand
        item.unit_price = _brand_price(actual)
        item.discount_value = 0
        item.discount_is_percent = False
        item.commission_amount = 0
        item.vaccine_brand_id = actual.id if actual else None
        if actual is not None:
            name = (actual.vaccine.display_name(lang) if actual.vaccine
                    else actual.display_name(lang))
            item.description = f"{name} — {actual.display_name(lang)}"
        # The dose that was really given is billed on this invoice now, so the
        # cashier's "uncollected vaccines" list stops chasing it.
        if settlement.dose is not None:
            settlement.dose.invoice_id = invoice.id
    invoice.recalc_status()
    settlement.status = "done"
    settlement.settled_at = datetime.utcnow()
    settlement.settled_by = user_id
    return invoice


def pending_settlements(limit=50):
    """Open settlements for the cashier screen, newest first."""
    return (VaccineSettlement.query.filter_by(status="pending")
            .order_by(VaccineSettlement.id.desc()).limit(limit).all())
