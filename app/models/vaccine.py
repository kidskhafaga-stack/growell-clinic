"""Vaccine catalogue, brands and per-brand dose schedules (Phase 6).

A vaccine can have several brands (e.g. Rotavirus → RotaRix 2 doses /
RotaTeq 3 doses); each brand carries its own dose schedule and price. The
patient's administered doses are recorded in ``PatientVaccine``.
"""
from datetime import datetime

from app.extensions import db


class Vaccine(db.Model):
    __tablename__ = "vaccines"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    is_mandatory = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    brands = db.relationship(
        "VaccineBrand", back_populates="vaccine", cascade="all, delete-orphan",
        order_by="VaccineBrand.id",
    )

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name_ar

    @property
    def default_brand(self):
        for b in self.brands:
            if b.is_default:
                return b
        return self.brands[0] if self.brands else None

    def __repr__(self):
        return f"<Vaccine {self.code}>"


class VaccineBrand(db.Model):
    __tablename__ = "vaccine_brands"

    id = db.Column(db.Integer, primary_key=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    manufacturer = db.Column(db.String(120))
    price = db.Column(db.Float)              # selling price
    purchase_price = db.Column(db.Float)     # cost price
    max_discount = db.Column(db.Float)       # max allowed discount (%)
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    vaccine = db.relationship("Vaccine", back_populates="brands")
    doses = db.relationship(
        "VaccineBrandDose", back_populates="brand", cascade="all, delete-orphan",
        order_by="VaccineBrandDose.dose_number",
    )
    batches = db.relationship(
        "VaccineInventory", back_populates="brand", cascade="all, delete-orphan",
    )

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def doses_count(self):
        return len(self.doses)

    @property
    def stock(self):
        """Total remaining usable units across all batches."""
        return sum(b.qty_remaining for b in self.batches)

    @property
    def available_batches(self):
        """In-stock, non-expired batches, soonest expiry first."""
        from datetime import date as _date
        usable = [b for b in self.batches
                  if b.qty_remaining > 0 and (not b.expiry_date or b.expiry_date >= _date.today())]
        return sorted(usable, key=lambda b: (b.expiry_date or _date.max))

    def __repr__(self):
        return f"<VaccineBrand {self.name}>"


class VaccineBrandDose(db.Model):
    __tablename__ = "vaccine_brand_doses"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=False, index=True)
    dose_number = db.Column(db.Integer, nullable=False)
    age_months = db.Column(db.Integer, nullable=False)

    brand = db.relationship("VaccineBrand", back_populates="doses")

    def __repr__(self):
        return f"<BrandDose b={self.brand_id} #{self.dose_number}@{self.age_months}mo>"


class PatientVaccine(db.Model):
    __tablename__ = "patient_vaccines"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=False)
    dose_number = db.Column(db.Integer, nullable=False)

    given_date = db.Column(db.Date, nullable=False)
    lot_number = db.Column(db.String(60))
    # Inventory batch this dose was drawn from (clinic-administered only).
    inventory_id = db.Column(db.Integer, db.ForeignKey("vaccine_inventory.id"), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="patient_vaccines")
    vaccine = db.relationship("Vaccine")
    brand = db.relationship("VaccineBrand")
    batch = db.relationship("VaccineInventory")

    def __repr__(self):
        return f"<PatientVaccine p={self.patient_id} v={self.vaccine_id} #{self.dose_number}>"
