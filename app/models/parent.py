"""Parent / guardian records belonging to a family.

``client_category`` drives discount eligibility in the finance phase, so it is
captured here from day one.
"""
from datetime import datetime

from app.extensions import db

# Relation of the guardian to the child.
PARENT_RELATIONS = ["father", "mother", "guardian"]

# Client categories that influence discounts later (normal/friend/relative/employee).
CLIENT_CATEGORIES = ["normal", "friend", "relative", "employee"]


class Parent(db.Model):
    __tablename__ = "parents"

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(
        db.Integer, db.ForeignKey("families.id"), nullable=False, index=True
    )

    relation = db.Column(db.String(20), nullable=False, default="father")
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))
    national_id = db.Column(db.String(20))
    phone = db.Column(db.String(30))
    phone_alt = db.Column(db.String(30))
    email = db.Column(db.String(120))
    occupation = db.Column(db.String(120))
    address = db.Column(db.String(255))

    client_category = db.Column(db.String(20), default="normal", nullable=False)
    is_primary_contact = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    family = db.relationship("Family", back_populates="parents")

    def display_name(self, lang="ar"):
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    @staticmethod
    def valid_relation(value):
        return value in PARENT_RELATIONS

    @staticmethod
    def valid_category(value):
        return value in CLIENT_CATEGORIES

    def __repr__(self):
        return f"<Parent {self.full_name} ({self.relation})>"
