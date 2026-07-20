"""Vaccine catalogue, brands and per-brand dose schedules (Phase 6).

A vaccine can have several brands (e.g. Rotavirus → RotaRix 2 doses /
RotaTeq 3 doses); each brand carries its own dose schedule and price. The
patient's administered doses are recorded in ``PatientVaccine``.
"""
from datetime import datetime

from app.extensions import db

# Administration routes (طريقة الإعطاء).
VACCINE_ROUTES = ["IM", "SC", "ID", "oral", "intranasal"]

# Vaccine platform/type (نوع اللقاح).
VACCINE_TYPES = ["live", "inactivated", "conjugate", "toxoid", "subunit",
                 "polysaccharide", "recombinant", "mRNA", "combination"]

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
    # Extended professional catalogue fields (all optional / additive).
    vaccine_type = db.Column(db.String(40))           # حي / معطل / مقترن / توكسويد / وحدة / mRNA
    min_interval_days = db.Column(db.Integer)         # أدنى فاصل بين الجرعات
    catch_up_notes = db.Column(db.Text)               # شروط الجرعات التعويضية (catch-up)
    coadministration_notes = db.Column(db.Text)       # إمكانية الإعطاء مع لقاحات أخرى
    precautions = db.Column(db.Text)                  # الاحتياطات
    reference = db.Column(db.String(255))             # المصدر / المرجع للمعلومات

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

    @staticmethod
    def age_label(months, lang="ar"):
        """A friendly age label for a dose: birth / N months / N years (+months).

        Under 2 years we speak in months (so 18mo reads "18 شهر"); from 2 years
        we speak in years, adding the remaining months when not a whole year."""
        if months is None:
            return ""
        if months <= 0:
            return "At birth" if lang == "en" else "عند الولادة"
        if months < 24:
            return f"{months} mo" if lang == "en" else f"{months} شهر"
        years, rem = divmod(months, 12)
        if lang == "en":
            return f"{years}y" if rem == 0 else f"{years}y {rem}m"
        yr = "سنة" if years == 1 else f"{years} سنة"
        return yr if rem == 0 else f"{yr} و{rem} شهر"

    def routine_schedule(self, lang="ar"):
        """The vaccine's normal (routine) schedule as friendly age labels —
        taken from the preferred/government brand's dose ages."""
        brand = self.default_brand
        if brand is None:
            return []
        doses = sorted(brand.doses, key=lambda d: d.age_months or 0)
        return [self.age_label(d.age_months, lang) for d in doses]

    def age_range_label(self, lang="ar"):
        """"min–max" eligible age as friendly labels, if either bound is set."""
        if self.min_age_months is None and self.max_age_months is None:
            return ""
        lo = self.age_label(self.min_age_months, lang) if self.min_age_months is not None else "—"
        hi = self.age_label(self.max_age_months, lang) if self.max_age_months is not None else "—"
        return f"{lo} → {hi}"

    def __repr__(self):
        return f"<Vaccine {self.code}>"


class VaccineBrand(db.Model):
    __tablename__ = "vaccine_brands"

    id = db.Column(db.Integer, primary_key=True)
    vaccine_id = db.Column(db.Integer, db.ForeignKey("vaccines.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    manufacturer = db.Column(db.String(120))
    # Commercial identifiers for search / scanning (ERP inventory item).
    barcode = db.Column(db.String(60), index=True)
    item_code = db.Column(db.String(40), index=True)
    min_stock = db.Column(db.Integer)        # reorder level (patient doses)
    price = db.Column(db.Float)              # selling price
    purchase_price = db.Column(db.Float)     # cost price
    doctor_fee = db.Column(db.Float)         # part of the price that goes to the doctor
    # Sell-price policy: "manual" (default) or "auto" — auto refreshes the sell
    # price from each new purchase cost × (1 + margin%). NULL margin = clinic default.
    price_policy = db.Column(db.String(10), default="manual", nullable=False)
    margin_percent = db.Column(db.Float)
    max_discount = db.Column(db.Float)       # max allowed discount (%)
    # Patient doses obtained from one purchased vial/ampoule. 1 = single-dose
    # ampoule (one vial per patient); >1 = multi-dose vial (e.g. a vial drawn
    # for 10 patients). Stock is always counted in patient doses.
    doses_per_vial = db.Column(db.Integer, default=1, nullable=False)
    # Human-readable unit labels for the item card. The *purchase (addition) unit*
    # is what you buy/receive (e.g. vial/عبوة); the *dispense unit* is what you
    # bill/administer (e.g. dose/جرعة). doses_per_vial is how many dispense units
    # come out of one purchase unit. Left blank → sensible vial/dose defaults.
    purchase_unit = db.Column(db.String(30))
    dispense_unit = db.Column(db.String(30))
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_discontinued = db.Column(db.Boolean, default=False, nullable=False)  # production stopped
    # Trade-name-specific schedule/catch-up when it differs from the vaccine's
    # (RotaRix 2 doses vs RotaTeq 3; Menactra ≥9mo vs Menveo ≥2mo; Trumenba ≥10y).
    # Falls back to the vaccine's catch-up when blank.
    catch_up_notes = db.Column(db.Text)

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

    def schedule_ages(self, lang="ar"):
        """This trade name's own dose schedule as friendly age labels."""
        doses = sorted(self.doses, key=lambda d: d.age_months or 0)
        return [Vaccine.age_label(d.age_months, lang) for d in doses]

    def effective_catch_up(self):
        """This brand's catch-up rule, falling back to the vaccine's when the
        trade name has no schedule difference of its own."""
        if self.catch_up_notes:
            return self.catch_up_notes
        return self.vaccine.catch_up_notes if self.vaccine else None

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
    def is_low(self):
        """At or below the reorder level (only when a level is set)."""
        return bool(self.min_stock) and self.stock <= self.min_stock

    @property
    def stock_value(self):
        """On-hand valuation = Σ remaining doses × batch unit cost."""
        return round(sum(b.qty_remaining * (b.unit_cost or 0) for b in self.batches), 2)

    @property
    def avg_cost(self):
        """Weighted-average unit cost across received batches that carry a cost."""
        qty = sum((b.qty_received or 0) for b in self.batches if b.unit_cost)
        if qty <= 0:
            return self.purchase_price
        val = sum((b.qty_received or 0) * (b.unit_cost or 0) for b in self.batches if b.unit_cost)
        return round(val / qty, 2)

    def recompute_avg_cost(self):
        """Refresh the item's cost price to the weighted average of its batches."""
        avg = self.avg_cost
        if avg is not None:
            self.purchase_price = avg
        return self.purchase_price

    @property
    def clinic_margin(self):
        """Clinic profit per dose = sell price − cost − doctor's fee."""
        return round((self.price or 0) - (self.purchase_price or 0) - (self.doctor_fee or 0), 2)

    @property
    def profit(self):
        """Gross profit per dispense unit = sell price − cost."""
        return round((self.price or 0) - (self.purchase_price or 0), 2)

    @property
    def profit_margin(self):
        """Profit as a % of the sell price (None when there is no sell price)."""
        if not self.price:
            return None
        return round(self.profit / self.price * 100, 1)

    def purchase_unit_label(self, lang="ar"):
        if self.purchase_unit:
            return self.purchase_unit
        return "عبوة" if lang == "ar" else "vial"

    def dispense_unit_label(self, lang="ar"):
        if self.dispense_unit:
            return self.dispense_unit
        return "جرعة" if lang == "ar" else "dose"

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
    # Where this schedule comes from: the manufacturer's leaflet (SmPC), the WHO
    # position paper, the national EPI program, or a clinic-authored one. The
    # doctor can keep several sources side by side and pick which to follow.
    source = db.Column(db.String(20), default="custom", nullable=False)
    # Whether the app auto-created this template (so re-seeding can leave the
    # doctor's own edits untouched while still filling gaps).
    is_seeded = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    SOURCES = ["manufacturer", "who", "national", "custom"]

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
