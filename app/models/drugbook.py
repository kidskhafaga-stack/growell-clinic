"""The drug reference (المرجع الدوائي) — the clinical layer above the
prescribable products.

Four levels, the way a paediatrician actually thinks:

1. ``DrugClass``   — المجموعة الدوائية (خافضات حرارة، مضادات حيوية…)
2. ``GenericDrug`` — المادة الفعالة, and everything clinical hangs here:
   paediatric dosing by weight and by age, ceilings, minimum age,
   contraindications, black-box warnings, renal/hepatic adjustment,
   pregnancy & lactation.
3. the **trade name** and 4. its **strength + form** are the existing
   ``Drug`` rows (that's what a prescription writes), now linked up to their
   generic — so one active ingredient carries every brand in the market.

Everything is editable clinic data with sensible starting values; the reference
never prescribes on its own — it computes and warns, the doctor decides.
"""
from datetime import datetime

from app.extensions import db

# How the per-kilogram figure is meant: per single dose, or per whole day.
DOSE_BASES = ["per_dose", "per_day"]

# Pregnancy safety grade (classic FDA letters — still what local leaflets use).
PREGNANCY_CATEGORIES = ["A", "B", "C", "D", "X"]


class DrugClass(db.Model):
    """Level 1 — المجموعة الدوائية."""
    __tablename__ = "drug_classes"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, index=True)
    name_ar = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    description = db.Column(db.Text)
    icon = db.Column(db.String(40))            # bootstrap-icons name
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    generics = db.relationship("GenericDrug", back_populates="drug_class",
                               order_by="GenericDrug.name_en")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name_ar

    def __repr__(self):
        return f"<DrugClass {self.code}>"


class GenericDrug(db.Model):
    """Level 2 — المادة الفعالة, with the paediatric dosing rules."""
    __tablename__ = "generic_drugs"

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("drug_classes.id"),
                         nullable=True, index=True)
    name_ar = db.Column(db.String(140), nullable=False, index=True)
    name_en = db.Column(db.String(140), index=True)
    atc_code = db.Column(db.String(20))
    routes = db.Column(db.String(120))          # oral, IV, IM, topical…

    # --- weight-based dosing ------------------------------------------
    # ``dose_per_kg`` is read according to ``dose_basis``: mg/kg per single
    # dose, or mg/kg per day split over ``doses_per_day``.
    dose_per_kg = db.Column(db.Float)
    dose_per_kg_max = db.Column(db.Float)       # upper end of the usual range
    dose_basis = db.Column(db.String(10), default="per_dose", nullable=False)
    doses_per_day = db.Column(db.Integer)
    max_per_kg_day = db.Column(db.Float)        # never exceed, mg/kg/day
    max_single_dose_mg = db.Column(db.Float)    # adult ceiling per dose
    max_daily_dose_mg = db.Column(db.Float)     # adult ceiling per day
    dose_note = db.Column(db.String(255))       # e.g. "أول يوم 10 ثم 5 مج/كج"

    # --- eligibility / safety -----------------------------------------
    # How long a course of this may run before somebody looks again. Empty on
    # almost everything and that is correct: it is filled only where a printed
    # limit exists to point at, and the clinic sets its own from the screen.
    # Nothing here decides what a course *should* be.
    max_course_days = db.Column(db.Integer)
    min_age_months = db.Column(db.Integer)      # e.g. ibuprofen = 6
    max_age_months = db.Column(db.Integer)
    min_weight_kg = db.Column(db.Float)
    black_box = db.Column(db.Text)              # تحذير أسود
    contraindications = db.Column(db.Text)
    precautions = db.Column(db.Text)
    side_effects = db.Column(db.Text)
    indications = db.Column(db.Text)
    renal_adjustment = db.Column(db.Text)
    hepatic_adjustment = db.Column(db.Text)
    pregnancy_category = db.Column(db.String(2))
    pregnancy_note = db.Column(db.String(255))
    lactation_note = db.Column(db.String(255))
    monitoring = db.Column(db.String(255))
    notes = db.Column(db.Text)
    reference = db.Column(db.String(255))       # WHO / BNF-C / NICE / EDA…
    reference_url = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    drug_class = db.relationship("DrugClass", back_populates="generics")
    age_bands = db.relationship(
        "GenericDoseBand", back_populates="generic",
        cascade="all, delete-orphan", order_by="GenericDoseBand.min_age_months")
    brands = db.relationship("Drug", back_populates="generic",
                             order_by="Drug.trade_name")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name_ar

    def full_name(self, lang="ar"):
        """Both names when we have them — prescribers read either."""
        if self.name_en and self.name_ar and self.name_en != self.name_ar:
            return (f"{self.name_en} ({self.name_ar})" if lang == "en"
                    else f"{self.name_ar} ({self.name_en})")
        return self.display_name(lang)

    @property
    def dose_range_label(self):
        """"25–50 mg/kg/day ÷ 3" — the rule in one line."""
        if not self.dose_per_kg:
            return ""
        lo = _trim(self.dose_per_kg)
        rng = f"{lo}–{_trim(self.dose_per_kg_max)}" if self.dose_per_kg_max else lo
        unit = "mg/kg/day" if self.dose_basis == "per_day" else "mg/kg/dose"
        out = f"{rng} {unit}"
        if self.doses_per_day:
            out += f" ÷ {self.doses_per_day}"
        return out

    def band_for(self, age_months):
        """The age band that covers ``age_months``, if any."""
        if age_months is None:
            return None
        for b in self.age_bands:
            lo = b.min_age_months if b.min_age_months is not None else -1
            hi = b.max_age_months if b.max_age_months is not None else 10 ** 6
            if lo <= age_months <= hi:
                return b
        return None

    def __repr__(self):
        return f"<GenericDrug {self.name_en or self.name_ar}>"


class GenericDoseBand(db.Model):
    """Dose by age, for drugs dosed by age band rather than by weight
    (cetirizine, montelukast, most syrups sold by spoon)."""
    __tablename__ = "generic_dose_bands"

    id = db.Column(db.Integer, primary_key=True)
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=False, index=True)
    min_age_months = db.Column(db.Integer)
    max_age_months = db.Column(db.Integer)
    dose_text = db.Column(db.String(160), nullable=False)   # "5 مل مرة يومياً"
    dose_mg = db.Column(db.Float)                            # when quantifiable
    doses_per_day = db.Column(db.Integer)
    notes = db.Column(db.String(200))

    generic = db.relationship("GenericDrug", back_populates="age_bands")

    def age_label(self, lang="ar"):
        from app.models.vaccine import Vaccine
        lo, hi = self.min_age_months, self.max_age_months
        if lo is None and hi is None:
            return "—"
        if hi is None:
            return (f"{Vaccine.age_label(lo, lang)}+" if lang == "en"
                    else f"من {Vaccine.age_label(lo, lang)}")
        if lo is None:
            return (f"< {Vaccine.age_label(hi, lang)}" if lang == "en"
                    else f"حتى {Vaccine.age_label(hi, lang)}")
        return f"{Vaccine.age_label(lo, lang)} – {Vaccine.age_label(hi, lang)}"

    def __repr__(self):
        return f"<GenericDoseBand {self.dose_text}>"


def _trim(v):
    """1.0 → 1, 0.15 → 0.15 (doses read badly with trailing zeros)."""
    if v is None:
        return ""
    return str(int(v)) if float(v).is_integer() else str(v)
