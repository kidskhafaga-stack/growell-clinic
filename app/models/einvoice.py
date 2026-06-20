"""Egyptian Tax Authority (ETA) e-invoice documents queue.

Each ``EInvoiceDocument`` represents a clinic invoice queued for / submitted to
the ETA e-invoicing portal. The queue tracks status and the identifiers the
portal returns (UUID / long id). Submission itself lives in
``app/utils/einvoice.py`` and supports a demo (simulation) mode so the whole
flow can be shown without live credentials.
"""
from datetime import datetime

from app.extensions import db

EINVOICE_STATUSES = ["queued", "submitted", "valid", "rejected", "cancelled"]


class EInvoiceDocument(db.Model):
    __tablename__ = "einvoice_documents"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, unique=True, index=True)
    status = db.Column(db.String(12), default="queued", nullable=False, index=True)

    uuid = db.Column(db.String(80))            # document UUID from ETA
    long_id = db.Column(db.String(120))        # human-readable long id
    submission_uuid = db.Column(db.String(80))
    public_url = db.Column(db.Text)            # portal view link
    doc_json = db.Column(db.Text)              # the built payload (snapshot)
    error = db.Column(db.Text)                 # rejection reasons
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    submitted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    invoice = db.relationship("Invoice")

    def __repr__(self):
        return f"<EInvoiceDocument inv={self.invoice_id} {self.status}>"
