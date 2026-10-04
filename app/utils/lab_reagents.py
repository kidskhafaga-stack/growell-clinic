"""Reagent lots: received, inspected, opened, finished — GAHAR DAS.12.

The intent's five items, and where each is:

* **(أ) inspection, acceptance and rejection** — a lot is received with the
  decision and, when rejected, why; a lot already expired on arrival can
  only be rejected;
* **(ب) identification and listing** — each lot by its item (or name), lot
  number and expiry; the list is the laboratory's inventory of lots;
* **(ج) never using expired material** — an expired lot is refused when
  somebody tries to open it, and every expired lot still on the shelf or in
  use is listed until somebody finishes it;
* **(د) safety limits for reordering** — the store already holds each
  item's reorder level; the items of the lab's store at or under it are
  shown here, read from the store, not kept twice;
* **(هـ) requesting, issuing and dispatching** — the store's own documents.

Near expiry is thirty days unless the laboratory says otherwise
(``lab_expiry_warn_days``) — a warning window, not a clinical figure.
"""
from datetime import date, datetime, timedelta

from app.extensions import db

DECISIONS = ("accepted", "rejected")
WARN_SETTING = "lab_expiry_warn_days"


class LotError(ValueError):
    """A refusal with a key the screen can name (``lab_reagents.err_<key>``)."""


def warn_days():
    from app.models import Setting

    try:
        days = int(Setting.get(WARN_SETTING) or 30)
    except (TypeError, ValueError):
        days = 30
    return days if days > 0 else 30


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def receive(form, user=None, at=None):
    """A lot arrived and was inspected. The caller commits."""
    from app.models import ReagentLot, StoreItem

    item = None
    item_id = form.get("item_id")
    if item_id and str(item_id).isdigit():
        item = db.session.get(StoreItem, int(item_id))
    name = (form.get("name") or "").strip()[:160] or None
    if item is None and not name:
        raise LotError("need_item")
    lot_number = (form.get("lot_number") or "").strip()[:60]
    if not lot_number:
        raise LotError("need_lot")
    expiry = _day(form.get("expiry_date"))
    if expiry is None:
        raise LotError("need_expiry")
    decision = form.get("decision") or "accepted"
    if decision not in DECISIONS:
        raise LotError("bad_decision")
    note = (form.get("inspection_note") or "").strip()[:200] or None
    if decision == "accepted" and expiry < _today():
        raise LotError("expired_on_arrival")
    if decision == "rejected" and not note:
        raise LotError("need_reason")
    try:
        quantity = int(form.get("quantity") or 0) or None
    except ValueError:
        quantity = None
    row = ReagentLot(item_id=item.id if item else None, name=None if item else name,
                     lot_number=lot_number, expiry_date=expiry, quantity=quantity,
                     decision=decision, inspection_note=note,
                     received_at=at or datetime.utcnow(),
                     received_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def state(lot, today=None):
    """``rejected``, ``finished``, ``expired``, ``near``, ``in_use`` or
    ``in_stock``."""
    today = today or _today()
    if lot.decision == "rejected":
        return "rejected"
    if lot.finished_at is not None:
        return "finished"
    if lot.expiry_date < today:
        return "expired"
    if lot.expiry_date <= today + timedelta(days=warn_days()):
        return "near"
    return "in_use" if lot.opened_at is not None else "in_stock"


def open_lot(lot, user=None, at=None):
    """Put a lot into use — never an expired or rejected one."""
    if lot is None or lot.decision != "accepted":
        raise LotError("not_accepted")
    if lot.finished_at is not None:
        raise LotError("finished")
    if lot.expiry_date < _today():
        raise LotError("expired")
    if lot.opened_at is None:
        lot.opened_at = at or datetime.utcnow()
        lot.opened_by = getattr(user, "id", None)
    db.session.flush()
    return lot


def finish(lot, user=None, at=None):
    """Used up, or taken off the shelf (an expired lot is finished too)."""
    if lot is None or lot.decision != "accepted":
        raise LotError("not_accepted")
    if lot.finished_at is None:
        lot.finished_at = at or datetime.utcnow()
        lot.finished_by = getattr(user, "id", None)
    db.session.flush()
    return lot


def shelf():
    """Every lot not finished — accepted ones still in stock or in use —
    expired first, then by expiry."""
    from sqlalchemy.orm import selectinload

    from app.models import ReagentLot

    return (ReagentLot.query.options(selectinload(ReagentLot.item))
            .filter(ReagentLot.decision == "accepted",
                    ReagentLot.finished_at.is_(None))
            .order_by(ReagentLot.expiry_date, ReagentLot.id).all())


def recent_rejected(limit=20):
    from app.models import ReagentLot

    return (ReagentLot.query.filter(ReagentLot.decision == "rejected")
            .order_by(ReagentLot.received_at.desc()).limit(limit).all())


def expired_on_shelf():
    """How many expired lots are still not finished — the bench's warning."""
    from app.models import ReagentLot

    return (db.session.query(db.func.count(ReagentLot.id))
            .filter(ReagentLot.decision == "accepted",
                    ReagentLot.finished_at.is_(None),
                    ReagentLot.expiry_date < _today()).scalar() or 0)


def low_items():
    """The lab store's items at or under their reorder level, with what the
    store holds — read from the store (DAS.12 د)."""
    from app.utils import lab_stock

    store = lab_stock.store()
    if store is None:
        return []
    from app.models import StoreItem

    out = []
    for item in StoreItem.query.filter(StoreItem.is_active.is_(True)).all():
        if not item.reorder_level:
            continue
        held = item.stock_in(store)
        if held <= item.reorder_level:
            out.append((item, held))
    return out
