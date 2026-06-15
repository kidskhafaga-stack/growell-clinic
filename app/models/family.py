"""Family grouping — links parents and sibling patients under one record.

Families enable shared context (the same parents, sibling discounts later in
the finance phase, and a single family file across siblings).
"""
from datetime import datetime

from app.extensions import db


class Family(db.Model):
    __tablename__ = "families"

    id = db.Column(db.Integer, primary_key=True)
    # Family/last name and an optional human-friendly family file number.
    family_name = db.Column(db.String(120), nullable=False)
    family_name_en = db.Column(db.String(120))
    family_number = db.Column(db.String(40), unique=True, index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parents = db.relationship(
        "Parent", back_populates="family", cascade="all, delete-orphan"
    )
    patients = db.relationship("Patient", back_populates="family")

    def display_name(self, lang="ar"):
        if lang == "en" and self.family_name_en:
            return self.family_name_en
        return self.family_name

    @property
    def sibling_count(self):
        return len(self.patients)

    def __repr__(self):
        return f"<Family {self.family_name} ({self.id})>"
