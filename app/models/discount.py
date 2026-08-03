"""Named (reusable) discounts that layer on top of manual line discounts.

Unlike a one-off manual discount typed on an invoice line, a named discount is
defined once and applied by name: a clinic campaign (with a date window), a
doctor's discount, a client-category discount (relatives / friends / staff), or
a special discount. It reuses the same effective-date idea as payer contracts.

**One discount per line.** A child can qualify for several at once — his club
gives members 20%, and he came with his brother for 50% — but he is never given
both on the same service. The billing side prices every rule the patient
qualifies for against the actual invoice and applies the single biggest one;
reception can override the choice.
"""
from datetime import date, datetime

from app.extensions import db

DISCOUNT_TYPES = ["campaign", "doctor", "category", "payer", "sibling",
                  "special"]

# A scope that is not a service category, because a vaccine vial is not a
# service: it is priced by its brand and billed by it. It needs its own name
# here so the vial and the fee for giving it can be aimed at separately — they
# used to share the fee's service, which made a discount on "رسم تطعيم" reduce
# the price of the vaccine as well.
VACCINE_SCOPE = "vaccine"


# Which clubs, companies or syndicates one discount covers.
#
# It started as a single ``payer_id``, which forced a clinic offering the same
# terms to four clubs to keep four identical rules — and four places to forget
# when the terms change. The offer is one thing; the list of cards it honours
# is a list.
named_discount_payers = db.Table(
    "named_discount_payers",
    db.Column("discount_id", db.Integer, db.ForeignKey("named_discounts.id"),
              primary_key=True),
    db.Column("payer_id", db.Integer, db.ForeignKey("payer_entities.id"),
              primary_key=True),
)


class DiscountMember(db.Model):
    """One person named on a discount by hand — or taken off it by hand.

    Eligibility here has always been *computed*: a club discount looks for a
    card, a category discount looks at the parents' category, a doctor's
    discount looks at who is seeing the child. That is right for the common
    case and useless for the two a clinic actually runs into.

    **"These people, by name."** The list the clinic keeps in its head — the
    doctors' children, the four families from the old practice — with nothing
    on file that a rule could match on.

    **"Everyone except him."** A member whose discount the clinic has stopped,
    without deleting the rule that covers the other three hundred.

    ``mode`` says which. An exclusion always wins: taking somebody off a
    discount is an instruction, and an instruction that a rule can override is
    not one.
    """
    __tablename__ = "discount_members"

    id = db.Column(db.Integer, primary_key=True)
    discount_id = db.Column(db.Integer, db.ForeignKey("named_discounts.id"),
                            nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    mode = db.Column(db.String(10), default="include", nullable=False)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    patient = db.relationship("Patient")
    discount = db.relationship("NamedDiscount", back_populates="members")

    @property
    def is_exclusion(self):
        return self.mode == "exclude"

    def __repr__(self):
        return f"<DiscountMember d={self.discount_id} p={self.patient_id} {self.mode}>"


class NamedDiscount(db.Model):
    __tablename__ = "named_discounts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    name_en = db.Column(db.String(120))
    dtype = db.Column(db.String(12), default="special", nullable=False)

    value = db.Column(db.Float, default=0, nullable=False)
    is_percent = db.Column(db.Boolean, default=True, nullable=False)

    # What the discount is applied *to*: "all" (every line) or a single service
    # category — consultation (كشف/استشارة), procedure/radiology (جهاز),
    # vaccination_fee (تطعيم), lab… — so the reception sees exactly what a named
    # discount reduces and it never bleeds onto unrelated lines.
    scope = db.Column(db.String(20), default="all", nullable=False)
    # Narrower still: one named service. A clinic that wants "الإخوة الثاني
    # نص تمن الكشف" means the exam, not every line of the category.
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=True, index=True)

    # Eligibility: a doctor (doctor type), a client category (category type),
    # or a payer's members (payer type) — the club/company/syndicate whose
    # card the patient holds. The last one is how a club gets a flat member
    # discount without negotiating a per-service price list.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    client_category = db.Column(db.String(20))
    # Kept for the rules written before a discount could name several: it is
    # still read, so nothing an existing clinic saved stops working, and it is
    # still written when exactly one is chosen.
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"),
                         nullable=True, index=True)
    payers = db.relationship("PayerEntity", secondary=named_discount_payers,
                             lazy="selectin")

    # People named on this discount by hand — see :class:`DiscountMember`.
    members = db.relationship("DiscountMember", back_populates="discount",
                              cascade="all, delete-orphan", lazy="selectin")
    # Whether the named list *replaces* the rule or adds to it.
    #
    # Off by default, and that default is the whole safety of this feature: an
    # existing discount gains a members list without anybody's eligibility
    # changing. Switched on, only the named people get it — which is what a
    # clinic means by "the discount is for these families" and would be a
    # catastrophe to assume.
    members_only = db.Column(db.Boolean, default=False, nullable=False)
    # Sibling discount: how many children of the same family have to be seen
    # on the same day before it applies (2 = "two brothers together").
    min_siblings = db.Column(db.Integer, default=2)
    # …and whether they have to be with the *same* doctor. "الأخوين سوا" is an
    # offer a doctor makes on their own list; two children who happened to see
    # two different doctors on the same day are two separate visits.
    same_doctor = db.Column(db.Boolean, default=True, nullable=False)

    # A club card is held by the family, not by one child: when the brother is
    # the member, his sibling is a member too. Switch it off for a payer whose
    # card really is personal (a staff card, a syndicate membership).
    family_wide = db.Column(db.Boolean, default=True, nullable=False)

    # Whether the system may pick this rule by itself. Eligibility rules
    # (club / siblings / doctor / category / campaign) normally should. A
    # "خصم خاص" never does, whatever this says — that type exists precisely to
    # be chosen by hand for one bill.
    auto_apply = db.Column(db.Boolean, default=True, nullable=False)

    # Optional validity window (used by campaigns; open-ended otherwise).
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    payer = db.relationship("PayerEntity")
    service = db.relationship("Service")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def is_all_scope(self):
        return not self.scope or self.scope == "all"

    def scope_label(self, lang="ar"):
        """Human label for what this discount applies to (كشف / جهاز / تطعيم…)."""
        from app.i18n import t
        if self.service_id and self.service is not None:
            return self.service.display_name(lang)
        if self.is_all_scope:
            return t("discounts.scope_all")
        if self.scope == VACCINE_SCOPE:
            return t("discounts.scope_vaccine")
        return t("service_categories." + self.scope)

    def applies_to_line(self, item):
        """Whether this discount may reduce one invoice line.

        Takes the **line**, not just its service, because not every charge is a
        service. A vaccine vial is priced by its brand and carries no service at
        all: it used to borrow the vaccination-fee service's id, which made the
        fee and the vial indistinguishable to this method — so a discount aimed
        at "رسم تطعيم" quietly reduced the price of the vaccine as well, and the
        fee could be discounted while the vial was collected in full.

        A discount aimed at one service hits only that service; an "all"
        discount hits every line; the ``vaccine`` scope hits vial lines; and any
        other scope matches a service category. A free-text line with no service
        and no brand is reached only by an "all" discount, because there is
        nothing narrower to aim at.
        """
        service = getattr(item, "service", None)
        is_vial = bool(getattr(item, "vaccine_brand_id", None))
        if self.service_id:
            return service is not None and service.id == self.service_id
        if self.is_all_scope:
            return True
        if self.scope == VACCINE_SCOPE:
            return is_vial
        # A vial is never caught by a service-category scope: it has no service,
        # and the fee's category must not reach it.
        if service is None:
            return False
        return service.category == self.scope

    def in_window(self, on_date=None):
        d = on_date or date.today()
        return ((not self.start_date or self.start_date <= d)
                and (not self.end_date or d <= self.end_date))

    def applies_to(self, patient=None, doctor_id=None, on_date=None):
        """Eligibility check for an invoice context."""
        if not self.is_active or not self.in_window(on_date):
            return False

        # What a person put on the list, before what a rule works out.
        #
        # An exclusion wins over everything: taking somebody off a discount is
        # an instruction, and one a rule can override is not an instruction.
        # An inclusion wins over the rule the other way — that is the point of
        # naming somebody who has nothing on file to match on.
        if patient is not None and self.members:
            named = {m.patient_id: m for m in self.members}
            hit = named.get(patient.id)
            if hit is not None:
                return not hit.is_exclusion
            if self.members_only:
                return False
        elif self.members_only:
            return False        # a list-only discount with nobody on the list

        if self.dtype == "doctor":
            return self.doctor_id is not None and self.doctor_id == doctor_id
        if self.dtype == "category":
            # Every parent's category, not just the contact's. A child with a
            # staff father and a friend mother is entitled through both, and
            # which of the two is worth more is decided by pricing each rule
            # against the actual bill — not here.
            if patient is None or self.client_category is None:
                return False
            return self.client_category in patient.client_categories
        if self.dtype == "sibling":
            # Needs the day's context (who else from the family was seen), so
            # the caller decides — here we only confirm the rule is live.
            return patient is not None and patient.family_id is not None
        if self.dtype == "payer":
            # Members only: the patient must hold a *valid* card for one of the
            # named payers — or, for a family card, one of their siblings must.
            if not self.payer_ids or patient is None:
                return False
            if self._has_card(patient):
                return True
            if self.family_wide:
                return any(self._has_card(s)
                           for s in (getattr(patient, "siblings", None) or []))
            return False
        # campaign / special apply broadly.
        return True

    @property
    def payer_ids(self):
        """Every payer this discount honours, old single column included.

        One offer can cover several clubs. Reading both shapes here is what
        lets the new list arrive without rewriting the rules a clinic already
        saved — and a rule saved with one club keeps working untouched.
        """
        ids = {p.id for p in (self.payers or [])}
        if self.payer_id:
            ids.add(self.payer_id)
        return ids

    def _has_card(self, patient):
        """A valid membership card of any of these payers, on this file."""
        wanted = self.payer_ids
        return any(c.payer_id in wanted and c.is_valid
                   for c in (getattr(patient, "coverages", None) or []))

    def amount_for(self, gross):
        """Discount amount this rule yields for a given line gross."""
        gross = max(gross or 0, 0)
        if self.is_percent:
            return round(gross * (self.value or 0) / 100.0, 2)
        return round(min(self.value or 0, gross), 2)

    def __repr__(self):
        return f"<NamedDiscount {self.name} {self.dtype}>"
