"""Drug catalogue & prescriptions (clinic, not a pharmacy/stock system).

A ``Drug`` is a reference entry doctors pick from while writing a
``Prescription``; search works on both trade and generic names. Basic safety
checks are supported: editable drug-drug ``DrugInteraction`` pairs, and an
optional per-drug max daily dose for guidance/over-dose flags.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

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
        """A transient, fully-on white template used when none is configured.

        The flags have to be set here in so many words. ``default=True`` on a
        Column is applied by the *database*, at INSERT — and this object is
        never inserted. So every ``show_*`` on it read ``None``, and a clinic
        that had not built a print template printed prescriptions with no
        doctor's name, no specialty, no licence, **no patient block**, no
        diagnosis, no signature and no stamp. Only the drug table survived,
        because nothing guards it.

        That is the reported symptom exactly — *"I didn't see the doctor's
        name … where is the signature, there's no stamp"* — and it looked like
        a dozen separate holes in the printout rather than one line here. The
        docstring said "fully-on" the whole time, which is the part worth
        remembering: it described the intention, and nothing checked it.
        """
        return cls(name="default", mode="white", logo_source="clinic",
                   **{flag: True for flag in cls.BOOLS})

    def __repr__(self):
        return f"<RxPrintTemplate {self.name}>"


# A combination product is genuinely several substances. Hanging it off one
# ``generic_id`` was enough for dosing — you dose Augmentin on its amoxicillin —
# but not for safety: a child allergic to clavulanic acid would sail past the
# allergy check, because the second ingredient was nowhere in the data.
drug_ingredients = db.Table(
    "drug_ingredients",
    db.Column("drug_id", db.Integer, db.ForeignKey("drugs.id"),
              primary_key=True),
    db.Column("generic_id", db.Integer, db.ForeignKey("generic_drugs.id"),
              primary_key=True),
)


class Drug(db.Model):
    __tablename__ = "drugs"

    id = db.Column(db.Integer, primary_key=True)
    trade_name = db.Column(db.String(160), nullable=False, index=True)
    # The name printed on the box in Arabic — what a parent reads back to you
    # over the phone, and what they search for.
    trade_name_ar = db.Column(db.String(160), index=True)
    generic_name = db.Column(db.String(160), index=True)
    # Link to the drug reference (المرجع الدوائي): the active ingredient this
    # brand carries. Optional — a brand typed in a hurry still works, it just
    # doesn't get the paediatric dosing and the safety flags.
    generic_id = db.Column(db.Integer, db.ForeignKey("generic_drugs.id"),
                           nullable=True, index=True)
    form = db.Column(db.String(20))
    route = db.Column(db.String(20))               # oral / topical / injection…
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
    # What kind of medicine this is, as the Egyptian register classifies it
    # ("ANTIBIOTICS", "COLD PRODUCTS", "SKIN CARE"…). It was in the register
    # file all along and was dropped when the catalogue was compressed, so
    # 24,634 drugs arrived with no way to group them at all.
    drug_class = db.Column(db.String(80), index=True)
    # Catalogue media: the package photo the parent recognises on the shelf,
    # and the leaflet/SPC to read before prescribing.
    image = db.Column(db.String(255))
    leaflet = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    generic = db.relationship("GenericDrug", back_populates="brands")
    # Every active ingredient, ``generic`` being the one dosing is read from.
    ingredients = db.relationship("GenericDrug", secondary=drug_ingredients,
                                  lazy="selectin")

    def label(self, lang="ar"):
        parts = [self.trade_name]
        if self.strength:
            parts.append(self.strength)
        return " ".join(parts)

    def display_name(self, lang="ar"):
        """The name to show: Arabic when we have it and Arabic is being read."""
        if lang == "ar" and (self.trade_name_ar or "").strip():
            return self.trade_name_ar
        return self.trade_name

    def all_ingredients(self):
        """Every ingredient behind this product, primary first, deduplicated.

        Falls back to ``generic`` alone for the products imported before the
        combination link existed — a single-ingredient product is the same
        answer either way."""
        out, seen = [], set()
        for gen in [self.generic] + list(self.ingredients or []):
            if gen is not None and gen.id not in seen:
                seen.add(gen.id)
                out.append(gen)
        return out

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
    rx_date = db.Column(db.Date, default=local_today, nullable=False)
    diagnosis = db.Column(db.String(255))
    diagnosis_code = db.Column(db.String(20))   # ICD-10 code snapshot
    # How settled the diagnosis is. A guardian reading "التهاب رئوي" cannot
    # tell whether the doctor is sure or still working it out, and the two
    # mean very different things to the next doctor who sees the child.
    diagnosis_stage = db.Column(db.String(16))  # provisional | working | final
    # The complaint in the family's own words, kept apart from the diagnosis.
    complaint = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # The unguessable address of the copy the family opens. Only set when a
    # copy is actually sent: a token that exists for every prescription ever
    # written is a bigger surface than one that exists for the ones somebody
    # chose to share.
    share_token = db.Column(db.String(48), unique=True, index=True)

    def share_link_token(self):
        """The token for this prescription, minted on first use."""
        import secrets

        if not self.share_token:
            self.share_token = secrets.token_urlsafe(24)
        return self.share_token

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    visit = db.relationship("Visit", backref="prescriptions")
    items = db.relationship("PrescriptionItem", back_populates="prescription",
                            cascade="all, delete-orphan")
    investigations = db.relationship(
        "PrescriptionInvestigation", back_populates="prescription",
        cascade="all, delete-orphan",
    )

    #: The stages a diagnosis can be at, in the order they progress.
    DIAGNOSIS_STAGES = ["provisional", "working", "final"]

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
    # A doctor writes a line for the record that the family should not carry
    # out of the room — a medicine they are stopping, a note to themselves.
    # Default true, so nothing a doctor wrote disappears from the paper by
    # accident: leaving something *off* has to be a deliberate press.
    printed = db.Column(db.Boolean, default=True, nullable=False)

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


class RxPreset(db.Model):
    """A prescription the doctor writes over and over, saved once.

    Half a paediatric clinic's day is four or five familiar pictures — a cold,
    a sore throat, gastroenteritis, a chest infection. The medicines barely
    change; only the child does. Saving the set means writing it once and then
    adjusting a dose, instead of retyping four lines every time.

    A preset belongs to the doctor who made it unless they share it: two
    doctors in one clinic rarely treat a cold identically, and one quietly
    overwriting the other's habits is worse than a little duplication.
    """
    __tablename__ = "rx_presets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    note = db.Column(db.String(255))                # when to reach for it
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True,
                          index=True)
    is_shared = db.Column(db.Boolean, default=False, nullable=False)
    diagnosis = db.Column(db.String(200))           # pre-fills the visit's Dx
    use_count = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    items = db.relationship("RxPresetItem", back_populates="preset",
                            cascade="all, delete-orphan",
                            order_by="RxPresetItem.id")

    def visible_to(self, user):
        """Theirs, shared, or the clinic's (no owner)."""
        if user is None:
            return self.is_shared or self.doctor_id is None
        return (self.is_shared or self.doctor_id is None
                or self.doctor_id == user.id)

    def __repr__(self):
        return f"<RxPreset {self.name}>"


class RxPresetItem(db.Model):
    """One medicine inside a saved set — the same shape as a written line."""
    __tablename__ = "rx_preset_items"

    id = db.Column(db.Integer, primary_key=True)
    preset_id = db.Column(db.Integer, db.ForeignKey("rx_presets.id"),
                          nullable=False, index=True)
    drug_id = db.Column(db.Integer, db.ForeignKey("drugs.id"), nullable=True)
    drug_name = db.Column(db.String(200), nullable=False)
    dose = db.Column(db.String(120))
    frequency = db.Column(db.String(120))
    duration = db.Column(db.String(120))
    instructions = db.Column(db.String(255))

    preset = db.relationship("RxPreset", back_populates="items")
    drug = db.relationship("Drug")
