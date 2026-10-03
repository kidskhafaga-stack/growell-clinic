"""What a contract takes back from its cover: the family's share and the
payer's ceilings.

Asked as *«حسب كل عقد ايه الى داخل على العقد وايه الى المريض بيحاسب
عنده»*. The rules (`PayerContract.rule_for`) say what share of each line the
payer covers. An agreement then says more, per bill and per year:

1. **Room** — the payer pays a ward bed up to so much a night; a private
   room is the difference, the family's.
2. **Deductible** — the first so much of what would be covered each year is
   the family's.
3. **Copay** — a fixed sum the family pays on each bill.
4. **Ceiling per bill** — past it, the family's.
5. **Ceiling per year** — the most the payer pays for one member; past it,
   the family's.

In that order: what the family owes is taken first, and the ceilings then
cut what is left for the payer. Each cut comes off a line's cover, which is
stored as that line's discount, so the family's balance and the claim move
together; the line keeps the reason and the amount (``cover_note``,
``cover_cut``) so the bill can say why.

**Every figure is the hospital's own, and empty means no limit.** A contract
with no terms reads exactly as it did, and nothing here runs a query for it.

**Run again, it gives the same answer.** A stay's bill is charged night by
night and covered each time; the lines this module cut are recomputed from
their full cover, and a year's deductible and ceiling count the member's
*other* bills only — so the fifth night does not take the deductible a
fifth time.
"""
from app.extensions import db

NOTES = ("not_covered", "excluded", "deductible", "copay", "room_ceiling",
         "over_ceiling")


def has_terms(contract):
    return bool(contract is not None and (
        contract.terms or contract.deductible_year or contract.ceiling_year))


def _cut(item, amount, note):
    """Take ``amount`` off this line's cover. Returns what was taken."""
    amount = round(min(max(amount, 0.0), item.payer_amount or 0.0), 2)
    if amount <= 0:
        return 0.0
    item.payer_amount = round((item.payer_amount or 0) - amount, 2)
    item.discount_value = item.payer_amount
    item.discount_is_percent = False
    item.cover_cut = round((item.cover_cut or 0) + amount, 2)
    item.cover_note = note
    return amount


def _take(lines, amount, note):
    """Take ``amount`` off the cover of ``lines``, in their order."""
    left = round(amount, 2)
    for item in lines:
        if left <= 0:
            break
        left = round(left - _cut(item, left, note), 2)
    return round(amount - left, 2)


def _others(invoice, contract):
    """The member's other bills with this payer in the contract's year."""
    from app.models import Invoice

    start, end = contract.year_window(invoice.invoice_date)
    query = Invoice.query.filter(Invoice.patient_id == invoice.patient_id,
                                 Invoice.payer_id == invoice.payer_id,
                                 Invoice.invoice_date >= start,
                                 Invoice.invoice_date <= end,
                                 Invoice.status != "refunded")
    if invoice.id is not None:
        query = query.filter(Invoice.id != invoice.id)
    return query.all()


def _deductible_used(others):
    return round(sum(inv.deductible_taken or 0 for inv in others), 2)


def _nights(lines):
    """``{item_id: nights}`` for the lines that are a bed by the night."""
    from app.models.bed_charge import BedCharge

    ids = [i.id for i in lines if i.id is not None]
    if not ids:
        return {}
    out = {}
    for charge in BedCharge.query.filter(BedCharge.invoice_item_id.in_(ids)).all():
        if charge.basis == "hour":
            continue
        out[charge.invoice_item_id] = out.get(charge.invoice_item_id, 0) + (charge.quantity or 1)
    return out


def apply(invoice, contract, setting):
    """Cut the cover on ``invoice`` by ``contract``'s terms for ``setting``.
    Returns ``{note: amount}`` of what was taken."""
    taken = {}
    # Kept on the bill rather than read back off its lines: one line can
    # carry the deductible and the copay both, and its note says only one.
    invoice.deductible_taken = None
    if not has_terms(contract):
        return taken
    lines = [i for i in invoice.items if (i.payer_amount or 0) > 0]
    if not lines:
        return taken
    term = contract.term_for(setting)

    def note(key, amount):
        if amount > 0:
            taken[key] = round(taken.get(key, 0) + amount, 2)

    # 1. The room: the payer pays a ward bed up to so much a night.
    if term is not None and term.night_ceiling:
        by_line = _nights(lines)
        for item in lines:
            nights = by_line.get(item.id) if item.id else None
            if not nights:
                continue
            cap = round(term.night_ceiling * nights, 2)
            note("room_ceiling", _cut(item, (item.payer_amount or 0) - cap, "room_ceiling"))

    others = None
    # 2. The year's deductible — what the member has not yet carried of it.
    if contract.deductible_year:
        others = _others(invoice, contract)
        left = round(contract.deductible_year - _deductible_used(others), 2)
        if left > 0:
            got = _take(lines, left, "deductible")
            note("deductible", got)
            invoice.deductible_taken = got or None

    # 3. The fixed share on each bill.
    if term is not None and term.copay_amount:
        note("copay", _take(lines, term.copay_amount, "copay"))

    # 4. The ceiling per bill — the later charges are the ones past it.
    paid = round(sum(i.payer_amount or 0 for i in lines), 2)
    if term is not None and term.ceiling_case and paid > term.ceiling_case:
        note("over_ceiling", _take(list(reversed(lines)), paid - term.ceiling_case,
                                   "over_ceiling"))

    # 5. The ceiling per year, across the member's other bills.
    if contract.ceiling_year:
        if others is None:
            others = _others(invoice, contract)
        used = round(sum(inv.payer_total for inv in others), 2)
        paid = round(sum(i.payer_amount or 0 for i in lines), 2)
        over = round(used + paid - contract.ceiling_year, 2)
        if over > 0:
            note("over_ceiling", _take(list(reversed(lines)), over, "over_ceiling"))
    db.session.flush()
    return taken
