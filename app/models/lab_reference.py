"""What a test measures, and what counts as usual for a child of this age.

Asked as *«قايمة التحاليل كل تحليل ليه حجات هو بيقيسها»* — a CBC is not one
number, it is a dozen, and each has its own unit and its own usual range for a
child of a given age and sex.

**The range belongs to the analyte, not to the test.** Sodium is the same
sodium ordered on its own or inside a chemistry panel, and haemoglobin is the
same inside a CBC or on its own; a range written once serves every test that
measures it. So three tables:

* ``LabAnalyte`` — one thing measured (sodium, haemoglobin, platelets), with
  its unit;
* ``LabTestAnalyte`` — which analytes an orderable test is made of, in the
  order a report lists them;
* ``LabRange`` — the usual range of one analyte for an age band and a sex,
  **with where it came from and whether the laboratory has approved it**.

**Nothing here is the program's.** Every figure arrives by an import the
hospital runs (``utils/lab_import``) from a sheet it chose, and says so: the
source and its link are kept on the row. An imported range is a *draft* until
the laboratory's director approves it, and a draft is shown beside a result as
a reference but never used to call a result high or low — the same rule the
neonatal jaundice table has lived by since it existed. Critical limits are
the laboratory's and arrive the same way, or not at all.

**And none of it reaches a clinic.** These tables fill only from the lab
module's import; the starter catalogue every clinic is given on install and
update (``utils/investigations``) is not touched by any of it.
"""
from datetime import datetime

from app.extensions import db

#: Who a range is for. ``all`` is the fallback when no sex-specific row fits.
RANGE_SEXES = ("all", "male", "female")

#: What kind of row it is. An *interval* is a usual range; a *cutoff* is a
#: one-sided guideline figure (a lipid target) that is not "normal" and is
#: never shown as if it were; a *note* carries no figure at all — «may be 35%
#: longer in the newborn» — and is shown as words.
RANGE_KINDS = ("interval", "cutoff", "note")


class LabAnalyte(db.Model):
    """One thing a laboratory measures."""
    __tablename__ = "lab_analytes"

    id = db.Column(db.Integer, primary_key=True)
    # The laboratory's own name for it, as its reports print it.
    name = db.Column(db.String(160), nullable=False, index=True)
    name_ar = db.Column(db.String(160))
    unit = db.Column(db.String(30))
    # Other names the same analyte goes by — «Hb; HGB» — separated by «;».
    aliases = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    ranges = db.relationship("LabRange", back_populates="analyte",
                             cascade="all, delete-orphan",
                             order_by="LabRange.age_from_days")

    def display_name(self, lang="ar"):
        return self.name_ar if (lang == "ar" and self.name_ar) else self.name

    def names(self):
        """Every name this analyte answers to, for matching."""
        out = [self.name] + ([self.name_ar] if self.name_ar else [])
        out += [a.strip() for a in (self.aliases or "").split(";") if a.strip()]
        return out

    def __repr__(self):
        return f"<LabAnalyte {self.name}>"


class LabTestAnalyte(db.Model):
    """One analyte of an orderable test, in report order."""
    __tablename__ = "lab_test_analytes"
    __table_args__ = (
        db.UniqueConstraint("investigation_id", "analyte_id",
                            name="uq_lab_test_analyte"),
    )

    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"),
                                 nullable=False, index=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"),
                           nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    investigation = db.relationship(
        "Investigation", backref=db.backref(
            "analyte_links", order_by="LabTestAnalyte.sort_order",
            cascade="all, delete-orphan"))
    analyte = db.relationship("LabAnalyte")


class LabRange(db.Model):
    """The usual range of one analyte for one age band and sex."""
    __tablename__ = "lab_ranges"

    id = db.Column(db.Integer, primary_key=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"),
                           nullable=False, index=True)
    # Age in days, from inclusive to exclusive; no end is «and older». Days,
    # because the first weeks of life move in days and a band written in
    # years cannot say «15 days to 4 weeks».
    age_from_days = db.Column(db.Integer, default=0, nullable=False)
    age_to_days = db.Column(db.Integer)
    sex = db.Column(db.String(6), default="all", nullable=False)
    kind = db.Column(db.String(10), default="interval", nullable=False)
    low = db.Column(db.Float)
    high = db.Column(db.Float)
    # The laboratory's alert limits. Never filled from anywhere but a sheet
    # the laboratory supplied — a generic critical value is exactly the kind
    # of clinical number this program does not make up.
    critical_low = db.Column(db.Float)
    critical_high = db.Column(db.Float)
    # The band as the sheet wrote it — «8 weeks-5 months» — kept so the
    # screen can say what the laboratory said rather than a conversion of it.
    age_label = db.Column(db.String(60))
    note = db.Column(db.String(255))
    # Where the figure came from, as the sheet named it, and the link.
    source = db.Column(db.String(160))
    source_url = db.Column(db.String(300))
    # **Approved or not.** Empty is a draft: shown as a reference, never used
    # to flag a result. Approving is the laboratory director's act.
    approved_at = db.Column(db.DateTime, index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # **Typed by hand on the test's page**, not read from a sheet. A hand row
    # is a draft like any other until approved; what differs is what its
    # approval replaces — only the row it corrects (``replaces_id``), never
    # every approved band of the analyte the way a new sheet does.
    manual = db.Column(db.Boolean, default=False)
    replaces_id = db.Column(db.Integer, db.ForeignKey("lab_ranges.id"))
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    analyte = db.relationship("LabAnalyte", back_populates="ranges")

    @property
    def approved(self):
        return self.approved_at is not None

    def covers(self, age_days, sex=None):
        """Whether this row is for a child of this age (and sex)."""
        if age_days is None or age_days < (self.age_from_days or 0):
            return False
        if self.age_to_days is not None and age_days >= self.age_to_days:
            return False
        return self.sex == "all" or (sex is not None and self.sex == sex)

    def __repr__(self):
        return f"<LabRange {self.analyte_id} {self.age_label} {self.sex}>"


#: What a value was called against its range. ``None`` — no flag — is its own
#: answer: no approved range for this child, or a range that is a guideline
#: and not a usual range. It is never "normal".
FLAGS = ("normal", "low", "high", "critical_low", "critical_high")


class LabResultValue(db.Model):
    """One analyte's value on one order — «Hb 9.1 g/dL, low».

    **The range it was read against is copied onto the row.** A range is
    approved, replaced by a newer sheet, approved again; a result from March
    must still say what it was called in March and against what, or last
    spring's «normal» quietly turns into this autumn's «low» with nobody
    having looked at the child again.
    """
    __tablename__ = "lab_result_values"
    __table_args__ = (
        db.UniqueConstraint("order_id", "analyte_id", name="uq_lab_result_value"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"),
                         nullable=False, index=True)
    analyte_id = db.Column(db.Integer, db.ForeignKey("lab_analytes.id"),
                           nullable=False, index=True)
    sort_order = db.Column(db.Integer, default=0, nullable=False)

    # A number when it is one; the words when it is not — «Negative», «+++»,
    # «No growth». Never both invented from each other.
    value = db.Column(db.Float)
    text = db.Column(db.String(120))
    unit = db.Column(db.String(30))

    # The range it was read against, as it stood that moment. ``range_id``
    # says which row; the figures are copied because that row can change.
    range_id = db.Column(db.Integer, db.ForeignKey("lab_ranges.id"))
    range_approved = db.Column(db.Boolean, default=False, nullable=False)
    ref_kind = db.Column(db.String(10))
    ref_low = db.Column(db.Float)
    ref_high = db.Column(db.Float)
    crit_low = db.Column(db.Float)
    crit_high = db.Column(db.Float)
    ref_label = db.Column(db.String(60))
    ref_note = db.Column(db.String(255))

    flag = db.Column(db.String(14))

    entered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    entered_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    order = db.relationship(
        "VisitInvestigation", backref=db.backref(
            "analyte_values", order_by="LabResultValue.sort_order",
            cascade="all, delete-orphan"))
    analyte = db.relationship("LabAnalyte")

    @property
    def has_value(self):
        return self.value is not None or bool((self.text or "").strip())

    @property
    def abnormal(self):
        return self.flag not in (None, "normal")

    @property
    def critical(self):
        return self.flag in ("critical_low", "critical_high")

    def shown(self):
        """The value as the report prints it: the number, or the words."""
        if self.value is None:
            return self.text or ""
        return f"{self.value:g}"

    def __repr__(self):
        return f"<LabResultValue {self.order_id}:{self.analyte_id} {self.shown()}>"


class LabConsumable(db.Model):
    """A store item one run of a test uses — a strip, a reagent, a tube.

    «غالباً بيبقى بيخصم برده مستهلكات». Taken off the lab's store **when the
    result is entered**, not when the bill is printed: the strip is used
    whether or not the family has paid, and a test the clinic does not bill
    separately uses it just the same. See ``utils/lab_stock.py``.
    """
    __tablename__ = "lab_consumables"
    __table_args__ = (
        db.UniqueConstraint("investigation_id", "store_item_id",
                            name="uq_lab_consumable"),
    )

    id = db.Column(db.Integer, primary_key=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"),
                                 nullable=False, index=True)
    store_item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"),
                              nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)  # per run

    investigation = db.relationship(
        "Investigation", backref=db.backref("lab_consumables",
                                            cascade="all, delete-orphan"))
    item = db.relationship("StoreItem")


class ReferralLabPrice(db.Model):
    """What a referral laboratory charges for one test — its agreement's price
    list (GAHAR DAS.13 asks for the agreement; the account follows from it).

    The price a sample is charged at is copied onto the sample when it is sent
    (``VisitInvestigation.sent_cost``), so a price changed in March does not
    rewrite February's statement — the rule ``BedCharge.unit_price`` keeps.
    """
    __tablename__ = "referral_lab_prices"
    __table_args__ = (db.UniqueConstraint("lab_id", "investigation_id",
                                          name="uq_referral_lab_price"),)

    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("referral_labs.id"),
                       nullable=False, index=True)
    investigation_id = db.Column(db.Integer, db.ForeignKey("investigations.id"),
                                 nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    lab = db.relationship("ReferralLab")
    investigation = db.relationship("Investigation")


class ReferralInvoice(db.Model):
    """A referral laboratory's invoice, matched against what the program says
    was sent. A statement, not a ledger entry: the payment is recorded where
    every other payment is (the expenses screen), and nothing here posts.

    ``our_total`` is what the samples sent in the period came to when the
    invoice was checked — kept, so the difference read later is the one the
    person saw, even if a sample is recalled afterwards.
    """
    __tablename__ = "referral_invoices"

    id = db.Column(db.Integer, primary_key=True)
    lab_id = db.Column(db.Integer, db.ForeignKey("referral_labs.id"),
                       nullable=False, index=True)
    number = db.Column(db.String(60), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    our_total = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(255))
    checked_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    checked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    lab = db.relationship("ReferralLab")
    checker = db.relationship("User", foreign_keys=[checked_by])

    @property
    def difference(self):
        return round((self.amount or 0) - (self.our_total or 0), 2)


class SpecimenStore(db.Model):
    """A tube kept after its result — GAHAR DAS.20 (ج)(هـ)(و).

    *"Criteria for specimen storage … the defined retention time of patient
    samples … specimens' disposal"*, and evidence 6: *"required specimens
    are easily retrieved"* — which is the reason any of it is written down:
    a doctor asks for one more test on this morning's blood, and somebody
    has to know which shelf it is on and whether it is still there.

    **One row per tube, not per test.** One tube often carries three tests
    under one code; the tube is what sits on the shelf and what is thrown
    away. The tests are found by the code (``VisitInvestigation.sample_code``).
    """
    __tablename__ = "specimen_stores"

    id = db.Column(db.Integer, primary_key=True)
    sample_code = db.Column(db.String(24), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # Where — a line of the laboratory's own list (`Lookup` domain
    # ``sample_store``): «ثلاجة ١ — رف ٢».
    place_key = db.Column(db.String(40))
    place_text = db.Column(db.String(80))
    stored_at = db.Column(db.DateTime, default=datetime.utcnow,
                          nullable=False, index=True)
    stored_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # The day it may go, worked out from the laboratory's figure when it was
    # put away. Empty when the laboratory wrote none — never called due.
    keep_until = db.Column(db.Date, index=True)

    disposed_at = db.Column(db.DateTime, index=True)
    disposed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Thrown away before its day says why.
    disposed_note = db.Column(db.String(200))

    patient = db.relationship("Patient")
    storer = db.relationship("User", foreign_keys=[stored_by])
    disposer = db.relationship("User", foreign_keys=[disposed_by])

    @property
    def is_kept(self):
        return self.disposed_at is None

    def __repr__(self):
        return f"<SpecimenStore {self.sample_code}>"


class SampleRejection(db.Model):
    """A specimen the laboratory refused — GAHAR DAS.15 (ب-٢).

    *"Records of rejection are maintained, including the cause of rejection,
    time and date, name of rejecting person, and name of the notified
    individual."* A row of its own and not columns on the order, because an
    order can be refused more than once — haemolysed at eight, clotted at
    ten — and each refused tube is a record the surveyor asks for. The order
    goes back to be drawn again; this keeps the tube that was turned away,
    with the number it carried and who drew it.
    """
    __tablename__ = "sample_rejections"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("visit_investigations.id"),
                         nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # The tube as it was: its number, when and by whom it was drawn.
    sample_code = db.Column(db.String(24))
    collected_at = db.Column(db.DateTime)
    collected_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Why — a line of the laboratory's own list (`Lookup` domain
    # ``sample_reject``), or its words when the list has none that fits.
    reason_key = db.Column(db.String(40))
    reason_text = db.Column(db.String(200))
    # Who was told to draw it again.
    told_to = db.Column(db.String(120), nullable=False)
    rejected_at = db.Column(db.DateTime, default=datetime.utcnow,
                            nullable=False, index=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    order = db.relationship("VisitInvestigation", backref=db.backref(
        "rejections", order_by="SampleRejection.id",
        cascade="all, delete-orphan"))
    patient = db.relationship("Patient")
    collector = db.relationship("User", foreign_keys=[collected_by])
    rejecter = db.relationship("User", foreign_keys=[rejected_by])

    def __repr__(self):
        return f"<SampleRejection {self.order_id} {self.reason_key or self.reason_text}>"


class ReferralLab(db.Model):
    """A laboratory this one sends samples to — GAHAR DAS.13.

    The standard asks for the agreement itself (scope, accreditation, sample
    requirements, turnaround time, reporting, disputes, validity) as a signed
    paper, and for the referral laboratory to be evaluated on its quality,
    turnaround time and reporting. What the program holds is what is used
    every day and what lapses: the name, the accreditation as stated, the
    turnaround the agreement promises, the date the agreement runs to, and
    the last evaluation — the turnaround it actually kept is measured from
    the samples themselves (`utils/lab_sendout`).
    """
    __tablename__ = "referral_labs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    accreditation = db.Column(db.String(160))
    contact = db.Column(db.String(160))
    # The turnaround the agreement promises, in days — and only that: a
    # sample is called late against the laboratory's own word, never ours.
    tat_days = db.Column(db.Integer)
    agreement_until = db.Column(db.Date)
    evaluated_on = db.Column(db.Date)
    evaluation_note = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<ReferralLab {self.name}>"


class ReagentLot(db.Model):
    """One lot of a reagent or laboratory supply — GAHAR DAS.12.

    *"Criteria for inspection, acceptance, and rejection of provided
    reagent … identification, enlisting and labelling of all reagents …
    measures to ensure that the laboratory does not use expired
    materials."* The store counts how many strips there are; it has never
    known which lot they came from or when it expires, and the standard is
    about exactly that. So the laboratory keeps its lots here, beside the
    store and without changing it: received and inspected (accepted, or
    rejected with why), opened for use, finished — and an expired lot is
    never opened (`utils/lab_reagents`).
    """
    __tablename__ = "reagent_lots"

    id = db.Column(db.Integer, primary_key=True)
    # The store item when the reagent is kept in the store; its own name
    # when it is not.
    item_id = db.Column(db.Integer, db.ForeignKey("store_items.id"), index=True)
    name = db.Column(db.String(160))
    lot_number = db.Column(db.String(60), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False, index=True)
    quantity = db.Column(db.Integer)
    # Inspection at receipt (DAS.12 أ): accepted, or rejected with why.
    decision = db.Column(db.String(10), default="accepted", nullable=False)
    inspection_note = db.Column(db.String(200))
    received_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    opened_at = db.Column(db.DateTime)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    finished_at = db.Column(db.DateTime)
    finished_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    item = db.relationship("StoreItem")
    receiver = db.relationship("User", foreign_keys=[received_by])
    opener = db.relationship("User", foreign_keys=[opened_by])

    def display_name(self, lang="ar"):
        if self.item is not None:
            return self.item.display_name(lang)
        return self.name or ""

    def __repr__(self):
        return f"<ReagentLot {self.lot_number} {self.expiry_date}>"

