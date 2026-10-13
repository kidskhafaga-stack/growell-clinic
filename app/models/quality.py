"""The quality programme's own records — GAHAR QPI.01, QPI.05–09, QPI.12.

* **performance measures** (QPI.05–08): each with its identity sheet in the
  standard's elements (a)–(g) — definition, data source, frequency,
  sampling, formula, method, and the target the hospital sets — and its
  values by period; the clinical ones in QPI.06's areas, the managerial ones
  in QPI.07's. A value is the numerator and denominator as collected; the
  program divides and draws, and validates nothing it was not told;
* **the risk register** (QPI.09): each risk with its category in the
  standard's own words (f), whether the hospital rates it high, its owner,
  its mitigation and its review date; the annual **proactive assessment** of
  one high-risk process (ev. 4); and the quarterly report to the governing
  body (ev. 5);
* **improvement projects** (QPI.12): the problem, the aim, the method, the
  tests and what came of them; a utilization project is marked, because one
  a year is the standard's ask (ev. 5);
* **the quality committee** (QPI.01): meetings, decisions, and its annual
  self-evaluation (ev. 5).
"""
from datetime import datetime

from app.extensions import db

MEASURE_KINDS = ("clinical", "managerial")
#: QPI.06 (a)–(h) and QPI.07 (a)–(h), as keys.
CLINICAL_AREAS = ("waiting", "assessment", "procedures", "medications", "records", "infection",
                  "med_errors", "diagnostic_errors")
MANAGERIAL_AREAS = ("compliance", "patient_satisfaction", "complaints", "staff_satisfaction",
                    "staff_complaints", "demographics", "procurement", "finance")
#: QPI.09 (f), the standard's own list.
RISK_CATEGORIES = ("strategic", "operational", "reputational", "financial", "clinical", "other")


class PerformanceMeasure(db.Model):
    __tablename__ = "performance_measures"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    area = db.Column(db.String(20), nullable=False)
    definition = db.Column(db.Text, nullable=False)
    data_source = db.Column(db.String(255), nullable=False)
    frequency = db.Column(db.String(60), nullable=False)
    sampling = db.Column(db.String(255))
    numerator = db.Column(db.String(255), nullable=False)
    denominator = db.Column(db.String(255))
    #: Per 100, per 1000 … — the formula's multiplier, as the sheet says.
    per = db.Column(db.Integer)
    method = db.Column(db.Text)
    target = db.Column(db.Float)
    #: Whether a higher value is better — for the target's reading only.
    higher_better = db.Column(db.Boolean)
    owner = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    values = db.relationship("MeasureValue", back_populates="measure",
                             order_by="MeasureValue.period", cascade="all, delete-orphan")


class MeasureValue(db.Model):
    __tablename__ = "measure_values"

    id = db.Column(db.Integer, primary_key=True)
    measure_id = db.Column(db.Integer, db.ForeignKey("performance_measures.id"), nullable=False, index=True)
    period = db.Column(db.String(10), nullable=False)
    numerator = db.Column(db.Float, nullable=False)
    denominator = db.Column(db.Float)
    note = db.Column(db.String(255))
    validated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    measure = db.relationship("PerformanceMeasure", back_populates="values")

    @property
    def value(self):
        per = self.measure.per or 1
        if self.denominator in (None, 0):
            return self.numerator if self.measure.denominator is None else None
        return self.numerator / self.denominator * per


class RiskItem(db.Model):
    __tablename__ = "risk_register"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(14), nullable=False)
    description = db.Column(db.Text)
    #: The hospital's own rating, in its words (its matrix, its scale).
    rating = db.Column(db.String(60))
    high = db.Column(db.Boolean, default=False, nullable=False)
    owner = db.Column(db.String(120), nullable=False)
    mitigation = db.Column(db.Text)
    review_on = db.Column(db.Date)
    closed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ProactiveAssessment(db.Model):
    __tablename__ = "proactive_assessments"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    process = db.Column(db.String(200), nullable=False)
    tool = db.Column(db.String(60), nullable=False)
    findings = db.Column(db.Text, nullable=False)
    actions = db.Column(db.Text)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class RiskReport(db.Model):
    __tablename__ = "risk_reports"

    id = db.Column(db.Integer, primary_key=True)
    quarter = db.Column(db.String(7), nullable=False, index=True)
    sent_to = db.Column(db.String(160), nullable=False)
    note = db.Column(db.String(255))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ImprovementProject(db.Model):
    __tablename__ = "improvement_projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    utilization = db.Column(db.Boolean, default=False, nullable=False)
    problem = db.Column(db.Text, nullable=False)
    aim = db.Column(db.Text, nullable=False)
    method = db.Column(db.String(80))
    measure_id = db.Column(db.Integer, db.ForeignKey("performance_measures.id"))
    tests = db.Column(db.Text)
    result = db.Column(db.Text)
    implemented = db.Column(db.Boolean, default=False, nullable=False)
    started_on = db.Column(db.Date, nullable=False)
    closed_on = db.Column(db.Date)

    measure = db.relationship("PerformanceMeasure")


#: QPI.01's quality committee, PCC.01's patient-centred culture committee,
#: and OGM.05's environmental safety and mortality and morbidity committees,
#: OGM.15's ethics committee and OGM.01's governing body — the same minutes
#: and decisions, kept apart. Infection control and the pharmacy committee
#: keep theirs on their own screens.
COMMITTEES = ("quality", "patient", "environment", "mortality", "ethics", "governing")


class QualityMeeting(db.Model):
    __tablename__ = "quality_meetings"

    id = db.Column(db.Integer, primary_key=True)
    committee = db.Column(db.String(20), default="quality", nullable=False, index=True)
    held_on = db.Column(db.Date, nullable=False, index=True)
    attendees = db.Column(db.Text, nullable=False)
    minutes = db.Column(db.Text, nullable=False)
    #: OGM.05 ev. 4 — to whom the minutes were sent.
    circulated_to = db.Column(db.String(255))
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    decisions = db.relationship("QualityDecision", back_populates="meeting",
                                order_by="QualityDecision.id", cascade="all, delete-orphan")


class QualityDecision(db.Model):
    __tablename__ = "quality_decisions"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("quality_meetings.id"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    owner = db.Column(db.String(120), nullable=False)
    due_on = db.Column(db.Date)
    done_at = db.Column(db.DateTime)
    done_note = db.Column(db.String(255))

    meeting = db.relationship("QualityMeeting", back_populates="decisions")


class QualitySelfEvaluation(db.Model):
    __tablename__ = "quality_self_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    text = db.Column(db.Text, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
