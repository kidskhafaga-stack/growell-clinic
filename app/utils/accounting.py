"""Automatic journal posting (Phase 1 — F2).

Operational events call the ``post_*`` helpers after their own commit; each
builds a balanced JournalEntry from the seeded chart of accounts. Posting
failures are swallowed by the callers (a bookkeeping hiccup must never block
billing a patient) — but entries are simple enough that they don't fail.

Standard entries (per the HIS brainstorm):
* Invoice issued   → Dr 1030 Patients AR      / Cr 4010 Services revenue
* Payment received → Dr 1010 Cash drawer      / Cr 1030 Patients AR
* Refund paid      → Dr 1030 Patients AR      / Cr 1010 Cash drawer
* Expense recorded → Dr 5010 Operating costs  / Cr 1010 Cash drawer
"""
from datetime import date

from app.extensions import db
from app.models.accounting import Account, JournalEntry, JournalLine
from app.models.cash_account import CashAccount
from app.utils.clock import local_today

# (code, name_ar, name_en, type, parent_code)
CHART = [
    ("1000", "الأصول", "Assets", "asset", None),
    ("1010", "الخزنة", "Cash drawer", "asset", "1000"),
    ("1011", "إنستاباي", "InstaPay", "asset", "1000"),
    ("1012", "المحفظة الإلكترونية", "Mobile wallet", "asset", "1000"),
    ("1013", "الفيزا — تحت التحصيل", "Card — under collection", "asset", "1000"),
    ("1020", "البنك", "Bank", "asset", "1000"),
    ("1030", "العملاء — مرضى", "Patients (AR)", "asset", "1000"),
    ("1040", "المخزون", "Inventory", "asset", "1000"),
    ("2000", "الخصوم", "Liabilities", "liability", None),
    ("2010", "الموردون", "Suppliers (AP)", "liability", "2000"),
    ("2020", "ضرائب مستحقة", "Taxes payable", "liability", "2000"),
    ("3000", "حقوق الملكية", "Equity", "equity", None),
    ("3010", "رأس المال / أرباح مرحّلة", "Capital / retained earnings", "equity", "3000"),
    ("4000", "الإيرادات", "Revenue", "revenue", None),
    ("4010", "إيرادات الكشف والخدمات", "Services revenue", "revenue", "4000"),
    ("4020", "إيرادات التطعيمات", "Vaccination revenue", "revenue", "4000"),
    ("5000", "المصروفات", "Expenses", "expense", None),
    ("5010", "مصروفات تشغيل", "Operating expenses", "expense", "5000"),
    ("5020", "تكلفة المبيعات", "Cost of goods sold", "expense", "5000"),
    # Doctor shares are a cost of running the clinic and not an operating
    # expense among the rent and the electricity: it is the largest single
    # line in most clinics and the one an owner asks about by itself.
    ("5030", "أنصبة الأطباء", "Doctor shares", "expense", "5000"),
]


def ensure_seeded():
    """Create any missing core account (idempotent, safe pre-table).

    Tops up rather than bailing out on the first existing row: the chart grows
    — the till accounts were added to it long after the first clinics
    installed — and "some accounts exist, so skip" would leave every one of
    those installs unable to post to the new ones.
    """
    try:
        by_code = {a.code: a for a in Account.query.all()}
        made = 0
        for code, name, name_en, typ, parent in CHART:
            if code in by_code:
                continue
            acc = Account(code=code, name=name, name_en=name_en, type=typ,
                          is_system=True, parent=by_code.get(parent))
            by_code[code] = acc
            db.session.add(acc)
            made += 1
        if made:
            db.session.commit()
        return made > 0
    except Exception:  # noqa: BLE001 - tables not ready yet
        db.session.rollback()
        return False


def _account(code):
    return Account.query.filter_by(code=code).first()


# Where a clinic's own tills are numbered. The seeded chart runs 1010–1040 and
# a clinic adding a drawer must not land on 1030 (patients) or 1040 (stock),
# so its tills start well clear of the block the program reserves for itself.
FIRST_TILL_CODE = 1050


def next_till_code():
    """The next free code for a till the clinic is creating.

    Reads both books before answering. A code free in the chart of accounts
    but already worn by a till would post that till's money into somebody
    else's account, and a code free among the tills but taken in the chart
    cannot be created at all — so a code is free only when neither has it.
    """
    taken = {a.code for a in Account.query.all()}
    taken |= {a.code for a in CashAccount.query.all()}
    code = FIRST_TILL_CODE
    while str(code) in taken:
        code += 1
    return str(code)


def ensure_till_account(till):
    """Give a till its account in the chart of accounts. Returns it.

    **This is what makes a till's money reach the books.** ``post_entry``
    looks its lines up by code and returns None — quietly, by design, so a
    half-installed database does not crash — when a code is not in the chart.
    A till created without this would move money on every screen in the
    treasury and post not one line of it to the ledger: the drawer visibly
    holding cash, the trial balance certain it does not exist, and nothing
    anywhere saying which to believe.

    Idempotent, and it never touches an account that is already there. A
    clinic may have renamed the account the seeded chart gave it, and a
    rename is not a mistake to correct on the next upgrade.
    """
    if till is None or not till.code:
        return None
    existing = _account(till.code)
    if existing is not None:
        return existing
    # The chart is seeded first so the till has a parent to hang under. An
    # account with no parent is not in the tree: it never rolls up into
    # Assets, so the balance sheet omits the till's money and still balances
    # — wrong in the way that is hardest to find. `ensure_seeded` is
    # idempotent and leaves a clinic's own edits alone.
    ensure_seeded()
    account = Account(code=till.code, name=till.name,
                      name_en=till.name_en, type="asset",
                      parent=_account("1000"), is_system=False)
    db.session.add(account)
    db.session.flush()
    return account


def repair_till_accounts():
    """Give a chart account to every till that has none. Returns how many.

    Runs on upgrade, alongside the other repairs, because the rule above
    fixes what happens from now on and does nothing for a till already
    sitting in a clinic's database without an account behind it. Idempotent
    and safe to run again — a till that has one is passed over.
    """
    made = 0
    for till in CashAccount.query.all():
        if till.code and _account(till.code) is None:
            ensure_till_account(till)
            made += 1
    return made


def _je_number():
    prefix = "JE-"
    top = 0
    rows = (JournalEntry.query.filter(JournalEntry.entry_number.like(prefix + "%"))
            .with_entities(JournalEntry.entry_number).all())
    for (num,) in rows:
        tail = num[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:06d}"


def post_entry(source_type, source_id, memo, lines, entry_date=None, user_id=None,
               replace=False):
    """Create a balanced journal entry.

    ``lines``: iterable of (account_code, debit, credit, description).
    Skips silently when accounts aren't seeded; raises ValueError when the
    entry doesn't balance (a programming error worth surfacing in dev).
    Commits on success and returns the entry (or None when skipped).

    ``replace=True``: when the source document was already posted, rebuild the
    existing entry's lines in place (same entry number) instead of skipping —
    used for invoices that grow during the day (one invoice per visit).
    """
    built = []
    for code, debit, credit, desc in lines:
        amount_d = round(float(debit or 0), 2)
        amount_c = round(float(credit or 0), 2)
        if amount_d <= 0 and amount_c <= 0:
            continue
        acc = _account(code)
        if acc is None:
            return None  # chart not seeded — skip quietly
        built.append(JournalLine(account_id=acc.id, debit=amount_d,
                                 credit=amount_c, description=desc))
    if not built:
        return None
    total_d = round(sum(ln.debit for ln in built), 2)
    total_c = round(sum(ln.credit for ln in built), 2)
    if abs(total_d - total_c) > 0.01:
        raise ValueError(f"unbalanced entry: D{total_d} != C{total_c}")

    # Avoid double-posting the same source document. With ``replace`` the
    # existing entry is refreshed (delete-orphan swaps the lines) so the
    # ledger always mirrors the document's current state.
    if source_type and source_id:
        existing = JournalEntry.query.filter_by(
            source_type=source_type, source_id=source_id).first()
        if existing is not None:
            if not replace:
                return None
            existing.lines = built
            existing.memo = memo
            if entry_date:
                existing.entry_date = entry_date
            db.session.commit()
            return existing

    entry = JournalEntry(entry_number=_je_number(),
                         entry_date=entry_date or local_today(),
                         memo=memo, source_type=source_type,
                         source_id=source_id, created_by=user_id)
    entry.lines = built
    db.session.add(entry)
    db.session.commit()
    return entry


def _vaccine_split(invoice):
    """Split the invoice's net between vaccination and other services, using
    each line's service type when known (fallback: everything → services)."""
    vac = 0.0
    for item in invoice.items:
        stype = getattr(getattr(item, "service", None), "service_type", None)
        if stype == "vaccination":
            vac += item.net
    vac = round(min(vac, invoice.total), 2)
    return vac, round(invoice.total - vac, 2)


def post_invoice(invoice, user_id=None):
    """Invoice issued: Dr Patients AR / Cr revenue (split by service type)."""
    if not invoice or invoice.total <= 0:
        return None
    vac, svc = _vaccine_split(invoice)
    lines = [("1030", invoice.total, 0, invoice.invoice_number)]
    if svc > 0:
        lines.append(("4010", 0, svc, invoice.invoice_number))
    if vac > 0:
        lines.append(("4020", 0, vac, invoice.invoice_number))
    return post_entry("invoice", invoice.id,
                      f"فاتورة {invoice.invoice_number}", lines,
                      entry_date=invoice.invoice_date, user_id=user_id,
                      replace=True)


def till_code(movement, fallback="1010"):
    """The ledger account a movement's money sits in.

    Every posting of money in or out goes through here, so "which account?" is
    answered in one place. A row taken before tills existed — or one whose till
    was deleted — falls back to the main drawer, which is where its journal
    entry was already posted; the alternative is a half-posted entry.
    """
    account = getattr(movement, "account", None)
    if account is not None and account.code:
        return account.code
    return fallback


def post_payment(payment, user_id=None):
    """Payment on an invoice: Dr Cash / Cr Patients AR (refund = reversed)."""
    if not payment or (payment.amount or 0) <= 0:
        return None
    number = payment.invoice.invoice_number if payment.invoice else ""
    code = till_code(payment)
    if getattr(payment, "kind", "payment") == "refund":
        lines = [("1030", payment.amount, 0, number),
                 (code, 0, payment.amount, number)]
        memo = f"استرداد — {number}"
    else:
        lines = [(code, payment.amount, 0, number),
                 ("1030", 0, payment.amount, number)]
        memo = f"سداد — {number}"
    return post_entry("payment", payment.id, memo, lines, user_id=user_id)


def post_expense(expense, user_id=None):
    """Expense recorded: Dr operating expenses / Cr cash."""
    if not expense or (expense.amount or 0) <= 0:
        return None
    memo = expense.description or "مصروف"
    lines = [("5010", expense.amount, 0, memo),
             (till_code(expense), 0, expense.amount, memo)]
    return post_entry("expense", expense.id, memo, lines,
                      entry_date=expense.expense_date, user_id=user_id)


def post_doctor_payout(payout, user_id=None):
    """Doctor paid: Dr doctor shares / Cr the till it left.

    Without this the money is gone from the drawer and absent from the income
    statement, so a clinic's profit reads higher than it is by exactly what it
    paid its doctors — which in most clinics is the biggest number on the page.
    """
    if not payout or (payout.amount or 0) <= 0:
        return None
    who = payout.doctor.display_name("ar") if payout.doctor else ""
    memo = f"صرف نصيب طبيب — {who}".strip(" —")
    lines = [("5030", payout.amount, 0, memo),
             (till_code(payout), 0, payout.amount, memo)]
    return post_entry("doctor_payout", payout.id, memo, lines,
                      entry_date=payout.paid_on, user_id=user_id)


def post_claim_payment(claim, user_id=None):
    """Payer settled a claim: Dr cash/bank / Cr services revenue.

    The covered share was billed as a line discount (never revenue, never
    AR), so the payer's money is recognised as revenue when it lands."""
    if claim is None or (claim.paid_amount or 0) <= 0:
        return None
    cash_code = "1010" if (claim.payment_method or "") == "cash" else "1020"
    memo = f"تحصيل مطالبة — {claim.claim_number}"
    lines = [(cash_code, claim.paid_amount, 0, claim.claim_number),
             ("4010", 0, claim.paid_amount, claim.claim_number)]
    return post_entry("claim", claim.id, memo, lines, user_id=user_id)


# ------------------------------------------------ warehouse documents (W3) --
def _doc_value(doc):
    """A store document's cost value: movement lines + linked vaccine batches."""
    from app.models import VaccineInventory

    value = sum(abs(m.qty or 0) * (m.unit_cost or 0) for m in doc.movements)
    for b in VaccineInventory.query.filter_by(document_id=doc.id).all():
        value += (b.qty_received or 0) * (b.unit_cost or 0)
    return round(value, 2)


def post_store_doc(doc, user_id=None):
    """Inventory-side journal for a warehouse document (skipped at value 0):

    * GRN (purchase)   → Dr 1040 المخزون / Cr 2010 الموردون
    * RTN (to supplier)→ Dr 2010 الموردون / Cr 1040 المخزون
    * ISS (consumption)→ Dr 5020 تكلفة المبيعات / Cr 1040 المخزون
    * WST (wastage)    → Dr 5010 مصروفات تشغيل / Cr 1040 المخزون
    Transfers and adjustments move quantity, not money — no entry.
    """
    if doc is None:
        return None
    value = _doc_value(doc)
    if value <= 0:
        return None
    memo_map = {"grn": "إذن إضافة", "return": "مرتجع مورد",
                "issue": "إذن صرف", "waste": "هالك مخزني"}
    memo = f"{memo_map.get(doc.kind, doc.kind)} — {doc.doc_number}"
    if doc.kind == "grn":
        lines = [("1040", value, 0, doc.doc_number),
                 ("2010", 0, value, doc.doc_number)]
    elif doc.kind == "return":
        lines = [("2010", value, 0, doc.doc_number),
                 ("1040", 0, value, doc.doc_number)]
    elif doc.kind == "issue":
        lines = [("5020", value, 0, doc.doc_number),
                 ("1040", 0, value, doc.doc_number)]
    elif doc.kind == "waste":
        lines = [("5010", value, 0, doc.doc_number),
                 ("1040", 0, value, doc.doc_number)]
    else:
        return None
    return post_entry("store_doc", doc.id, memo, lines,
                      entry_date=doc.doc_date, user_id=user_id)


def post_supplier_payment(payment, user_id=None):
    """Paying a supplier: Dr 2010 الموردون / Cr cash|bank. Clears the payable
    the goods-receipt raised."""
    if payment is None or (payment.amount or 0) <= 0:
        return None
    guess = "1020" if (payment.method or "") in ("bank", "transfer") else "1010"
    cash_code = till_code(payment, fallback=guess)
    name = payment.supplier.name if payment.supplier else "مورد"
    memo = f"سداد مورد — {name}"
    lines = [("2010", payment.amount, 0, memo),
             (cash_code, 0, payment.amount, memo)]
    return post_entry("supplier_payment", payment.id, memo, lines,
                      entry_date=payment.paid_at, user_id=user_id)


def post_dose_cogs(pv, user_id=None):
    """COGS for one administered vaccine dose: Dr 5020 / Cr 1040 at the batch
    cost (falling back to the brand's average purchase cost)."""
    if pv is None or getattr(pv, "given_outside", False):
        return None
    cost = None
    if getattr(pv, "batch", None) is not None:
        cost = pv.batch.unit_cost
    if not cost and getattr(pv, "brand", None) is not None:
        cost = getattr(pv.brand, "purchase_price", None)
    if not cost or cost <= 0:
        return None
    name = pv.brand.name if pv.brand else "جرعة تطعيم"
    memo = f"تكلفة جرعة — {name} #{pv.dose_number}"
    lines = [("5020", cost, 0, memo), ("1040", 0, cost, memo)]
    return post_entry("vaccine_dose", pv.id, memo, lines, user_id=user_id)
