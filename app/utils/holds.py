"""Hold a family's account, a bill or a document while money is written
against it (the money review, ف-١).

Money is «how much is there?» and then «write it», and two cashiers who ask
in the same instant both hear the same answer. Measured on a real file
(``tests/test_money_two_at_once.py``) before this existed:

* two give-backs of 70 from a family's 100 both passed — the account at −40;
* one account of 100 paid two bills of 100 at once — 200 spent from 100;
* two cashiers collecting one bill of 100 at once — paid 200, owed −100;
* the same document posted to the journal twice at once — two entries.

So the order is turned round, the way ``appointments.hold_the_diary`` does it
for a doctor's slot and ``sequences.claim`` for a number: something is
written first, and the question is asked after.

* **On SQLite** any write takes the database's write lock until the commit,
  so the second cashier waits — milliseconds — and then reads what the first
  one wrote.
* **On PostgreSQL** the write holds that one row, so two cashiers on two
  different families do not wait for each other; a document that has no row
  of its own is held by an advisory lock on its name.

Call a hold **before** reading the figure it protects, and commit or roll
back soon after: it is kept until then. Holds taken in one request are always
taken family first, then bill, so two requests never wait on each other in
a circle.
"""
import zlib

from sqlalchemy import text

from app.extensions import db

# The tables a hold may name — written into the statement, so never taken
# from a caller as free text.
_TABLES = {"patients": "patients", "invoices": "invoices",
           "supplier_installments": "supplier_installments",
           "vaccine_settlements": "vaccine_settlements",
           "cash_accounts": "cash_accounts"}


def _row(table, row_id):
    if not row_id:
        return
    name = _TABLES[table]
    db.session.execute(text(f"UPDATE {name} SET id = id WHERE id = :row"),
                       {"row": row_id})


def family(patient_id):
    """Hold a family's account (its patient's row) until the commit."""
    _row("patients", patient_id)


def bill(invoice):
    """Hold a bill until the commit, and forget what this session had read of
    its payments, so the balance asked next is the one on file."""
    if invoice is None or invoice.id is None:
        return
    _row("invoices", invoice.id)
    db.session.expire(invoice, ["payments"])


def this(row):
    """Hold one row that carries its own state — an instalment, a settlement
    — and read it again from the file, so «is it still pending?» is asked of
    what is there now and not of what this request loaded a moment ago."""
    if row is None or row.id is None:
        return
    _row(row.__table__.name, row.id)
    db.session.refresh(row)


def document(kind, number, row_hint=None):
    """Hold one source document — ``(kind, number)`` — for the journal.

    PostgreSQL: an advisory lock on the pair, released with the transaction.
    SQLite: any write locks the database; ``row_hint`` is an account the entry
    is about to post to, held with a harmless write.
    """
    if db.engine.dialect.name == "postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"),
                           {"a": zlib.crc32(str(kind).encode()) & 0x7FFFFFFF,
                            "b": int(number or 0) & 0x7FFFFFFF})
    elif row_hint:
        db.session.execute(text("UPDATE accounts SET id = id WHERE id = :row"),
                           {"row": row_hint})
