"""Drug catalogue & prescriptions (clinic, not a pharmacy/stock system).

A ``Drug`` is a reference entry doctors pick from while writing a
``Prescription``; search works on both trade and generic names. Basic safety
checks are supported: editable drug-drug ``DrugInteraction`` pairs, and an
optional per-drug max daily dose for guidance/over-dose flags.
"""
from datetime import datetime

from app.extensions import db

DRUG_FORMS = ["tablet", "capsule", "syrup", "suspension", "drops",
              "injection", "cream", "ointment", "suppository", "inhaler", "other"]


class Drug(db.Model):
    __tablename__ = "drugs"

    id = db.Column(db.Integer, primary_key=True)
    trade_name = db.Column(db.String(160), nullable=False, index=True)
    generic_name = db.Column(db.String(160), index=True)
    form = db.Column(db.String(20))
    strength = db.Column(db.String(60))            # e.g. "250 mg/5 ml"
    default_dose = db.Column(db.String(120))       # suggested dose text
    default_frequency = db.Column(db.String(80))   # e.g. "كل 8 ساعات"
    default_instructions = db.Column(db.String(200))
    max_daily_dose = db.Column(db.String(120))     # guidance text
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def label(self, lang="ar"):
        parts = [self.trade_name]
        if self.strength:
            parts.append(self.strength)
        return " ".join(parts)

    def __repr__(self):
        return f"<Drug {self.trade_name}>"


class DrugInteraction(db.Model):
    """An editable drug-drug interaction warning (symmetric pair)."""
    __tablename__ = "drug_interactions"

    id = db.Column(db.Integer, primary_key=True)
    drug_a_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=False, index=True)
    drug_b_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=False, index=True)
    severity = db.Column(db.String(12), default="moderate")  # mild|moderate|severe
    note = db.Column(db.String(255))

    drug_a = db.relationship("Drug", foreign_keys=[drug_a_id])
    drug_b = db.relationship("Drug", foreign_keys=[drug_b_id])


class Prescription(db.Model):
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    rx_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), nullable=False)
    diagnosis = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    items = db.relationship("PrescriptionItem", back_populates="prescription",
                            cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Prescription {self.id} p={self.patient_id}>"


class PrescriptionItem(db.Model):
    __tablename__ = "prescription_items"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=False, index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    drug_name = db.Column(db.String(200), nullable=False)  # snapshot
    dose = db.Column(db.String(120))
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    instructions = db.Column(db.String(255))

    prescription = db.relationship("Prescription", back_populates="items")
    drug = db.relationship("Drug")
