"""What a test uses, taken off the lab's store when it is run.

Asked as *«غالباً بيبقى بيخصم برده مستهلكات وليه مخزن شرايط التحاليل»*.

**When:** the moment the order is answered (``labs.settle`` moves it to
``resulted``), once per order. Not when the bill is printed — the strip is
used whether or not the family has paid, and a test the clinic does not
bill separately uses it just the same. A result cleared and typed again is
the same run and takes nothing more.

**From where:** the store the lab draws from (``lab_store`` on the tests
screen). **None chosen, nothing is taken** — a clinic that has not set this
up sees exactly what it saw before. A test with no consumables takes nothing.

**Never refused for want of stock**, for the reason a ward's doses are not:
the test was run, and the count is the store's to reconcile.

**And not twice.** A test's price service may carry consumables of its own,
which the till takes at billing (`finance._deduct_service_consumables`). The
tests screen says so beside any test where both are filled, so the clinic
chooses one place — this module does not guess which.
"""
from datetime import datetime

from app.extensions import db

STORE_KEY = "lab_store_warehouse_id"


def store():
    """The warehouse the lab draws from, or ``None``."""
    from app.models import Setting, Warehouse

    try:
        wid = int(Setting.get(STORE_KEY) or 0)
    except (TypeError, ValueError):
        return None
    row = db.session.get(Warehouse, wid) if wid else None
    return row if row is not None and row.is_active else None


def set_store(warehouse_id):
    from app.models import Setting, Warehouse

    row = db.session.get(Warehouse, warehouse_id) if warehouse_id else None
    Setting.set(STORE_KEY, str(row.id) if row is not None else "")
    return row


def consumables_cost(investigation):
    """What one run's consumables cost at the store's issue price, or
    ``None`` when nothing is listed or nothing has a price yet."""
    from app.utils.costing import issue_unit_cost

    total, priced = 0.0, False
    for c in getattr(investigation, "lab_consumables", None) or []:
        unit = issue_unit_cost(c.item) if c.item is not None else None
        if unit is not None:
            total += unit * (c.quantity or 1)
            priced = True
    return round(total, 2) if priced else None


def double_taken(investigation):
    """Whether the price service also carries consumables — the till would
    take those at billing, on top of these at the run."""
    service = getattr(investigation, "service", None)
    return bool(service is not None and getattr(service, "consumables", None)
                and getattr(investigation, "lab_consumables", None))


def take(order, user=None):
    """Take this order's consumables off the lab's store, once. Returns how
    many items moved (0 when there is no store, nothing listed, or it was
    already taken)."""
    from app.models import StockMovement
    from app.utils import cost_centres
    from app.utils.costing import issue_unit_cost
    from app.utils.store_docs import open_document

    if order is None or order.consumed_at is not None or order.kind != "lab":
        return 0
    test = order.investigation
    rows = [c for c in (getattr(test, "lab_consumables", None) or [])
            if c.store_item_id and (c.quantity or 0) > 0]
    warehouse = store()
    if not rows or warehouse is None:
        return 0
    document = open_document("issue", reference=f"LAB-{order.id}"[:60])
    centre = cost_centres.centre_id("lab")
    name = order.name or (test.name_ar if test else "")
    for c in rows:
        db.session.add(StockMovement(
            item_id=c.store_item_id, kind="out", qty=-abs(int(c.quantity or 1)),
            reason=f"{name} — {order.sample_code or order.id}"[:160],
            unit_cost=issue_unit_cost(c.item) if c.item is not None else None,
            warehouse_id=warehouse.id, cost_centre_id=centre,
            created_by=getattr(user, "id", None), document_id=document.id))
    order.consumed_at = datetime.utcnow()
    db.session.flush()
    _post(document, user)
    return len(rows)


def _post(document, user):
    """The cost of what was used, to the journal — best effort, the way the
    till posts its own issues: a journal hiccup never undoes a result."""
    try:
        from app.utils import accounting

        with db.session.begin_nested():
            accounting.post_store_doc(document, user_id=getattr(user, "id", None))
    except Exception:  # noqa: BLE001
        pass


def set_consumables(investigation, pairs):
    """Replace a test's consumables with ``[(store_item_id, quantity)]``."""
    from app.models import LabConsumable, StoreItem

    investigation.lab_consumables.clear()
    db.session.flush()
    seen = set()
    for item_id, qty in pairs:
        if not item_id or item_id in seen or (qty or 0) <= 0:
            continue
        if db.session.get(StoreItem, item_id) is None:
            continue
        seen.add(item_id)
        db.session.add(LabConsumable(investigation_id=investigation.id,
                                     store_item_id=item_id,
                                     quantity=min(int(qty), 999)))
    db.session.flush()
