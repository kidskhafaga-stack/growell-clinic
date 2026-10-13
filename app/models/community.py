"""The hospital and its community — GAHAR CAI.01–CAI.08.

* :class:`CommunityPartner` — CAI.02: who the hospital works with, and the
  channel it reaches each one by;
* :class:`NeedsAssessment` — CAI.03: the population, the five needs
  (i)–(v), with whom it was done, when it was shared with the governing body
  and the partners, and the services planned on it; every two years
  (CAI.06 ev. 2 — the standard's figure);
* :class:`CommunityActivity` — CAI.04, CAI.05, CAI.08: health education, a
  screening, a national or international initiative, accreditation
  awareness, help to another hospital — with the partner, the need it
  answers, how many came and how satisfied they were (CAI.06 ev. 3);
* :class:`Advertisement` — CAI.07: every advertisement reviewed for accuracy
  and against the law and the syndicates' codes before it goes out, and what
  was done when one was not.

The programme itself is a document in the plans register.
"""
from datetime import datetime

from app.extensions import db

PARTNER_KINDS = ("health_authority", "municipality", "school", "ngo", "religious", "media",
                 "university", "other")
ACTIVITY_KINDS = ("health_education", "screening", "campaign", "initiative", "accreditation",
                  "peer_support", "other")
#: CAI.03 (b) i–v.
NEEDS = ("access", "hazards", "unmet", "education", "expectations")
#: CAI.06 ev. 2 — "every two years".
ASSESS_EVERY_MONTHS = 24

activity_partners = db.Table(
    "community_activity_partners",
    db.Column("activity_id", db.Integer, db.ForeignKey("community_activities.id"), primary_key=True),
    db.Column("partner_id", db.Integer, db.ForeignKey("community_partners.id"), primary_key=True),
)
assessment_partners = db.Table(
    "needs_assessment_partners",
    db.Column("assessment_id", db.Integer, db.ForeignKey("needs_assessments.id"), primary_key=True),
    db.Column("partner_id", db.Integer, db.ForeignKey("community_partners.id"), primary_key=True),
)


class CommunityPartner(db.Model):
    __tablename__ = "community_partners"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(18), nullable=False)
    contact = db.Column(db.String(160))
    #: CAI.02 ev. 2 — how the hospital reaches them.
    channel = db.Column(db.String(200), nullable=False)
    last_contact_on = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class NeedsAssessment(db.Model):
    __tablename__ = "needs_assessments"

    id = db.Column(db.Integer, primary_key=True)
    done_on = db.Column(db.Date, nullable=False, index=True)
    population = db.Column(db.Text, nullable=False)
    #: Primary (surveys, interviews) and secondary (registries, census) sources.
    sources = db.Column(db.Text, nullable=False)
    #: ``{need: text}`` for CAI.03 (b) i–v.
    findings = db.Column(db.JSON, nullable=False, default=dict)
    #: CAI.03 (c), ev. 4 — the services to provide or update.
    services_plan = db.Column(db.Text, nullable=False)
    shared_board_on = db.Column(db.Date)
    shared_partners_on = db.Column(db.Date)
    file = db.Column(db.String(255))
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    partners = db.relationship("CommunityPartner", secondary=assessment_partners)


class CommunityActivity(db.Model):
    __tablename__ = "community_activities"

    id = db.Column(db.Integer, primary_key=True)
    held_on = db.Column(db.Date, nullable=False, index=True)
    kind = db.Column(db.String(18), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    #: CAI.05 — the initiative it is part of (WHO, a national campaign).
    initiative = db.Column(db.String(200))
    #: CAI.04 ev. 3 — the assessed need it answers.
    need = db.Column(db.String(255))
    attendance = db.Column(db.Integer)
    #: CAI.06 ev. 3 — how many were asked, and how many were satisfied.
    surveyed = db.Column(db.Integer)
    satisfied = db.Column(db.Integer)
    #: CAI.05 ev. 3 — what was learnt about the community's health.
    learnt = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    partners = db.relationship("CommunityPartner", secondary=activity_partners)


class Advertisement(db.Model):
    __tablename__ = "advertisements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    channel = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    reviewed_on = db.Column(db.Date, nullable=False)
    reviewed_by = db.Column(db.String(160), nullable=False)
    #: CAI.07 ev. 2 — accurate, and within the law and the syndicates' codes.
    compliant = db.Column(db.Boolean, nullable=False)
    published_on = db.Column(db.Date)
    #: CAI.07 ev. 4 — when it was not: what was done.
    action = db.Column(db.Text)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
