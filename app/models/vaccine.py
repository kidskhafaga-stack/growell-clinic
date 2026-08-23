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

    # **How far this schedule describes people — not how old is too old.**
    #
    # These are two different sentences and conflating them is the mistake
    # this column exists to make impossible. `VaccineBrand.max_age_final_dose_days`
    # is a fact about a *product*: past it the vial may not be given, and a
    # dose there reads `expired`. This one is a fact about a *reference*: past
    # it the schedule simply stops covering the patient, and a dose reads
    # `out_of_scope`.
    #
    # The distinction came out of a review of the four vaccines still without
    # an upper age. It proposed eighteen years for MMR, IPV and MenACWY from
    # CDC's child-and-adolescent schedule — and said so itself: that is the
    # ceiling of a *paediatric catch-up engine*, not a limit on the vaccine.
    # It is right. CDC's position on MMR is that anyone twelve months or older
    # who is due one should have it, so writing eighteen into the product
    # column would tell a twenty-year-old their window had shut. Same number,
    # opposite meaning, and the wrong column costs somebody a vaccine.
    #
    # The precedent is already in the schedule catalogue: WHO's pneumococcal
    # table stops at five because the position paper is titled *"…children
    # under 5 years of age"*. Scope, not licensing. This column is that idea
    # given a name.
    #
    # Left NULL almost everywhere on purpose. It is written only where a named
    # source states a range narrower than the product's own licence, so a
    # blank means "nothing published says where this stops" and never "nobody
    # got round to it".
    scope_max_age_days = db.Column(db.Integer)

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

    # ── The trade name's own regulatory and window facts ──────────────
    #
    # Kept on the **brand**, not the vaccine, because that is where they
    # actually differ. The rotavirus series has to be finished by 24 weeks on
    # RotaRix, 32 on RotaTeq and 34 on Rotasiil; Synflorix stops at five years
    # while every other pneumococcal keeps going. A single number on the
    # vaccine was wrong for all six of them.
    #
    # In **days**, deliberately. The labels are written in weeks, and 24 weeks
    # is 5.5 months — rounding that to a whole month either closes the window
    # two weeks early or leaves it two weeks too long, on the one vaccine
    # where the window is the whole point.
    max_age_final_dose_days = db.Column(db.Integer)   # NULL = no ceiling
    # The latest a **first** dose may be given, in days. A different question
    # from the ceiling above and the one nobody was asking: rotavirus must be
    # finished by 24 weeks on RotaRix, and it must also not be *started* after
    # about 15. A child past the start window but inside the finish window was
    # being offered a series that cannot be begun — the program asking when to
    # give a dose without ever asking whether it may.
    max_age_first_dose_days = db.Column(db.Integer)
    valency = db.Column(db.String(120))               # "13-valent PCV"
    dose_volume = db.Column(db.String(40))            # "0.5 mL"
    # Registered is not the same as obtainable, and conflating them puts a
    # product on the shelf that nobody can buy. `available_now` is
    # deliberately three-valued — NULL means nobody has checked, which is the
    # honest state for most of the catalogue most of the time.
    registered_in_egypt = db.Column(db.Boolean)
    available_now = db.Column(db.Boolean)             # NULL = unknown
    # Whether the number of doses depends on how old the child was at the
    # first one (HPV 2 vs 3, Synflorix, Nimenrix). Nothing reads this yet; it
    # marks the brands that need an age-banded schedule before the plan can be
    # right for them, so the gap is visible in the data instead of remembered.
    doses_change_by_start_age = db.Column(db.Boolean, default=False,
                                          nullable=False)
    # How this brand may be reminded about at all. Rabies is the reason it
    # exists: it is given after a bite, and a routine reminder for it is a
    # frightening message about a course nobody is on.
    reminder_scope = db.Column(db.String(40))         # see REMINDER_SCOPES
    source_url = db.Column(db.String(255))            # where the fact came from

    # ── Switching **to** this product, never away from it ──────────────
    #
    # Read as: *the next dose is this brand and the earlier ones were not —
    # what does this brand's leaflet say?* Destination, not source. Every SmPC
    # is written that way, describing children arriving at its own product,
    # and interchangeability is not symmetric — so one column only works if
    # everybody reads it in the same direction. Hence the name.
    #
    #   full        — the leaflet allows switching in at any point
    #   conditional — allowed with a stated reservation. Prevenar 20's is that
    #                 safety and immunogenicity under 15 months, in a child who
    #                 began another pneumococcal, have not been established.
    #   limited     — the data are thin. Finishing on the same product is
    #                 preferred and a mixed series is worth a second look.
    #   none        — earlier doses of another product do not count here.
    #
    # ``none`` is deliberately **not** the value for "limited evidence".
    # Turning a reservation into a prohibition is as wrong as turning it into
    # silence, and four states exist so neither has to happen — the same
    # reasoning that gave `available_now` three.
    interchange_to = db.Column(db.String(12))
    # The age in months below which `conditional` becomes a flag rather than a
    # quiet yes. Measured at the switch, which is what the label describes.
    interchange_flag_under_months = db.Column(db.Integer)

    INTERCHANGE = ["full", "conditional", "limited", "none"]

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

    def stock_in(self, warehouse):
        """Doses held in one warehouse.

        Mirrors ``StoreItem.stock_in``: a batch with no warehouse on it was
        received before the fridge was a place, and belongs to the default
        warehouse. Without this a clinic with a fridge could see its vaccines
        on the shelf list and find nothing to count inside the fridge.
        """
        if warehouse is None:
            return self.stock
        return sum(b.qty_remaining for b in self.batches
                   if b.warehouse_id == warehouse.id
                   or (b.warehouse_id is None and warehouse.is_default))

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


# What a brand may be reminded about, from narrowest to widest.
#
# ``event`` is the one that changes behaviour: rabies is given because
# something happened, so it must never appear on a routine due list. The rest
# are descriptive today and are carried so the suggestions screen can filter
# on them rather than hard-code a list of exceptions.
REMINDER_SCOPES = ["event", "travel", "risk", "seasonal", "routine"]


class VaccineBrandDose(db.Model):
    __tablename__ = "vaccine_brand_doses"

    id = db.Column(db.Integer, primary_key=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"), nullable=False, index=True)
    dose_number = db.Column(db.Integer, nullable=False)
    age_months = db.Column(db.Integer, nullable=False)
    # A booster is not "one more dose": it is what the parent is told about,
    # and what decides whether the course is finished after it.
    is_booster = db.Column(db.Boolean, default=False, nullable=False)

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
    age_group = db.Column(db.String(120))             # "2-6 months" (display)
    # The same band, in numbers the program can choose by. `age_group` is free
    # text for a human to read; these decide which schedule a child is on.
    #
    # Measured against the age **at the first dose**, never the age today.
    # Raised by the doctor as the rule that matters most: a child who started
    # HPV at fourteen and eleven months is on the two-dose schedule, and does
    # not jump to three because a birthday passed between doses. So the band
    # is matched once, when the course starts, and the answer stays.
    start_age_min_months = db.Column(db.Integer)
    start_age_max_months = db.Column(db.Integer)      # inclusive; NULL = open
    # Whose schedule this is. NULL means the vaccine's own — every trade name
    # follows it. Named brands exist because the leaflets genuinely differ:
    # WHO speaks about pneumococcal conjugate as a class and never about
    # Vaxneuvance, while Merck's own catch-up is Vaxneuvance's alone and would
    # be wrong applied to Synflorix, which stops at five years.
    #
    # A brand's own schedule wins over the vaccine's; with none, the vaccine's
    # applies. So the common case stays one schedule in one place, and the
    # exception is one row rather than a fork.
    brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                         nullable=True, index=True)
    # What the child's record has to look like for this schedule to apply.
    #
    # The leaflets do not name a band by age alone. The category is
    # "**Unvaccinated** 7 to <12 months", and the first word is half the
    # definition: a child who already had two pneumococcal doses and is
    # switching product is not unvaccinated, and handing them the catch-up
    # course restarts a series they are most of the way through.
    #
    #   NULL   — any history; the ordinary routine schedule
    #   "none" — nothing of this vaccine before this brand's first dose
    #   "some" — had some, whatever the trade name
    #
    # Counted per **vaccine**, never per brand: a dose of Prevenar is a
    # pneumococcal dose when the next one is Vaxneuvance, which is the
    # clinical rule and also the one `dose_infer` already numbers by.
    requires_previous_doses = db.Column(db.String(10))
    # The gap actually achieved between the first two doses, in days, for this
    # schedule to apply. Same shape as the age band and for the same reason:
    # a number the program compares, not prose a person reads.
    #
    # HPV is why it exists. Two doses are enough from nine to fourteen **if
    # the second comes five to thirteen months after the first**; given
    # sooner, the course becomes three. So the count depends on something that
    # already happened rather than on anything known at the start, and a
    # schedule chosen once at the first dose cannot express it.
    first_gap_min_days = db.Column(db.Integer)
    first_gap_max_days = db.Column(db.Integer)   # exclusive
    # "…and has had fewer than two before" — a count, which `requires_previous_
    # doses` (none / some) cannot say. Influenza needs it: under nine, a child
    # with none and a child with one both owe two doses this season, and a
    # child with two owes one. Inclusive bounds; blank means no condition.
    previous_doses_min = db.Column(db.Integer)
    previous_doses_max = db.Column(db.Integer)
    # Which age decides this band: "start" (the age at the first dose) or
    # "today" (the age now). Two different clinical shapes, and using one for
    # both is wrong in opposite directions.
    #
    # HPV locks at the first dose: a child who begins at fourteen and eleven
    # months keeps the two-dose course when they turn fifteen between doses.
    # A pneumococcal catch-up does the opposite — it reads the age *now* and
    # the doses already given, and a healthy child who reaches two years after
    # an infant dose is no longer in the infant series at all. Matched on the
    # first dose, that child is chased for the rest of a baby's course until
    # they are sixteen.
    match_age_on = db.Column(db.String(8), default="start")
    # A catch-up: this band's doses are **additional** to what is on file
    # rather than the whole course, so the earlier doses do not fill its slots.
    #
    # Without it a catch-up cannot be written down at all. "One dose to
    # complete, for a healthy child of two to four" is a one-dose course, and
    # a one-dose course has its single slot filled by the infant dose the
    # child already had — so "one more" comes out as "nothing owed", which is
    # the opposite of what it says.
    #
    # The same shape as a season: the slots start empty, and the doses already
    # given decide how *long* the course is rather than filling it. That
    # machinery was built for influenza and is reused here.
    starts_fresh = db.Column(db.Boolean, default=False, nullable=False)
    # The reference recommends *something* here and does not say how much.
    #
    # A real category, and one nothing in the engine could express. WHO's
    # pneumococcal position paper recommends catch-up between one and five
    # years and then says, in as many words, that "current data are
    # insufficient for a firm recommendation on the optimal number of doses
    # (1 or 2) required" in a child of 12–23 months.
    #
    # Neither of the two answers the engine had was true of that. An empty
    # course says "nothing is owed", which is the opposite of what the
    # reference says. No band at all says "this age is not scheduled", and
    # left an unvaccinated two-year-old with a blank card in a clinic whose
    # guideline recommends vaccinating them.
    #
    # So the band exists, carries no number, and asks for the doctor. It is
    # the same discipline as everywhere else in this engine — the program will
    # not invent a clinical number — said about a gap in the guideline rather
    # than a contradiction in the record.
    needs_review = db.Column(db.Boolean, default=False, nullable=False)

    PREVIOUS_STATES = ["none", "some"]
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

    SOURCES = ["egypt", "manufacturer", "cdc", "who", "national", "custom"]

    # Which of those a clinic can *follow*. The national EPI rows and a
    # clinic's own edits are schedules in their own right; the four below are
    # the published references a clinic chooses between as a policy.
    #
    # The choice is a setting, not a fork in the code. Bexsero's course is the
    # European label's from two months and the CDC's from ten years — the same
    # product, two published positions — and a clinic changing which one it
    # follows must not need a developer, or a re-entry of a single dose.
    #
    # `egypt` is a profile in the same sense as the other three: a set of rows
    # tagged with it, seeded from the Egyptian programme, edited in the same
    # editor. There is no code path that reads `egypt` and goes looking
    # somewhere else — a profile that was a name for another profile's rules
    # would be a lie told in a settings box, and the whole point of the
    # setting is that the clinic can read what it is following.
    #
    # It is silent about the vaccines the Egyptian programme does not run, and
    # silence is not a gap to be papered over: for those, the leaflet answers,
    # which is exactly how a private-market vaccine is given here.
    GUIDELINE_PROFILES = ["manufacturer", "egypt", "cdc", "who"]

    # What a clinic follows until somebody says otherwise. Named here rather
    # than spelled out at each reader, because a default that lives in three
    # places is a default that will disagree with itself.
    #
    # The leaflet, on the doctor's instruction and for the doctor's reason:
    # *"من المصنع، لأن الطبيب بيختار ويرجحه اللي مندوب الأدوية بيقوله."* The
    # product's own label is what is actually being quoted across the desk,
    # and a default that names it is a default that describes the practice.
    #
    # And it costs nothing to switch to, which is why this is a change of
    # label more than of behaviour. `egypt` states no schedule outside the
    # national programme, and for the national programme the rows are the
    # leaflet's anyway — measured child by child, `egypt → manufacturer` moves
    # nothing at all (see IMPROVEMENTS_BACKLOG). What changes is that a clinic
    # reading its own settings screen sees the reference it is really on,
    # instead of one that quietly hands most of the fridge to the leaflet.
    DEFAULT_GUIDELINE_PROFILE = "manufacturer"

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
    # Where it was given — the government unit, another clinic, abroad. Asked
    # for because "the first dose was somewhere else" is only half an answer.
    outside_place = db.Column(db.String(160))

    # Clinical documentation (PDF): given / refused / delayed, plus details.
    event_type = db.Column(db.String(20), default="given", nullable=False)
    # Set when this dose came from a history import rather than from a nurse
    # recording it here. It marks the doses whose numbering was *inferred* from
    # dates rather than observed, which is exactly the set a doctor may need to
    # correct — and it is what lets an import be undone without touching what
    # the clinic has entered since.
    import_batch_id = db.Column(db.Integer, nullable=True, index=True)
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


# Why the money and the clinic can disagree about a vaccine, and what to do
# about it: the dose was paid for at reception, then the doctor refused it
# (fever) or swapped the brand inside the room.
SETTLEMENT_REASONS = ["refused", "swapped"]


class VaccineSettlement(db.Model):
    """A paid vaccine that didn't happen as billed — and the money it owes.

    Reception collects the vaccine up front, so anything the doctor decides in
    the room (refuse the dose, swap RotaRix for RotaTeq) leaves the invoice
    describing something that never happened. Rather than let that drift, the
    clinical record raises a settlement: the invoice line that billed the
    vaccine, what actually happened, and the difference — negative to refund,
    positive to collect. Reception applies it from the cashier screen, which
    rewrites the line to reality and hands back (or takes) the difference.
    """
    __tablename__ = "vaccine_settlements"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"),
                        nullable=False, index=True)
    billed_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                                nullable=False)
    # NULL when the dose was refused outright (nothing replaced it).
    actual_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                                nullable=True)
    dose_id = db.Column(db.Integer, db.ForeignKey("patient_vaccines.id"),
                        nullable=True)
    reason = db.Column(db.String(12), default="refused", nullable=False)
    # + = collect from the patient, − = refund to the patient.
    amount = db.Column(db.Float, default=0, nullable=False)
    status = db.Column(db.String(10), default="pending", nullable=False)  # pending|done|cancelled
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    settled_at = db.Column(db.DateTime)
    settled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    patient = db.relationship("Patient")
    invoice = db.relationship("Invoice")
    item = db.relationship("InvoiceItem")
    billed_brand = db.relationship("VaccineBrand", foreign_keys=[billed_brand_id])
    actual_brand = db.relationship("VaccineBrand", foreign_keys=[actual_brand_id])
    dose = db.relationship("PatientVaccine")
    settler = db.relationship("User")

    @property
    def is_refund(self):
        return (self.amount or 0) < 0

    @property
    def abs_amount(self):
        return round(abs(self.amount or 0), 2)

    def __repr__(self):
        return f"<VaccineSettlement {self.reason} {self.amount}>"
