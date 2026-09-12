"""Packages: a number of sessions sold once, and drawn down one at a time.

Asked for as *«خلي الاثنين متاحين باقة وجلسة بجلسة»* — both, not one instead
of the other. A psychology course is the case that raised it: some families
pay for ten sessions up front at a better rate, and some pay each time they
come, and the same service has to be sellable both ways on the same screen.

**The money moves once, at the sale.** A package on the invoice is an ordinary
line at an ordinary price — the same line, the same till, the same journal as
everything else. What the package adds is a *balance in sessions*, not a
balance in money, and drawing on it puts a zero line on that day's bill
saying which session of how many it was. Nothing here invents a second way
for money to arrive, and nothing here holds money the accounts cannot see.

**And that is why the draw is worth recording at all.** The alternative — the
covered visit simply producing no bill — loses the one fact a family asks
about six weeks later: *which* session was that, and how many are left. The
zero line is the answer, on the document they already keep.

Three ways a balance can be gone, and they are not the same fact:

* **spent** — ten of ten drawn;
* **expired** — the course had a window and it closed;
* **cancelled** — the sale was undone (a refund, a family that stopped).

Each is stored separately because each reads differently to the person at the
desk, and because "no sessions left" and "this was refunded" must never be one
column with one empty value standing for both.
"""
from datetime import datetime

from app.extensions import db


class ServicePackage(db.Model):
    """A catalogue offer: *N sessions of this service, for this price.*

    Hangs off a service rather than replacing it, so per-session stays exactly
    what it was — the service keeps its own price and every screen that sells
    it is untouched. A clinic that never defines a package never sees one.
    """

    __tablename__ = "service_packages"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=False, index=True)
    name_ar = db.Column(db.String(120))
    name_en = db.Column(db.String(120))
    sessions = db.Column(db.Integer, default=1, nullable=False)
    price = db.Column(db.Float, default=0, nullable=False)
    # How long the course stays usable, in days from the sale. NULL is "no
    # window" and is stored as NULL on purpose: zero would read as "expires
    # the day it is sold", which is a real thing to say and the opposite of
    # what an unset field means.
    valid_days = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    service = db.relationship("Service")

    def display_name(self, lang="ar"):
        name = self.name_en if lang == "en" else self.name_ar
        if name:
            return name
        if self.service is not None:
            return f"{self.service.display_name(lang)} × {self.sessions}"
        return f"× {self.sessions}"

    @property
    def per_session(self):
        """What one session works out at inside the package.

        The number the family is actually comparing against the walk-in price,
        so the screen shows it rather than making somebody divide.
        """
        if not self.sessions:
            return 0
        return round((self.price or 0) / self.sessions, 2)

    def __repr__(self):
        return f"<ServicePackage svc={self.service_id} x{self.sessions}>"


class PatientPackage(db.Model):
    """A package this family bought — the balance itself.

    Everything that decides what it covers is **copied here at the sale**, not
    read back through the catalogue: the service, the count, the name, the
    price paid. A clinic that later renames the offer, reprices it, or points
    it at another service must not thereby change what a family already paid
    for.
    """

    __tablename__ = "patient_packages"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           nullable=False, index=True)
    # Where it came from, for the screen. Nullable, because the catalogue row
    # can be retired and this balance still has to work.
    package_id = db.Column(db.Integer, db.ForeignKey("service_packages.id"),
                           index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=False, index=True)
    # The line that paid for it. The link the balance rests on: without it,
    # "was this package actually paid for" has no answer but somebody's word.
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), index=True)
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"))
    name = db.Column(db.String(120))
    sessions_total = db.Column(db.Integer, default=1, nullable=False)
    price_paid = db.Column(db.Float, default=0)
    sold_on = db.Column(db.Date, index=True)
    expires_on = db.Column(db.Date, index=True)
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(200))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    patient = db.relationship("Patient")
    package = db.relationship("ServicePackage")
    service = db.relationship("Service")
    invoice = db.relationship("Invoice")
    uses = db.relationship("PackageUse", back_populates="package",
                           cascade="all, delete-orphan",
                           order_by="PackageUse.id")

    def display_name(self, lang="ar"):
        if self.name:
            return self.name
        if self.package is not None:
            return self.package.display_name(lang)
        if self.service is not None:
            return f"{self.service.display_name(lang)} × {self.sessions_total}"
        return f"× {self.sessions_total}"

    @property
    def used(self):
        return len(self.uses)

    @property
    def remaining(self):
        return max(0, (self.sessions_total or 0) - self.used)

    def expired(self, on=None):
        """Has the window closed? A package with no window never expires."""
        if not self.expires_on:
            return False
        from app.utils.clock import local_today

        return (on or local_today()) > self.expires_on

    def is_open(self, on=None):
        """Can a session be drawn from it right now — and only then."""
        return (self.cancelled_at is None
                and self.remaining > 0
                and not self.expired(on))

    def state(self, on=None):
        """Why it cannot be drawn on, when it cannot — for the screen.

        One of ``open`` / ``cancelled`` / ``spent`` / ``expired``. Cancelled
        wins over spent, and spent over expired, because that is the order a
        person would say them in: a refunded course is refunded whatever its
        count says.
        """
        if self.cancelled_at is not None:
            return "cancelled"
        if self.remaining <= 0:
            return "spent"
        if self.expired(on):
            return "expired"
        return "open"

    def __repr__(self):
        return f"<PatientPackage p={self.patient_id} {self.used}/{self.sessions_total}>"


class PackageUse(db.Model):
    """One session drawn from a balance.

    The row *is* the drawdown: the remaining count is derived from these and
    never stored, so there is no second number to fall out of step with them.
    """

    __tablename__ = "package_uses"

    id = db.Column(db.Integer, primary_key=True)
    patient_package_id = db.Column(db.Integer,
                                   db.ForeignKey("patient_packages.id"),
                                   nullable=False, index=True)
    used_on = db.Column(db.Date, index=True)
    # The zero line on that day's bill, which is how the family sees it.
    # Nullable: a session can be drawn from the package screen for a visit
    # that raised no invoice at all.
    invoice_item_id = db.Column(db.Integer, db.ForeignKey("invoice_items.id"))
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    package = db.relationship("PatientPackage", back_populates="uses")

    @property
    def number(self):
        """Which session of the course this is — 1-based, by the order drawn."""
        rows = self.package.uses if self.package is not None else []
        for i, row in enumerate(rows, start=1):
            if row is self:
                return i
        return len(rows) + 1

    def __repr__(self):
        return f"<PackageUse pkg={self.patient_package_id} on={self.used_on}>"
