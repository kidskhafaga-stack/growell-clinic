"""The money check — every stored amount to the piastre, and the books balanced.

MONEY_SAFETY_PLAN.md ف-٤, against the owner's conditions for accepting the
change («شروط قبول النقل»):

* no invoice, family balance, till or insurer account differs afterwards;
* no decimal is lost and nothing is rounded without approval;
* every change can be traced to the row it came from;
* a backup and an audit record before and after.

The arithmetic is in whole piastres now (`utils/money`), and what is stored
keeps its shape. What this looks for is a figure written **before** that: an
amount stored with a third decimal — a share worked out as 18.825 and kept as
it came — which the new arithmetic reads half up. :func:`scan` finds them and
checks the books; :func:`fix` rounds each to the piastre, half up, with a
backup before and after and one activity line per change saying which row,
which column, what it was and what it became; and the totals before and after
are compared, so the difference is exactly the sum of what was listed.

Never touched: unit costs (an average cost per tablet is legitimately 0.3333)
and percentages — neither is an amount of money.
"""
from decimal import Decimal

from sqlalchemy import inspect, text

from app.extensions import db
from app.utils import money

#: ``(table, column)`` that hold an amount of money, in pounds, to two places.
MONEY_COLUMNS = (
    ("bank_statement_lines", "amount"), ("bank_statement_lines", "balance"),
    ("bed_charges", "unit_price"),
    ("care_charges", "amount"),
    ("cash_accounts", "opening_balance"), ("cash_accounts", "min_balance"),
    ("cash_accounts", "max_balance"),
    ("cash_counts", "counted"), ("cash_counts", "expected"),
    ("cash_drawer_days", "opening_float"), ("cash_drawer_days", "counted_cash"),
    ("cash_movements", "amount"), ("cash_movements", "fee"),
    ("cashier_shifts", "opening_float"), ("cashier_shifts", "counted_cash"),
    ("claim_items", "amount"),
    ("claim_lines", "amount"), ("claim_lines", "accepted"),
    ("claims", "total_amount"), ("claims", "approved_amount"), ("claims", "paid_amount"),
    ("dental_plan_items", "price"),
    ("doctor_case_rates", "price_override"),
    ("doctor_payouts", "amount"),
    ("doctor_service_commissions", "price_override"),
    ("doctor_settlements", "lines_amount"), ("doctor_settlements", "vaccine_amount"),
    ("doctor_settlements", "duty_amount"), ("doctor_settlements", "gross_amount"),
    ("doctor_settlements", "advances"), ("doctor_settlements", "net_due"),
    ("doctor_settlements", "awaiting"),
    ("drugs", "price"),
    ("duties", "amount"), ("duty_rates", "amount"), ("duty_rates", "on_call_amount"),
    ("expenses", "amount"),
    ("imported_services", "price"), ("imported_services", "doctor_share"),
    ("imported_services", "paid_cash"), ("imported_services", "paid_company"),
    ("insurance_approvals", "estimate"), ("insurance_approvals", "approved_amount"),
    ("investigations", "cost"),
    ("invoice_items", "unit_price"), ("invoice_items", "commission_amount"),
    ("invoice_items", "payer_amount"), ("invoice_items", "cover_cut"),
    ("invoice_items", "group_discount"),
    ("invoices", "deductible_taken"),
    ("journal_lines", "debit"), ("journal_lines", "credit"),
    ("online_payments", "amount"), ("online_payments", "reported_amount"),
    ("patient_credits", "amount"),
    ("patient_packages", "price_paid"),
    ("payer_contract_rates", "special_price"),
    ("payer_contract_terms", "copay_amount"), ("payer_contract_terms", "ceiling_case"),
    ("payer_contract_terms", "night_ceiling"), ("payer_contract_terms", "deposit_amount"),
    ("payer_contracts", "deductible_year"), ("payer_contracts", "ceiling_year"),
    ("payments", "amount"), ("payments", "tendered"),
    ("referral_invoices", "amount"), ("referral_invoices", "our_total"),
    ("referral_lab_prices", "price"),
    ("refund_notices", "amount"), ("refund_notices", "doctor_amount"),
    ("refund_requests", "amount"),
    ("service_packages", "price"),
    ("services", "price"), ("services", "cost"),
    ("store_items", "purchase_price"), ("store_items", "sell_price"),
    ("supplier_installments", "amount"), ("supplier_payments", "amount"),
    ("vaccine_brands", "price"), ("vaccine_brands", "purchase_price"),
    ("vaccine_brands", "doctor_fee"),
    ("vaccine_settlements", "amount"),
    ("visit_investigations", "sent_cost"),
)


def _present():
    """The listed columns this database actually has — an older file may
    lack a table, and a check that crashes on it checks nothing."""
    insp = inspect(db.engine)
    tables = set(insp.get_table_names())
    have = {}
    for table, column in MONEY_COLUMNS:
        if table not in tables:
            continue
        if table not in have:
            have[table] = {c["name"] for c in insp.get_columns(table)}
        if column in have[table]:
            yield table, column


def _exact(value):
    """The stored figure as the exact decimal its spelling says."""
    return Decimal(str(value))


def off_by_piastres():
    """``[{table, column, id, stored, becomes}]`` — every stored amount with
    more than two places after the point, and what it rounds to (half up)."""
    out = []
    for table, column in _present():
        rows = db.session.execute(text(
            f'SELECT id, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'))
        for row_id, value in rows:
            exact = _exact(value) * 100
            if exact != exact.to_integral_value():
                out.append({"table": table, "column": column, "id": row_id,
                            "stored": value,
                            "becomes": money.pounds(money.piastres(value))})
    return out


def column_totals():
    """``{"table.column": piastres}`` — each listed column summed exactly,
    every figure read half up to the piastre. The fingerprint compared before
    and after a fix."""
    out = {}
    for table, column in _present():
        rows = db.session.execute(text(
            f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'))
        out[f"{table}.{column}"] = sum(money.piastres(v) for (v,) in rows)
    return out


def unbalanced_entries():
    """Journal entries whose debits and credits differ by a piastre or more."""
    rows = db.session.execute(text(
        "SELECT entry_id, debit, credit FROM journal_lines"))
    sums = {}
    for entry_id, debit, credit in rows:
        d, c = sums.get(entry_id, (0, 0))
        sums[entry_id] = (d + money.piastres(debit), c + money.piastres(credit))
    return sorted(e for e, (d, c) in sums.items() if d != c)


def overpaid_invoices():
    """Invoices that took more than they came to, or owe a negative sum."""
    from app.models import Invoice

    out = []
    for bill in Invoice.query.yield_per(500):
        if bill.refunded_at is not None:
            continue
        if bill.paid_piastres > bill.total_piastres:
            out.append(bill.id)
    return out


def negative_family_accounts():
    """Families whose account (money in − money out) is below zero."""
    rows = db.session.execute(text(
        "SELECT patient_id, kind, amount FROM patient_credits"))
    held = {}
    for patient_id, kind, amount in rows:
        whole = money.piastres(amount)
        held[patient_id] = held.get(patient_id, 0) + (whole if kind == "in" else -whole)
    return sorted(p for p, n in held.items() if n < 0)


def scan():
    """Everything the check looks at, read only."""
    off = off_by_piastres()
    return {"off": off,
            "unbalanced": unbalanced_entries(),
            "overpaid": overpaid_invoices(),
            "negative": negative_family_accounts(),
            "columns": len(list(_present())),
            "clean": not off}


def fix(user=None, ip_address=None):
    """Round every stored amount with a third decimal to the piastre.

    In order: a backup; the totals; each change written, with one activity
    line naming the row, the column, the figure before and after; the
    totals again; a second backup. Returns what was done, and whether the
    totals moved by exactly the listed differences — nothing else.
    """
    from app.models import ActivityLog
    from app.utils.backups import create_backup

    off = off_by_piastres()
    if not off:
        return {"changed": [], "before_backup": None, "after_backup": None,
                "totals_match": True}
    before_backup = create_backup("money_before")
    before = column_totals()
    for row in off:
        db.session.execute(text(
            f'UPDATE "{row["table"]}" SET "{row["column"]}" = :v WHERE id = :i'),
            {"v": row["becomes"], "i": row["id"]})
        ActivityLog.record(
            "money.fix", user_id=getattr(user, "id", None), entity=row["table"],
            entity_id=row["id"],
            detail=f'{row["column"]}: {row["stored"]!r} → {row["becomes"]:.2f}',
            ip_address=ip_address)
    db.session.commit()
    after = column_totals()
    # Every figure is read half up, before and after: the rounding the fix
    # writes is the rounding the reading already did. So the fingerprint must
    # not move by a piastre — and if it does, the screen says so.
    totals_match = before == after
    after_backup = create_backup("money_after")
    return {"changed": off, "before_backup": before_backup,
            "after_backup": after_backup, "totals_match": totals_match}
