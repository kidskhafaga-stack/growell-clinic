"""Patient model — the core clinical record.

The file number (``patient_number``) can be entered manually (to preserve
legacy numbers) or generated automatically as ``PM-YYYY-NNNN``.
"""
from datetime import date, datetime

from app.extensions import db

GENDERS = ["male", "female"]
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    patient_number = db.Column(
        db.String(40), unique=True, nullable=False, index=True
    )

    family_id = db.Column(
        db.Integer, db.ForeignKey("families.id"), nullable=True, index=True
    )

    # Bilingual names.
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))

    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    national_id = db.Column(db.String(20))
    blood_type = db.Column(db.String(5))
    photo = db.Column(db.String(255))

    # Medical alerts surfaced prominently on the profile.
    allergies = db.Column(db.Text)
    chronic_diseases = db.Column(db.Text)
    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    family = db.relationship("Family", back_populates="patients")

    # --- Display helpers ---------------------------------------------------
    def display_name(self, lang="ar"):
        if lang == "en" and self.full_name_en:
            return self.full_name_en
        return self.full_name

    @property
    def age_parts(self):
        """Return (years, months) since birth — accurate for pediatric ages."""
        if not self.date_of_birth:
            return (0, 0)
        today = date.today()
        years = today.year - self.date_of_birth.year
        months = today.month - self.date_of_birth.month
        if today.day < self.date_of_birth.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        return (max(years, 0), max(months, 0))

    @property
    def age_days(self):
        if not self.date_of_birth:
            return 0
        return (date.today() - self.date_of_birth).days

    @property
    def has_alerts(self):
        return bool((self.allergies or "").strip() or (self.chronic_diseases or "").strip())

    @property
    def siblings(self):
        """Other active patients in the same family."""
        if not self.family_id or not self.family:
            return []
        return [p for p in self.family.patients if p.id != self.id]

    @staticmethod
    def valid_gender(value):
        return value in GENDERS

    def __repr__(self):
        return f"<Patient {self.patient_number} {self.full_name}>"
