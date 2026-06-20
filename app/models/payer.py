"""Payer entities & discount claims (Finance).

A ``PayerEntity`` is a third party that covers part of patients' bills under an
agreement — a club, a syndicate, an insurer, a company. When an invoice is
linked to a payer, the discount granted on that invoice is claimable from the
entity; the claims report aggregates those amounts per entity per period.
"""
from datetime import datetime

from app.extensions import db

PAYER_TYPES = ["club", "syndicate", "insurance", "company", "other"]


class PayerEntity(db.Model):
    __tablename__ = "payer_entities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    entity_type = db.Column(db.String(20), default="club", nullable=False)
    discount_percent = db.Column(db.Float, default=0)  # agreed discount rate
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    invoices = db.relationship("Invoice", back_populates="payer")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def __repr__(self):
        return f"<PayerEntity {self.name}>"
