"""The laboratory's quality control — GAHAR DAS.18 and DAS.19.

**Internal** (DAS.18): a control material — a stabilised sample with a
known target — is run beside the patients' samples, and its value is read
against the target the manufacturer's insert gives for that lot. The
target mean and SD are the laboratory's to write, from the insert or its
own data; the program never supplies one. Which rules reject a run are the
laboratory's policy too (``lab_qc_rules``); until it picks them, every run
is judged by the person who ran it. Reviewed at least monthly by somebody
authorized, and the review is a record.

**External** (DAS.19): proficiency-testing rounds — the provider, the
round, when the samples came and when results went back, the grade, the
review and any remedial action — or the inter-laboratory comparison used
where no scheme exists. Kept, never deleted: two years of records are asked
for.
"""
from datetime import datetime

from app.extensions import db


class QcMaterial(db.Model):
    """One control material at one level, one lot."""
    __tablename__ = "qc_materials"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"), index=True)
    level = db.Column(db.String(40))
    lot_number = db.Column(db.String(60))
    expiry_date = db.Column(db.Date)
    target_mean = db.Column(db.Float, nullable=False)
    target_sd = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(30))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    analyte = db.relationship("LabAnalyte")
    runs = db.relationship("QcRun", back_populates="material",
                           order_by="QcRun.run_at", cascade="all, delete-orphan")

    def label(self, lang="ar"):
        parts = [self.analyte.display_name(lang) if self.analyte else None,
                 self.name, self.level]
        return " · ".join(p for p in parts if p)


class QcRun(db.Model):
    """One control value, and what was decided about it."""
    __tablename__ = "qc_runs"

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("qc_materials.id"),
                            nullable=False, index=True)
    value = db.Column(db.Float, nullable=False)
    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    run_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # The rules the laboratory chose that this run broke, if any.
    rule_broken = db.Column(db.String(60))
    accepted = db.Column(db.Boolean, nullable=False, default=True)
    # DAS.18 (ز): remedial and corrective action when a run fails.
    action = db.Column(db.String(255))

    material = db.relationship("QcMaterial", back_populates="runs")
    runner = db.relationship("User")


class QcReview(db.Model):
    """The monthly review of the control data — DAS.18 (و)."""
    __tablename__ = "qc_reviews"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, index=True)   # YYYY-MM
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note = db.Column(db.String(255))

    reviewer = db.relationship("User")


class EqaRound(db.Model):
    """One external quality round, or one inter-laboratory comparison."""
    __tablename__ = "eqa_rounds"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(12), default="proficiency", nullable=False)  # proficiency | interlab
    provider = db.Column(db.String(160), nullable=False)
    round_code = db.Column(db.String(60))
    tests = db.Column(db.String(255))
    received_on = db.Column(db.Date)
    due_on = db.Column(db.Date)
    submitted_on = db.Column(db.Date)
    outcome = db.Column(db.String(12), default="pending", nullable=False)  # pending | acceptable | unacceptable
    grade_note = db.Column(db.String(255))
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    remedial_action = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    reviewer = db.relationship("User", foreign_keys=[reviewed_by])
