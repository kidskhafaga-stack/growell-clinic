"""Key/value system settings.

A simple, future-proof store for clinic-wide configuration (clinic name,
default growth reference, currency, etc.) that admins can edit without code
changes. Values are stored as strings; callers cast as needed.
"""
from datetime import datetime

from app.extensions import db


class Setting(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @classmethod
    def get(cls, key, default=None):
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key, value):
        row = cls.query.filter_by(key=key).first()
        if row is None:
            row = cls(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)
        return row

    def __repr__(self):
        return f"<Setting {self.key}={self.value!r}>"
