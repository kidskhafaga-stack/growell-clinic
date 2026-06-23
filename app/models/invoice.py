"""Invoicing & payments (Finance core).

An ``Invoice`` groups charged ``InvoiceItem`` lines for a patient (optionally
tied to a visit and credited to a doctor). Each line snapshots its price,
discount and the doctor commission at the time of billing, so later changes to
service rates never rewrite history. ``Payment`` rows record (possibly partial)
collections; the invoice status is derived from paid-vs-total.
"""
from datetime import datetime

from app.extensions import db

INVOICE_STATUSES = ["unpaid", "partial", "paid"]
PAYMENT_METHODS = ["cash", "card", "transfer", "wallet"]


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=True, index=True)
    coverage_card = db.Column(db.String(60))   # snapshot: membership/card no.
    coverage_expiry = db.Column(db.Date)        # snapshot: card expiry
    # Named discount applied to this invoice (snapshot of the rule's name).
    discount_id = db.Column(db.Integer, db.ForeignKey("named_discounts.id"), nullable=True)
    discount_name = db.Column(db.String(120))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    invoice_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), nullable=False)
    status = db.Column(db.String(10), default="unpaid", nullable=False)
    is_tax = db.Column(db.Boolean, default=False, nullable=False)  # ETA tax invoice
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    visit = db.relationship("Visit")
    payer = db.relationship("PayerEntity", back_populates="invoices")
    items = db.relationship("InvoiceItem", back_populates="invoice",
                            cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="invoice",
                               cascade="all, delete-orphan")

    # --- money ---------------------------------------------------------
    @property
    def subtotal(self):
        return round(sum(i.gross for i in self.items), 2)

    @property
    def discount_total(self):
        return round(sum(i.discount_amount for i in self.items), 2)

    @property
    def total(self):
        return round(sum(i.net for i in self.items), 2)

    @property
    def paid(self):
        return round(sum(p.amount or 0 for p in self.payments), 2)

    @property
    def balance(self):
        return round(self.total - self.paid, 2)

    @property
    def doctor_share_total(self):
        return round(sum(i.commission_amount or 0 for i in self.items), 2)

    @property
    def clinic_share_total(self):
        return round(self.total - self.doctor_share_total, 2)

    def recalc_status(self):
        paid, total = self.paid, self.total
        if total > 0 and paid >= total:
            self.status = "paid"
        elif paid > 0:
            self.status = "partial"
        else:
            self.status = "unpaid"
        return self.status

    def __repr__(self):
        return f"<Invoice {self.invoice_number}>"


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)

    description = db.Column(db.String(200), nullable=False)  # snapshot name
    unit_price = db.Column(db.Float, default=0, nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    discount_value = db.Column(db.Float, default=0)          # raw input
    discount_is_percent = db.Column(db.Boolean, default=False)
    commission_amount = db.Column(db.Float, default=0)        # doctor cut snapshot

    invoice = db.relationship("Invoice", back_populates="items")
    service = db.relationship("Service")

    @property
    def gross(self):
        return round((self.unit_price or 0) * (self.quantity or 1), 2)

    @property
    def discount_amount(self):
        if self.discount_is_percent:
            return round(self.gross * (self.discount_value or 0) / 100.0, 2)
        return round(min(self.discount_value or 0, self.gross), 2)

    @property
    def net(self):
        return round(self.gross - self.discount_amount, 2)

    def __repr__(self):
        return f"<InvoiceItem {self.description}>"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)
    method = db.Column(db.String(12), default="cash", nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.String(200))

    invoice = db.relationship("Invoice", back_populates="payments")
    receiver = db.relationship("User")

    def __repr__(self):
        return f"<Payment {self.amount} for inv={self.invoice_id}>"
