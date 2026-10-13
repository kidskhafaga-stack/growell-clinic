"""Being ready, and keeping the plans current — GAHAR EFS.01, EFS.13 and the
"approved and reviewed annually" that runs through EFS and OGM.

* :class:`EmergencyHazard` — EFS.13 (a)–(c): each emergency the hospital
  could face, internal, external or an epidemic, weighed by probability and
  impact as the hospital's own tool scores them, with how prepared it is;
* :class:`CallTreeEntry` — EFS.13 (d): who is called, in what order, by
  title and number, and the outside numbers (civil defence, the ambulance
  centre, the police);
* :class:`HospitalPlan` — every approved plan and policy the standards ask
  for (the fire plan, the hazardous-materials plan, the mission statement,
  the strategic plan…), when it was approved, by whom, and when it is due
  for review; EFS.01 ev. 6 and the annual review in each plan's intent;
* :class:`ExternalInspection` — EFS.01 ev. 2: civil defence or another
  authority's visit, what it found, the corrective plan, its deadline, and
  when it was closed.
"""
from datetime import datetime

from app.extensions import db

HAZARD_KINDS = ("internal", "external", "epidemic")
#: The plans and policies the standards name, by key. ``other`` for the
#: hospital's own.
PLAN_KINDS = ("fire", "hazmat", "safety", "security", "medical_equipment", "utilities",
              "water", "emergency", "smoking", "mission", "strategic", "operational",
              "quality", "staff_health", "supply_chain", "inventory", "billing",
              "ethics_code", "communication",
              # CAI.01, CAI.07 — the community programme and the advertising
              # process; ATH.03, ATH.04, ATH.06, ATH.07, ATH.09 — a teaching
              # hospital's curriculum and policies.
              "community", "advertising",
              "curriculum", "bedside_teaching", "orientation", "graduate", "research",
              "other")
#: The plans only a teaching hospital is asked for.
TEACHING_PLANS = ("curriculum", "bedside_teaching", "orientation", "graduate", "research")
#: EFS.01 / EFS.06–EFS.13 / OGM.02, 06, 07 — "reviewed annually".
REVIEW_MONTHS = 12


class EmergencyHazard(db.Model):
    __tablename__ = "emergency_hazards"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(10), nullable=False)
    #: Whole numbers on the scale of the tool the hospital adopted — the
    #: program fixes no scale, it only multiplies the two to rank them.
    probability = db.Column(db.Integer, nullable=False)
    impact = db.Column(db.Integer, nullable=False)
    preparedness = db.Column(db.Text)
    resources = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    assessed_on = db.Column(db.Date, nullable=False)
    assessed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    @property
    def score(self):
        return (self.probability or 0) * (self.impact or 0)


class CallTreeEntry(db.Model):
    __tablename__ = "call_tree"

    id = db.Column(db.Integer, primary_key=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    #: The title is what the tree is built on — whoever holds it tonight.
    title = db.Column(db.String(160), nullable=False)
    name = db.Column(db.String(160))
    phone = db.Column(db.String(40), nullable=False)
    #: Civil defence, the ambulance centre, the police.
    external = db.Column(db.Boolean, default=False, nullable=False)
    duty = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class HospitalPlan(db.Model):
    __tablename__ = "hospital_plans"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    approved_on = db.Column(db.Date, nullable=False)
    #: The governing body, the director, the committee.
    approved_by = db.Column(db.String(160), nullable=False)
    review_months = db.Column(db.Integer, default=REVIEW_MONTHS, nullable=False)
    file = db.Column(db.String(255))
    #: What changed in this version, from the last year's evaluation.
    changes = db.Column(db.Text)
    #: A newer version replaces this one; the old stays as history.
    replaced_by = db.Column(db.Integer, db.ForeignKey("hospital_plans.id"))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ExternalInspection(db.Model):
    __tablename__ = "external_inspections"

    id = db.Column(db.Integer, primary_key=True)
    authority = db.Column(db.String(160), nullable=False)
    visited_on = db.Column(db.Date, nullable=False, index=True)
    observations = db.Column(db.Text, nullable=False)
    corrective_plan = db.Column(db.Text, nullable=False)
    due_on = db.Column(db.Date)
    file = db.Column(db.String(255))
    closed_on = db.Column(db.Date)
    closed_note = db.Column(db.String(255))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
