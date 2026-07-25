"""Drug catalogue & prescriptions (clinic, not a pharmacy/stock system).

A ``Drug`` is a reference entry doctors pick from while writing a
``Prescription``; search works on both trade and generic names. Basic safety
checks are supported: editable drug-drug ``DrugInteraction`` pairs, and an
optional per-drug max daily dose for guidance/over-dose flags.
"""
from datetime import datetime

from app.extensions import db

DRUG_FORMS = ["tablet", "capsule", "syrup", "suspension", "drops",
              "injection", "cream", "ointment", "suppository", "inhaler", "other"]

# Investigation kinds: lab tests (تحاليل) and radiology / imaging (أشعة).
INVESTIGATION_KINDS = ["lab", "imaging"]

# Supported print paper sizes.
RX_PAGE_SIZES = ["A4", "A5"]


class RxPrintTemplate(db.Model):
    """A configurable prescription print layout (white paper or pre-printed)."""
    __tablename__ = "rx_print_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    mode = db.Column(db.String(12), default="white")        # white | preprinted
    logo_source = db.Column(db.String(12), default="clinic")  # clinic | personal | none
    page_size = db.Column(db.String(4), default="A4")       # A4 | A5
    font_size = db.Column(db.Integer, default=14)
    margin_mm = db.Column(db.Integer, default=12)           # uniform fallback
    # Per-side margins (mm). When NULL they fall back to ``margin_mm`` so old
    # templates keep working; setting them gives fine control to line content up
    # with pre-printed letterhead paper.
    margin_top_mm = db.Column(db.Integer)
    margin_right_mm = db.Column(db.Integer)
    margin_bottom_mm = db.Column(db.Integer)
    margin_left_mm = db.Column(db.Integer)
    top_offset_mm = db.Column(db.Integer, default=0)        # clear letterhead

    show_doctor = db.Column(db.Boolean, default=True, nullable=False)
    show_specialty = db.Column(db.Boolean, default=True, nullable=False)
    show_contact = db.Column(db.Boolean, default=True, nullable=False)
    show_license = db.Column(db.Boolean, default=True, nullable=False)
    show_patient = db.Column(db.Boolean, default=True, nullable=False)
    show_diagnosis = db.Column(db.Boolean, default=True, nullable=False)
    show_signature = db.Column(db.Boolean, default=True, nullable=False)
    show_stamp = db.Column(db.Boolean, default=True, nullable=False)
    show_investigations = db.Column(db.Boolean, default=True, nullable=False)

    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    BOOLS = ["show_doctor", "show_specialty", "show_contact", "show_license",
             "show_patient", "show_diagnosis", "show_signature", "show_stamp",
             "show_investigations"]

    def _side(self, value):
        return value if value is not None else (self.margin_mm or 0)

    @property
    def m_top(self):
        return self._side(self.margin_top_mm)

    @property
    def m_right(self):
        return self._side(self.margin_right_mm)

    @property
    def m_bottom(self):
        return self._side(self.margin_bottom_mm)

    @property
    def m_left(self):
        return self._side(self.margin_left_mm)

    @classmethod
    def default_instance(cls):
        """A transient, fully-on white template used when none is configured."""
        return cls(name="default", mode="white", logo_source="clinic")

    def __repr__(self):
        return f"<RxPrintTemplate {self.name}>"


class Drug(db.Model):
    __tablename__ = "drugs"

    id = db.Column(db.Integer, primary_key=True)
    trade_name = db.Column(db.String(160), nullable=False, index=True)
    generic_name = db.Column(db.String(160), index=True)
    # Link to the drug reference (المرجع الدوائي): the active ingredient this
    # brand carries. Optional — a brand typed in a hurry still works, it just
    # doesn't get the paediatric dosing and the safety flags.
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=True, index=True)
    form = db.Column(db.String(20))
    strength = db.Column(db.String(60))            # e.g. "250 mg/5 ml"
    default_dose = db.Column(db.String(120))       # suggested dose text
    default_frequency = db.Column(db.String(80))   # e.g. "كل 8 ساعات"
    default_instructions = db.Column(db.String(200))
    max_daily_dose = db.Column(db.String(120))     # guidance text
    # Weight-based dosing (paediatric): mg per kg per dose, max mg/kg/day, and
    # the liquid concentration (mg per ml) to convert a computed mg dose to ml.
    dose_per_kg = db.Column(db.Float)
    max_per_kg = db.Column(db.Float)
    conc_mg_per_ml = db.Column(db.Float)
    # Commercial data (EDA / pharmacy): pack, price and barcode.
    pack_size = db.Column(db.String(60))
    price = db.Column(db.Float)
    price_updated_at = db.Column(db.DateTime)     # when the price was last set
    barcode = db.Column(db.String(60), index=True)
    manufacturer = db.Column(db.String(120))
    # Catalogue media: the package photo the parent recognises on the shelf,
    # and the leaflet/SPC to read before prescribing.
    image = db.Column(db.String(255))
    leaflet = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    generic = db.relationship("GenericDrug", back_populates="brands")

    def label(self, lang="ar"):
        parts = [self.trade_name]
        if self.strength:
            parts.append(self.strength)
        return " ".join(parts)

    @property
    def price_per_unit(self):
        """Price per millilitre (or per unit of pack) — what makes two brands
        of the same ingredient actually comparable."""
        if not self.price or not self.pack_size:
            return None
        digits = "".join(c for c in str(self.pack_size)
                         if c.isdigit() or c == ".").strip(".")
        try:
            size = float(digits)
        except ValueError:
            return None
        return round(self.price / size, 3) if size > 0 else None

    def alternatives(self, limit=12):
        """Other products carrying the same active ingredient, cheapest first
        (products with no price last) — the answer to "is there a cheaper one?"."""
        if not self.generic_id:
            return []
        rows = [d for d in Drug.query.filter(Drug.generic_id == self.generic_id,
                                             Drug.id != self.id,
                                             Drug.is_active.is_(True)).all()]
        return sorted(rows, key=lambda d: (d.price is None, d.price or 0))[:limit]

    def __repr__(self):
        return f"<Drug {self.trade_name}>"


class Investigation(db.Model):
    """Reference catalogue of lab tests / imaging studies for autocomplete."""
    __tablename__ = "investigations"

    id = db.Column(db.Integer, primary_key=True)
    name_ar = db.Column(db.String(160), nullable=False, index=True)
    name_en = db.Column(db.String(160), index=True)
    kind = db.Column(db.String(12), default="lab", nullable=False)  # lab | imaging
    category = db.Column(db.String(80))     # grouping (e.g. Hematology, X-ray)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name_ar

    def __repr__(self):
        return f"<Investigation {self.kind}:{self.name_ar}>"


class DrugInteraction(db.Model):
    """An editable drug-drug interaction warning (symmetric pair).

    Pairs may be given as brands (the legacy rows) or — better — as the two
    **active ingredients**, so every brand of them is covered by one rule.
    ``alternative`` is what to prescribe instead, which is the part a doctor
    actually needs at the moment of the warning.
    """
    __tablename__ = "drug_interactions"

    id = db.Column(db.Integer, primary_key=True)
    drug_a_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True, index=True)
    drug_b_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True, index=True)
    generic_a_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                             nullable=True, index=True)
    generic_b_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                             nullable=True, index=True)
    severity = db.Column(db.String(12), default="moderate")  # mild|moderate|severe
    note = db.Column(db.String(255))
    alternative = db.Column(db.String(200))     # ما البديل الآمن
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    drug_a = db.relationship("Drug", foreign_keys=[drug_a_id])
    drug_b = db.relationship("Drug", foreign_keys=[drug_b_id])
    generic_a = db.relationship("GenericDrug", foreign_keys=[generic_a_id])
    generic_b = db.relationship("GenericDrug", foreign_keys=[generic_b_id])

    def pair_names(self, lang="ar"):
        a = (self.generic_a.display_name(lang) if self.generic_a
             else (self.drug_a.trade_name if self.drug_a else ""))
        b = (self.generic_b.display_name(lang) if self.generic_b
             else (self.drug_b.trade_name if self.drug_b else ""))
        return a, b


class Prescription(db.Model):
    __tablename__ = "prescriptions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    rx_date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), nullable=False)
    diagnosis = db.Column(db.String(255))
    diagnosis_code = db.Column(db.String(20))   # ICD-10 code snapshot
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    visit = db.relationship("Visit", backref="prescriptions")
    items = db.relationship("PrescriptionItem", back_populates="prescription",
                            cascade="all, delete-orphan")
    investigations = db.relationship(
        "PrescriptionInvestigation", back_populates="prescription",
        cascade="all, delete-orphan",
    )

    def labs(self):
        return [x for x in self.investigations if x.kind == "lab"]

    def imaging(self):
        return [x for x in self.investigations if x.kind == "imaging"]

    def __repr__(self):
        return f"<Prescription {self.id} p={self.patient_id}>"


class PrescriptionItem(db.Model):
    __tablename__ = "prescription_items"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(db.Integer, db.ForeignKey("prescriptions.id"), nullable=False, index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    drug_name = db.Column(db.String(200), nullable=False)  # snapshot
    dose = db.Column(db.String(120))
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    instructions = db.Column(db.String(255))

    prescription = db.relationship("Prescription", back_populates="items")
    drug = db.relationship("Drug")


class PrescriptionInvestigation(db.Model):
    """A requested lab test or imaging study on a prescription."""
    __tablename__ = "prescription_investigations"

    id = db.Column(db.Integer, primary_key=True)
    prescription_id = db.Column(
        db.Integer, db.ForeignKey("prescriptions.id"), nullable=False, index=True
    )
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"), nullable=True)
    kind = db.Column(db.String(12), default="lab", nullable=False)  # lab | imaging
    name = db.Column(db.String(200), nullable=False)  # Arabic / primary snapshot
    name_en = db.Column(db.String(200))               # English snapshot (bilingual)
    notes = db.Column(db.String(255))

    prescription = db.relationship("Prescription", back_populates="investigations")
    investigation = db.relationship("Investigation")

    def display_name(self, lang="ar"):
        if lang == "en" and (self.name_en or "").strip():
            return self.name_en
        return self.name
