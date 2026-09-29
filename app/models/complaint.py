"""A complaint, a suggestion or a thank-you — one numbered case each.

Asked as: *«قسم الشكاوى ده يبقى كامل ويقيس مدى رضاء العميل — كل شكوى تاخد
رقم ومتابعة وإيه اللي حصل فيها»*, and GAHAR ``PCC.16``: complaints and
suggestions, oral or written, through a defined process that tracks them
(b), names who answers (c), answers within a timeframe (d) and is monitored
(e).

Until now a complaint was a WhatsApp thread with the topic ``complaint``: it
could be assigned and closed, but it had no number to quote to the family, no
record of what was found or done, no deadline, and nothing asked the family
afterwards whether the answer satisfied them. The thread is still where the
conversation happens; this is the case file beside it.

**Anyone takes one, customer service owns it.** Reception writes down what a
parent said at the desk and hands them the number; the case lands with
customer service (``complaints_manage``), who contact the family, find out,
answer, and close. Registering is not handling, and a desk that books all
morning is not the desk that investigates.
"""
import secrets
from datetime import datetime, timedelta

from app.extensions import db

#: What was said. A suggestion and a thank-you go through the same book —
#: PCC.16 is "complaints and suggestions" — and are counted apart.
KINDS = ("complaint", "suggestion", "compliment")
#: How it reached the clinic.
CHANNELS = ("desk", "phone", "whatsapp", "survey", "paper", "online")
#: Which side of the clinic it is about — the survey's three, and "other".
SIDES = ("medical", "service", "finance", "other")
#: How serious. "serious" is harm or the risk of it: it is the one the
#: manager is told about, and the one that belongs in an incident report too.
SEVERITIES = ("normal", "important", "serious")
#: new → in_progress (somebody spoke to the family) → answered (they were
#: told what was found and done) → closed. Reopened goes back to in_progress.
STATUSES = ("new", "in_progress", "answered", "closed")
OPEN_STATUSES = ("new", "in_progress", "answered")
#: The timeline's entries.
EVENT_KINDS = ("opened", "assigned", "contacted", "note", "answered",
               "closed", "reopened", "rated", "message", "printed", "edited")


class Complaint(db.Model):
    __tablename__ = "complaints"

    id = db.Column(db.Integer, primary_key=True)
    # "C-2026-0001": what the family is told and what they quote back.
    number = db.Column(db.String(24), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default="complaint", index=True)
    channel = db.Column(db.String(12), nullable=False, default="desk")
    status = db.Column(db.String(12), nullable=False, default="new", index=True)
    severity = db.Column(db.String(12), nullable=False, default="normal")
    side = db.Column(db.String(12))

    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=True, index=True)
    # Nobody's name on it, by choice. PCC.16 asks for anonymous complaints to
    # be possible; a name typed in anyway is not kept.
    anonymous = db.Column(db.Boolean, nullable=False, default=False)
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(30))
    # The part of the clinic it is about — the same list the money is
    # counted by, so a unit's complaints and its revenue sit side by side.
    cost_centre_id = db.Column(db.Integer, db.ForeignKey("cost_centres.id"),
                               nullable=True, index=True)

    # In their words, and what they are asking for.
    description = db.Column(db.Text, nullable=False)
    wanted = db.Column(db.Text)

    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True,
                         index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,
                           nullable=False, index=True)
    first_contact_at = db.Column(db.DateTime)
    answered_at = db.Column(db.DateTime)
    closed_at = db.Column(db.DateTime, index=True)
    reopened_count = db.Column(db.Integer, nullable=False, default=0)

    # What customer service found, what was done about it, and what the
    # family was told — three different things, and a file that only has the
    # last one cannot show that anything changed.
    finding = db.Column(db.Text)
    action = db.Column(db.Text)
    answer = db.Column(db.Text)

    # The family's own verdict on how it was handled — the number that says
    # whether complaints are *solved*, not just closed.
    resolution_rating = db.Column(db.Integer)
    resolution_comment = db.Column(db.Text)
    rated_at = db.Column(db.DateTime)

    # The public link for the verdict.
    token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    # Where it came from, when it came from somewhere.
    feedback_id = db.Column(db.Integer, db.ForeignKey("feedback.id"),
                            nullable=True, index=True)
    thread_key = db.Column(db.String(40), index=True)

    patient = db.relationship("Patient")
    owner = db.relationship("User", foreign_keys=[owner_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    cost_centre = db.relationship("CostCentre")
    feedback = db.relationship("Feedback")
    events = db.relationship("ComplaintEvent", backref="complaint",
                             order_by="ComplaintEvent.at",
                             cascade="all, delete-orphan")

    @staticmethod
    def new_token():
        return secrets.token_urlsafe(16)[:32]

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    def contact_due(self, hours):
        return self.created_at + timedelta(hours=hours)

    def close_due(self, days):
        return self.created_at + timedelta(days=days)

    def who(self, lang="ar"):
        """The name to show: the patient's, the one they gave, or none."""
        if self.anonymous:
            return None
        if self.patient is not None:
            return self.patient.display_name(lang)
        return self.contact_name

    def __repr__(self):
        return f"<Complaint {self.number}>"


class ComplaintEvent(db.Model):
    """One line of what happened on a case, and who did it."""
    __tablename__ = "complaint_events"

    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id"),
                             nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    kind = db.Column(db.String(12), nullable=False)
    text = db.Column(db.Text)

    user = db.relationship("User")
