"""A report somebody built and kept (REPORTS_PLAN.md ت-٢).

What is kept is the builder's question — its arguments, as a query string — not the numbers:
opening a saved report runs it again on today's data, with the permissions of
whoever opens it. A shared report a colleague may not run (money, for
somebody without the finance rights) says so instead of showing anything.
"""
from datetime import datetime

from app.extensions import db


class SavedReport(db.Model):
    __tablename__ = "saved_reports"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Seen by everyone who can open the builder, not only its owner.
    shared = db.Column(db.Boolean, default=False, nullable=False)
    args = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    owner = db.relationship("User")

    def __repr__(self):
        return f"<SavedReport {self.id} {self.name!r}>"
