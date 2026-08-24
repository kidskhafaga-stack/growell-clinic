"""Patient model — the core clinical record.

The file number (``patient_number``) can be entered manually (to preserve
legacy numbers) or generated automatically as ``PM-YYYY-NNNN``.
"""
from datetime import date, datetime

from app.extensions import db
from app.utils.clock import local_today

GENDERS = ["male", "female"]
BLOOD_TYPES = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

# From this age a child can carry their own phone, so we prompt reception to
# capture a personal number for direct contact.
OWN_PHONE_AGE = 13


def own_phone_cutoff(today=None):
    """Latest date of birth that makes a patient at least ``OWN_PHONE_AGE``."""
    today = today or local_today()
    try:
        return today.replace(year=today.year - OWN_PHONE_AGE)
    except ValueError:  # 29 Feb
        return today.replace(year=today.year - OWN_PHONE_AGE, day=28)


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
    # This link was made by the program, not by a person. Kept apart because
    # the two are not equally trustworthy: a receptionist who links two files
    # has looked at both of them, while the program has only matched a phone
    # and a name. The screen says which it was, and an automatic link is the
    # one somebody undoes without wondering whose decision they are undoing.
    family_auto = db.Column(db.Boolean, default=False, nullable=False)

    # Bilingual names.
    full_name = db.Column(db.String(120), nullable=False)
    full_name_en = db.Column(db.String(120))

    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    national_id = db.Column(db.String(20))
    # The patient's own phone (captured once they're old enough to carry one),
    # so we can reach the teen directly rather than only through a guardian.
    own_phone = db.Column(db.String(20))
    blood_type = db.Column(db.String(5))

    # ---- What the child arrived with -----------------------------------
    #
    # Both are usually the parent's memory rather than a discharge summary —
    # *"غالباً سن الحمل عند الولادة والوزن عند الولادة تقريباً بيعوزوها"* — so
    # neither is required and neither is ever inferred. A blank one means
    # nobody said, which is a different thing from a normal one.
    #
    # Gestation is kept as weeks *and* days because that is how it is said and
    # written: "36+4", not "36.57". Storing the fraction would make the screen
    # show a number no discharge summary ever printed, and correcting a
    # premature child's age is arithmetic on days.
    birth_weight_kg = db.Column(db.Float)
    gestation_weeks = db.Column(db.Integer)
    gestation_days = db.Column(db.Integer)
    photo = db.Column(db.String(255))

    # Medical alerts surfaced prominently on the profile.
    allergies = db.Column(db.Text)
    chronic_diseases = db.Column(db.Text)
    notes = db.Column(db.Text)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    # Archiving: an inactive file is kept (never deleted) but set is_active=False.
    # ``archived_at`` stamps when, and ``archive_reason`` records how it happened
    # ("auto" = the inactivity sweep, "manual" = a user archived it deliberately).
    archived_at = db.Column(db.DateTime)
    archive_reason = db.Column(db.String(20))
    # Guardian has opted out of WhatsApp messages — CRM sends skip this patient.
    wa_opt_out = db.Column(db.Boolean, default=False, nullable=False)
    # Opaque token for public vaccination-certificate QR verification.
    qr_token = db.Column(db.String(32), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    family = db.relationship("Family", back_populates="patients")

    @property
    def is_archived(self):
        return not self.is_active

    @property
    def last_activity_date(self):
        """Most recent sign of activity: the latest visit date, falling back to
        when the file was created. Used to judge inactivity for archiving."""
        from app.models import Visit

        last = (db.session.query(db.func.max(Visit.visit_date))
                .filter(Visit.patient_id == self.id).scalar())
        created = self.created_at.date() if self.created_at else None
        dates = [d for d in (last, created) if d is not None]
        return max(dates) if dates else None

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
        today = local_today()
        years = today.year - self.date_of_birth.year
        months = today.month - self.date_of_birth.month
        if today.day < self.date_of_birth.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        return (max(years, 0), max(months, 0))

    @property
    def gestation(self):
        """``"36+4"`` — the way it is written, or ``None`` if nobody said."""
        if self.gestation_weeks is None:
            return None
        return f"{self.gestation_weeks}+{self.gestation_days or 0}"

    @property
    def gestation_total_days(self):
        """Gestation in days, or ``None``. 37+0 is 259."""
        if self.gestation_weeks is None:
            return None
        return self.gestation_weeks * 7 + (self.gestation_days or 0)

    @property
    def is_preterm(self):
        """Born before 37 completed weeks — or ``None`` when nobody said.

        Three-valued deliberately. "We do not know" and "no, they were term"
        lead to different conversations, and a screen that showed the second
        when it meant the first would be the program answering a question it
        was never told the answer to.
        """
        if self.gestation_weeks is None:
            return None
        return self.gestation_total_days < 37 * 7

    @property
    def age_days(self):
        if not self.date_of_birth:
            return 0
        return (local_today() - self.date_of_birth).days

    @property
    def age_years(self):
        return self.age_parts[0] if self.date_of_birth else 0

    @property
    def needs_own_phone(self):
        """Active teen (≥ OWN_PHONE_AGE) who has no personal number yet — a
        prompt for reception to update their contact details."""
        return (self.is_active and self.age_years >= OWN_PHONE_AGE
                and not (self.own_phone or "").strip())

    @property
    def has_alerts(self):
        return bool((self.allergies or "").strip() or (self.chronic_diseases or "").strip())

    @property
    def latest_growth(self):
        """The most recent measurement carrying a weight, or ``None``.

        Delegates rather than querying, so "the child's current weight" has
        one definition in the program. The dosing calculator and the printed
        prescription must never be able to disagree about it.
        """
        from app.utils.dosing import latest_weight_record

        return latest_weight_record(self)

    @property
    def growth_picture(self):
        """The newest measurement event, and each reading's percentile.

        ``{"record": GrowthRecord|None, "rows": [...]}``. One event rather
        than the newest of each measurement separately — see
        ``growth.summarise`` for why that distinction matters.
        """
        from app.models.growth_record import GrowthRecord
        from app.utils.growth import summarise

        record = (GrowthRecord.query.filter_by(patient_id=self.id)
                  .order_by(GrowthRecord.record_date.desc(),
                            GrowthRecord.id.desc()).first())
        return {"record": record, "rows": summarise(self, record)}

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
        """Best contact number: the patient's own phone if set, then the primary
        guardian, else any guardian with a phone."""
        if (self.own_phone or "").strip():
            return self.own_phone.strip()
        if not self.family or not self.family.parents:
            return None
        parents = sorted(self.family.parents,
                         key=lambda p: (0 if p.is_primary_contact else 1))
        for p in parents:
            if p.phone:
                return p.phone
        return None

    @property
    def primary_guardian(self):
        """The primary-contact guardian (else the first parent), or None."""
        if not self.family or not self.family.parents:
            return None
        parents = sorted(self.family.parents,
                         key=lambda p: (0 if p.is_primary_contact else 1))
        return parents[0] if parents else None

    @property
    def client_category(self):
        """The primary guardian's category — for showing, not for pricing.

        Kept because a screen has to print *one* thing next to the child's name.
        Discount eligibility must use :attr:`client_categories` instead: a
        family has more than one parent and they need not agree.
        """
        if not self.family or not self.family.parents:
            return "normal"
        parents = sorted(self.family.parents,
                         key=lambda p: (0 if p.is_primary_contact else 1))
        return parents[0].client_category if parents else "normal"

    @property
    def client_categories(self):
        """Every category the child is entitled through — **all** the parents.

        The single-category version read the primary contact and stopped, so a
        child whose father is staff and whose mother is a friend and happens to
        be the contact was priced as a friend: the father's entitlement was
        thrown away by a field that only decides who to phone.

        Note what this deliberately does **not** do: it does not rank the
        categories. Whether "staff" is worth more than "friend" is the clinic's
        pricing decision, written in the discounts themselves — inventing an
        order here would quietly overrule it. The billing side already prices
        every rule the child qualifies for against the real invoice and applies
        the largest; widening eligibility is all this has to do.
        """
        if not self.family or not self.family.parents:
            return {"normal"}
        found = {(p.client_category or "normal") for p in self.family.parents}
        return found or {"normal"}

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


PROBLEM_STATUSES = ["active", "resolved"]


class PatientProblem(db.Model):
    """A structured, longitudinal problem list (GAHAR): the patient's ongoing
    and past problems/chronic conditions carried across visits — richer than the
    free-text ``chronic_diseases`` field.
    """
    __tablename__ = "patient_problems"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)   # Arabic primary
    title_en = db.Column(db.String(255))
    icd_code = db.Column(db.String(20))
    status = db.Column(db.String(12), default="active", nullable=False)
    onset_date = db.Column(db.Date)                     # when it started
    noted_date = db.Column(db.Date, default=date.today) # when added to the list
    resolved_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref=db.backref(
        "problems", cascade="all, delete-orphan", order_by="PatientProblem.created_at.desc()"))

    def display_title(self, lang="ar"):
        return self.title_en if (lang == "en" and self.title_en) else self.title

    @property
    def is_active(self):
        return self.status == "active"

    def __repr__(self):
        return f"<PatientProblem p={self.patient_id} {self.title!r} {self.status}>"


# Consent kinds a pediatric clinic documents (guardian-signed).
CONSENT_TYPES = ["general", "examination", "procedure", "vaccination",
                 "anesthesia", "data_privacy", "photography"]


class Consent(db.Model):
    """Documented informed consent (GAHAR). In pediatrics the patient is a
    minor, so consent is given and signed by the **guardian**, not the child.
    """
    __tablename__ = "consents"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    consent_type = db.Column(db.String(20), default="general", nullable=False)
    # Who consents on the child's behalf.
    guardian_name = db.Column(db.String(120), nullable=False)
    guardian_relation = db.Column(db.String(20))
    guardian_id_no = db.Column(db.String(20))          # national ID of the signer
    statement = db.Column(db.Text)                     # the consent text
    notes = db.Column(db.Text)
    signed_date = db.Column(db.Date, default=date.today, nullable=False)
    obtained_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref=db.backref(
        "consents", cascade="all, delete-orphan", order_by="Consent.signed_date.desc()"))
    staff = db.relationship("User")

    def __repr__(self):
        return f"<Consent p={self.patient_id} {self.consent_type} {self.signed_date}>"
