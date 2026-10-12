"""The controlled-drug register — see ``models/controlled``.

Every line carries the book's balance after it, worked from the line before
on the same page (drug × place), so the balance is never typed and never
edited: a wrong line is answered by another line, the way the paper book is
corrected.
"""
from datetime import datetime

from app.extensions import db
from app.models.controlled import WITNESSED, ControlledEntry, ControlledItem


class ControlledError(ValueError):
    """A refusal with a locale key (``ctrl.err_<key>``)."""


def _qty(raw):
    try:
        value = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _text(raw, limit):
    return (raw or "").strip()[:limit] or None


def save_item(form, row=None):
    name, unit = _text(form.get("name"), 160), _text(form.get("unit"), 30)
    if not name or not unit:
        raise ControlledError("item")
    row = row or ControlledItem()
    row.name, row.unit = name, unit
    row.drug_id = _int(form.get("drug_id"))
    db.session.add(row)
    db.session.flush()
    return row


def balance(item_id, area_id):
    last = (ControlledEntry.query.filter_by(item_id=item_id, area_id=area_id)
            .order_by(ControlledEntry.id.desc()).first())
    return last.balance if last else 0.0


def _witness(kind, user, witness_id):
    if kind not in WITNESSED:
        return None
    me = getattr(user, "id", None)
    if not witness_id or witness_id == me:
        raise ControlledError("witness")
    return witness_id


def record(item, area, form, user):
    """One line in the book. ``form`` keys: kind, qty, admission_id, source,
    other_area_id, counted, note, witness_id."""
    from app.models.admission import Admission
    from app.models.med_storage import StorageArea

    kind = form.get("kind")
    if kind not in ("received", "given", "wasted", "transfer", "count"):
        raise ControlledError("kind")
    witness = _witness(kind, user, _int(form.get("witness_id")))
    now = datetime.utcnow()
    book = balance(item.id, area.id)
    note = _text(form.get("note"), 255)
    by = getattr(user, "id", None)
    row = ControlledEntry(item_id=item.id, area_id=area.id, kind=kind, by_id=by,
                          witness_id=witness, note=note, at=now)

    if kind == "count":
        counted = _qty(form.get("counted"))
        if counted is None:
            raise ControlledError("qty")
        diff = round(counted - book, 4)
        if diff and not note:
            raise ControlledError("discrepancy")
        row.counted, row.qty, row.balance = counted, diff, counted
        db.session.add(row)
        db.session.flush()
        return row

    qty = _qty(form.get("qty"))
    if not qty:
        raise ControlledError("qty")
    if kind == "received":
        source = _text(form.get("source"), 160)
        if not source:
            raise ControlledError("source")
        row.source, row.qty, row.balance = source, qty, book + qty
    else:
        if qty > book + 1e-9:
            raise ControlledError("more_than_book")
        row.qty, row.balance = qty, book - qty
        if kind == "given":
            stay = db.session.get(Admission, _int(form.get("admission_id")) or 0)
            if stay is None:
                raise ControlledError("patient")
            row.admission_id, row.patient_id = stay.id, stay.patient_id
        elif kind == "wasted":
            if not note:
                raise ControlledError("reason")
        elif kind == "transfer":
            other = db.session.get(StorageArea, _int(form.get("other_area_id")) or 0)
            if other is None or other.id == area.id:
                raise ControlledError("other_area")
            row.kind, row.other_area_id = "transfer_out", other.id
            db.session.add(row)
            db.session.add(ControlledEntry(
                item_id=item.id, area_id=other.id, kind="transfer_in", qty=qty,
                balance=balance(item.id, other.id) + qty, other_area_id=area.id,
                note=note, at=now, by_id=by))
            db.session.flush()
            return row
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def pages():
    """Every (drug, place) with a line: the balance, the last count and
    whether it found a difference."""
    out = {}
    for e in ControlledEntry.query.order_by(ControlledEntry.id).all():
        p = out.setdefault((e.item_id, e.area_id), {"item": e.item, "area": e.area,
                                                    "balance": 0.0, "last_count": None})
        p["balance"] = e.balance
        if e.kind == "count":
            p["last_count"] = e
    return sorted(out.values(), key=lambda p: (p["item"].name, p["area"].name))


def page(item_id, area_id):
    return (ControlledEntry.query.filter_by(item_id=item_id, area_id=area_id)
            .order_by(ControlledEntry.id.desc()).all())


__all__ = ["ControlledError", "balance", "page", "pages", "record", "save_item"]
