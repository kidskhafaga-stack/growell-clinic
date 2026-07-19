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
