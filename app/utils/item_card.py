"""The movement card for a vaccine: every dose in and every dose out.

*"كارت الصنف (بيان حركة الأصناف) — تقريباً احنا عاملينه بس محتاج افهمه أو
نطوّر فيه"*. What existed was a list of batches with their remaining
quantities: a photograph of now. A store card is the opposite — it is the
history that explains now, and it is what somebody reaches for when the shelf
and the screen disagree.

**Derived, not stored.** Every movement a vaccine can make is already written
down somewhere: a batch is a receipt, a ``PatientVaccine`` is a dose leaving,
a transfer opens a batch in one warehouse and consumes from another. Building
a ledger table and filling it from today would have given every existing
clinic an empty card and a note saying the history starts now, which is the
one thing a card is for.

The exception is the stocktake, which had nothing to derive from because
counting the fridge silently rewrote a number. That is why
:class:`~app.models.inventory.VaccineAdjustment` exists, and it is the only
part of this that is stored.
"""
from app.models import PatientVaccine, VaccineAdjustment, VaccineInventory


def ledger(brand, warehouse=None):
    """Every movement of one item, oldest first, with a running balance.

    ``warehouse`` narrows it to one place — the question "what happened in the
    fridge" is not the same as "what happened to this vaccine", and a clinic
    with two fridges needs to be able to ask the first one.
    """
    rows = []
    for batch in brand.batches:
        if not _in(batch, warehouse):
            continue
        rows.extend(_batch_rows(batch))
    rows.sort(key=lambda r: (r["date"], r["seq"]))

    balance = 0
    for row in rows:
        balance += row["qty"]
        row["balance"] = balance
    return rows


def _in(batch, warehouse):
    if warehouse is None:
        return True
    return (batch.warehouse_id == warehouse.id
            or (batch.warehouse_id is None and warehouse.is_default))


def _batch_rows(batch):
    """One batch's whole story: how it arrived, what left it, what was counted."""
    rows = [{
        "date": batch.received_date, "seq": 0, "kind": "in",
        "qty": batch.qty_received or 0, "batch": batch,
        # A transfer arriving is a receipt here and an issue somewhere else;
        # calling both "receipt" is how a card stops adding up across stores.
        "reason": batch.receipt_reason or "opening",
        "who": None, "ref": batch.document.doc_number if batch.document else None,
        "note": batch.notes,
    }]

    for dose in PatientVaccine.query.filter_by(inventory_id=batch.id).all():
        rows.append({
            "date": dose.given_date, "seq": 1, "kind": "out", "qty": -1,
            "batch": batch, "reason": "dose", "who": dose.patient,
            "ref": None, "note": None,
        })

    for adj in (VaccineAdjustment.query.filter_by(batch_id=batch.id)
                .order_by(VaccineAdjustment.id).all()):
        rows.append({
            "date": adj.created_at.date(), "seq": 2, "kind": "adjust",
            "qty": adj.diff, "batch": batch, "reason": "stocktake",
            "who": None, "at": adj.created_at, "counter": adj.counter,
            "ref": adj.document.doc_number if adj.document else None,
            "note": adj.reason,
        })

    # What left as a transfer is not written anywhere of its own: the source
    # batch's ``qty_used`` simply grew. Anything used that no dose and no
    # count accounts for is that, and saying so is better than a card whose
    # closing balance quietly disagrees with the shelf.
    accounted = sum(-r["qty"] for r in rows if r["kind"] == "out")
    accounted -= sum(r["qty"] for r in rows if r["kind"] == "adjust")
    unexplained = (batch.qty_used or 0) - accounted
    if unexplained > 0:
        rows.append({
            "date": batch.received_date, "seq": 3, "kind": "out",
            "qty": -unexplained, "batch": batch, "reason": "other",
            "who": None, "ref": None, "note": None,
        })
    return rows


def by_warehouse(brand):
    """``[(warehouse, doses)]`` for the places this item is actually held.

    Empty warehouses are left out: a list of everywhere the clinic could
    theoretically keep a vaccine is not information.
    """
    from app.models import Warehouse

    default = Warehouse.default()
    totals = {}
    for batch in brand.batches:
        if batch.qty_remaining <= 0:
            continue
        wh = batch.warehouse or default
        entry = totals.setdefault(wh.id, {"warehouse": wh, "doses": 0})
        entry["doses"] += batch.qty_remaining
    return sorted(totals.values(), key=lambda e: -e["doses"])


def last_count(warehouse=None):
    """The most recent stocktake adjustment — "counted when, by whom"."""
    query = VaccineAdjustment.query
    if warehouse is not None:
        query = query.filter(VaccineAdjustment.warehouse_id == warehouse.id)
    return query.order_by(VaccineAdjustment.created_at.desc()).first()


def batches_in(warehouse):
    """The batches a stocktake of this warehouse has to walk.

    Includes the emptied ones: a batch counted down to zero last month is
    exactly the one somebody needs to be able to say "there are three of these
    still here" about.
    """
    rows = [b for b in VaccineInventory.query.all() if _in(b, warehouse)]
    return sorted(rows, key=lambda b: (
        b.brand.name if b.brand else "", b.expiry_date is None, b.expiry_date))
