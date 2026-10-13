"""The building's own safety records — GAHAR EFS.03 / GSR.23, EFS.04 /
GSR.24, EFS.09 (the abduction drill), EFS.11 / GSR.28, EFS.12 (the water
analyses) and EFS.13 (the disaster drill).

The plans themselves (fire and smoke, utilities) are documents the hospital
writes and approves; the program keeps the records the evidence asks to see:

* :class:`FireDrill` — EFS.04: date and time, shift, areas, announced or
  not, who took part, the evaluation and the corrective action;
* :class:`FireSystemCheck` — EFS.03 evidence 5: inspection, testing and
  maintenance of the alarm, detection, suppression, extinguishers, smoke
  containment and the exit paths;
* :class:`FireTraining` — EFS.03 evidence 2: who was trained, and when;
* :class:`UtilitySystem` / :class:`UtilityCheck` — EFS.11: the inventory of
  essential utilities, which are critical and their backup, and every
  inspection, test, maintenance, generator test, water tank cleaning, water
  sample and alarm test.

Kept, never edited or deleted.
"""
from datetime import datetime

from app.extensions import db

SHIFTS = ("morning", "evening", "night")
#: What a drill rehearses: fire (EFS.04), a child taken (EFS.09 g) and a
#: disaster (EFS.13 h). One record, because the evidence is the same — when,
#: where, who, what was seen and what is to be done about it.
DRILL_KINDS = ("fire", "abduction", "disaster")
#: What a member of staff was trained on, a year at a time: fire (EFS.03),
#: hazardous materials and waste (EFS.06), the safety plan (EFS.07), the
#: security plan (EFS.09) and the emergency plan (EFS.13).
TRAINING_TOPICS = ("fire", "hazmat", "safety", "security", "emergency")
#: EFS.03 (b)–(d): what a fire system check is about.
FIRE_SYSTEMS = ("alarm", "detection", "suppression", "extinguisher",
                "smoke_containment", "exit_path")
RESULTS = ("pass", "fail")
#: EFS.11 (a): the essential utilities, by kind.
UTILITY_KINDS = ("electricity", "generator", "water", "medical_gas", "hvac",
                 "elevator", "nurse_call", "other")
#: EFS.11 (d)–(h): what was done to a utility.
UTILITY_CHECKS = ("inspection", "test", "maintenance", "generator_load",
                  "generator_no_load", "water_tank", "water_sample",
                  "alarm_test",
                  # EFS.12 ev. 3 — the chemical and microbiological analyses
                  # of the water, and of the dialysis water where there is any.
                  "water_chemical", "water_micro", "dialysis_water")

drill_participants = db.Table(
    "fire_drill_participants",
    db.Column("drill_id", db.Integer, db.ForeignKey("fire_drills.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class FireDrill(db.Model):
    __tablename__ = "fire_drills"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(12), default="fire", nullable=False, index=True)
    held_at = db.Column(db.DateTime, nullable=False, index=True)
    shift = db.Column(db.String(10), nullable=False)
    areas = db.Column(db.String(400), nullable=False)
    unannounced = db.Column(db.Boolean, default=False, nullable=False)
    #: Minutes until the area was clear, if it was timed.
    evacuation_minutes = db.Column(db.Integer)
    #: People who took part and have no account (visitors, contractors).
    others = db.Column(db.Integer)
    evaluation = db.Column(db.Text, nullable=False)
    corrective_action = db.Column(db.Text, nullable=False)
    #: EFS.13 (h) i–v — the scenario, what was seen (the code, the timing,
    #: who came, the response, the communication, the triage and the clinical
    #: management), the debriefing, and when the committee was told.
    scenario = db.Column(db.Text)
    observations = db.Column(db.Text)
    debrief = db.Column(db.Text)
    committee_told_on = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    participants = db.relationship("User", secondary=drill_participants)


class FireSystemCheck(db.Model):
    __tablename__ = "fire_system_checks"

    id = db.Column(db.Integer, primary_key=True)
    system = db.Column(db.String(20), nullable=False, index=True)
    location = db.Column(db.String(160))
    checked_on = db.Column(db.Date, nullable=False, index=True)
    #: Inspection, test or maintenance, and by whom (the company or person).
    done_by = db.Column(db.String(160))
    result = db.Column(db.String(8), nullable=False)
    details = db.Column(db.Text)
    action = db.Column(db.Text)
    next_due = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FireTraining(db.Model):
    __tablename__ = "fire_training"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    topic = db.Column(db.String(12), default="fire", nullable=False, index=True)
    trained_on = db.Column(db.Date, nullable=False, index=True)
    trainer = db.Column(db.String(160))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])


class UtilitySystem(db.Model):
    __tablename__ = "utility_systems"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False, index=True)
    location = db.Column(db.String(160))
    #: EFS.11 (j) — critical, and what takes over when it fails.
    is_critical = db.Column(db.Boolean, default=False, nullable=False)
    backup = db.Column(db.String(200))
    #: The manufacturer's or the plan's interval for a check, in days — with
    #: none, nothing is called overdue.
    check_every_days = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    checks = db.relationship("UtilityCheck", back_populates="system",
                             order_by="UtilityCheck.done_on.desc()",
                             cascade="all, delete-orphan")


class UtilityCheck(db.Model):
    __tablename__ = "utility_checks"

    id = db.Column(db.Integer, primary_key=True)
    system_id = db.Column(db.Integer, db.ForeignKey("utility_systems.id"),
                          nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    done_on = db.Column(db.Date, nullable=False, index=True)
    done_by = db.Column(db.String(160))
    result = db.Column(db.String(8), nullable=False)
    details = db.Column(db.Text)
    action = db.Column(db.Text)
    #: EFS.11 (g) — the generator's fuel, as read, in the hospital's words.
    fuel = db.Column(db.String(60))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    system = db.relationship("UtilitySystem", back_populates="checks")
