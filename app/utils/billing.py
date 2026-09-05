"""The one door every invoice goes through — whoever raised it.

**Why this file exists.** Pricing an invoice in this program means four
things: the clinic's cash price list, the payer's contract tariff and cover
split, the named discounts, and a line in the ledger. All four lived as
private helpers inside ``blueprints/finance/routes.py``, which was fine while
the cashier's screen was the only thing that ever made an invoice.

Then the wards started making them. ``bed_billing`` raised a bill for a stay
from outside that file and therefore missed every one of the four: a child
with an insurance card was billed the cash rate for eleven nights, nothing
became claimable, the family's own discount never reached the bed lines, and
the hospital's largest single revenue line never reached the P&L. Reported in
one sentence — *"والجزء المحاسبي والمالي ماظبط؟"* — and it was not.

So the parts that are not about a screen live here, and the screen keeps a
thin wrapper. **Nothing in this file talks to a person**: the two places that
used to raise a flash take a ``warn`` callback instead, because a bed charge
is posted from a route with no cashier standing at it, and a `flash` outside a
request context is a crash rather than a message.

**Behaviour is unchanged, deliberately.** This was a move, not a rewrite: the
same repricing, the same skip rules, the same "one discount per line, never
stacked". The commission arithmetic in particular is left exactly as it was —
a vaccine product line carries no invoice commission because the doctor's
share of a vaccine is the brand's ``doctor_fee``, and a tidy-looking
"recompute every line" here would have quietly paid it twice.
"""
from app.extensions import db


def apply_cash_prices(invoice):
    """Reprice the lines from the clinic's cash price list (التسعيرة النقدية).

    The cash agreement needs no membership card — it is what the walk-in
    patient pays — so it is applied to every invoice with no payer. Lines the
    user priced by hand (a manual discount) are left alone.
    """
    from app.utils.pricing import cash_tariff

    for item in invoice.items:
        if not item.service_id or (item.discount_value or 0) > 0:
            continue
        price = cash_tariff(item.service, invoice.invoice_date)
        if price is None or price == item.unit_price:
            continue
        item.unit_price = price
        if item.service is not None:
            # Against the line's own doctor when it has one. A theatre line on
            # a stay's bill is owed to the surgeon, and repricing it from the
            # cash list used to hand it back to the admitting doctor's rate —
            # a number that changed for no reason anybody could point at.
            item.commission_amount = item.service.doctor_share(
                item.net, item.doctor or invoice.doctor)


def apply_coverage(invoice, patient, warn=None, then=None):
    """Auto-apply a member's per-service coverage to the invoice lines.

    For each covered line the entity's share becomes the line discount (so the
    patient pays the rest and the entity share is claimable). Uncovered
    services are left untouched (patient pays full — option ب). An expired card
    is not applied automatically; the caller is warned instead.

    ``warn`` is called with a translation key when there is something a person
    ought to be told; ``then`` is called with ``(invoice, patient)`` once the
    coverage is settled, and is where the screen applies its named discounts.
    Both default to doing nothing, which is what a ward round needs: it posts
    a bed charge with nobody standing in front of the screen.
    """
    warn = warn or (lambda key: None)
    coverage = patient.active_coverage if patient else None
    # If the card exists but is expired/inactive, warn and skip auto-apply.
    if coverage is None:
        expired = [c for c in getattr(patient, "coverages", []) if not c.is_valid]
        if expired:
            warn("coverage.expired_warn")
        # No payer → the clinic's own cash price list applies, automatically.
        # It is not a third party that pays, so no payer is stamped on the
        # invoice and nothing becomes claimable — it only sets the price.
        apply_cash_prices(invoice)
        if then is not None:
            then(invoice, patient)
        return

    payer = coverage.payer
    invoice.payer_id = payer.id
    invoice.coverage_card = coverage.membership_number
    invoice.coverage_expiry = coverage.expiry_date

    # If the entity works by contracts, one must be in force on the invoice date.
    if payer.contracts and payer.active_contract(invoice.invoice_date) is None:
        warn("contracts.none_active_warn")
        return

    for item in invoice.items:
        if not item.service_id or (item.discount_value or 0) > 0:
            continue  # keep manual discounts; skip free-text lines
        # Contract tariff (سعر تعاقدي): members are billed at the contract's
        # negotiated price for the service, then coverage splits it.
        tariff = payer.tariff(item.service, invoice.invoice_date)
        if tariff is not None:
            item.unit_price = tariff
        covered = payer.covers(item.service, item.gross, invoice.invoice_date)
        if covered > 0:
            item.discount_value = covered
            item.discount_is_percent = False
            if item.service is not None:
                item.commission_amount = item.service.doctor_share(
                    item.net, invoice.doctor)

    # A club whose agreement is "members pay 15% less" carries no price list,
    # so nothing above touched the invoice — its member discount lands there.
    if then is not None:
        then(invoice, patient)


def post_to_ledger(kind, obj, user_id=None):
    """Best-effort automatic journal posting.

    A bookkeeping hiccup must never block billing, so every failure is
    swallowed after a rollback — the invoice and the money it took are the
    facts, and a journal entry that could not be written is a report to fix
    later rather than a payment to refuse now.

    **Called from the wards as well as from the till.** Before this moved, the
    only caller was the checkout screen, so a stay billed on the ward and paid
    the next morning never reached the ledger at all: the revenue report saw it
    (it reads invoices) and the profit-and-loss did not (it reads the journal),
    and the two disagreed by the largest number in the hospital.
    """
    try:
        from app.utils import accounting as acct

        if kind == "invoice":
            acct.post_invoice(obj, user_id=user_id)
            for payment in obj.payments:
                acct.post_payment(payment, user_id=user_id)
            # COGS for consumables issued with this invoice (W3).
            issued = getattr(obj, "_iss_doc", None)
            if issued is not None:
                acct.post_store_doc(issued, user_id=user_id)
        elif kind == "payment":
            acct.post_payment(obj, user_id=user_id)
        elif kind == "expense":
            acct.post_expense(obj, user_id=user_id)
    except Exception:  # noqa: BLE001
        db.session.rollback()


def stay_invoice(patient_id):
    """An unsettled invoice raised for a stay this patient is still on.

    **The reason the cashier could not find a bed bill.** The till looks for
    "today's invoice for this patient" — right for an outpatient, who arrives
    and pays on one date. A stay runs across days: the nights are charged on
    the ward on Tuesday and the family pays at the desk on Thursday, and the
    date rule opened a *second* invoice and left the first one hanging. The
    same shape as the appointment bug fixed in `invoices.appointment_id`: the
    desk was matching by date because nothing recorded what the bill was for.

    Only an invoice with money still owed on it is offered, so a stay that was
    settled at discharge does not reappear when the child comes back for a
    follow-up.
    """
    from app.models.admission import Admission
    from app.models.invoice import Invoice

    rows = (Invoice.query
            .join(Admission, Invoice.admission_id == Admission.id)
            .filter(Invoice.patient_id == patient_id,
                    Invoice.status != "refunded")
            .order_by(Invoice.id.desc()).all())
    for invoice in rows:
        if round(invoice.total - invoice.paid, 2) > 0:
            return invoice
    return None
