"""Reading the tills: what is in each one, and how it got there.

The balance is computed from the movements every time it is asked for, and
that is deliberate. A stored ``current_balance`` column is the easiest thing in
this module to write and the most dangerous thing to live with: the moment one
write is interrupted, or a row is edited, or a migration runs half way, there
are two answers to "how much is in this till" and nothing to say which of them
is lying. Opening balance plus movements has exactly one answer.

If this is ever too slow to read, the fix is a cache with a rebuild command —
added as an optimisation, never promoted to the source of truth.
"""
from datetime import datetime

# The tills a fresh install starts with. Generic on purpose: a clinic renames
# them to what is on the wall ("خزنة استقبال الدور الأرضي") and adds its own.
# The codes sit under 1000 (assets) beside the two that already existed.
DEFAULT_ACCOUNTS = [
    # code, ar, en, kind, methods, settles_into
    ("1010", "الخزنة الرئيسية", "Main cash drawer", "cash", "cash", None),
    ("1011", "إنستاباي", "InstaPay", "wallet", "instapay", None),
    ("1012", "المحفظة الإلكترونية", "Mobile wallet", "wallet", "wallet", None),
    ("1013", "الفيزا — تحت التحصيل", "Card — under collection", "clearing",
     "card", "1020"),
    ("1020", "حساب البنك", "Bank account", "bank", "transfer", None),
]


def seed_accounts():
    """Create the starter tills once. Never touches a clinic's own.

    Idempotent, so it is safe on every ``upgrade-db``: a till already carrying
    its code is left exactly as the clinic edited it.
    """
    from app.extensions import db
    from app.models import CashAccount

    existing = {a.code for a in CashAccount.query.all()}
    made = 0
    for order, (code, ar, en, kind, methods, _settles) in enumerate(
            DEFAULT_ACCOUNTS):
        if code in existing:
            continue
        db.session.add(CashAccount(
            code=code, name=ar, name_en=en, kind=kind,
            default_methods=methods, sort_order=order, is_active=True))
        made += 1
    if made:
        db.session.flush()
    # Second pass: the card till settles into the bank, which may only have
    # been created a moment ago.
    by_code = {a.code: a for a in CashAccount.query.all()}
    for code, _ar, _en, _kind, _methods, settles in DEFAULT_ACCOUNTS:
        account = by_code.get(code)
        target = by_code.get(settles) if settles else None
        if account is not None and target is not None \
                and account.settles_into_id is None:
            account.settles_into_id = target.id
            made += 1
    if made:
        db.session.commit()
    return made


def movements(account, since=None, upto=None, limit=None):
    """Every movement in or out of one till, oldest first.

    Read from the movement tables rather than from the ledger, so a statement
    line can link back to the invoice or the supplier it came from — a journal
    line knows an amount and a memo, and "which patient was this?" is the first
    question anybody asks of a till statement.
    """
    from app.models import Expense, Payment, SupplierPayment

    rows = []
    for payment in _scoped(Payment.query.filter(Payment.account_id == account.id),
                           Payment.paid_at, since, upto).all():
        inflow = payment.kind != "refund"
        rows.append({
            "at": payment.paid_at,
            "kind": "payment" if inflow else "refund",
            "amount": (payment.amount or 0) * (1 if inflow else -1),
            "method": payment.method,
            "label": (payment.invoice.invoice_number
                      if payment.invoice else ""),
            "who": (payment.invoice.patient.display_name("ar")
                    if payment.invoice and payment.invoice.patient else ""),
            "id": payment.id,
        })
    for expense in _scoped(Expense.query.filter(Expense.account_id == account.id),
                           Expense.expense_date, since, upto).all():
        rows.append({
            "at": _as_datetime(expense.expense_date),
            "kind": "expense",
            "amount": -(expense.amount or 0),
            "method": expense.payment_method,
            "label": expense.description or "",
            "who": expense.vendor or "",
            "id": expense.id,
        })
    for sp in _scoped(
            SupplierPayment.query.filter(SupplierPayment.account_id == account.id),
            SupplierPayment.paid_at, since, upto).all():
        rows.append({
            "at": _as_datetime(sp.paid_at),
            "kind": "supplier",
            "amount": -(sp.amount or 0),
            "method": sp.method,
            "label": sp.reference or "",
            "who": sp.supplier.name if sp.supplier else "",
            "id": sp.id,
        })

    rows.sort(key=lambda r: r["at"] or datetime.min)
    return rows[-limit:] if limit else rows


def _scoped(query, column, since, upto):
    if since is not None:
        query = query.filter(column >= since)
    if upto is not None:
        query = query.filter(column <= upto)
    return query


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime(value.year, value.month, value.day)


def account_balance(account, upto=None):
    """Opening balance plus every movement. The only answer there is."""
    total = account.opening_balance or 0
    for row in movements(account, upto=upto):
        total += row["amount"]
    return round(total, 2)


def overview():
    """Every active till with its balance — the screen people open for this.

    Flags a cash till holding more than its maximum, which is the one limit
    that protects money rather than convenience.
    """
    from app.models import CashAccount

    out = []
    for account in CashAccount.active():
        balance = account_balance(account)
        out.append({
            "account": account,
            "balance": balance,
            "over": bool(account.max_balance and balance > account.max_balance),
            "under": bool(account.min_balance is not None
                          and balance < account.min_balance),
        })
    return out


def total_by_kind():
    """Money on hand, grouped by how it would be verified."""
    totals = {}
    for row in overview():
        kind = row["account"].kind
        totals[kind] = round(totals.get(kind, 0) + row["balance"], 2)
    return totals
