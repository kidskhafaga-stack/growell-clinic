"""Severity scores and the deaths they expect (HOSPITAL_PLAN.md ٥‑د ت-٦ب).

Three tables, because three different things are being kept:

``SeverityScore``
    One version of one score, **as the hospital entered it from the original
    paper**: its inputs, its numbers, the worked examples from the paper or
    the official calculator, the source, and whose licence it is used under.
    The program ships no score and no coefficient — it never writes a
    clinical number. A version that is in use is never edited; a change is a
    new version.

``SeverityUnitChoice``
    Which score a unit (ICU, NICU) uses from which day. A change is a new row:
    the history of which score was in force is itself a record.

``SeverityRecord``
    One child's score on entering the unit, with the score's version and the
    values it was computed from. Changing the unit's score later rewrites
    nothing.
"""
from datetime import datetime

from app.extensions import db

STATUSES = ("draft", "active", "retired")
KINDS = ("equation", "points")


class SeverityScore(db.Model):
    __tablename__ = "severity_scores"
    __table_args__ = (db.UniqueConstraint("key", "version", name="uq_severity_key_version"),)

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    kind = db.Column(db.String(10), nullable=False, default="equation")
    # Where every number came from, and on whose permission it is used.
    source = db.Column(db.Text)
    licence_holder = db.Column(db.String(200))
    licence_ref = db.Column(db.String(200))
    # The window the readings must fall in, in hours around entering the unit.
    window_before_h = db.Column(db.Float)
    window_after_h = db.Column(db.Float)
    # Equation: logit = intercept + Σ coefficient × reading.
    # Points: probability = 1 / (1 + e^-(intercept + slope × total)), when the
    # paper gives that line; a points score without it expects no deaths.
    intercept = db.Column(db.Float)
    slope = db.Column(db.Float)
    inputs = db.Column(db.JSON, nullable=False, default=list)
    examples = db.Column(db.JSON, nullable=False, default=list)
    tolerance = db.Column(db.Float, nullable=False, default=0.001)
    status = db.Column(db.String(10), nullable=False, default="draft", index=True)
    test_ok = db.Column(db.Boolean, nullable=False, default=False)
    test_at = db.Column(db.DateTime)
    test_detail = db.Column(db.JSON)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    approval_note = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    approver = db.relationship("User", foreign_keys=[approved_by])

    def display_name(self, lang="ar"):
        name = (self.name_en if lang == "en" and self.name_en else self.name_ar)
        return f"{name} v{self.version}"

    def __repr__(self):
        return f"<SeverityScore {self.key} v{self.version} {self.status}>"


class SeverityUnitChoice(db.Model):
    __tablename__ = "severity_unit_choices"

    id = db.Column(db.Integer, primary_key=True)
    unit_kind = db.Column(db.String(12), nullable=False, index=True)
    # None: the unit stopped scoring from that day.
    score_id = db.Column(db.Integer, db.ForeignKey("severity_scores.id"))
    since = db.Column(db.Date, nullable=False)
    set_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    set_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note = db.Column(db.String(255))

    score = db.relationship("SeverityScore")
    setter = db.relationship("User", foreign_keys=[set_by])


class SeverityRecord(db.Model):
    __tablename__ = "severity_records"
    __table_args__ = (db.UniqueConstraint("admission_id", "unit_kind", name="uq_severity_stay_unit"),)

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey("admissions.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    unit_kind = db.Column(db.String(12), nullable=False, index=True)
    score_id = db.Column(db.Integer, db.ForeignKey("severity_scores.id"), nullable=False)
    entered_at = db.Column(db.DateTime, nullable=False)
    measured_at = db.Column(db.DateTime, nullable=False)
    values = db.Column(db.JSON, nullable=False, default=dict)
    # The inputs that were not measured and took the paper's own rule.
    missing = db.Column(db.JSON, nullable=False, default=list)
    points = db.Column(db.Float)
    probability = db.Column(db.Float)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    score = db.relationship("SeverityScore")
    admission = db.relationship("Admission")
    recorder = db.relationship("User", foreign_keys=[recorded_by])
