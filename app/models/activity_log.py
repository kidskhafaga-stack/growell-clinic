"""Audit trail of significant user actions.

Phase 1 records authentication and user-management events; later phases reuse
the same table for clinical and financial auditing.
"""
from datetime import datetime

from app.extensions import db


class ActivityLog(db.Model):
    __tablename__ = "activity_log"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(80), nullable=False)
    entity = db.Column(db.String(80))
    entity_id = db.Column(db.Integer)
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", backref="activities")

    @classmethod
    def record(cls, action, user_id=None, entity=None, entity_id=None,
               detail=None, ip_address=None):
        entry = cls(
            action=action,
            user_id=user_id,
            entity=entity,
            entity_id=entity_id,
            detail=detail,
            ip_address=ip_address,
        )
        db.session.add(entry)
        return entry

    def __repr__(self):
        return f"<ActivityLog {self.action} by {self.user_id}>"
