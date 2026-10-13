"""Emergency medication carts — see ``models/emergency_cart``."""
from datetime import datetime

from app.extensions import db
from app.models.emergency_cart import CartCheck, CartItem, CartUse

#: The hospital's hours to restock a used cart — empty until written.
HOURS_SETTING = "cart_replace_hours"


class CartError(ValueError):
    """A refusal with a locale key (``cart.err_<key>``)."""


def _text(raw, limit):
    return (raw or "").strip()[:limit] or None


def replace_hours():
    from app.models import Setting

    try:
        value = float((Setting.get(HOURS_SETTING) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def set_hours(raw):
    from app.models import Setting

    raw = (raw or "").strip()
    if raw:
        try:
            if float(raw) <= 0:
                raise ValueError
        except ValueError:
            raise CartError("hours") from None
    Setting.set(HOURS_SETTING, raw)


def items():
    return CartItem.query.filter_by(is_active=True).order_by(CartItem.drawer, CartItem.sort_order,
                                                             CartItem.id).all()


def add_item(form):
    drawer, name = _text(form.get("drawer"), 40), _text(form.get("name"), 160)
    if not drawer or not name:
        raise CartError("item")
    row = CartItem(drawer=drawer, name=name, quantity=_text(form.get("quantity"), 40),
                   sort_order=CartItem.query.count())
    db.session.add(row)
    db.session.flush()
    return row


def check(area, form, user):
    if not items():
        raise CartError("no_list")
    complete = form.get("complete") == "1"
    missing = _text(form.get("missing"), 255)
    if not complete and not missing:
        raise CartError("missing")
    row = CartCheck(area_id=area.id, seal=_text(form.get("seal"), 40), complete=complete,
                    missing=None if complete else missing, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def use(area, form, user):
    what = _text(form.get("what"), 255)
    if not what:
        raise CartError("what")
    row = CartUse(area_id=area.id, what=what, by_id=getattr(user, "id", None),
                  patient_id=_int(form.get("patient_id")))
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def restock(row, form, user):
    if row.replaced_at is not None:
        raise CartError("done")
    seal = _text(form.get("seal_after"), 40)
    if not seal:
        raise CartError("seal")
    row.replaced_at, row.replaced_by, row.seal_after = datetime.utcnow(), getattr(user, "id", None), seal
    db.session.flush()
    return row


def board():
    """Per cart: the last check, the open uses with their wait in hours and
    whether that is past the hospital's time."""
    from app.models.med_storage import StorageArea

    hours = replace_hours()
    now = datetime.utcnow()
    out = []
    for area in (StorageArea.query.filter_by(kind="cart", is_active=True)
                 .order_by(StorageArea.name).all()):
        last = CartCheck.query.filter_by(area_id=area.id).order_by(CartCheck.at.desc()).first()
        open_uses = []
        for u in (CartUse.query.filter_by(area_id=area.id, replaced_at=None)
                  .order_by(CartUse.used_at).all()):
            waited = (now - u.used_at).total_seconds() / 3600.0
            open_uses.append({"use": u, "hours": waited, "late": hours is not None and waited > hours})
        out.append({"area": area, "last": last, "open": open_uses})
    return out


def late_count():
    hours = replace_hours()
    if hours is None:
        return 0
    now = datetime.utcnow()
    return sum(1 for u in CartUse.query.filter_by(replaced_at=None).all()
               if (now - u.used_at).total_seconds() / 3600.0 > hours)


__all__ = ["CartError", "HOURS_SETTING", "add_item", "board", "check", "items", "late_count",
           "replace_hours", "restock", "set_hours", "use"]
