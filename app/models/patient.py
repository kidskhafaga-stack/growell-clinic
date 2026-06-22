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
    # System-generated professional code (always unique).
    patient_number = db.Column(
        db.String(40), unique=True, nullable=False, index=True
    )
    # The clinic's legacy/paper file number, kept as a searchable reference.
    # Not enforced unique so messy legacy data can be imported without loss.
    reference_number = db.Column(db.String(60), index=True)

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
    # Opaque token for public vaccination-certificate QR verification.
    qr_token = db.Column(db.String(32), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    family = db.relationship("Family", back_populates="patients")

    def ensure_qr_token(self):
        """Lazily assign a random verification token; returns it."""
        if not self.qr_token:
            import uuid
            self.qr_token = uuid.uuid4().hex
        return self.qr_token

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
    def active_coverage(self):
        """The patient's current valid membership/insurance, if any."""
        valid = [c for c in getattr(self, "coverages", []) if c.is_valid]
        if not valid:
            return None
        return sorted(valid, key=lambda c: c.created_at or datetime.min,
                      reverse=True)[0]

    @property
    def contact_phone(self):
        """Best contact number: primary guardian first, else any with a phone."""
        if not self.family or not self.family.parents:
            return None
        parents = sorted(self.family.parents,
                         key=lambda p: (0 if p.is_primary_contact else 1))
        for p in parents:
            if p.phone:
                return p.phone
        return None

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
