"""Accounts payable: per-supplier balances, statements and payment posting.

The ledger already holds the liability — every purchase goods-receipt (GRN)
posts ``Dr Inventory / Cr Suppliers (AP)``. This module reads that back per
supplier (what was billed), nets it against :class:`SupplierPayment` records
(what was paid), and posts the settlement journal when a payment is recorded.
"""
from datetime import date

from app.extensions import db


def doc_value(doc):
    """Cost value of a goods-receipt (movements + linked vaccine batches)."""
    from app.utils.accounting import _doc_value
    return _doc_value(doc)


def _purchase_grns(supplier_id):
    """Purchase goods-receipts for a supplier (the billed documents)."""
    from app.models import StoreDocument
    return (StoreDocument.query
            .filter(StoreDocument.supplier_id == supplier_id,
                    StoreDocument.kind == "grn")
            .order_by(StoreDocument.doc_date, StoreDocument.id).all())


def _returns(supplier_id):
    from app.models import StoreDocument
    return (StoreDocument.query
            .filter(StoreDocument.supplier_id == supplier_id,
                    StoreDocument.kind == "return")
            .order_by(StoreDocument.doc_date, StoreDocument.id).all())


def supplier_billed(supplier_id):
    """Net goods billed by a supplier (receipts − returns)."""
    billed = sum(doc_value(d) for d in _purchase_grns(supplier_id))
    billed -= sum(doc_value(d) for d in _returns(supplier_id))
    return round(billed, 2)


def supplier_paid(supplier_id):
    from app.models import SupplierPayment
    total = (db.session.query(db.func.sum(SupplierPayment.amount))
             .filter(SupplierPayment.supplier_id == supplier_id).scalar())
    return round(total or 0, 2)


def supplier_balance(supplier_id):
    """What we still owe the supplier (billed − paid)."""
    return round(supplier_billed(supplier_id) - supplier_paid(supplier_id), 2)


def ap_summary():
    """Every supplier with any activity, with billed / paid / balance.
    Ordered by outstanding balance (largest first)."""
    from app.models import Supplier

    rows = []
    for s in Supplier.query.order_by(Supplier.name).all():
        billed = supplier_billed(s.id)
        paid = supplier_paid(s.id)
        if billed == 0 and paid == 0:
            continue
        rows.append({"supplier": s, "billed": billed, "paid": paid,
                     "balance": round(billed - paid, 2)})
    rows.sort(key=lambda r: -r["balance"])
    return rows


def supplier_statement(supplier_id):
    """Chronological events (receipts +, returns −, payments −) with a running
    balance — the supplier's كشف حساب."""
    from app.models import SupplierPayment

    events = []
    for d in _purchase_grns(supplier_id):
        events.append({"date": d.doc_date, "kind": "grn", "ref": d.doc_number,
                       "doc_id": d.id, "supplier_ref": d.supplier_ref,
                       "due": d.due_date, "terms": d.payment_terms,
                       "amount": doc_value(d)})
    for d in _returns(supplier_id):
        events.append({"date": d.doc_date, "kind": "return", "ref": d.doc_number,
                       "doc_id": d.id, "supplier_ref": d.supplier_ref,
                       "due": None, "amount": -doc_value(d)})
    for p in (SupplierPayment.query.filter_by(supplier_id=supplier_id)
              .order_by(SupplierPayment.paid_at, SupplierPayment.id).all()):
        events.append({"date": p.paid_at, "kind": "payment",
                       "ref": p.reference or "", "supplier_ref": None,
                       "due": None, "amount": -(p.amount or 0), "method": p.method})
    events.sort(key=lambda e: (e["date"] or date.today(),
                               0 if e["kind"] != "payment" else 1))
    running = 0.0
    for e in events:
        running = round(running + e["amount"], 2)
        e["running"] = running
    return events


AP_AGING_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, None)]


def ap_aging(today=None):
    """Outstanding supplier balances bucketed by how overdue each open receipt
    is (by due date, falling back to the receipt date). Because payments are on
    account, the supplier's balance is spread across its open receipts oldest-
    first (FIFO) to age it."""
    from app.models import Supplier

    today = today or date.today()
    totals = [0.0] * len(AP_AGING_BUCKETS)
    rows = []
    for s in Supplier.query.all():
        balance = supplier_balance(s.id)
        if balance <= 0.009:
            continue
        buckets = [0.0] * len(AP_AGING_BUCKETS)
        remaining = balance
        # Age the outstanding balance across open receipts, oldest first.
        for d in _purchase_grns(s.id):
            if remaining <= 0.009:
                break
            val = min(doc_value(d), remaining)
            if val <= 0:
                continue
            ref_date = d.due_date or d.doc_date
            # Not-yet-due balances (negative age) sit in the current bucket.
            age = max((today - ref_date).days, 0) if ref_date else 0
            idx = next(i for i, (lo, hi) in enumerate(AP_AGING_BUCKETS)
                       if age >= lo and (hi is None or age <= hi))
            buckets[idx] = round(buckets[idx] + val, 2)
            totals[idx] = round(totals[idx] + val, 2)
            remaining = round(remaining - val, 2)
        rows.append({"supplier": s, "buckets": buckets, "total": balance})
    rows.sort(key=lambda r: -r["total"])
    return rows, totals, round(sum(totals), 2)


def record_payment(supplier_id, amount, method="cash", paid_at=None,
                   reference=None, notes=None, document_id=None, user_id=None):
    """Create a supplier payment and post its journal. Returns the payment."""
    from app.models import SupplierPayment
    from app.utils.accounting import post_supplier_payment

    payment = SupplierPayment(
        supplier_id=supplier_id, amount=round(float(amount or 0), 2),
        method=method, paid_at=paid_at or date.today(),
        reference=(reference or None), notes=(notes or None),
        document_id=document_id, created_by=user_id)
    db.session.add(payment)
    db.session.commit()
    try:
        post_supplier_payment(payment, user_id=user_id)
    except Exception:  # noqa: BLE001 - a bookkeeping hiccup must not block paying
        db.session.rollback()
    return payment
