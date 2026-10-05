"""Medicines kept well, and shown to be — GAHAR MMS.04 / GSR.19.

Four things, each with the evidence it answers:

1. **The lot and the expiry** (evidence 5, and the expired medicine of
   MMS.08). Written at receipt when the store has them; picked on the
   pharmacy's shelf when the pharmacist chooses to. :func:`lots` works out
   what is left of each lot from what was received and issued — an issue
   with no lot named is counted against the lot that expires first among
   those that were on the shelf and still good that day, which is how the
   standard expects a shelf to be used. Nothing about receiving or
   dispensing changed for a store that never writes a lot: it simply has
   no lots to show.
2. **The monthly inspection** (evidence 4) — per storage area, a checklist,
   what was found and what was done; an area with no inspection in the last
   month is listed.
3. **The temperature** (intent: *"temperature, light, humidity 24 hours a
   day, seven days a week"*) — read against the range the hospital wrote for
   that place. **The program has no range of its own**: a place with none is
   measured, never judged, and a reading out of the hospital's range needs
   what was done written beside it.
4. **A power outage** (evidence 3) — when, where, and the pharmacist's
   decision for each medicine affected before any of it is used.
"""
from datetime import date, datetime, time, timedelta

from app.extensions import db
from app.models.med_storage import (ANSWERS, AREA_KINDS, INSPECTION_ITEMS,
                                    OUTAGE_DECISIONS, OutageDecision,
                                    PowerOutage, StorageArea,
                                    StorageInspection, TempReading)

#: An expiry within this many days is "near" — the same figure the vaccine
#: batches already use, so one shelf is not judged by two rules.
from app.models.inventory import NEAR_EXPIRY_DAYS  # noqa: E402


class StorageError(ValueError):
    """A refusal with a key the screen can name (``med_store.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _number(value):
    raw = str(value if value is not None else "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise StorageError("bad_number") from None


def _day(value):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise StorageError("bad_date") from None


def _moment(value):
    if isinstance(value, datetime):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        local = datetime.fromisoformat(raw)
    except ValueError:
        raise StorageError("bad_date") from None
    from app.utils.clock import to_utc

    return to_utc(local)


def may_manage(user):
    """The pharmacy and whoever builds the lists set the places and decide
    on an outage."""
    return bool(user is not None and (user.is_admin or user.can_access("pharmacy")))


def may_record(user):
    """A reading or an inspection is written by whoever is standing there —
    the pharmacy, the store, or the ward's nurse at the fridge."""
    return bool(user is not None and (
        user.is_admin or any(user.can_access(m) for m in ("pharmacy", "inventory", "beds"))))


# ================================================================ the lots ===
def _transfer_ids(movements):
    from app.models import StoreDocument

    ids = {m.document_id for m in movements if m.document_id}
    if not ids:
        return set()
    return {d.id for d in StoreDocument.query.filter(
        StoreDocument.id.in_(ids), StoreDocument.kind == "transfer")}


def lots(item, today=None):
    """``[{"lot", "expiry", "received", "left", "state"}]`` for one store
    item, earliest expiry first; only lots with something left.

    ``state`` is ``expired`` · ``near`` · ``ok`` · ``no_date``. A move
    between two of the clinic's own warehouses is neither a receipt nor an
    issue here."""
    from app.utils.clock import local_date

    today = today or _today()
    movements = sorted(item.movements, key=lambda m: (m.created_at, m.id))
    moved = _transfer_ids(movements)
    table = {}
    for m in movements:
        if m.document_id in moved:
            continue
        lot = (m.lot_number or "").strip()
        if (m.qty or 0) > 0 and lot:
            row = table.setdefault(lot, {"lot": lot, "expiry": None, "received": m.created_at,
                                         "left": 0})
            row["left"] += m.qty
            row["expiry"] = m.expiry_date or row["expiry"]
        elif (m.qty or 0) < 0:
            want = -m.qty
            if lot and lot in table:
                table[lot]["left"] -= want
                continue
            on_day = local_date(m.created_at) or m.created_at.date()
            usable = sorted(
                (r for r in table.values()
                 if r["left"] > 0 and r["received"] <= m.created_at
                 and (r["expiry"] is None or r["expiry"] >= on_day)),
                key=lambda r: (r["expiry"] is None, r["expiry"] or date.max))
            for row in usable:
                if want <= 0:
                    break
                take = min(row["left"], want)
                row["left"] -= take
                want -= take
    out = []
    for row in table.values():
        if row["left"] <= 0:
            continue
        row["state"] = expiry_state(row["expiry"], today)
        out.append(row)
    out.sort(key=lambda r: (r["expiry"] is None, r["expiry"] or date.max, r["lot"]))
    return out


def expiry_state(expiry, today=None):
    today = today or _today()
    if expiry is None:
        return "no_date"
    if expiry < today:
        return "expired"
    if expiry <= today + timedelta(days=NEAR_EXPIRY_DAYS):
        return "near"
    return "ok"


def suggested_lot(item, today=None):
    """The lot to hand over first: the earliest expiry that is still good."""
    for row in lots(item, today):
        if row["state"] in ("near", "ok", "no_date"):
            return row
    return None


def check_pick(item, lot, today=None):
    """A lot picked on the shelf must be one the store holds, and good."""
    lot = (lot or "").strip()
    if not lot:
        return None
    for row in lots(item, today):
        if row["lot"] == lot:
            if row["state"] == "expired":
                raise StorageError("lot_expired")
            return lot
    raise StorageError("lot_unknown")


def expiry_list(today=None, within=None):
    """Every lot with something left that is expired or near — store items
    and vaccine batches together, expired first."""
    from app.models import StockMovement, StoreItem, VaccineInventory

    today = today or _today()
    rows = []
    lotted = {i for (i,) in db.session.query(StockMovement.item_id)
              .filter(StockMovement.lot_number.isnot(None),
                      StockMovement.lot_number != "", StockMovement.qty > 0)
              .distinct()}
    for item in StoreItem.query.filter(StoreItem.id.in_(lotted or [0])).all():
        for row in lots(item, today):
            if row["state"] in ("expired", "near"):
                rows.append({"kind": "store", "item": item, **row})
    for batch in VaccineInventory.query.all():
        if batch.qty_remaining <= 0:
            continue
        state = expiry_state(batch.expiry_date, today)
        if state in ("expired", "near"):
            rows.append({"kind": "vaccine", "item": batch.brand, "batch": batch,
                         "lot": batch.lot_number or "—", "expiry": batch.expiry_date,
                         "left": batch.qty_remaining, "state": state})
    rows.sort(key=lambda r: (r["state"] != "expired", r["expiry"] or date.max))
    return rows


# =============================================================== the places ==
def areas(active_only=True):
    query = StorageArea.query
    if active_only:
        query = query.filter_by(is_active=True)
    return query.order_by(StorageArea.kind, StorageArea.name).all()


def save_area(form, row=None):
    name = (form.get("name") or "").strip()[:120]
    if not name:
        raise StorageError("need_name")
    kind = form.get("kind") if form.get("kind") in AREA_KINDS else "other"
    t_min, t_max = _number(form.get("temp_min")), _number(form.get("temp_max"))
    if t_min is not None and t_max is not None and t_min >= t_max:
        raise StorageError("bad_range")
    per_day = (form.get("readings_per_day") or "").strip()
    row = row or StorageArea()
    row.name, row.kind = name, kind
    row.warehouse_id = int(form.get("warehouse_id")) if str(
        form.get("warehouse_id") or "").isdigit() else None
    row.temp_min, row.temp_max = t_min, t_max
    row.humidity_max = _number(form.get("humidity_max"))
    row.readings_per_day = int(per_day) if per_day.isdigit() and 0 < int(per_day) <= 24 else None
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


# ============================================================== inspections ==
def inspect(area, user, form, today=None):
    if area is None:
        raise StorageError("no_area")
    on = _day(form.get("inspected_on")) or (today or _today())
    if on > (today or _today()):
        raise StorageError("future")
    answers = {}
    for key in INSPECTION_ITEMS:
        value = form.get(f"q_{key}")
        if value not in ANSWERS:
            raise StorageError("answer_all")
        answers[key] = value
    findings = (form.get("findings") or "").strip()[:1000] or None
    action = (form.get("action") or "").strip()[:1000] or None
    if "no" in answers.values() and not action:
        raise StorageError("need_action")
    row = StorageInspection(area_id=area.id, inspected_on=on, answers=answers,
                            findings=findings, action=action,
                            inspector_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def last_inspection(area_id):
    return (StorageInspection.query.filter_by(area_id=area_id)
            .order_by(StorageInspection.inspected_on.desc(),
                      StorageInspection.id.desc()).first())


def inspection_due(area, today=None):
    """No inspection in the last month — *"at least monthly"*."""
    today = today or _today()
    last = last_inspection(area.id)
    if last is None:
        return True
    month_on = last.inspected_on
    try:
        month_on = month_on.replace(month=month_on.month % 12 + 1,
                                    year=month_on.year + (month_on.month // 12))
    except ValueError:                  # 31 January → no 31 February
        month_on = month_on + timedelta(days=31)
    return month_on < today


# ============================================================= temperature ==
def read_temp(area, user, temp, humidity=None, action=None, at=None):
    if area is None:
        raise StorageError("no_area")
    value = _number(temp)
    if value is None:
        raise StorageError("need_temp")
    if not -40 <= value <= 60:
        raise StorageError("bad_temp")
    hum = _number(humidity)
    if hum is not None and not 0 <= hum <= 100:
        raise StorageError("bad_humidity")
    out = ((area.temp_min is not None and value < area.temp_min)
           or (area.temp_max is not None and value > area.temp_max)
           or (hum is not None and area.humidity_max is not None
               and hum > area.humidity_max))
    action = (action or "").strip()[:500] or None
    if out and not action:
        raise StorageError("need_temp_action")
    row = TempReading(area_id=area.id, taken_at=at or datetime.utcnow(),
                      temp_c=value, humidity=hum, temp_min=area.temp_min,
                      temp_max=area.temp_max, out_of_range=bool(out),
                      action=action, taken_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def readings(area_id, start, end):
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    return (TempReading.query.filter(TempReading.area_id == area_id,
                                     TempReading.taken_at >= since,
                                     TempReading.taken_at <= until)
            .order_by(TempReading.taken_at.desc()).all())


def today_state(area, today=None):
    """``{"count", "wanted", "short", "out", "last"}`` for today."""
    today = today or _today()
    rows = readings(area.id, today, today)
    wanted = area.readings_per_day
    return {"count": len(rows), "wanted": wanted,
            "short": bool(wanted and len(rows) < wanted),
            "out": [r for r in rows if r.out_of_range],
            "last": rows[0] if rows else None}


# ================================================================= outages ==
def open_outage(user, form):
    start = _moment(form.get("started_at"))
    if start is None:
        raise StorageError("need_start")
    end = _moment(form.get("ended_at"))
    if end is not None and end < start:
        raise StorageError("end_before")
    chosen = [int(x) for x in (form.getlist("area_ids") if hasattr(form, "getlist")
                               else form.get("area_ids") or []) if str(x).isdigit()]
    known = {a.id for a in areas(active_only=False)}
    chosen = [a for a in chosen if a in known]
    if not chosen:
        raise StorageError("need_areas")
    row = PowerOutage(started_at=start, ended_at=end,
                      area_ids=",".join(str(a) for a in chosen),
                      highest_temp=_number(form.get("highest_temp")),
                      note=(form.get("note") or "").strip()[:500] or None,
                      recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def end_outage(outage, form):
    if outage is None or outage.closed_at is not None:
        raise StorageError("closed")
    end = _moment(form.get("ended_at")) or datetime.utcnow()
    if end < outage.started_at:
        raise StorageError("end_before")
    outage.ended_at = end
    high = _number(form.get("highest_temp"))
    if high is not None:
        outage.highest_temp = high
    return outage


def decide(outage, user, form):
    if outage is None or outage.closed_at is not None:
        raise StorageError("closed")
    decision = form.get("decision")
    if decision not in OUTAGE_DECISIONS:
        raise StorageError("need_decision")
    item_id = form.get("store_item_id")
    item_id = int(item_id) if str(item_id or "").isdigit() else None
    medicine = (form.get("medicine") or "").strip()[:200] or None
    if item_id is None and medicine is None:
        raise StorageError("need_medicine")
    reason = (form.get("reason") or "").strip()[:400]
    if not reason:
        raise StorageError("need_reason")
    row = OutageDecision(outage_id=outage.id, store_item_id=item_id,
                         medicine=medicine,
                         lot_number=(form.get("lot_number") or "").strip()[:60] or None,
                         decision=decision, reason=reason,
                         decided_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def close_outage(outage, user):
    """Closed once the power is back and the pharmacist decided for at
    least one medicine — an outage closed with nothing decided is the very
    gap evidence 3 is about."""
    if outage is None or outage.closed_at is not None:
        raise StorageError("closed")
    if outage.ended_at is None:
        raise StorageError("still_out")
    if not outage.decisions:
        raise StorageError("nothing_decided")
    outage.closed_at = datetime.utcnow()
    outage.closed_by = getattr(user, "id", None)
    return outage


def open_outages():
    return (PowerOutage.query.filter(PowerOutage.closed_at.is_(None))
            .order_by(PowerOutage.started_at.desc()).all())


# ================================================================== summary ==
def board(today=None):
    """The storage screen: each place with its inspection and today's
    temperatures, the open outages, and how many lots are expired or near."""
    today = today or _today()
    places = []
    for area in areas():
        places.append({"area": area, "last": last_inspection(area.id),
                       "due": inspection_due(area, today),
                       "temps": today_state(area, today)})
    expiring = expiry_list(today)
    return {"places": places, "outages": open_outages(),
            "expired": sum(1 for r in expiring if r["state"] == "expired"),
            "near": sum(1 for r in expiring if r["state"] == "near")}


def attention(today=None):
    """How many things on the storage screen want a look — for a badge."""
    data = board(today)
    return (sum(1 for p in data["places"]
                if p["due"] or p["temps"]["short"] or p["temps"]["out"])
            + len(data["outages"]) + data["expired"])
