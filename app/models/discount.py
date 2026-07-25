"""Named (reusable) discounts that layer on top of manual line discounts.

Unlike a one-off manual discount typed on an invoice line, a named discount is
defined once and applied by name: a clinic campaign (with a date window), a
doctor's discount, a client-category discount (relatives / friends / staff), or
a special discount. It reuses the same effective-date idea as payer contracts.
"""
from datetime import date, datetime

from app.extensions import db

DISCOUNT_TYPES = ["campaign", "doctor", "category", "payer", "special"]


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

    # Eligibility: a doctor (doctor type), a client category (category type),
    # or a payer's members (payer type) — the club/company/syndicate whose
    # card the patient holds. The last one is how a club gets a flat member
    # discount without negotiating a per-service price list.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    client_category = db.Column(db.String(20))
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"),
                         nullable=True, index=True)

    # Optional validity window (used by campaigns; open-ended otherwise).
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doctor = db.relationship("User")
    payer = db.relationship("PayerEntity")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    @property
    def is_all_scope(self):
        return not self.scope or self.scope == "all"

    def scope_label(self, lang="ar"):
        """Human label for what this discount applies to (كشف / جهاز / تطعيم…)."""
        from app.i18n import t
        if self.is_all_scope:
            return t("discounts.scope_all")
        return t("service_categories." + self.scope)

    def applies_to_line(self, service):
        """Whether this discount may reduce a line billed for ``service``.

        An "all" discount hits every line; a scoped discount only hits lines
        whose service category matches — free-text lines (no service) are only
        touched by an "all" discount."""
        if self.is_all_scope:
            return True
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
        if self.dtype == "doctor":
            return self.doctor_id is not None and self.doctor_id == doctor_id
        if self.dtype == "category":
            cat = patient.client_category if patient else None
            return self.client_category is not None and self.client_category == cat
        if self.dtype == "payer":
            # Members only: the patient must hold a *valid* card for this payer.
            if self.payer_id is None or patient is None:
                return False
            return any(c.payer_id == self.payer_id and c.is_valid
                       for c in getattr(patient, "coverages", []))
        # campaign / special apply broadly.
        return True

    def amount_for(self, gross):
        """Discount amount this rule yields for a given line gross."""
        gross = max(gross or 0, 0)
        if self.is_percent:
            return round(gross * (self.value or 0) / 100.0, 2)
        return round(min(self.value or 0, gross), 2)

    def __repr__(self):
        return f"<NamedDiscount {self.name} {self.dtype}>"
