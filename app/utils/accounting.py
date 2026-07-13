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

# (code, name_ar, name_en, type, parent_code)
CHART = [
    ("1000", "الأصول", "Assets", "asset", None),
    ("1010", "الخزنة", "Cash drawer", "asset", "1000"),
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
]


def ensure_seeded():
    """Create the core chart of accounts once (idempotent, safe pre-table)."""
    try:
        if Account.query.first() is not None:
            return False
        by_code = {}
        for code, name, name_en, typ, parent in CHART:
            acc = Account(code=code, name=name, name_en=name_en, type=typ,
                          is_system=True,
                          parent=by_code.get(parent))
            by_code[code] = acc
            db.session.add(acc)
        db.session.commit()
        return True
    except Exception:  # noqa: BLE001 - tables not ready yet
        db.session.rollback()
        return False


def _account(code):
    return Account.query.filter_by(code=code).first()


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


def post_entry(source_type, source_id, memo, lines, entry_date=None, user_id=None):
    """Create a balanced journal entry.

    ``lines``: iterable of (account_code, debit, credit, description).
    Skips silently when accounts aren't seeded; raises ValueError when the
    entry doesn't balance (a programming error worth surfacing in dev).
    Commits on success and returns the entry (or None when skipped).
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

    # Avoid double-posting the same source document.
    if source_type and source_id and JournalEntry.query.filter_by(
            source_type=source_type, source_id=source_id).first() is not None:
        return None

    entry = JournalEntry(entry_number=_je_number(),
                         entry_date=entry_date or date.today(),
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
                      entry_date=invoice.invoice_date, user_id=user_id)


def post_payment(payment, user_id=None):
    """Payment on an invoice: Dr Cash / Cr Patients AR (refund = reversed)."""
    if not payment or (payment.amount or 0) <= 0:
        return None
    number = payment.invoice.invoice_number if payment.invoice else ""
    if getattr(payment, "kind", "payment") == "refund":
        lines = [("1030", payment.amount, 0, number),
                 ("1010", 0, payment.amount, number)]
        memo = f"استرداد — {number}"
    else:
        lines = [("1010", payment.amount, 0, number),
                 ("1030", 0, payment.amount, number)]
        memo = f"سداد — {number}"
    return post_entry("payment", payment.id, memo, lines, user_id=user_id)


def post_expense(expense, user_id=None):
    """Expense recorded: Dr operating expenses / Cr cash."""
    if not expense or (expense.amount or 0) <= 0:
        return None
    memo = expense.description or "مصروف"
    lines = [("5010", expense.amount, 0, memo),
             ("1010", 0, expense.amount, memo)]
    return post_entry("expense", expense.id, memo, lines,
                      entry_date=expense.expense_date, user_id=user_id)
