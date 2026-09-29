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
