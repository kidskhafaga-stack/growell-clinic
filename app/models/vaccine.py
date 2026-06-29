"""Vaccine catalogue, brands and per-brand dose schedules (Phase 6).

A vaccine can have several brands (e.g. Rotavirus → RotaRix 2 doses /
RotaTeq 3 doses); each brand carries its own dose schedule and price. The
patient's administered doses are recorded in ``PatientVaccine``.
"""
from datetime import datetime

from app.extensions import db

# Administration routes (طريقة الإعطاء).
VACCINE_ROUTES = ["IM", "SC", "ID", "oral", "intranasal"]

# Documentation outcome of a dose event (PDF clinical notes).
VACCINE_EVENT_TYPES = ["given", "refused", "delayed"]


class Vaccine(db.Model):
    __tablename__ = "vaccines"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    is_mandatory = db.Column(db.Boolean, default=True, nullable=False)
    # Given only when indicated (post-exposure / travel) — e.g. rabies, yellow
    # fever, cholera. Never suggested routinely by age; only added on purpose.
    on_demand = db.Column(db.Boolean, default=False, nullable=False)
    route = db.Column(db.String(20))  # طريقة الإعطاء: IM/SC/ID/oral/intranasal
    sort_order = db.Column(db.Integer, default=0)

    # Lifecycle: a vaccine may stop production and be replaced by a newer one.
    is_discontinued = db.Column(db.Boolean, default=False, nullable=False)
    replaced_by_id = db.Column(
        db.Integer, db.ForeignKey("vaccines.id"), nullable=True
    )
    replaced_by = db.relationship("Vaccine", remote_side=[id])

    # Medical metadata (PDF "Medical Information"). All optional / additive.
    diseases_covered = db.Column(db.String(255))      # الأمراض المغطّاة
    min_age_months = db.Column(db.Integer)            # أدنى عمر
    max_age_months = db.Column(db.Integer)            # أقصى عمر
    booster_required = db.Column(db.Boolean, default=False, nullable=False)
    is_seasonal = db.Column(db.Boolean, default=False, nullable=False)  # تطعيم موسمي
    pregnancy_recommendation = db.Column(db.String(120))   # توصية الحمل
    risk_groups = db.Column(db.String(255))           # فئات الخطر
    contraindications = db.Column(db.Text)            # موانع الإعطاء
    adverse_events_info = db.Column(db.Text)          # الأعراض الجانبية المحتملة

    brands = db.relationship(
        "VaccineBrand", back_populates="vaccine", cascade="all, delete-orphan",
        order_by="VaccineBrand.id",
    )
    schedule_templates = db.relationship(
        "VaccineScheduleTemplate", back_populates="vaccine",
        cascade="all, delete-orphan", order_by="VaccineScheduleTemplate.sort_order",
    )

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name_ar

    @property
    def default_brand(self):
        """Preferred brand for a new course: the marked default if still
        available, else the first non-discontinued brand, else any brand."""
        active = [b for b in self.brands if not b.is_discontinued]
        for b in active:
            if b.is_default:
                return b
        if active:
            return active[0]
        return self.brands[0] if self.brands else None

    @property
    def active_brands(self):
        return [b for b in self.brands if not b.is_discontinued]

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
    doctor_fee = db.Column(db.Float)         # part of the price that goes to the doctor
    max_discount = db.Column(db.Float)       # max allowed discount (%)
    # Patient doses obtained from one purchased vial/ampoule. 1 = single-dose
    # ampoule (one vial per patient); >1 = multi-dose vial (e.g. a vial drawn
    # for 10 patients). Stock is always counted in patient doses.
    doses_per_vial = db.Column(db.Integer, default=1, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_discontinued = db.Column(db.Boolean, default=False, nullable=False)  # production stopped

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
        """Total remaining usable patient doses across all batches."""
        return sum(b.qty_remaining for b in self.batches)

    @property
    def is_multidose(self):
        return (self.doses_per_vial or 1) > 1

    @property
    def stock_vials(self):
        """Whole vials still on the shelf (multi-dose only), rounded down."""
        per = self.doses_per_vial or 1
        return self.stock // per if per > 1 else self.stock

    @property
    def clinic_margin(self):
        """Clinic profit per dose = sell price − cost − doctor's fee."""
        return round((self.price or 0) - (self.purchase_price or 0) - (self.doctor_fee or 0), 2)

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


class VaccineScheduleTemplate(db.Model):
    """A named dosing schedule for a vaccine (PDF "Vaccine Schedule Templates").

    Schedules are kept *out* of the vaccine record (per the PDF) so the same
    vaccine can carry several schedules — e.g. PCV13 Schedule A (start at 2
    months) vs. Schedule C (start at 12 months) for catch-up. Each template
    holds an ordered list of dose rows with recommended age and min/max
    intervals from the previous dose.
    """
    __tablename__ = "vaccine_schedule_templates"

    id = db.Column(db.Integer, primary_key=True)
    vaccine_id = db.Column(
        db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True
    )
    code = db.Column(db.String(20), nullable=False)   # A / B / C / D / standard
    label = db.Column(db.String(120))                 # "Start at 2 months"
    age_group = db.Column(db.String(120))             # "2-6 months"
    is_catch_up = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    vaccine = db.relationship("Vaccine", back_populates="schedule_templates")
    doses = db.relationship(
        "VaccineScheduleDose", back_populates="template",
        cascade="all, delete-orphan", order_by="VaccineScheduleDose.dose_number",
    )

    def __repr__(self):
        return f"<ScheduleTemplate v={self.vaccine_id} {self.code}>"


class VaccineScheduleDose(db.Model):
    """One dose row within a :class:`VaccineScheduleTemplate`."""
    __tablename__ = "vaccine_schedule_doses"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("vaccine_schedule_templates.id"),
        nullable=False, index=True,
    )
    dose_number = db.Column(db.Integer, nullable=False)
    recommended_age_months = db.Column(db.Integer)    # العمر الموصى به
    min_interval_days = db.Column(db.Integer)         # أدنى فاصل من الجرعة السابقة
    max_interval_days = db.Column(db.Integer)         # أقصى فاصل من الجرعة السابقة
    booster_required = db.Column(db.Boolean, default=False, nullable=False)

    template = db.relationship("VaccineScheduleTemplate", back_populates="doses")

    def __repr__(self):
        return f"<ScheduleDose t={self.template_id} #{self.dose_number}>"


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

    # Doctor credited with the dose (for the doctor's vaccine share / statement).
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    # Invoice this dose was billed on (NULL = not charged yet).
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True, index=True)
    # Dose the doctor confirms was given elsewhere (gov. unit / another clinic):
    # informational only — no stock deduction, no charge, no doctor fee.
    given_outside = db.Column(db.Boolean, default=False, nullable=False)

    # Clinical documentation (PDF): given / refused / delayed, plus details.
    event_type = db.Column(db.String(20), default="given", nullable=False)
    adverse_events = db.Column(db.Text)        # ملاحظات الأعراض الجانبية بعد الجرعة
    refusal_reason = db.Column(db.String(200))  # سبب الرفض / التأجيل
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="patient_vaccines")
    vaccine = db.relationship("Vaccine")
    brand = db.relationship("VaccineBrand")
    batch = db.relationship("VaccineInventory")
    doctor = db.relationship("User")

    def __repr__(self):
        return f"<PatientVaccine p={self.patient_id} v={self.vaccine_id} #{self.dose_number}>"
