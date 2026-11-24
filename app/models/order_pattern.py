"""A doctor's own habits with a diagnosis — SMART_PATTERNS_PLAN ج-٣.

«When I write this diagnosis, what do I usually order?» counted from the
doctor's own visits of the last 18 months, once a day, and kept here so the
visit screen reads a ready answer. Not advice: a count of what this doctor
(or, for a doctor new to the diagnosis, the clinic's doctors together) did.
"""
from datetime import datetime

from app.extensions import db

KINDS = ("test", "drug")
ACTIONS = ("shown", "taken", "never")


class OrderPattern(db.Model):
    __tablename__ = "order_patterns"

    id = db.Column(db.Integer, primary_key=True)
    #: ``None`` — the clinic's doctors together («زملاءك»).
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    #: The ICD code as written, or its three-character category.
    dx_key = db.Column(db.String(12), nullable=False, index=True)
    kind = db.Column(db.String(8), nullable=False)
    #: ``investigations.id`` or ``drugs.id``.
    item_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    #: The drug's usual frequency and duration with this diagnosis — never
    #: its dose, which is this child's, from today's weight.
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    #: Visits with the diagnosis, and how many of them had this item.
    visits = db.Column(db.Integer, nullable=False)
    seen = db.Column(db.Integer, nullable=False)
    share = db.Column(db.Float, nullable=False)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SuggestionFeedback(db.Model):
    """What a doctor did with a suggestion: shown, taken, or «مش عايز ده»."""

    __tablename__ = "suggestion_feedback"

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), index=True)
    dx_key = db.Column(db.String(12), nullable=False)
    kind = db.Column(db.String(8), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(8), nullable=False, index=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
