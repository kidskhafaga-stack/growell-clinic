"""What the ledger is missing — found, named, and posted again.

The till posts to the journal **after** the bill is saved, and a posting
that fails is rolled back so the family is never refused over bookkeeping.
Right for the family; wrong for the books if nobody ever hears of it: the
revenue report reads invoices, the profit-and-loss reads the journal, and
the two drift apart by exactly what went missing.

So this reads the gap directly, whatever caused it — a failure written to
the audit log, one from before that log existed, a path that never posted:
every invoice, payment and expense that should have an entry and has none.
The journal screen lists them and posts them again. Posting is safe to
repeat (an existing entry is refreshed or left alone, never duplicated), so
pressing it twice is harmless.

**Only from the day the ledger started.** A clinic that ran for a year
before its chart of accounts existed has a year of documents that were
never meant to be in the journal, and listing them would bury the one that
went missing yesterday. The start is the first automatic entry on record;
with no entries at all, the ledger is not in use and nothing is missing.
"""
from sqlalchemy import and_

from app.extensions import db

#: What the till posts automatically, and the source type it posts it under.
KINDS = ("invoice", "payment", "expense")


def started():
    """When the ledger began posting by itself, or ``None``."""
    from app.models import JournalEntry

    return (db.session.query(db.func.min(JournalEntry.created_at))
            .filter(JournalEntry.source_type.in_(KINDS)).scalar())


def _without_entry(model, kind, since_column, since):
    from app.models import JournalEntry

    return (model.query
            .outerjoin(JournalEntry,
                       and_(JournalEntry.source_type == kind,
                            JournalEntry.source_id == model.id))
            .filter(JournalEntry.id.is_(None), since_column >= since))


def missing(since=None):
    """``{"invoice": [...], "payment": [...], "expense": [...]}`` — every
    document that should be in the journal and is not."""
    from app.models import Expense, Invoice, Payment

    since = since or started()
    out = {k: [] for k in KINDS}
    if since is None:
        return out
    # An invoice that comes to nothing, and a payment or expense of nothing,
    # are posted as nothing — they are not gaps.
    out["invoice"] = [i for i in _without_entry(
        Invoice, "invoice", Invoice.created_at, since).order_by(Invoice.id)
        if (i.total or 0) > 0]
    out["payment"] = (_without_entry(Payment, "payment", Payment.paid_at, since)
                      .filter(Payment.amount > 0).order_by(Payment.id).all())
    out["expense"] = (_without_entry(Expense, "expense", Expense.created_at, since)
                      .filter(Expense.amount > 0)
                      .order_by(Expense.id).all())
    return out


def count(since=None):
    return sum(len(v) for v in missing(since).values())


def repair(user_id=None):
    """Post everything missing. Returns ``(posted, still_missing)``.

    Each document goes through the same poster the till uses, one at a time,
    so one that still fails does not stop the rest — it stays on the list.
    """
    from app.utils.billing import post_to_ledger

    before = missing()
    for kind in KINDS:
        for obj in before[kind]:
            # The till's own poster: it never raises, it writes a failure to
            # the audit log, and an invoice brings its payments with it —
            # which is safe, because a payment already posted is skipped.
            post_to_ledger(kind, obj, user_id=user_id)
    total = sum(len(v) for v in before.values())
    left = count()
    return total - left, left
