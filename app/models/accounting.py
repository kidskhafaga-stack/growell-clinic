"""Accounting engine (Phase 1 — F2): chart of accounts + journal entries.

A lightweight double-entry core: operational events (invoice, payment,
refund, expense) post balanced journal entries automatically — no manual
bookkeeping. Accounts are data (seeded, editable later), never code.
"""
from datetime import date, datetime

from app.extensions import db

ACCOUNT_TYPES = ["asset", "liability", "equity", "revenue", "expense"]


class Account(db.Model):
    """A node in the chart of accounts (شجرة الحسابات)."""

    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)         # Arabic
    name_en = db.Column(db.String(120))
    type = db.Column(db.String(12), nullable=False)          # ACCOUNT_TYPES
    parent_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    is_system = db.Column(db.Boolean, default=False, nullable=False)  # seeded core
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    parent = db.relationship("Account", remote_side=[id], backref="children")

    def display_name(self, lang="ar"):
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    @property
    def balance(self):
        """Net movement: debit-positive for assets/expenses, credit-positive
        for liabilities/equity/revenue (the natural balance side)."""
        total_d = sum(ln.debit or 0 for ln in self.lines)
        total_c = sum(ln.credit or 0 for ln in self.lines)
        if self.type in ("asset", "expense"):
            return round(total_d - total_c, 2)
        return round(total_c - total_d, 2)

    def __repr__(self):
        return f"<Account {self.code} {self.name}>"


class JournalEntry(db.Model):
    """A balanced accounting document generated from an operational event."""

    __tablename__ = "journal_entries"

    id = db.Column(db.Integer, primary_key=True)
    entry_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    memo = db.Column(db.String(255))
    # The operational document this entry came from (audit trail both ways).
    source_type = db.Column(db.String(20), index=True)   # invoice/payment/refund/expense/manual
    source_id = db.Column(db.Integer, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    lines = db.relationship("JournalLine", back_populates="entry",
                            cascade="all, delete-orphan")

    @property
    def total_debit(self):
        return round(sum(ln.debit or 0 for ln in self.lines), 2)

    @property
    def total_credit(self):
        return round(sum(ln.credit or 0 for ln in self.lines), 2)

    def __repr__(self):
        return f"<JournalEntry {self.entry_number}>"


class JournalLine(db.Model):
    __tablename__ = "journal_lines"

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"),
                         nullable=False, index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"),
                           nullable=False, index=True)
    debit = db.Column(db.Float, default=0, nullable=False)
    credit = db.Column(db.Float, default=0, nullable=False)
    description = db.Column(db.String(255))

    entry = db.relationship("JournalEntry", back_populates="lines")
    account = db.relationship("Account", backref="lines")

    def __repr__(self):
        return f"<JournalLine {self.account_id} D{self.debit} C{self.credit}>"


PERIOD_STATUSES = ["open", "closed"]


class AccountingPeriod(db.Model):
    """A closed accounting period (فترة محاسبية) — the month/quarter/year the
    books were reviewed and handed over.

    Once a period is closed, money can no longer be written into it: no
    back-dated invoice, payment, refund, expense or manual entry. That is the
    whole point — a report you printed for January must still say the same
    thing in March. An admin can reopen a period (a deliberate, logged act)
    when something genuinely has to be corrected.
    """

    __tablename__ = "accounting_periods"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)      # يناير 2026
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), default="open", nullable=False, index=True)
    notes = db.Column(db.String(200))
    closed_at = db.Column(db.DateTime)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    closer = db.relationship("User")

    @property
    def is_closed(self):
        return self.status == "closed"

    def covers(self, on_date):
        return bool(on_date and self.start_date <= on_date <= self.end_date)

    def __repr__(self):
        return f"<AccountingPeriod {self.name} {self.status}>"
