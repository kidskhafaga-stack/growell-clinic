"""Hand hygiene — GAHAR IPC.04 / GSR.22.

The policy itself (techniques, indications, PPE, nails and jewellery) is a
document the hospital writes and approves; the program keeps the evidence
that it is lived:

* :class:`HandHygieneSession` and :class:`HandHygieneOpportunity` — the WHO
  observation tool (evidence 3 and 6): an observer stands in one area for a
  while and writes, for each opportunity, who (the staff category, never the
  name), which of the five moments, and what was done — rub, wash or missed.
  Compliance is actions over opportunities, the WHO's own formula;
* :class:`HandHygieneFacilityCheck` — evidence 4 and 5: in each area, a
  working sink, soap, single-use towels, alcohol rub, the poster and a waste
  basket — and, for anything missing, what was done about it;
* :class:`HandHygieneAction` — evidence 6: what the hospital decided on a
  month's results, for one area or the whole hospital;
* :class:`HandHygieneTraining` — evidence 2: who was trained, when, by whom.

Kept, never edited or deleted: these are the records a surveyor reads.
"""
from datetime import datetime

from app.extensions import db

#: The WHO's five moments, in the WHO's order.
MOMENTS = (1, 2, 3, 4, 5)
RUB, WASH, MISSED = ("rub", "wash", "missed")
ACTIONS = (RUB, WASH, MISSED)
#: The WHO observation form's professional categories.
CATEGORIES = ("doctor", "nurse", "technician", "student", "other")
#: What a hand hygiene station needs (IPC.04 intent, evidence 4–5).
FACILITY_ITEMS = ("sink", "soap", "towels", "rub", "poster", "waste")


class _Area:
    """An area is a care unit where the hospital has them, else what the
    observer wrote — so a clinic without wards can still say «the
    vaccination room»."""

    def area_name(self, lang="ar"):
        if self.unit is not None:
            return self.unit.display_name(lang)
        return self.area or "—"

    @property
    def area_key(self):
        return ("u", self.unit_id) if self.unit_id else ("a", (self.area or "").strip())


class HandHygieneSession(_Area, db.Model):
    __tablename__ = "hand_hygiene_sessions"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"), index=True)
    area = db.Column(db.String(120))
    observed_on = db.Column(db.Date, nullable=False, index=True)
    observer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    note = db.Column(db.Text)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unit = db.relationship("Unit")
    observer = db.relationship("User")
    opportunities = db.relationship("HandHygieneOpportunity", back_populates="session",
                                    order_by="HandHygieneOpportunity.id",
                                    cascade="all, delete-orphan")


class HandHygieneOpportunity(db.Model):
    __tablename__ = "hand_hygiene_opportunities"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("hand_hygiene_sessions.id"),
                           nullable=False, index=True)
    category = db.Column(db.String(16), nullable=False)
    #: One opportunity can answer more than one moment (the WHO form lets the
    #: observer tick several) — kept as the digits, ``"14"`` for 1 and 4.
    moments = db.Column(db.String(8), nullable=False)
    action = db.Column(db.String(8), nullable=False)
    #: Gloves on in place of hand hygiene — the WHO form's own box.
    gloves = db.Column(db.Boolean, default=False, nullable=False)

    session = db.relationship("HandHygieneSession", back_populates="opportunities")

    @property
    def done(self):
        return self.action in (RUB, WASH)


class HandHygieneFacilityCheck(_Area, db.Model):
    __tablename__ = "hand_hygiene_facility_checks"

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"), index=True)
    area = db.Column(db.String(120))
    checked_on = db.Column(db.Date, nullable=False, index=True)
    sink = db.Column(db.Boolean, default=False, nullable=False)
    soap = db.Column(db.Boolean, default=False, nullable=False)
    towels = db.Column(db.Boolean, default=False, nullable=False)
    rub = db.Column(db.Boolean, default=False, nullable=False)
    poster = db.Column(db.Boolean, default=False, nullable=False)
    waste = db.Column(db.Boolean, default=False, nullable=False)
    #: Required when anything is missing.
    action = db.Column(db.Text)
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unit = db.relationship("Unit")
    checker = db.relationship("User")

    @property
    def missing(self):
        return [k for k in FACILITY_ITEMS if not getattr(self, k)]


class HandHygieneAction(_Area, db.Model):
    __tablename__ = "hand_hygiene_actions"

    id = db.Column(db.Integer, primary_key=True)
    #: The first day of the month the results belong to.
    month = db.Column(db.Date, nullable=False, index=True)
    #: Neither set: the whole hospital.
    unit_id = db.Column(db.Integer, db.ForeignKey("care_units.id"))
    area = db.Column(db.String(120))
    finding = db.Column(db.Text, nullable=False)
    action = db.Column(db.Text, nullable=False)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    unit = db.relationship("Unit")
    recorder = db.relationship("User")


class HandHygieneTraining(db.Model):
    __tablename__ = "hand_hygiene_training"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    trained_on = db.Column(db.Date, nullable=False)
    trainer = db.Column(db.String(160))
    valid_until = db.Column(db.Date)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
