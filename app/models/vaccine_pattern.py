"""«اللي أخدوا A أخدوا X» — the clinic's own vaccine pattern (SMART_PATTERNS ج-٥).

Counted once a day from the doses given, and kept so a child's vaccination
screen reads a ready answer. A pair is kept only when it means something:
A given to 150 children or more, X in 35 % of them or more, and that 1.5
times X's share among all vaccinated children — the vaccination unit's
program's conditions, carried over as they were.
"""
from datetime import datetime

from app.extensions import db


class VaccinePattern(db.Model):
    __tablename__ = "vaccine_patterns"

    id = db.Column(db.Integer, primary_key=True)
    a_vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True)
    x_vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True)
    #: Children who had A, and of them those who had X too.
    with_a = db.Column(db.Integer, nullable=False)
    with_both = db.Column(db.Integer, nullable=False)
    #: P(X | A) and P(X), 0–1.
    share = db.Column(db.Float, nullable=False)
    base = db.Column(db.Float, nullable=False)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
