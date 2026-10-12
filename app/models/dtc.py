"""The drug and therapeutics committee — GAHAR MMS.01 ev. 3 and 5, and
MMS.03 ev. 5 and 6.

* **meetings** with who attended, the minutes, and decisions with an owner
  and a date — a formulary addition or removal is a decision too (MMS.03
  ev. 5), naming the ingredient;
* **the annual review** of the programme (MMS.01 ev. 5), one per year, a
  line for each of the intent's elements (a)–(g), as the committee writes it;
* **shortages** announced to prescribers (MMS.03 ev. 6): the drug, since
  when, when expected back if known, and the alternative the committee
  names — never one the program suggests.
"""
from datetime import datetime

from app.extensions import db

DECISION_KINDS = ("general", "formulary_add", "formulary_remove")
#: MMS.01 intent (a)–(g).
REVIEW_ELEMENTS = ("planning", "selection", "storage", "ordering", "preparing",
                   "administration", "monitoring")


class DtcMeeting(db.Model):
    __tablename__ = "dtc_meetings"

    id = db.Column(db.Integer, primary_key=True)
    held_on = db.Column(db.Date, nullable=False, index=True)
    attendees = db.Column(db.Text, nullable=False)
    minutes = db.Column(db.Text, nullable=False)
    written_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    written_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    decisions = db.relationship("DtcDecision", back_populates="meeting",
                                order_by="DtcDecision.id", cascade="all, delete-orphan")


class DtcDecision(db.Model):
    __tablename__ = "dtc_decisions"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("dtc_meetings.id"), nullable=False, index=True)
    kind = db.Column(db.String(18), default="general", nullable=False)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"))
    text = db.Column(db.Text, nullable=False)
    owner = db.Column(db.String(120), nullable=False)
    due_on = db.Column(db.Date)
    done_at = db.Column(db.DateTime)
    done_note = db.Column(db.String(255))

    meeting = db.relationship("DtcMeeting", back_populates="decisions")
    generic = db.relationship("GenericDrug")


class DtcAnnualReview(db.Model):
    __tablename__ = "dtc_annual_reviews"

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    planning = db.Column(db.Text)
    selection = db.Column(db.Text)
    storage = db.Column(db.Text)
    ordering = db.Column(db.Text)
    preparing = db.Column(db.Text)
    administration = db.Column(db.Text)
    monitoring = db.Column(db.Text)
    signed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    signed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class DrugShortage(db.Model):
    __tablename__ = "drug_shortages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    started_on = db.Column(db.Date, nullable=False)
    expected_back = db.Column(db.String(60))
    alternative = db.Column(db.String(255))
    note = db.Column(db.String(255))
    announced_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    ended_at = db.Column(db.DateTime)
