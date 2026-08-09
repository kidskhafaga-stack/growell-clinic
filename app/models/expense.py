"""Clinic expenses and the inputs for the P&L report.

A one-off expense is dated and counts in its month. A ``is_recurring`` expense
is a fixed monthly cost (rent, salaries…) and counts in every month's P&L
without re-entering it.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

EXPENSE_CATEGORIES = [
    "rent", "salaries", "utilities", "supplies",
    "maintenance", "marketing", "taxes", "other",
]


class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    expense_date = db.Column(
        db.Date, default=local_today, nullable=False, index=True
    )
    category = db.Column(db.String(20), default="other", nullable=False, index=True)
    description = db.Column(db.String(200))
    amount = db.Column(db.Float, default=0, nullable=False)

    # A fixed monthly cost that recurs every month (not tied to one month).
    is_recurring = db.Column(db.Boolean, default=False, nullable=False, index=True)
    # Optional active window for a recurring cost: it only counts in months
    # within [recur_start, recur_end]. Null bounds mean "since forever" /
    # "until cancelled", so an unbounded recurring expense behaves as before.
    recur_start = db.Column(db.Date)
    recur_end = db.Column(db.Date)

    def active_in(self, start, end):
        """Whether a recurring expense is active for the month spanning
        ``start``..``end`` (inclusive), honouring its optional window."""
        if not self.is_recurring:
            return False
        if self.recur_start and self.recur_start > end:
            return False
        if self.recur_end and self.recur_end < start:
            return False
        return True

    vendor = db.Column(db.String(120))
    payment_method = db.Column(db.String(20))
    # The till it was paid out of.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    # The open shift this cash left, so the drawer's expected count drops by
    # it. Null when it was not cash, or when no shift was open.
    shift_id = db.Column(db.Integer, db.ForeignKey("cashier_shifts.id"),
                         nullable=True, index=True)
    notes = db.Column(db.Text)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    creator = db.relationship("User")
    account = db.relationship("CashAccount")

    def __repr__(self):
        return f"<Expense {self.category} {self.amount}>"
