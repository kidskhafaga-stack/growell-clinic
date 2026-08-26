"""Invoicing & payments (Finance core).

An ``Invoice`` groups charged ``InvoiceItem`` lines for a patient (optionally
tied to a visit and credited to a doctor). Each line snapshots its price,
discount and the doctor commission at the time of billing, so later changes to
service rates never rewrite history. ``Payment`` rows record (possibly partial)
collections; the invoice status is derived from paid-vs-total.
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

INVOICE_STATUSES = ["unpaid", "partial", "paid"]
PAYMENT_METHODS = ["cash", "card", "instapay", "transfer", "wallet"]


class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    payer_id = db.Column(db.Integer, db.ForeignKey("payer_entities.id"), nullable=True, index=True)
    coverage_card = db.Column(db.String(60))   # snapshot: membership/card no.
    coverage_expiry = db.Column(db.Date)        # snapshot: card expiry
    # Named discount applied to this invoice (snapshot of the rule's name).
    discount_id = db.Column(db.Integer, db.ForeignKey("named_discounts.id"), nullable=True)
    discount_name = db.Column(db.String(120))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    invoice_date = db.Column(db.Date, default=local_today, nullable=False)
    status = db.Column(db.String(10), default="unpaid", nullable=False)
    is_tax = db.Column(db.Boolean, default=False, nullable=False)  # ETA tax invoice
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    creator = db.relationship("User", foreign_keys=[created_by])
    visit = db.relationship("Visit")
    payer = db.relationship("PayerEntity", back_populates="invoices")
    items = db.relationship("InvoiceItem", back_populates="invoice",
                            cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="invoice",
                               cascade="all, delete-orphan")

    # --- money ---------------------------------------------------------
    @property
    def subtotal(self):
        return round(sum(i.gross for i in self.items), 2)

    @property
    def discount_total(self):
        return round(sum(i.discount_amount for i in self.items), 2)

    @property
    def total(self):
        return round(sum(i.net for i in self.items), 2)

    @property
    def paid(self):
        """Net collected = payments − refunds."""
        return round(sum(p.signed_amount for p in self.payments), 2)

    @property
    def refunded(self):
        return round(sum(p.amount or 0 for p in self.payments if p.kind == "refund"), 2)

    @property
    def tendered(self):
        """Cash actually handed over by the patient (≥ ``paid`` when they paid
        with a bigger note). Used on the receipt so the review can see that the
        patient gave 200 for a 127.50 bill."""
        return round(sum(p.handed_over for p in self.payments
                         if p.kind != "refund"), 2)

    @property
    def change_given(self):
        """Change the cashier had to give back (tendered − applied)."""
        return round(sum(p.change_due for p in self.payments), 2)

    @property
    def balance(self):
        return round(self.total - self.paid, 2)

    @property
    def doctor_share_total(self):
        return round(sum(i.commission_amount or 0 for i in self.items), 2)

    @property
    def clinic_share_total(self):
        return round(self.total - self.doctor_share_total, 2)

    @property
    def no_charge(self):
        """Settled because there was nothing to charge, not because money came.

        A 100% staff discount and a service priced at zero both produce an
        invoice that is closed the moment it exists. Calling that "paid" is
        true about the *collection* — there is nothing left to collect — and
        misleading about the money, because none moved. The status stays
        "paid" so every filter, report and query keeps working; only the word
        on the screen changes.
        """
        return self.total <= 0 and self.paid == 0

    @property
    def status_label(self):
        """The wording key for this invoice's state.

        One place, because two screens render this badge and a third renders
        the same idea on the appointment board. Written out three times it
        would be right in two of them.
        """
        return "invoices.st_free" if self.no_charge else f"invoices.st_{self.status}"

    def recalc_status(self):
        """Settled, part-paid, or owing — from what is actually left.

        The ``total > 0`` guard this used to open with meant a bill that came
        to nothing was never settled. A staff member's child on a 100%
        discount produced an invoice of 0.00 with 0.00 paid, which is not
        "unpaid" — nobody owes anything on it — and it sat in the till's *who
        still owes* list for ever, offering a Collect button that answered
        "already fully settled" when pressed.

        The same was true of an invoice whose last line had been deleted.

        So the question is simply whether anything is left to collect. Nothing
        left is settled, whether that is because the money came in or because
        there was never any to come.
        """
        paid, total = self.paid, self.total
        if paid >= total:
            self.status = "paid"
        elif paid > 0:
            self.status = "partial"
        else:
            self.status = "unpaid"
        return self.status

    def __repr__(self):
        return f"<Invoice {self.invoice_number}>"


def settle_what_has_nothing_left_to_collect():
    """Repair invoices whose stored status outlived the rule that set it.

    ``recalc_status`` only runs when something happens to an invoice, so
    fixing it does nothing for the rows already written — a clinic upgrading
    would still find last month's fully-discounted visits sitting in the till.
    This is the same shape as the About page's carried-over supervisor: a
    one-time data repair that runs from ``apply_schema``, is idempotent, and
    can be run again without effect.

    The candidates are narrowed in SQL and decided in Python. Deciding it in
    SQL would mean writing the discount arithmetic a second time, in a second
    language, where it could disagree with :meth:`InvoiceItem.net` — and an
    invoice quietly marked settled by a formula that rounds differently is a
    worse bug than the one being fixed. So the rows are loaded and asked.

    Returns the number of invoices corrected.
    """
    from sqlalchemy.orm import selectinload

    open_ones = (Invoice.query
                 .options(selectinload(Invoice.items),
                          selectinload(Invoice.payments))
                 .filter(Invoice.status.in_(["unpaid", "partial"])).all())
    fixed = 0
    for invoice in open_ones:
        before = invoice.status
        if invoice.recalc_status() != before:
            fixed += 1
    return fixed


class InvoiceItem(db.Model):
    __tablename__ = "invoice_items"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)

    description = db.Column(db.String(200), nullable=False)  # snapshot name
    # Set on lines that charge a vaccine product, so a dose the doctor later
    # refuses or swaps can be settled against the exact line that billed it.
    vaccine_brand_id = db.Column(db.Integer, db.ForeignKey("vaccine_brands.id"),
                                 nullable=True, index=True)
    # Which dose of that course was paid for. Set when a vaccine is sold
    # *forward* — the family pays at reception and the nurse gives it after —
    # so the choice made on the till screen is a fact the record can be
    # settled against. Without it, "which dose" would be asked, answered, and
    # thrown away, which is worse than not asking.
    vaccine_dose_number = db.Column(db.Integer)
    unit_price = db.Column(db.Float, default=0, nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    discount_value = db.Column(db.Float, default=0)          # raw input
    discount_is_percent = db.Column(db.Boolean, default=False)
    commission_amount = db.Column(db.Float, default=0)        # doctor cut snapshot

    invoice = db.relationship("Invoice", back_populates="items")
    service = db.relationship("Service")

    @property
    def gross(self):
        return round((self.unit_price or 0) * (self.quantity or 1), 2)

    @property
    def discount_amount(self):
        if self.discount_is_percent:
            return round(self.gross * (self.discount_value or 0) / 100.0, 2)
        return round(min(self.discount_value or 0, self.gross), 2)

    @property
    def net(self):
        return round(self.gross - self.discount_amount, 2)

    def __repr__(self):
        return f"<InvoiceItem {self.description}>"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    amount = db.Column(db.Float, default=0, nullable=False)
    method = db.Column(db.String(12), default="cash", nullable=False)
    # "payment" = money in; "refund" = money out (e.g. exam re-billed as consult).
    kind = db.Column(db.String(10), default="payment", nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # The cashier shift (وردية) this money was taken in, so each till session
    # reconciles independently. Null for payments recorded outside any shift.
    shift_id = db.Column(db.Integer, db.ForeignKey("cashier_shifts.id"), nullable=True, index=True)
    # Which till this money landed in. The method says how the family paid;
    # this says where it came to rest — two different facts, and a clinic with
    # reception on two floors has both of them taking cash.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.String(200))
    # What the patient actually handed over, when it is more than the amount
    # applied to the invoice (a 200 note for a 127.50 bill). Only ``amount``
    # enters the drawer/ledger; the difference is change given back on the
    # spot. Null = the patient paid the exact amount.
    tendered = db.Column(db.Float)

    account = db.relationship("CashAccount")

    @property
    def handed_over(self):
        """Cash put on the counter for this payment (= amount when exact)."""
        return round(self.tendered if self.tendered is not None
                     else (self.amount or 0), 2)

    @property
    def change_due(self):
        """Change the cashier owes the patient for this payment."""
        if self.kind == "refund" or self.tendered is None:
            return 0.0
        return round(max(0.0, self.tendered - (self.amount or 0)), 2)

    @property
    def signed_amount(self):
        """+ for a payment, − for a refund (drawer/paid maths)."""
        return -(self.amount or 0) if self.kind == "refund" else (self.amount or 0)

    invoice = db.relationship("Invoice", back_populates="payments")
    receiver = db.relationship("User")
    shift = db.relationship("CashierShift", back_populates="payments")

    def __repr__(self):
        return f"<Payment {self.amount} for inv={self.invoice_id}>"


class RefundRequest(db.Model):
    """A refund awaiting a manager's decision (F4 approval workflow).

    Non-admin staff can't take money out of the drawer directly: their refund
    becomes a pending request; an admin approves (which posts the real refund
    Payment + journal entry) or rejects it. Admins refund directly as before.
    """

    __tablename__ = "refund_requests"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"),
                           nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(12), default="cash", nullable=False)
    reason = db.Column(db.String(200))
    status = db.Column(db.String(10), default="pending", nullable=False,
                       index=True)  # pending / approved / rejected
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    invoice = db.relationship("Invoice")
    requester = db.relationship("User", foreign_keys=[requested_by])
    decider = db.relationship("User", foreign_keys=[decided_by])

    def __repr__(self):
        return f"<RefundRequest {self.amount} inv={self.invoice_id} {self.status}>"


class CashDrawerDay(db.Model):
    """The cashier's drawer for one day: the opening change float reception is
    handed at the start of the day. Expected cash = float + cash collected −
    cash refunds, reconciled against the counted amount at close.
    """
    __tablename__ = "cash_drawer_days"

    id = db.Column(db.Integer, primary_key=True)
    drawer_date = db.Column(db.Date, unique=True, nullable=False, index=True)
    opening_float = db.Column(db.Float, default=0, nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Close-of-day reconciliation (optional).
    # The till this shift is a session on. One shift = one person + one
    # drawer + a window of time; two cash drawers open at once are two shifts,
    # because two people are each short on their own.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    counted_cash = db.Column(db.Float)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    closed_at = db.Column(db.DateTime)
    notes = db.Column(db.String(255))

    account = db.relationship("CashAccount")
    opener = db.relationship("User", foreign_keys=[opened_by])
    closer = db.relationship("User", foreign_keys=[closed_by])

    def __repr__(self):
        return f"<CashDrawerDay {self.drawer_date} float={self.opening_float}>"


class CashierShift(db.Model):
    """A cashier's till session (وردية). A cashier opens a shift with a change
    float, collects money against it, then closes it against the counted cash.
    Every ``Payment`` taken while the shift is open is tagged to it, so each
    session reconciles on its own (X/Z report) instead of one big daily bucket.
    """
    __tablename__ = "cashier_shifts"

    id = db.Column(db.Integer, primary_key=True)
    # Serial audit number (SHIFT-2026-000001) — the shift's identity on
    # reviews and the end-of-day report.
    shift_number = db.Column(db.String(40), unique=True, index=True)
    label = db.Column(db.String(60))                 # optional name (صباحي/مسائي)
    status = db.Column(db.String(10), default="open", nullable=False)  # open|closed
    opening_float = db.Column(db.Float, default=0, nullable=False)
    opened_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    # Close-of-shift reconciliation.
    # The till this shift is a session on. One shift = one person + one
    # drawer + a window of time; two cash drawers open at once are two shifts,
    # because two people are each short on their own.
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=True, index=True)
    counted_cash = db.Column(db.Float)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    closed_at = db.Column(db.DateTime)
    notes = db.Column(db.String(255))

    account = db.relationship("CashAccount")
    opener = db.relationship("User", foreign_keys=[opened_by])
    closer = db.relationship("User", foreign_keys=[closed_by])
    payments = db.relationship("Payment", back_populates="shift")

    # --- lookups -------------------------------------------------------
    @classmethod
    def open_for(cls, user_id):
        """The user's currently-open shift, if any."""
        return (cls.query.filter_by(opened_by=user_id, status="open")
                .order_by(cls.opened_at.desc()).first())

    @classmethod
    def any_open(cls):
        return cls.query.filter_by(status="open").order_by(cls.opened_at.desc()).first()

    # --- money ---------------------------------------------------------
    @property
    def by_method(self):
        """Net collected per method (payments − refunds)."""
        out = {}
        for p in self.payments:
            out[p.method] = round(out.get(p.method, 0) + p.signed_amount, 2)
        return out

    @property
    def collected(self):
        """Net money in over the shift (payments − refunds)."""
        return round(sum(p.signed_amount for p in self.payments), 2)

    @property
    def refunds(self):
        return round(sum(p.amount or 0 for p in self.payments if p.kind == "refund"), 2)

    @property
    def cash_collected(self):
        return round(sum(p.signed_amount for p in self.payments if p.method == "cash"), 2)

    @property
    def cash_paid_out(self):
        """Cash that left this drawer during the shift.

        The cashier pays a supplier 175 out of the till. Until this existed
        the shift still expected those 175 to be there, so the count came up
        short and the variance landed on the cashier — for doing their job.

        Matched by ``shift_id`` rather than by a date window, because an
        expense carries a date and a shift carries a time: two shifts on the
        same day would each have been charged the other's payments.
        """
        return self.paid_out_for([self.id]).get(self.id, 0.0)

    @classmethod
    def paid_out_for(cls, shift_ids):
        """``{shift_id: cash out}`` for many shifts in two queries.

        The property above used to do its own two queries, which is fine for
        one shift and is sixty shifts × two on a month's summary. Batched here
        and called with a single id from the property, so there is one
        definition of "cash that left this drawer" rather than a fast copy
        beside a slow one — a rollup that disagreed with the shift report it
        totals would be worse than a slow rollup.
        """
        from app.models.doctor_payout import DoctorPayout
        from app.models.expense import Expense
        from app.models.payable import SupplierPayment

        ids = [i for i in (shift_ids or []) if i]
        if not ids:
            return {}
        out = {i: 0.0 for i in ids}
        # A doctor paid out of the drawer is cash that left the drawer. Leave
        # it out and the shift expects money that is not there, and the cashier
        # is short by exactly what the clinic told them to hand over.
        for model in (Expense, SupplierPayment, DoctorPayout):
            for shift_id, total in (
                    db.session.query(model.shift_id,
                                     db.func.sum(model.amount))
                    .filter(model.shift_id.in_(ids))
                    .group_by(model.shift_id).all()):
                out[shift_id] = round(out.get(shift_id, 0.0) + (total or 0), 2)
        return out

    @property
    def expected_cash(self):
        """What the drawer should hold: float + cash in − cash out."""
        return round((self.opening_float or 0) + self.cash_collected
                     - self.cash_paid_out, 2)

    @property
    def variance(self):
        """Counted − expected (over/short). None until the shift is closed."""
        if self.counted_cash is None:
            return None
        return round(self.counted_cash - self.expected_cash, 2)

    @property
    def duration_minutes(self):
        end = self.closed_at or datetime.utcnow()
        return int((end - self.opened_at).total_seconds() // 60)

    def __repr__(self):
        return f"<CashierShift {self.id} {self.status} float={self.opening_float}>"
