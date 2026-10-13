"""How the hospital is governed — GAHAR OGM.01, OGM.03, OGM.05, OGM.10,
OGM.13, OGM.15, and EFS.02's reports to the governing body.

* :class:`CommitteeCharter` — OGM.05 ev. 2: each committee's terms of
  reference (membership, duties, to whom it reports, how often it meets, its
  quorum and its standing agenda), one per committee, whether its minutes
  are kept in quality, infection control or the pharmacy;
* :class:`CommitteeReview` — OGM.05 ev. 5 and OGM.01 ev. 4: each
  committee's own evaluation, once a year;
* :class:`GovernanceReport` — OGM.03 ev. 3–4 and EFS.02 ev. 5: the quarterly
  report to the governing body, and its feedback;
* :class:`EthicsIssue` — OGM.15: an ethical issue raised, discussed,
  resolved and told, within the hospital's timeframe, and whether it was
  used to teach;
* :class:`ContractedService` / :class:`ContractEvaluation` — OGM.13: every
  contracted service, clinical or not, its selection criteria and measures,
  the head of department who watches it, and the yearly decision to renew
  or end it;
* :class:`SupplierEvaluation` — OGM.10 ev. 4: each supplier, evaluated at
  least once a year.
"""
from datetime import datetime

from app.extensions import db

#: OGM.05 (a)–(e), then PCC.01's patient-centred culture committee, OGM.15's
#: ethics committee and OGM.01's governing body. ``ipc`` and ``dtc`` keep
#: their minutes on their own screens; the rest in quality.
CHARTER_KEYS = ("environment", "ipc", "dtc", "quality", "mortality", "patient", "ethics", "governing")
#: OGM.05 (a)–(e) — the committees every hospital must have.
REQUIRED_COMMITTEES = ("environment", "ipc", "dtc", "quality", "mortality")
REPORT_KINDS = ("performance", "environment")
#: OGM.15 (c)–(f), and anything else the committee is asked.
ETHICS_KINDS = ("dilemma", "conflict_of_interest", "discrimination", "harassment",
                "gender_equality", "other")
SERVICE_KINDS = ("clinical", "non_clinical")
CONTRACT_DECISIONS = ("renew", "improve", "terminate")
SUPPLIER_DECISIONS = ("keep", "warn", "stop")


class CommitteeCharter(db.Model):
    __tablename__ = "committee_charters"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(20), nullable=False, unique=True)
    membership = db.Column(db.Text, nullable=False)
    duties = db.Column(db.Text, nullable=False)
    reports_to = db.Column(db.String(160), nullable=False)
    #: How often the terms of reference say it meets, in days — the program
    #: calls a committee late against this and nothing else.
    every_days = db.Column(db.Integer)
    quorum = db.Column(db.String(120))
    agenda = db.Column(db.Text)
    approved_on = db.Column(db.Date)
    approved_by = db.Column(db.String(160))
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class CommitteeReview(db.Model):
    __tablename__ = "committee_reviews"
    __table_args__ = (db.UniqueConstraint("key", "year", name="uq_committee_review_year"),)

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(20), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GovernanceReport(db.Model):
    __tablename__ = "governance_reports"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(12), nullable=False, index=True)
    #: ``2026-Q3``.
    quarter = db.Column(db.String(7), nullable=False, index=True)
    sent_on = db.Column(db.Date, nullable=False)
    summary = db.Column(db.Text, nullable=False)
    file = db.Column(db.String(255))
    feedback = db.Column(db.Text)
    feedback_on = db.Column(db.Date)
    sent_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class EthicsIssue(db.Model):
    __tablename__ = "ethics_issues"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(22), nullable=False, index=True)
    raised_on = db.Column(db.Date, nullable=False, index=True)
    summary = db.Column(db.Text, nullable=False)
    #: Who raised it, as they chose to be named — or not.
    raised_by = db.Column(db.String(160))
    #: The hospital's timeframe for an answer.
    due_on = db.Column(db.Date)
    discussion = db.Column(db.Text)
    decision = db.Column(db.Text)
    communicated_to = db.Column(db.String(255))
    resolved_on = db.Column(db.Date)
    #: OGM.15 ev. 5 — used for education, and how.
    teaching = db.Column(db.String(255))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ContractedService(db.Model):
    __tablename__ = "contracted_services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(12), nullable=False)
    provider = db.Column(db.String(160), nullable=False)
    #: The head of department who takes part in choosing and watching it.
    head = db.Column(db.String(160), nullable=False)
    criteria = db.Column(db.Text, nullable=False)
    measures = db.Column(db.Text, nullable=False)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    evaluations = db.relationship("ContractEvaluation", back_populates="service",
                                  order_by="ContractEvaluation.evaluated_on.desc()",
                                  cascade="all, delete-orphan")


class ContractEvaluation(db.Model):
    __tablename__ = "contract_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("contracted_services.id"), nullable=False, index=True)
    evaluated_on = db.Column(db.Date, nullable=False)
    results = db.Column(db.Text, nullable=False)
    decision = db.Column(db.String(10), nullable=False)
    note = db.Column(db.String(255))
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    service = db.relationship("ContractedService", back_populates="evaluations")


class SupplierEvaluation(db.Model):
    __tablename__ = "supplier_evaluations"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False, index=True)
    evaluated_on = db.Column(db.Date, nullable=False)
    results = db.Column(db.Text, nullable=False)
    decision = db.Column(db.String(6), nullable=False)
    by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    supplier = db.relationship("Supplier")
