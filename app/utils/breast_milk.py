"""Expressed breast milk — see ``models/breast_milk``."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.breast_milk import STORAGES, MilkBag

#: The hospital's keeping times, in hours, per storage — empty until set.
HOURS_SETTINGS = {s: f"ebm_{s}_hours" for s in STORAGES}


class MilkError(ValueError):
    """A refusal with a locale key (``milk.err_<key>``)."""


def hours_for(storage):
    from app.models import Setting

    raw = (Setting.get(HOURS_SETTINGS.get(storage, "")) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def set_hours(form):
    from app.models import Setting

    for s, key in HOURS_SETTINGS.items():
        raw = (form.get(s) or "").strip()
        if raw:
            try:
                if float(raw) <= 0:
                    raise ValueError
            except ValueError:
                raise MilkError("hours") from None
        Setting.set(key, raw)


def _when(raw):
    """A local ``datetime-local`` value to UTC."""
    from app.utils.clock import to_utc

    try:
        return to_utc(datetime.fromisoformat(str(raw or "").strip()))
    except ValueError:
        return None


def receive(stay, form, user):
    storage = form.get("storage")
    if storage not in ("fridge", "freezer"):
        raise MilkError("storage")
    expressed = _when(form.get("expressed_at"))
    if expressed is None:
        raise MilkError("expressed_at")
    if expressed > datetime.utcnow() + timedelta(minutes=5):
        raise MilkError("future")
    hours = hours_for(storage)
    expires = expressed + timedelta(hours=hours) if hours else _when(form.get("expires_at"))
    if expires is None:
        raise MilkError("expires_at")
    try:
        volume = float(form.get("volume_ml")) if form.get("volume_ml") else None
    except ValueError:
        volume = None
    row = MilkBag(patient_id=stay.patient_id, admission_id=stay.id, expressed_at=expressed,
                  storage=storage, expires_at=expires, volume_ml=volume,
                  note=(form.get("note") or "").strip()[:255] or None,
                  received_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def find(code):
    raw = (code or "").strip().upper()
    if raw.startswith("EBM"):
        raw = raw[3:]
    return db.session.get(MilkBag, int(raw)) if raw.isdigit() else None


def give(stay, form, user):
    """Give a bag on this baby's stay — refused if it is another baby's,
    expired, or no longer stored."""
    bag = find(form.get("code"))
    if bag is None:
        raise MilkError("not_found")
    if bag.patient_id != stay.patient_id:
        raise MilkError("other_baby")
    if bag.status != "stored":
        raise MilkError("not_stored")
    if bag.expires_at <= datetime.utcnow():
        raise MilkError("expired")
    bag.status = "given"
    bag.given_at = datetime.utcnow()
    bag.given_by = getattr(user, "id", None)
    bag.second_check = (form.get("second_check") or "").strip()[:120] or None
    db.session.flush()
    return bag


def thaw(bag, user):
    """Out of the freezer: the thawed keeping time runs from now."""
    if bag.status != "stored" or bag.storage != "freezer":
        raise MilkError("not_frozen")
    hours = hours_for("thawed")
    if not hours:
        raise MilkError("thawed_hours")
    bag.storage = "thawed"
    bag.expires_at = min(bag.expires_at, datetime.utcnow() + timedelta(hours=hours))
    db.session.flush()
    return bag


def discard(bag, reason):
    if bag.status != "stored":
        raise MilkError("not_stored")
    reason = (reason or "").strip()[:160]
    if not reason:
        raise MilkError("reason")
    bag.status = "discarded"
    bag.discarded_at = datetime.utcnow()
    bag.discard_reason = reason
    db.session.flush()
    return bag


def stored_for(patient_id):
    return (MilkBag.query.filter_by(patient_id=patient_id, status="stored")
            .order_by(MilkBag.expires_at).all())


def board():
    """Every stored bag, soonest to expire first."""
    return MilkBag.query.filter_by(status="stored").order_by(MilkBag.expires_at).all()


__all__ = ["HOURS_SETTINGS", "MilkError", "board", "discard", "find", "give", "hours_for",
           "receive", "set_hours", "stored_for", "thaw"]
