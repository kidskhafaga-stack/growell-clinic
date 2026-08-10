"""Imported money, shown as its own line and never mixed into the books.

The history import carries a decade of another program's takings — 1.6 million
pounds over ten years in the file this was built for. Two things could be done
with that, and only one of them is safe:

*Replay it as invoices and journal entries.* Then the income statement and the
accountant's opening balances both contain the same decade, and every total the
clinic reads is wrong by ten years of revenue. This is what the plan file
refused, and it is still refused.

*Keep it, and show it beside the books rather than inside them.* The amounts
live on ``ImportedService`` where the import put them. Nothing here writes a
journal entry, and nothing here changes a number the accounting engine
produced: a screen asks for the imported total and prints it on its own line,
marked as imported.

**And it is only shown for the batches the clinic ticked.** The question is
asked on the preview, before anything is written, and the answer is stored per
batch — because a decade of old takings and last month's rows, imported because
the clinic switched over mid-year, are not the same answer and one global
setting could not say both.
"""
from app.extensions import db
from app.models import ImportBatch, ImportedService


def _counted_batch_ids():
    """Batches whose money the clinic said may appear on its money screens."""
    rows = (db.session.query(ImportBatch.id)
            .filter(ImportBatch.count_money.is_(True)).all())
    return [r[0] for r in rows]


def totals(date_from=None, date_to=None, doctor_id=None):
    """Imported money in a period: what was charged, collected, and the
    doctor's share — plus how many batches it came from.

    Returns zeros (and ``batches=0``) when no batch is flagged, which is the
    default and the common case. A screen can print the line or omit it on
    that number alone.
    """
    empty = {"price": 0.0, "collected": 0.0, "doctor_share": 0.0,
             "rows": 0, "batches": 0}
    ids = _counted_batch_ids()
    if not ids:
        return empty

    query = (db.session.query(
        db.func.sum(ImportedService.price),
        db.func.sum(ImportedService.paid_cash + ImportedService.paid_company),
        db.func.sum(ImportedService.doctor_share),
        db.func.count(ImportedService.id))
        .filter(ImportedService.batch_id.in_(ids)))
    if date_from:
        query = query.filter(ImportedService.service_date >= date_from)
    if date_to:
        query = query.filter(ImportedService.service_date <= date_to)
    if doctor_id:
        query = query.filter(ImportedService.doctor_id == doctor_id)

    price, collected, share, rows = query.one()
    if not rows:
        return dict(empty, batches=len(ids))
    return {
        "price": round(price or 0, 2),
        "collected": round(collected or 0, 2),
        "doctor_share": round(share or 0, 2),
        "rows": rows,
        "batches": len(ids),
    }


def is_counted(batch):
    """Whether one batch's money is allowed on the money screens."""
    return bool(batch is not None and batch.count_money)
