"""Payer entities, per-service coverage & patient memberships (Finance).

A ``PayerEntity`` is a third party that covers part of patients' bills under an
agreement — a club, a syndicate, an insurer, a company. Coverage is defined
**per service** (a benefits table): for each service the entity covers a
percentage or a fixed amount, and the patient pays the rest. Services with no
rule are not covered (the patient pays in full).

A ``PatientCoverage`` links a patient to an entity with their own card number
and expiry; when billing a member the per-service coverage is applied
automatically and the entity's share becomes claimable.
"""
from datetime import date, datetime

from app.extensions import db

PAYER_TYPES = ["club", "syndicate", "insurance", "company", "other"]
COVERAGE_TYPES = ["percent", "fixed"]


class PayerEntity(db.Model):
    __tablename__ = "payer_entities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    entity_type = db.Column(db.String(20), default="club", nullable=False)
    discount_percent = db.Column(db.Float, default=0)  # legacy default (fallback display)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    invoices = db.relationship("Invoice", back_populates="payer")
    service_rates = db.relationship("PayerServiceRate", back_populates="payer",
                                    cascade="all, delete-orphan")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def covers(self, service, amount):
        """Amount this entity covers for ``service`` on a line of ``amount``.

        Option (ب): a service with no rule is NOT covered (returns 0, so the
        patient pays in full).
        """
        if service is None:
            return 0.0
        rate = next((r for r in self.service_rates if r.service_id == service.id), None)
        if rate is None:
            return 0.0
        if rate.coverage_type == "percent":
            return round(max(amount, 0) * (rate.coverage_value or 0) / 100.0, 2)
        return round(min(rate.coverage_value or 0, max(amount, 0)), 2)

    def __repr__(self):
        return f"<PayerEntity {self.name}>"


class PayerServiceRate(db.Model):
    """One row of an entity's benefits table: coverage for a given service."""
    __tablename__ = "payer_service_rates"
    __table_args__ = (
        db.UniqueConstraint("payer_id", "service_id", name="uq_payer_service"),
    )

    id = db.Column(db.Integer, primary_key=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    coverage_type = db.Column(db.String(10), default="percent", nullable=False)
    coverage_value = db.Column(db.Float, default=0)  # what the entity covers

    payer = db.relationship("PayerEntity", back_populates="service_rates")
    service = db.relationship("Service")

    def __repr__(self):
        return f"<PayerServiceRate payer={self.payer_id} svc={self.service_id}>"


class PatientCoverage(db.Model):
    """A patient's membership/insurance card under a payer entity."""
    __tablename__ = "patient_coverages"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False)
    membership_number = db.Column(db.String(60))
    expiry_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="coverages")
    payer = db.relationship("PayerEntity")

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < date.today())

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    def __repr__(self):
        return f"<PatientCoverage p={self.patient_id} payer={self.payer_id}>"

