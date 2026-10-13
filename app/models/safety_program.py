"""The hospital's safety program, beyond fire and utilities — GAHAR EFS.02,
EFS.05–EFS.09 and OGM.14.

* :class:`SafetyRound` / :class:`RoundFinding` — the walk-round: who went,
  where, what they found, how serious, what is to be done, by whom and by
  when, and when it was closed. One record for the four reasons a hospital
  walks its own floors: the multidisciplinary environment round each quarter
  (EFS.02 ev. 4), the safety inspection (EFS.07 e), the security round
  (EFS.09) and the leaders' safety round (OGM.14 ev. 2);
* :class:`HazardousMaterial` — EFS.06 (a)–(c): the inventory with its hazard,
  place, use, consumption and who is responsible, its safety data sheet, and
  whether it is labelled;
* :class:`WasteHandover` — EFS.06 (e): hazardous waste handed to the licensed
  carrier, by the WHO category, with the manifest;
* :class:`PestControlVisit` — EFS.07 (d);
* :class:`ConstructionProject` / :class:`ConstructionCheck` — EFS.08: the
  pre-construction risk assessment (a)–(h), the departments involved, the
  work permit, and the monitoring of the work and the contractor;
* :class:`RestrictedArea` / :class:`VisitorPass` — EFS.09 (c), (d): the
  areas restricted and who may enter them, and every visitor, vendor and
  contractor signed in with a badge and where they may go, and out.

The plans themselves are the hospital's documents (``HospitalPlan``). Kept,
never deleted: a finding is closed, not erased.
"""
from datetime import datetime

from app.extensions import db

#: Why the round was walked.
ROUND_FOCUS = ("environment", "safety", "security", "leadership")
RISK_LEVELS = ("high", "medium", "low")

#: EFS.06 (b) — the kinds of hazard a safety data sheet names.
HAZARD_TYPES = ("flammable", "corrosive", "toxic", "cytotoxic", "carcinogenic",
                "oxidizer", "compressed_gas", "radioactive", "infectious", "irritant", "other")
#: EFS.06 — the WHO categories of hazardous healthcare waste, as the
#: standard lists them.
WASTE_CATEGORIES = ("infectious", "pathological", "pharmaceutical", "chemical",
                    "heavy_metals", "pressurized", "sharps", "cytotoxic", "radioactive")

#: EFS.08 (a)–(h) — what a pre-construction risk assessment weighs.
PCRA_ITEMS = ("noise", "vibration", "icra", "air", "fire", "hazmat", "waste", "other")
PROJECT_STATES = ("planned", "underway", "finished")

round_team = db.Table(
    "safety_round_team",
    db.Column("round_id", db.Integer, db.ForeignKey("safety_rounds.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class SafetyRound(db.Model):
    __tablename__ = "safety_rounds"

    id = db.Column(db.Integer, primary_key=True)
    focus = db.Column(db.String(12), nullable=False, index=True)
    held_on = db.Column(db.Date, nullable=False, index=True)
    #: The areas walked — independent entities (the coffee shop, the
    #: pharmacy that is not the hospital's) included, EFS.02 ev. 4.
    areas = db.Column(db.String(400), nullable=False)
    #: Team members without an account, or by role (the civil-defence
    #: officer, the contractor's engineer).
    others = db.Column(db.String(255))
    summary = db.Column(db.Text)
    #: To whom the report went — the committee, the leaders, the departments.
    sent_to = db.Column(db.String(255))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    team = db.relationship("User", secondary=round_team)
    findings = db.relationship("RoundFinding", back_populates="round",
                               order_by="RoundFinding.id", cascade="all, delete-orphan")

    @property
    def open_findings(self):
        return [f for f in self.findings if f.closed_at is None]


class RoundFinding(db.Model):
    __tablename__ = "round_findings"

    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey("safety_rounds.id"), nullable=False, index=True)
    area = db.Column(db.String(160))
    finding = db.Column(db.Text, nullable=False)
    risk = db.Column(db.String(8), nullable=False)
    action = db.Column(db.Text, nullable=False)
    owner = db.Column(db.String(160), nullable=False)
    due_on = db.Column(db.Date)
    closed_at = db.Column(db.DateTime)
    closed_note = db.Column(db.String(255))
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    round = db.relationship("SafetyRound", back_populates="findings")


class HazardousMaterial(db.Model):
    __tablename__ = "hazardous_materials"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    hazard = db.Column(db.String(16), nullable=False)
    location = db.Column(db.String(160), nullable=False)
    usage = db.Column(db.String(255))
    #: As the department counts it — "two litres a month".
    consumption = db.Column(db.String(80))
    responsible = db.Column(db.String(160), nullable=False)
    #: The safety data sheet — a file, and the day it was last checked
    #: against the supplier's current one.
    sds_file = db.Column(db.String(255))
    sds_reviewed_on = db.Column(db.Date)
    labelled = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class WasteHandover(db.Model):
    __tablename__ = "waste_handovers"

    id = db.Column(db.Integer, primary_key=True)
    handed_on = db.Column(db.Date, nullable=False, index=True)
    category = db.Column(db.String(16), nullable=False)
    #: As weighed, in kilograms.
    weight_kg = db.Column(db.Float)
    carrier = db.Column(db.String(160), nullable=False)
    manifest_no = db.Column(db.String(60))
    note = db.Column(db.String(255))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PestControlVisit(db.Model):
    __tablename__ = "pest_control_visits"

    id = db.Column(db.Integer, primary_key=True)
    visited_on = db.Column(db.Date, nullable=False, index=True)
    company = db.Column(db.String(160), nullable=False)
    areas = db.Column(db.String(400), nullable=False)
    #: What was used — and where, so a ward knows what was sprayed.
    method = db.Column(db.String(255))
    findings = db.Column(db.Text)
    action = db.Column(db.Text)
    next_due = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ConstructionProject(db.Model):
    __tablename__ = "construction_projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    area = db.Column(db.String(200), nullable=False)
    contractor = db.Column(db.String(160))
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)
    state = db.Column(db.String(10), default="planned", nullable=False, index=True)
    #: EFS.08 ev. 2 — every department the work touches.
    departments = db.Column(db.String(400), nullable=False)
    #: EFS.08 (a)–(h) — one level and one measure per item, as JSON
    #: ``{"noise": {"risk": "high", "measure": "..."}}``.
    assessment = db.Column(db.JSON, nullable=False, default=dict)
    #: The ICRA class the infection-control team gave the work.
    icra_class = db.Column(db.String(20))
    #: EFS.08 ev. 4 — the work permit: nothing starts before it.
    permit_by = db.Column(db.String(160))
    permit_on = db.Column(db.Date)
    assessed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    checks = db.relationship("ConstructionCheck", back_populates="project",
                             order_by="ConstructionCheck.checked_on.desc()",
                             cascade="all, delete-orphan")


class ConstructionCheck(db.Model):
    """EFS.08 ev. 3 and 5 — the work watched: were the measures kept, was
    the contractor compliant, and what was done when not."""
    __tablename__ = "construction_checks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("construction_projects.id"),
                           nullable=False, index=True)
    checked_on = db.Column(db.Date, nullable=False)
    compliant = db.Column(db.Boolean, nullable=False)
    note = db.Column(db.Text, nullable=False)
    action = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    project = db.relationship("ConstructionProject", back_populates="checks")


#: EFS.09 (c) — who comes in who is not a patient or staff.
VISITOR_KINDS = ("visitor", "vendor", "contractor", "other")


class RestrictedArea(db.Model):
    __tablename__ = "restricted_areas"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    #: Who may enter, and on what condition, in the hospital's words.
    rule = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class VisitorPass(db.Model):
    __tablename__ = "visitor_passes"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(12), nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    #: The company, for a vendor or a contractor.
    company = db.Column(db.String(160))
    #: Whom or what they came for — a ward, a department, a job.
    visiting = db.Column(db.String(200), nullable=False)
    badge_no = db.Column(db.String(30), nullable=False)
    #: Where they may go. A restricted area needs its permission written.
    allowed = db.Column(db.String(255))
    area_id = db.Column(db.Integer, db.ForeignKey("restricted_areas.id"))
    permitted_by = db.Column(db.String(160))
    in_at = db.Column(db.DateTime, nullable=False, index=True)
    out_at = db.Column(db.DateTime)
    signed_in_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    area = db.relationship("RestrictedArea")
