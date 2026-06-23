"""Clinic expenses and the inputs for the P&L report.

A one-off expense is dated and counts in its month. A ``is_recurring`` expense
is a fixed monthly cost (rent, salaries…) and counts in every month's P&L
without re-entering it.
"""
from datetime import datetime

from app.extensions import db

EXPENSE_CATEGORIES = [
    "rent", "salaries", "utilities", "supplies",
    "maintenance", "marketing", "taxes", "other",
]


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(
        db.Date, default=lambda: datetime.utcnow().date(), nullable=False, index=True
    )
    category = db.Column(db.String(20), default="other", nullable=False, index=True)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, default=0, nullable=False)

    # A fixed monthly cost that recurs every month (not tied to one month).
    is_recurring = db.Column(db.Boolean, default=False, nullable=False, index=True)

    vendor = db.Column(db.String(120))
    payment_method = db.Column(db.String(20))
    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship("User")

    def __repr__(self):
        return f"<Expense {self.category} {self.amount}>"
