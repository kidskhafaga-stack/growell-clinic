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


class PoctDevice(db.Model):
    """A point-of-care device and where it is — GAHAR DAS.24 دليل ٣."""
    __tablename__ = "poct_devices"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(80))
    serial = db.Column(db.String(80))
    location = db.Column(db.String(120))
    tests = db.Column(db.String(200))
    # How often the laboratory says its controls are run, in days — its own
    # figure; until it writes one, nothing is called overdue.
    qc_every_days = db.Column(db.Integer)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    responsible = db.relationship("User")
    operators = db.relationship("PoctOperator", back_populates="device",
                                cascade="all, delete-orphan")
    checks = db.relationship("PoctQc", back_populates="device",
                             order_by="PoctQc.run_at", cascade="all, delete-orphan")


class PoctOperator(db.Model):
    """Somebody trained and competent to use one device — DAS.24 دليل ٢."""
    __tablename__ = "poct_operators"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("poct_devices.id"),
                          nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    trained_on = db.Column(db.Date)
    competent_until = db.Column(db.Date)

    device = db.relationship("PoctDevice", back_populates="operators")
    user = db.relationship("User")


class PoctQc(db.Model):
    """A control run on a point-of-care device — DAS.24 دليل ٥."""
    __tablename__ = "poct_qc"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("poct_devices.id"),
                          nullable=False, index=True)
    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    run_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    level = db.Column(db.String(40))
    result = db.Column(db.String(80))
    passed = db.Column(db.Boolean, nullable=False, default=True)
    action = db.Column(db.String(255))

    device = db.relationship("PoctDevice", back_populates="checks")
    runner = db.relationship("User")


class LabProcedure(db.Model):
    """The written procedure for a test — GAHAR DAS.17.

    *"The laboratory has a written updated procedure for each analytical test
    method"* and *"the laboratory procedures are readily available when
    needed"*. The procedure itself is the laboratory's document — on paper
    at the bench, or a file on its shared drive — so what the program keeps
    is how to find it, which version is in force, who approved it, and when
    it is due its review: an out-of-date procedure is the finding, and only
    a date can show it.

    One row per version; the newest is the one in force, and the old ones
    stay so the version a result was produced under can be named.
    """
    __tablename__ = "lab_procedures"

    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"),
                                 nullable=False, index=True)
    code = db.Column(db.String(40))
    version = db.Column(db.String(20), nullable=False)
    # Where it is: a link to the file, or the shelf it sits on.
    location = db.Column(db.String(255), nullable=False)
    effective_on = db.Column(db.Date, nullable=False)
    review_due = db.Column(db.Date, index=True)
    approved_by = db.Column(db.String(120))
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    investigation = db.relationship("Investigation")
    writer = db.relationship("User", foreign_keys=[written_by])

    @property
    def is_link(self):
        return (self.location or "").lower().startswith(("http://", "https://"))

    def __repr__(self):
        return f"<LabProcedure {self.investigation_id} v{self.version}>"


#: DAS.16 — a method bought as validated is *verified* here; one the
#: laboratory built or changed is *validated*. Two words the surveyor reads.
METHOD_CHECK_KINDS = ("verification", "validation")


class MethodCheck(db.Model):
    """A test method verified or validated — GAHAR DAS.16.

    Evidence 4: *"records of verification and/or validation results fulfil
    acceptable criteria"*; evidence 5: *"recorded evidence of
    reverification/revalidation"*. The study itself — precision, accuracy,
    the run sheets — is the laboratory's file; the row is its outcome
    against the laboratory's own criteria, who signed it, and when it is due
    again. Accepted is the laboratory's verdict, never the program's.
    """
    __tablename__ = "lab_method_checks"

    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"),
                                 nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default="verification")
    done_on = db.Column(db.Date, nullable=False, index=True)
    # What was checked against what — the laboratory's criteria, in its words.
    summary = db.Column(db.String(400), nullable=False)
    accepted = db.Column(db.Boolean, nullable=False)
    signed_by = db.Column(db.String(120), nullable=False)
    due_again = db.Column(db.Date, index=True)
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    investigation = db.relationship("Investigation")
    writer = db.relationship("User", foreign_keys=[written_by])

    def __repr__(self):
        return f"<MethodCheck {self.investigation_id} {self.kind} {self.done_on}>"
