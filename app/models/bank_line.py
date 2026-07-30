"""A line off the bank's statement, and what it was matched to.

A till's balance is the program's claim. The bank's statement is the world's.
Reconciling them is the only way anybody finds out that a transfer never
arrived, that a fee was taken twice, or that a collection was recorded and the
money went somewhere else — and it cannot be done from memory once a month has
more than a handful of lines in it.

**The statement is stored, not just read.** An importer that matched what it
could and threw the rest away would answer "did these balance?" and lose the
only interesting question, which is *which lines did not*. A stored line can
sit unmatched for a week while somebody chases it, and can be pointed at the
right movement later by a person who knows something the program does not.

**Nothing here posts a journal entry.** Matching a statement line to a payment
says "these two are the same event", which is a statement about records the
clinic already has. A line with no match is a question, and the answer is
sometimes "record an expense" and sometimes "the bank made a mistake" — the
program is not in a position to pick.
"""
from datetime import datetime

from app.extensions import db

# unmatched  nobody has said what this is yet — the list worth looking at
# matched    tied to a payment / expense / supplier payment / till movement
# ignored    seen and deliberately set aside, with a reason
BANK_LINE_STATUSES = ["unmatched", "matched", "ignored"]


class BankLine(db.Model):
    """One row of an imported statement for one till."""

    __tablename__ = "bank_statement_lines"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("cash_accounts.id"),
                           nullable=False, index=True)
    line_date = db.Column(db.Date, nullable=False, index=True)
    # Signed the way the till sees it: positive is money arriving. A statement
    # with separate debit and credit columns is folded into this on import,
    # because "which column was it in" is a property of the export format and
    # not of what happened.
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(255))
    reference = db.Column(db.String(80))
    # The running balance off the statement, when the export carries one. Kept
    # for the eye rather than for arithmetic — it is the one column that makes
    # a mis-parsed row obvious to a human reading the screen.
    balance = db.Column(db.Float)

    # Fingerprint of the row as it appeared in the file, so importing the same
    # statement twice does not double it. Not unique: two genuinely identical
    # transactions on one day are two transactions, and a unique index here
    # would silently swallow the second. See ``bank_import.import_lines``.
    digest = db.Column(db.String(64), index=True)

    status = db.Column(db.String(12), default="unmatched", nullable=False,
                       index=True)
    # What it was matched to, in the vocabulary ``treasury.movements`` speaks:
    # payment / refund / expense / supplier / mv_deposit / mv_transfer / …
    matched_kind = db.Column(db.String(20))
    matched_id = db.Column(db.Integer)
    note = db.Column(db.String(255))

    imported_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    imported_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    matched_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    account = db.relationship("CashAccount")
    importer = db.relationship("User", foreign_keys=[imported_by])
    matcher = db.relationship("User", foreign_keys=[matched_by])

    @property
    def received(self):
        """Whether this line brought money in."""
        return (self.amount or 0) > 0

    @property
    def link(self):
        """The movement this line is tied to, as ``(kind, id)`` or None."""
        if self.status != "matched" or not self.matched_kind:
            return None
        return (self.matched_kind, self.matched_id)

    @property
    def needs_attention(self):
        """Whether somebody still has to say what this line is."""
        return self.status == "unmatched"

    def __repr__(self):
        return (f"<BankLine {self.line_date} {self.amount:+.2f} "
                f"{self.status}>")
