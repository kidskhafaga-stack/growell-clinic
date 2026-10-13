"""Drug recalls — see ``models/drug_recall``."""
from datetime import datetime

from app.extensions import db
from app.models.drug_recall import DrugRecall

STEPS = ("separated", "patients", "disposed")


class RecallError(ValueError):
    """A refusal with a locale key (``recall.err_<key>``)."""


def _text(raw, limit):
    return (raw or "").strip()[:limit] or None


def recalled_lots(item_id):
    """The lots of this item under an open recall."""
    return {r.lot_number for r in DrugRecall.query.filter_by(item_id=item_id, closed_at=None)}


def open_recall(form, user):
    from app.models import StoreItem

    item = db.session.get(StoreItem, _int(form.get("item_id")) or 0)
    lot = _text(form.get("lot_number"), 60)
    source = _text(form.get("notice_from"), 120)
    if item is None or not lot:
        raise RecallError("item_lot")
    if not source:
        raise RecallError("source")
    if lot in recalled_lots(item.id):
        raise RecallError("already")
    row = DrugRecall(item_id=item.id, lot_number=lot, notice_from=source,
                     notice_ref=_text(form.get("notice_ref"), 80),
                     reason=_text(form.get("reason"), 255), opened_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def record_step(row, step, note, user):
    if not row.is_open:
        raise RecallError("closed")
    if step not in STEPS:
        raise RecallError("step")
    note = _text(note, 255)
    if not note:
        raise RecallError("note")
    now = datetime.utcnow()
    if step == "separated":
        row.separated_at, row.separated_note = now, note
    elif step == "patients":
        row.patients_at, row.patients_note = now, note
    else:
        row.disposed_at, row.disposed_note = now, note
    db.session.flush()
    return row


def close(row, user):
    """Closed only when the lot was separated, the patients were decided
    about, and it was disposed of or returned."""
    if not (row.separated_at and row.patients_at and row.disposed_at):
        raise RecallError("steps_missing")
    row.closed_at, row.closed_by = datetime.utcnow(), getattr(user, "id", None)
    db.session.flush()
    return row


def trace(row):
    """Who had this lot: ``{"dispensed", "doses", "unlotted", "left"}``.

    ``dispensed`` — boxes handed over at the counter; ``doses`` — doses given
    on the ward; ``unlotted`` — issues of the same item since the lot first
    came in that did not record a lot, so cannot be ruled in or out."""
    from app.models import MedicationDose, PrescriptionItem, StockMovement
    from app.utils import med_storage

    moves = (StockMovement.query.filter_by(item_id=row.item_id)
             .order_by(StockMovement.created_at).all())
    lot_moves = [m for m in moves if (m.lot_number or "").strip() == row.lot_number]
    first_in = min((m.created_at for m in lot_moves if (m.qty or 0) > 0), default=None)
    out_ids = [m.id for m in lot_moves if (m.qty or 0) < 0]
    dispensed = (PrescriptionItem.query.filter(PrescriptionItem.stock_movement_id.in_(out_ids)).all()
                 if out_ids else [])
    doses = (MedicationDose.query.filter(MedicationDose.stock_movement_id.in_(out_ids)).all()
             if out_ids else [])
    unlotted = sum(1 for m in moves if (m.qty or 0) < 0 and not (m.lot_number or "").strip()
                   and first_in is not None and m.created_at >= first_in)
    left = next((r["left"] for r in med_storage.lots(row.item) if r["lot"] == row.lot_number), 0)
    return {"dispensed": dispensed, "doses": doses, "unlotted": unlotted, "left": left}


def board():
    return DrugRecall.query.order_by(DrugRecall.closed_at.isnot(None),
                                     DrugRecall.opened_at.desc()).all()


def open_count():
    return DrugRecall.query.filter(DrugRecall.closed_at.is_(None)).count()


__all__ = ["RecallError", "STEPS", "board", "close", "open_count", "open_recall",
           "recalled_lots", "record_step", "trace"]
