"""Named (reusable) discounts that layer on top of manual line discounts.

Unlike a one-off manual discount typed on an invoice line, a named discount is
defined once and applied by name: a clinic campaign (with a date window), a
doctor's discount, a client-category discount (relatives / friends / staff), or
a special discount. It reuses the same effective-date idea as payer contracts.
"""
from datetime import date, datetime

from app.extensions import db

DISCOUNT_TYPES = ["campaign", "doctor", "category", "special"]


class NamedDiscount(db.Model):
    __tablename__ = "named_discounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    dtype = db.Column(db.String(12), default="special", nullable=False)

    value = db.Column(db.Float, default=0, nullable=False)
    is_percent = db.Column(db.Boolean, default=True, nullable=False)

    # Scope: a doctor (doctor type) or a client category (category type).
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    client_category = db.Column(db.String(20))

    # Optional validity window (used by campaigns; open-ended otherwise).
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def in_window(self, on_date=None):
        d = on_date or date.today()
        return ((not self.start_date or self.start_date <= d)
                and (not self.end_date or d <= self.end_date))

    def applies_to(self, patient=None, doctor_id=None, on_date=None):
        """Eligibility check for an invoice context."""
        if not self.is_active or not self.in_window(on_date):
            return False
        if self.dtype == "doctor":
            return self.doctor_id is not None and self.doctor_id == doctor_id
        if self.dtype == "category":
            cat = patient.client_category if patient else None
            return self.client_category is not None and self.client_category == cat
        # campaign / special apply broadly.
        return True

    def amount_for(self, gross):
        """Discount amount this rule yields for a given line gross."""
        gross = max(gross or 0, 0)
        if self.is_percent:
            return round(gross * (self.value or 0) / 100.0, 2)
        return round(min(self.value or 0, gross), 2)

    def __repr__(self):
        return f"<NamedDiscount {self.name} {self.dtype}>"
