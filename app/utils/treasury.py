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
    from app.extensions import db
    from app.models import CashMovement, Expense, Payment, SupplierPayment

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

    # Deliberate movements: banking a drawer, topping up change, a card
    # settlement landing. One row serves both tills — the sign comes from
    # which side this account is on.
    deliberate = CashMovement.query.filter(
        db.or_(CashMovement.account_id == account.id,
               CashMovement.to_account_id == account.id))
    for mv in _scoped(deliberate, CashMovement.moved_on, since, upto).all():
        effect = mv.effect_on(account.id)
        if not effect:
            continue
        other = mv.to_account if mv.account_id == account.id else mv.account
        rows.append({
            "at": _as_datetime(mv.moved_on),
            "kind": f"mv_{mv.kind}",
            "amount": effect,
            "method": None,
            "label": mv.reference or "",
            "who": other.name if other is not None else "",
            "id": mv.id,
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


# --------------------------------------------------------- moving money ----
class MovementError(ValueError):
    """A movement that must not be recorded, with a key the screen can name."""


def record_movement(kind, account, amount, to_account=None, fee=0,
                    moved_on=None, reference=None, notes=None, user_id=None):
    """Bank a drawer, draw from a till, transfer, or settle a clearing account.

    Refuses rather than guesses. Every one of these is somebody deliberately
    moving the clinic's money, and a movement that quietly did something other
    than what was asked would be worse than one that did nothing.
    """
    from datetime import date

    from app.extensions import db
    from app.models import CASH_MOVEMENT_KINDS, CashMovement
    from app.models.cash_movement import NEEDS_TARGET

    if kind not in CASH_MOVEMENT_KINDS:
        raise MovementError("bad_kind")
    if account is None:
        raise MovementError("no_account")
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise MovementError("bad_amount")
    fee = round(float(fee or 0), 2)
    if fee < 0 or fee >= amount:
        # A fee that swallows the whole transfer means the numbers are wrong,
        # not that the clinic moved nothing.
        raise MovementError("bad_fee")

    if kind in NEEDS_TARGET:
        if to_account is None:
            raise MovementError("no_target")
        if to_account.id == account.id:
            raise MovementError("same_till")
        # Two currencies need rates, revaluation and an FX difference account.
        # None of that exists yet, so this is refused rather than computed
        # wrongly — a clear refusal beats a wrong number.
        if (account.currency or "") != (to_account.currency or ""):
            raise MovementError("cross_currency")
    else:
        to_account = None
        if fee:
            raise MovementError("fee_needs_transfer")

    if kind == "settle" and account.kind != "clearing":
        raise MovementError("not_clearing")
    # Money cannot leave a till that does not have it. A deposit is the one
    # kind that adds, so it is exempt.
    if kind != "deposit" and amount > account_balance(account):
        raise MovementError("insufficient")

    movement = CashMovement(
        kind=kind, account_id=account.id,
        to_account_id=to_account.id if to_account else None,
        amount=amount, fee=fee, moved_on=moved_on or date.today(),
        reference=reference or None, notes=notes or None, created_by=user_id)
    db.session.add(movement)
    db.session.commit()
    _post_movement(movement)
    return movement


def _post_movement(movement):
    """Journal one movement. Never lets a bookkeeping hiccup lose the record.

    The movement itself is already committed by the time this runs: a ledger
    that refused to balance must not cost the clinic the fact that the money
    moved, which they can see in the drawer.
    """
    from app.extensions import db
    from app.utils.accounting import post_entry

    src = movement.account
    dst = movement.to_account
    memo = _movement_memo(movement)
    try:
        if movement.kind == "deposit":
            lines = [(src.code, movement.amount, 0, memo),
                     ("3010", 0, movement.amount, memo)]
        elif movement.kind == "withdraw":
            lines = [("3010", movement.amount, 0, memo),
                     (src.code, 0, movement.amount, memo)]
        else:                                   # transfer / settle
            lines = [(dst.code, movement.received, 0, memo)]
            if movement.fee:
                # The processor's cut is a cost, not money that vanished.
                lines.append(("5010", movement.fee, 0, memo))
            lines.append((src.code, 0, movement.amount, memo))
        return post_entry("cash_movement", movement.id, memo, lines,
                          entry_date=movement.moved_on,
                          user_id=movement.created_by, replace=True)
    except Exception:  # noqa: BLE001 - the movement stands either way
        db.session.rollback()
        return None


def _movement_memo(movement):
    src = movement.account.name if movement.account else ""
    if movement.to_account is not None:
        return f"تحويل خزنة — {src} ← {movement.to_account.name}"
    return f"{'إيداع' if movement.kind == 'deposit' else 'سحب'} — {src}"


def pending_settlements():
    """Clearing tills holding money, and where each is meant to go.

    The follow-up list: card takings that have not reached the bank, cheques
    not collected, insurance not paid. A clearing till with a balance and
    nowhere to settle is called out — it can never be cleared to zero.
    """
    from app.models import CashAccount

    out = []
    for account in CashAccount.active():
        if account.kind != "clearing":
            continue
        balance = account_balance(account)
        if not balance:
            continue
        out.append({"account": account, "balance": balance,
                    "target": account.settles_into,
                    "orphan": account.settles_into is None})
    return out
