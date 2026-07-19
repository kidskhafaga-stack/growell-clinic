"""Supplier payments (accounts-payable settlement).

Goods receipts (GRNs) already post the liability ``Dr Inventory / Cr Suppliers
(AP 2010)`` when stock is received, so the money owed to each supplier lives in
the ledger. What was missing is the other half: paying that liability down. A
:class:`SupplierPayment` records money going out to a supplier (cash/bank),
posts ``Dr Suppliers (AP) / Cr Cash|Bank``, and lets each supplier's balance be
tracked and settled — in full, deferred, or in instalments.
"""
from datetime import datetime

from app.extensions import db

SUPPLIER_PAYMENT_METHODS = ["cash", "bank", "transfer", "cheque"]


class SupplierPayment(db.Model):
    __tablename__ = "supplier_payments"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"),
                            nullable=False, index=True)
    # Optionally settles one specific goods-receipt/bill; otherwise it is an
    # on-account payment reducing the supplier's overall balance.
    document_id = db.Column(db.Integer, db.ForeignKey("store_documents.id"),
                            nullable=True, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)
    method = db.Column(db.String(12), default="cash", nullable=False)
    reference = db.Column(db.String(80))       # cheque / transfer reference
    paid_at = db.Column(db.Date, default=lambda: datetime.utcnow().date(),
                        nullable=False, index=True)
    notes = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    supplier = db.relationship("Supplier")
    document = db.relationship("StoreDocument")

    def __repr__(self):
        return f"<SupplierPayment {self.amount} supplier={self.supplier_id}>"


class SupplierInstallment(db.Model):
    """One planned instalment of a credit goods-receipt (terms = installments).

    A schedule of dated amounts that should sum to the receipt's value. Each row
    is settled by recording a supplier payment against it; overdue/upcoming rows
    drive the payables follow-up.
    """
    __tablename__ = "supplier_installments"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("store_documents.id"),
                            nullable=False, index=True)
    seq = db.Column(db.Integer, default=1, nullable=False)     # 1..N
    due_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)
    status = db.Column(db.String(10), default="pending", nullable=False, index=True)  # pending|paid
    paid_at = db.Column(db.Date)
    payment_id = db.Column(db.Integer, db.ForeignKey("supplier_payments.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    document = db.relationship("StoreDocument")
    payment = db.relationship("SupplierPayment")

    @property
    def is_paid(self):
        return self.status == "paid"

    def is_overdue(self, today=None):
        from datetime import date as _date
        return (not self.is_paid and self.due_date
                and self.due_date < (today or _date.today()))

    def __repr__(self):
        return f"<SupplierInstallment doc={self.document_id} #{self.seq} {self.status}>"
