"""A teaching hospital's learners and its research — GAHAR ATH.02–ATH.09.

An opt-in module (``teaching``): a clinic that teaches nobody never sees it.

* :class:`Trainee` — a student, house officer, resident or fellow: the
  programme, the supervisor and mentor who answer for them, the scope they
  work within, the orientation (ATH.06 a–g) and the protected learning time;
* :class:`TrainingRotation` — each rotation with its supervisor and its
  evaluation and feedback (ATH.06 a);
* :class:`TraineeAssessment` — an assessment by a named assessor with an
  objective tool (ATH.07 ev. 4);
* :class:`TeachingConcern` — a learner's concern about safety or the
  standard of care, or an adverse event or near miss during teaching, and
  what was done about it (ATH.05 ev. 2, 3, 5);
* :class:`ResearchProtocol` — a study and its research ethics committee
  approval, its validity, and whether it involves children (ATH.08);
* :class:`ResearchParticipant` — a child enrolled, by the signed research
  consent on the child's own file (ATH.09 ev. 3), and withdrawn without
  question (d);
* :class:`ResearchSafetyEvent` — a safety issue found during a study: what,
  when the family was told and what was done (ATH.09 ev. 4).

Kept, never deleted.
"""
from datetime import datetime

from app.extensions import db

TRAINEE_KINDS = ("student", "house_officer", "resident", "fellow", "nursing_student", "other")
#: ATH.06 (a)–(g) — what the orientation covers.
ORIENTATION_ITEMS = ("rotations", "didactic", "supervision", "patient_care", "simulation",
                     "assessment", "policies")
#: ATH.07 ev. 4 — the objective tools an assessor uses.
ASSESSMENT_TOOLS = ("mini_cex", "dops", "cbd", "msf", "osce", "logbook", "other")
CONCERN_KINDS = ("safety", "standard_of_care", "adverse_event", "near_miss", "professionalism")
PROTOCOL_STATES = ("submitted", "approved", "rejected", "suspended", "closed")


class Trainee(db.Model):
    __tablename__ = "trainees"

    id = db.Column(db.Integer, primary_key=True)
    #: A learner with an account, or one without (a visiting student).
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(16), nullable=False, index=True)
    programme = db.Column(db.String(200))
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date)
    #: ATH.02 ev. 5, ATH.05 ev. 4 — the experienced supervisor who answers
    #: for them; ATH.02 ev. 3 — the mentor.
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    #: ATH.06 ev. 2 — what they may do, in the hospital's words.
    scope = db.Column(db.Text, nullable=False)
    #: ATH.06 ev. 1 — the items of the orientation done, ``{item: "date"}``.
    orientation = db.Column(db.JSON, nullable=False, default=dict)
    #: ATH.06 ev. 4 — protected learning time, as the programme sets it.
    protected_time = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    supervisor = db.relationship("User", foreign_keys=[supervisor_id])
    mentor = db.relationship("User", foreign_keys=[mentor_id])
    rotations = db.relationship("TrainingRotation", back_populates="trainee",
                                order_by="TrainingRotation.starts_on.desc()", cascade="all, delete-orphan")
    assessments = db.relationship("TraineeAssessment", back_populates="trainee",
                                  order_by="TraineeAssessment.on.desc()", cascade="all, delete-orphan")


class TrainingRotation(db.Model):
    __tablename__ = "training_rotations"

    id = db.Column(db.Integer, primary_key=True)
    trainee_id = db.Column(db.Integer, db.ForeignKey("trainees.id"), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"))
    department = db.Column(db.String(160), nullable=False)
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    evaluation = db.Column(db.Text)
    #: The trainee's own feedback on the rotation.
    feedback = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime)

    trainee = db.relationship("Trainee", back_populates="rotations")
    supervisor = db.relationship("User", foreign_keys=[supervisor_id])


class TraineeAssessment(db.Model):
    __tablename__ = "trainee_assessments"

    id = db.Column(db.Integer, primary_key=True)
    trainee_id = db.Column(db.Integer, db.ForeignKey("trainees.id"), nullable=False, index=True)
    on = db.Column(db.Date, nullable=False)
    tool = db.Column(db.String(10), nullable=False)
    assessor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    result = db.Column(db.String(120), nullable=False)
    comments = db.Column(db.Text)

    trainee = db.relationship("Trainee", back_populates="assessments")
    assessor = db.relationship("User", foreign_keys=[assessor_id])


class TeachingConcern(db.Model):
    __tablename__ = "teaching_concerns"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(18), nullable=False)
    raised_on = db.Column(db.Date, nullable=False, index=True)
    #: As the learner chose to be named — or not.
    raised_by = db.Column(db.String(160))
    concern = db.Column(db.Text, nullable=False)
    #: The incident report it became, when it is one (QPI.10).
    incident_id = db.Column(db.Integer, db.ForeignKey("incidents.id"))
    action = db.Column(db.Text)
    closed_on = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class ResearchProtocol(db.Model):
    __tablename__ = "research_protocols"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    investigator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    state = db.Column(db.String(10), default="submitted", nullable=False, index=True)
    #: ATH.08 ev. 4 — the research ethics committee's decision.
    rec_reference = db.Column(db.String(60))
    approved_on = db.Column(db.Date)
    valid_until = db.Column(db.Date)
    decision_note = db.Column(db.Text)
    involves_children = db.Column(db.Boolean, default=True, nullable=False)
    #: ATH.09 (a) — who may be enrolled.
    eligibility = db.Column(db.Text, nullable=False)
    file = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    investigator = db.relationship("User", foreign_keys=[investigator_id])
    participants = db.relationship("ResearchParticipant", back_populates="protocol",
                                   order_by="ResearchParticipant.enrolled_on.desc()",
                                   cascade="all, delete-orphan")


class ResearchParticipant(db.Model):
    __tablename__ = "research_participants"
    __table_args__ = (db.UniqueConstraint("protocol_id", "patient_id", name="uq_research_participant"),)

    id = db.Column(db.Integer, primary_key=True)
    protocol_id = db.Column(db.Integer, db.ForeignKey("research_protocols.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    #: ATH.09 ev. 3 — the guardian's signed research consent, on the child's
    #: own file; the study file points at it.
    consent_id = db.Column(db.Integer, db.ForeignKey("consents.id"), nullable=False)
    enrolled_on = db.Column(db.Date, nullable=False)
    enrolled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    withdrawn_on = db.Column(db.Date)
    withdrawn_note = db.Column(db.String(255))

    protocol = db.relationship("ResearchProtocol", back_populates="participants")
    patient = db.relationship("Patient")
    consent = db.relationship("Consent")
    events = db.relationship("ResearchSafetyEvent", back_populates="participant",
                             order_by="ResearchSafetyEvent.on.desc()", cascade="all, delete-orphan")


class ResearchSafetyEvent(db.Model):
    __tablename__ = "research_safety_events"

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey("research_participants.id"),
                               nullable=False, index=True)
    on = db.Column(db.Date, nullable=False)
    what = db.Column(db.Text, nullable=False)
    family_told_on = db.Column(db.Date, nullable=False)
    action = db.Column(db.Text, nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    participant = db.relationship("ResearchParticipant", back_populates="events")
