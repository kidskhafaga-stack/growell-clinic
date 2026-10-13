"""The blood store — see ``models/blood_bank``."""
from datetime import date, datetime

from app.extensions import db
from app.models.blood import CANCELLED, PRODUCTS, READY, REQUESTED, TRANSFUSED, BloodRequest, Transfusion
from app.models.blood_bank import ABO, CROSSMATCHED, RH, BloodSupplier, BloodUnit


class BloodBankError(ValueError):
    """A refusal with a locale key (``bbank.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _yes(form, key):
    v = form.get(key)
    return True if v == "yes" else False if v == "no" else None


# ============================================================== DAS.29 ==
def save_supplier(form):
    name = _text(form.get("name"), 160)
    if not name:
        raise BloodBankError("name")
    acceptance = _text(form.get("acceptance"))
    if not acceptance:
        raise BloodBankError("acceptance")
    row = BloodSupplier(name=name, accreditation=_text(form.get("accreditation"), 160),
                        agreement_until=_day(form.get("agreement_until")), agreement=_text(form.get("agreement")),
                        acceptance=acceptance)
    db.session.add(row)
    db.session.flush()
    return row


def evaluate_supplier(row, form):
    note = _text(form.get("evaluation_note"), 255)
    if not note:
        raise BloodBankError("evaluation_note")
    row.evaluated_on, row.evaluation_note = _day(form.get("evaluated_on")) or date.today(), note
    db.session.flush()
    return row


def suppliers():
    return BloodSupplier.query.filter_by(is_active=True).order_by(BloodSupplier.name).all()


# ============================================================== DAS.28 ==
def receive(form, user, today=None):
    """Received only with the label's nine elements and the inspection on
    arrival. A unit that fails the inspection is recorded as rejected, with
    the reason — the record of what came is kept either way."""
    today = today or date.today()
    number = _text(form.get("unit_number"), 64)
    if not number:
        raise BloodBankError("unit_number")
    if BloodUnit.query.filter_by(unit_number=number).first() is not None:
        raise BloodBankError("duplicate")
    supplier = db.session.get(BloodSupplier, form.get("supplier_id", type=int) or 0)
    if supplier is None:
        raise BloodBankError("supplier")
    product = form.get("product") if form.get("product") in PRODUCTS else None
    abo = form.get("abo") if form.get("abo") in ABO else None
    rh = form.get("rh") if form.get("rh") in RH else None
    storage = _text(form.get("storage"), 120)
    collected, expires = _day(form.get("collected_on")), _day(form.get("expires_on"))
    serone = _yes(form, "seronegative")
    for value, key in ((product, "product"), (abo, "abo"), (rh, "rh"), (storage, "storage"),
                       (collected, "collected_on"), (expires, "expires_on"), (serone, "seronegative")):
        if value is None:
            raise BloodBankError(key)
    transport, label = _yes(form, "transport_ok"), _yes(form, "label_ok")
    if transport is None or label is None:
        raise BloodBankError("inspection")
    confirmed = _yes(form, "abo_confirmed")
    if product in CROSSMATCHED and confirmed is None:
        raise BloodBankError("abo_confirmed")
    try:
        volume = int(form.get("volume_ml")) if form.get("volume_ml") else None
    except ValueError:
        volume = None
    row = BloodUnit(unit_number=number, supplier_id=supplier.id, product=product, volume_ml=volume, abo=abo,
                    rh=rh, seronegative=serone, anticoagulant=_text(form.get("anticoagulant"), 60),
                    storage=storage, collected_on=collected, expires_on=expires,
                    received_by=getattr(user, "id", None), transport_ok=transport, label_ok=label,
                    abo_confirmed=confirmed)
    failed = (not transport or not label or confirmed is False or not serone or expires < today)
    if failed:
        reason = _text(form.get("reject_reason"), 200)
        if not reason:
            raise BloodBankError("reject_reason")
        row.status, row.reject_reason = "rejected", reason
    db.session.add(row)
    db.session.flush()
    return row


def open_requests():
    return (BloodRequest.query.filter(BloodRequest.state.in_((REQUESTED, READY)))
            .order_by(BloodRequest.urgency.desc(), BloodRequest.requested_at).all())


# ============================================================== DAS.30 ==
def issue(unit, form, user, today=None):
    today = today or date.today()
    if unit.status != "stored":
        raise BloodBankError("not_stored")
    if unit.expires_on < today:
        raise BloodBankError("expired")
    req = db.session.get(BloodRequest, form.get("request_id", type=int) or 0)
    if req is None or req.state in (CANCELLED, TRANSFUSED):
        raise BloodBankError("request")
    visual = _yes(form, "visual_ok")
    if visual is None:
        raise BloodBankError("visual")
    if visual is False:
        raise BloodBankError("visual_failed")
    if unit.product in CROSSMATCHED:
        match = _yes(form, "compatible")
        if match is None:
            raise BloodBankError("crossmatch")
        if match is False:
            raise BloodBankError("incompatible")
        unit.crossmatch_compatible, unit.crossmatch_by = True, getattr(user, "id", None)
        unit.segment_number = _text(form.get("segment_number"), 40)
        if not unit.segment_number:
            raise BloodBankError("segment")
    unit.visual_ok, unit.request_id = True, req.id
    unit.issued_at, unit.issued_by, unit.status = datetime.utcnow(), getattr(user, "id", None), "issued"
    if req.state == REQUESTED:
        req.state = READY
    db.session.flush()
    return unit


def give_back(unit, form):
    """(f) returned to the store: reissued only when whoever took it back
    says it can be, and why."""
    if unit.status != "issued":
        raise BloodBankError("not_issued")
    note = _text(form.get("returned_note"), 200)
    if not note:
        raise BloodBankError("returned_note")
    reissue = _yes(form, "reissuable")
    if reissue is None:
        raise BloodBankError("reissuable")
    unit.returned_at, unit.returned_note = datetime.utcnow(), note
    if reissue:
        unit.status, unit.request_id, unit.issued_at = "stored", None, None
        unit.crossmatch_compatible = unit.crossmatch_by = unit.visual_ok = None
    else:
        unit.status, unit.discarded_at, unit.discard_reason = "discarded", datetime.utcnow(), note
    db.session.flush()
    return unit


def discard(unit, form):
    if unit.status != "stored":
        raise BloodBankError("not_stored")
    reason = _text(form.get("discard_reason"), 200)
    if not reason:
        raise BloodBankError("discard_reason")
    unit.status, unit.discarded_at, unit.discard_reason = "discarded", datetime.utcnow(), reason
    db.session.flush()
    return unit


def mark_transfused(unit_code, request_id):
    """Called when a bag goes up: the issued unit with that number is now
    in the child. Silent when the number is not a unit in the store."""
    code = (unit_code or "").strip()
    if not code:
        return None
    unit = BloodUnit.query.filter_by(unit_number=code, status="issued").first()
    if unit is None or (unit.request_id and request_id and unit.request_id != request_id):
        return None
    unit.status = "transfused"
    return unit


def trace(unit):
    """DAS.28 ev. 3 — from entry to the transfusion that used it."""
    bags = Transfusion.query.filter_by(unit_code=unit.unit_number).all()
    return {"unit": unit, "request": unit.request, "transfusions": bags}


def board(today=None):
    today = today or date.today()
    stored = (BloodUnit.query.filter_by(status="stored")
              .order_by(BloodUnit.expires_on, BloodUnit.id).all())
    return {"stored": stored, "expired": [u for u in stored if u.expires_on < today],
            "issued": BloodUnit.query.filter_by(status="issued").order_by(BloodUnit.issued_at).all(),
            "recent": (BloodUnit.query.filter(BloodUnit.status.in_(("transfused", "discarded", "rejected")))
                       .order_by(BloodUnit.id.desc()).limit(30).all()),
            "by_group": _by_group(stored, today), "today": today}


def _by_group(stored, today):
    out = {}
    for u in stored:
        if u.expires_on >= today:
            key = (u.product, u.abo + ("+" if u.rh == "pos" else "-"))
            out[key] = out.get(key, 0) + 1
    return sorted(out.items())


__all__ = ["BloodBankError", "board", "discard", "evaluate_supplier", "give_back", "issue", "mark_transfused",
           "open_requests", "receive", "save_supplier", "suppliers", "trace"]
