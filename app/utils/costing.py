"""Purchase-cost capture, sell-price policy, and issue-costing policies.

The clinic buys stock through purchase invoices / goods receipts; each line
carries a unit cost. This module is the one place that reacts to a new cost:

- **Last purchase cost** is stamped on the item (general store) — vaccines keep
  their weighted-average cost, recomputed from batches as before.
- **Sell-price policy** per item/brand: ``manual`` (default — nobody touches
  the price) or ``auto`` (sell = last cost × (1 + margin%), using the item's
  own margin or the clinic-wide default). Sensitive items simply stay manual.
- **Issue costing** for the general store: FIFO (default) or LIFO layers over
  the item's receipt movements — vaccines always dispense FEFO by expiry,
  which is the correct policy for pharma and is not configurable.
"""
from app.extensions import db

PRICE_POLICIES = ["manual", "auto"]
DISPENSE_POLICIES = ["fifo", "lifo"]


def default_margin():
    """Clinic-wide default profit margin % for auto-priced items."""
    from app.models import Setting
    try:
        return float(Setting.get("default_margin_percent", "25") or 25)
    except (TypeError, ValueError):
        return 25.0


def store_dispense_policy():
    """How the general store costs its issues: fifo (default) or lifo."""
    from app.models import Setting
    pol = (Setting.get("store_dispense_policy", "fifo") or "fifo").strip()
    return pol if pol in DISPENSE_POLICIES else "fifo"


def _auto_sell(cost, margin):
    return round((cost or 0) * (1 + (margin or 0) / 100.0), 2)


def apply_purchase_cost(obj, cost):
    """React to a new purchase cost on a VaccineBrand or StoreItem.

    Stamps the last purchase cost (general store items — vaccine brands keep
    their weighted-average, recomputed from batches elsewhere) and, when the
    item's pricing policy is ``auto``, refreshes the sell price from this cost
    and the item's margin (falling back to the clinic default). Returns True
    when the sell price changed."""
    if cost is None or cost <= 0:
        return False
    from app.models import StoreItem
    if isinstance(obj, StoreItem):
        obj.purchase_price = round(cost, 2)   # آخر سعر شراء
    if getattr(obj, "price_policy", "manual") != "auto":
        return False
    margin = obj.margin_percent if obj.margin_percent is not None else default_margin()
    new_price = _auto_sell(cost, margin)
    if isinstance(obj, StoreItem):
        if obj.sell_price == new_price:
            return False
        obj.sell_price = new_price
    else:  # VaccineBrand
        if obj.price == new_price:
            return False
        obj.price = new_price
    return True


def issue_unit_cost(item, policy=None):
    """Unit cost of the *next* unit issued from the general store under the
    clinic's dispensing policy.

    Builds cost layers from the item's receipt movements (opening stock is a
    layer at the item's purchase price), consumes them in FIFO or LIFO order
    against everything already issued, and returns the current layer's cost.
    Falls back to the item's purchase price when no layered cost is known."""
    policy = policy or store_dispense_policy()
    fallback = item.purchase_price or 0

    layers = []
    if item.opening_stock:
        layers.append([None, item.opening_stock, fallback])  # (ts, qty, cost)
    issued = 0
    for m in sorted(item.movements, key=lambda m: (m.created_at, m.id)):
        q = m.qty or 0
        if q > 0:
            layers.append([m.created_at, q, m.unit_cost if m.unit_cost is not None else fallback])
        else:
            issued += -q

    if policy == "lifo":
        layers.reverse()
    for _, qty, cost in layers:
        if issued < qty:
            return cost
        issued -= qty
    return fallback
