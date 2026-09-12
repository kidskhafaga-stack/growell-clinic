"""Nursing and medical care on the bill — both ways a hospital charges it.

The question was asked twice. First without an answer:

> «نسبة تقريباً من إجمالي الفاتورة بتتحسب الرعاية الطبية والتمريضية، عند
> إنهاء ولا على مستوى الليلة؟ مش عارف الصراحة»

and then, after both of us went and looked, with one:

> «هل ينفع نعملها تستوعب الاثنين حسب نظام المستشفى، علشان الآراء متباينة —
> فى ناس بتحسبها كده وفى ناس بتحسبها كده؟»

They are, and it does. Some hospitals put a daily nursing rate on the bill,
some add a percentage at the end, and a good many do both. **So the program
holds a rule and the hospital says which shape it is.** Picking one and
calling it standard would have been this program deciding a commercial policy
it has no business deciding — the same rule that stops it inventing a clinical
number.

Four things this has to get right, and each is a bill somebody argues with:

**The line is recomputed, not accumulated.** Every other charge here is
written once and stands. This one is a function of the rest of the bill, so a
stay posted again on its fifth night must *correct* its line to five days —
not add a second line of four. That is the whole reason
``InvoiceItem.care_charge_id`` exists.

**A percentage is never levied on a care charge.** Not on itself, and not on
the other one. Two of these on a bill each taking a cut of the other is a
number nobody can check and nobody meant.

**Which parts the percentage is levied on is the hospital's to say.** The
Egyptian practice is a percentage of the total *excluding medicines and
stamps*, and naming sections is what makes such a charge definable at all —
and checkable by a family afterwards. It is also why the bill-section axis was
built open: nothing reads a section by name, so «مستلزمات غرفة العمليات»
works the minute somebody types it.

**And a clinic that defines none has nothing happen.** No rules, no lines, no
change to a single bill — which is the promise made to every clinic already
running.
"""
from app.extensions import db
from app.models import CareCharge, InvoiceItem
from app.utils import invoice_totals


def rules_for(invoice):
    """The care rules that apply to this bill, in the clinic's own order."""
    if invoice is None:
        return []
    rows = (CareCharge.query
            .order_by(CareCharge.sort_order, CareCharge.id).all())
    return [r for r in rows if r.applies_to(invoice)]


def _base_for(invoice, rule):
    """What a percentage is levied on: the lines it names, and no care lines.

    Reads each line's **net** — after its own discount — because that is what
    the bill comes to, and a percentage of a number the family never sees is a
    percentage of nothing they can check.
    """
    wanted = rule.section_keys
    total = 0.0
    for item in invoice.items:
        # Never on another care charge, whatever sections were named. Two
        # rules each taking a cut of the other is the arithmetic nobody meant.
        if item.care_charge_id is not None:
            continue
        if wanted and invoice_totals._section_of(item) not in wanted:
            continue
        total += item.net
    return round(total, 2)


def _days_of(invoice, admission=None):
    """How many days a per-day charge counts.

    **The nights the bill already charged**, not a second count of the stay:
    if the bed says four nights, the nursing that went with them is four —
    and two counters of the same thing drift apart the first time anybody
    corrects one of them.

    Falls back to the stay's own nights where no bed line exists (a clinic
    that does not bill by the night still has nurses), and to one day for a
    bill with neither, because a care charge on a bill is a care charge for
    at least the day it was raised.
    """
    from app.models.service import Service

    nights = 0
    for item in invoice.items:
        if item.care_charge_id is not None or not item.service_id:
            continue
        service = item.service or db.session.get(Service, item.service_id)
        if service is not None and service.section_key() == "accommodation":
            nights += max(1, int(item.quantity or 1))
    if nights:
        return nights
    if admission is not None:
        from app.utils import bed_billing

        billable = bed_billing.nights(admission)
        if billable:
            return len(billable)
    return 1


def due(invoice, admission=None):
    """What each rule works out to on this bill, without writing anything.

    Returns ``[{rule, quantity, unit_price, amount, basis}]`` — the shape a
    screen can show before anybody presses anything, which is the only way a
    percentage charge is ever checkable.
    """
    out = []
    for rule in rules_for(invoice):
        service = rule.service
        if service is None:
            continue            # a rule with no service is not a charge
        if rule.basis == "per_day":
            quantity = _days_of(invoice, admission)
            unit = round(rule.amount or 0, 2)
            amount = round(unit * quantity, 2)
        else:
            quantity = 1
            base = _base_for(invoice, rule)
            amount = round(base * (rule.amount or 0) / 100.0, 2)
            unit = amount
        if amount <= 0:
            continue            # nothing to charge is nothing to write
        out.append({"rule": rule, "quantity": quantity, "unit_price": unit,
                    "amount": amount, "basis": rule.basis,
                    "base": (_base_for(invoice, rule)
                             if rule.basis == "percent" else None)})
    return out


def _describe(entry, lang="ar"):
    rule = entry["rule"]
    name = rule.display_name(lang)
    if entry["basis"] == "percent":
        pct = rule.amount or 0
        pct = int(pct) if float(pct).is_integer() else pct
        # The percentage and what it was taken of, on the line itself: a
        # family asking "why 840" gets the answer off the bill rather than off
        # somebody's calculator.
        if lang == "en":
            return f"{name} — {pct}% of {entry['base']:.2f}"[:200]
        return f"{name} — {pct}٪ من {entry['base']:.2f}"[:200]
    return name[:200]


def apply(invoice, admission=None, lang="ar"):
    """Put the care charges on the bill — correcting, never doubling.

    Returns how many lines it wrote or changed. Safe to call on every posting,
    which is what makes it usable at all: a long stay is posted again every
    day, and an accumulating charge would bill the fourth night's nursing four
    times by the fourth night.

    A rule that no longer applies — switched off, or its number set to zero —
    has its line **removed** rather than left standing at yesterday's figure.
    A derived line that stops being derived from anything is just a charge
    nobody can account for.
    """
    if invoice is None:
        return 0

    entries = {e["rule"].id: e for e in due(invoice, admission)}
    existing = {i.care_charge_id: i for i in invoice.items
                if i.care_charge_id is not None}
    touched = 0

    for rule_id, item in list(existing.items()):
        if rule_id not in entries:
            invoice.items.remove(item)
            db.session.delete(item)
            touched += 1

    for rule_id, entry in entries.items():
        rule = entry["rule"]
        item = existing.get(rule_id)
        if item is None:
            item = InvoiceItem(service_id=rule.service_id,
                               care_charge_id=rule.id)
            invoice.items.append(item)
        item.description = _describe(entry, lang)
        item.unit_price = entry["unit_price"]
        item.quantity = entry["quantity"]
        # **No doctor's share on a care charge.** It is the hospital's own
        # fee for its nurses and its supervision — nobody's percentage rides
        # on it, the same rule a box off the pharmacy shelf follows.
        item.commission_amount = 0
        item.doctor_id = None
        touched += 1

    if touched:
        db.session.flush()
    return touched
