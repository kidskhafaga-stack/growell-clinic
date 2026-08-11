"""Payer entities, per-service coverage & patient memberships (Finance).

A ``PayerEntity`` is a third party that covers part of patients' bills under an
agreement — a club, a syndicate, an insurer, a company. Coverage is defined
**per service** (a benefits table): for each service the entity covers a
percentage or a fixed amount, and the patient pays the rest. Services with no
rule are not covered (the patient pays in full).

A ``PatientCoverage`` links a patient to an entity with their own card number
and expiry; when billing a member the per-service coverage is applied
automatically and the entity's share becomes claimable.
"""
from datetime import date, datetime

from app.extensions import db
from app.utils.clock import local_today

PAYER_TYPES = ["club", "syndicate", "insurance", "company", "cash", "other"]
COVERAGE_TYPES = ["percent", "fixed"]


class PayerType(db.Model):
    """The clinic's own list of what kinds of entity it deals with.

    The third list to be opened up, after the service types and the client
    categories, and for the same reason each time: a fixed six was somebody
    else's guess at how a clinic is organised. "جمعية" and "بنك" and "مدرسة"
    are real payers, and forcing them into "other" makes every report that
    groups by type say nothing.

    ``cash`` is the one key code reads by name — it is how the clinic's own
    price list is recognised (:func:`app.utils.pricing.cash_payer`) — so keys
    never change once made, and the built-in rows cannot be deleted. A clinic
    can rename any of them and add its own.
    """
    __tablename__ = "payer_types"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False, index=True)
    name_ar = db.Column(db.String(60))
    name_en = db.Column(db.String(60))
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)

    def display_name(self, lang="ar"):
        if lang == "en":
            return self.name_en or self.name_ar or self.key
        return self.name_ar or self.name_en or self.key

    def __repr__(self):
        return f"<PayerType {self.key}>"


class PayerEntity(db.Model):
    __tablename__ = "payer_entities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    name_en = db.Column(db.String(160))
    entity_type = db.Column(db.String(20), default="club", nullable=False)
    discount_percent = db.Column(db.Float, default=0)  # legacy default (fallback display)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(120))
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    invoices = db.relationship("Invoice", back_populates="payer")
    service_rates = db.relationship("PayerServiceRate", back_populates="payer",
                                    cascade="all, delete-orphan")
    contracts = db.relationship("PayerContract", back_populates="payer",
                                cascade="all, delete-orphan",
                                order_by="PayerContract.start_date.desc()")

    def display_name(self, lang="ar"):
        return self.name_en if (lang == "en" and self.name_en) else self.name

    def active_contract(self, on_date=None):
        """The contract in force on ``on_date`` (defaults to today), or None.

        The clinic's today. These four dates decide **what a family is
        charged** — which contract applies, whether a price list has started,
        whether a card has expired — so a boundary crossing three hours late
        puts the wrong price on a real bill. They were left out of the first
        clock sweep as "expiry dates", which was wrong: a manufacturer's
        expiry on a vaccine vial is a fact about the vial, and this is a fact
        about the clinic's day.
        """
        d = on_date or local_today()
        live = [c for c in self.contracts if c.is_active
                and (not c.start_date or c.start_date <= d)
                and (not c.end_date or d <= c.end_date)]
        if not live:
            return None
        return sorted(live, key=lambda c: c.start_date or date.min, reverse=True)[0]

    def covers(self, service, amount, on_date=None):
        """Amount this entity covers for ``service`` on a line of ``amount``.

        Option (ب): a service with no rule is NOT covered (patient pays full).
        If the entity has any contracts, coverage applies only when a contract
        is in force on ``on_date`` — and when that contract carries its own
        price list, the contract's rows win over the payer-level defaults (so
        renewing a contract with new terms changes billing on its start date).
        """
        if service is None:
            return 0.0
        rate = None
        if self.contracts:
            contract = self.active_contract(on_date)
            if contract is None:
                return 0.0
            if contract.rates:
                rate = next((r for r in contract.rates
                             if r.service_id == service.id), None)
                if rate is None:
                    return 0.0      # contract list is authoritative when present
        if rate is None:
            rate = next((r for r in self.service_rates
                         if r.service_id == service.id), None)
        if rate is None:
            return 0.0
        if rate.coverage_type == "percent":
            return round(max(amount, 0) * (rate.coverage_value or 0) / 100.0, 2)
        return round(min(rate.coverage_value or 0, max(amount, 0)), 2)

    def tariff(self, service, on_date=None):
        """The active contract's negotiated price for ``service`` (or None).

        A contract row may fix the service's price for members (سعر تعاقدي) —
        e.g. a cash-agreement list or an insurer tariff. Billing reprices the
        line to this before coverage is applied."""
        if service is None or not self.contracts:
            return None
        contract = self.active_contract(on_date)
        if contract is None:
            return None
        rate = next((r for r in contract.rates
                     if r.service_id == service.id), None)
        return rate.special_price if rate and rate.special_price is not None else None

    def __repr__(self):
        return f"<PayerEntity {self.name}>"


class PayerServiceRate(db.Model):
    """One row of an entity's benefits table: coverage for a given service."""
    __tablename__ = "payer_service_rates"
    __table_args__ = (
        db.UniqueConstraint("payer_id", "service_id", name="uq_payer_service"),
    )

    id = db.Column(db.Integer, primary_key=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False, index=True)
    coverage_type = db.Column(db.String(10), default="percent", nullable=False)
    coverage_value = db.Column(db.Float, default=0)  # what the entity covers

    payer = db.relationship("PayerEntity", back_populates="service_rates")
    service = db.relationship("Service")

    def __repr__(self):
        return f"<PayerServiceRate payer={self.payer_id} svc={self.service_id}>"


class PayerContract(db.Model):
    """A date-bounded agreement with a payer entity (company/insurer)."""
    __tablename__ = "payer_contracts"

    id = db.Column(db.Integer, primary_key=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False, index=True)
    number = db.Column(db.String(60))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payer = db.relationship("PayerEntity", back_populates="contracts")
    rates = db.relationship("PayerContractRate", back_populates="contract",
                            cascade="all, delete-orphan")

    def copy_to(self, number=None, start_date=None, end_date=None):
        """A new (unsaved) contract for the same payer carrying a full copy of
        this contract's price list — the renewal workflow: copy, adjust prices,
        set the new period."""
        clone = PayerContract(
            payer_id=self.payer_id, number=number,
            start_date=start_date, end_date=end_date,
            notes=self.notes, is_active=True)
        for r in self.rates:
            clone.rates.append(PayerContractRate(
                service_id=r.service_id, special_price=r.special_price,
                coverage_type=r.coverage_type, coverage_value=r.coverage_value))
        return clone

    @property
    def is_current(self):
        d = local_today()
        return (self.is_active
                and (not self.start_date or self.start_date <= d)
                and (not self.end_date or d <= self.end_date))

    @property
    def is_scheduled(self):
        """Signed today, in force later — a price list that starts on a date."""
        return bool(self.is_active and self.start_date
                    and self.start_date > local_today())

    @property
    def status_key(self):
        """``current`` | ``scheduled`` | ``expired`` | ``inactive``."""
        if not self.is_active:
            return "inactive"
        if self.is_current:
            return "current"
        if self.is_scheduled:
            return "scheduled"
        return "expired"

    def overlaps(self, other):
        """Whether two contracts of the same payer share any day.

        Overlapping is allowed on purpose — a renewal is signed while the old
        one still runs, and one payer can hold several lists. On a shared day
        the one with the **later start date** is the one that bills."""
        if other is None or other.id == self.id or other.payer_id != self.payer_id:
            return False
        a_start = self.start_date or date.min
        a_end = self.end_date or date.max
        b_start = other.start_date or date.min
        b_end = other.end_date or date.max
        return a_start <= b_end and b_start <= a_end

    def overlapping(self):
        """Sibling contracts sharing days with this one (active ones only)."""
        return [c for c in self.payer.contracts
                if c.is_active and self.overlaps(c)] if self.payer else []

    def __repr__(self):
        return f"<PayerContract payer={self.payer_id} {self.start_date}..{self.end_date}>"


class PayerContractRate(db.Model):
    """One service row of a contract's price list: an optional negotiated
    price (سعر تعاقدي — what the line is billed at for members) and what the
    entity covers of it. A contract with rows is authoritative; one without
    falls back to the payer's default benefits table."""
    __tablename__ = "payer_contract_rates"
    __table_args__ = (
        db.UniqueConstraint("contract_id", "service_id", name="uq_contract_service"),
    )

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("payer_contracts.id"),
                            nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"),
                           nullable=False, index=True)
    special_price = db.Column(db.Float)            # NULL = clinic default price
    coverage_type = db.Column(db.String(10), default="percent", nullable=False)
    coverage_value = db.Column(db.Float, default=0)

    contract = db.relationship("PayerContract", back_populates="rates")
    service = db.relationship("Service")

    def __repr__(self):
        return f"<ContractRate c={self.contract_id} svc={self.service_id}>"


class PatientCoverage(db.Model):
    """A patient's membership/insurance card under a payer entity."""
    __tablename__ = "patient_coverages"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=False)
    membership_number = db.Column(db.String(60))
    expiry_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="coverages")
    payer = db.relationship("PayerEntity")

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < local_today())

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    def __repr__(self):
        return f"<PatientCoverage p={self.patient_id} payer={self.payer_id}>"



CLAIM_STATUSES = ["draft", "submitted", "approved", "rejected", "paid"]


class Claim(db.Model):
    """A numbered claim document (مطالبة) submitted to a payer entity.

    Snapshots the covered invoices of a period into an auditable document
    with a lifecycle: draft → submitted → approved/rejected → paid. Once an
    invoice sits on a live claim it can't be claimed again; a rejected
    claim releases its invoices.
    """

    __tablename__ = "claims"

    id = db.Column(db.Integer, primary_key=True)
    claim_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"),
                         nullable=False, index=True)
    date_from = db.Column(db.Date, nullable=False)
    date_to = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(10), default="draft", nullable=False, index=True)
    total_amount = db.Column(db.Float, default=0, nullable=False)   # snapshot
    approved_amount = db.Column(db.Float)     # what the payer accepted
    paid_amount = db.Column(db.Float)
    payment_method = db.Column(db.String(12))
    submitted_at = db.Column(db.DateTime)
    decided_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    notes = db.Column(db.String(255))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    payer = db.relationship("PayerEntity")
    creator = db.relationship("User")
    items = db.relationship("ClaimItem", back_populates="claim",
                            cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Claim {self.claim_number} {self.status}>"


class ClaimItem(db.Model):
    """One covered invoice inside a claim, with its claimable amount frozen."""

    __tablename__ = "claim_items"

    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey("claims.id"),
                         nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)

    claim = db.relationship("Claim", back_populates="items")
    invoice = db.relationship("Invoice")

    def __repr__(self):
        return f"<ClaimItem claim={self.claim_id} inv={self.invoice_id}>"
