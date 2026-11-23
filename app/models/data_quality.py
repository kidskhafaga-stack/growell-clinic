"""The data-quality score, kept day by day (``utils/data_quality``).

One row per day and section (``all`` for the overall score): the latest
reading that day. The checks themselves are counted live; this is only what
lets the improvement show (SMART_PATTERNS_PLAN ج-١).
"""
from datetime import datetime

from app.extensions import db


class DqDaily(db.Model):
    __tablename__ = "dq_daily"
    __table_args__ = (db.UniqueConstraint("day", "section", name="uq_dq_daily_day_section"),)

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, nullable=False, index=True)
    section = db.Column(db.String(24), nullable=False)
    #: ``None`` — nothing to score that day.
    score = db.Column(db.Float)
    at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
