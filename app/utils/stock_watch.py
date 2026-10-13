"""How fast each store item is used, and every time it ran out — GAHAR
OGM.11 ev. 3 ("utilization rate … and monitoring of out-stock events").

Nothing new is stored. The store already keeps every movement with its
time, so both answers are read back from it:

* **use** — what left the shelf to be used: an ``out`` movement that is an
  issue (or was written before documents existed), never a transfer between
  warehouses or a return to the supplier; ``waste`` (expired, damaged) is
  counted apart, because it is a loss, not use;
* **a stock-out** — the item's balance, replayed movement by movement from
  its opening stock, falling from something to zero; it ends the moment
  stock comes back. An item never stocked has not run out.

The program sets no reorder level and no cover target: it reports the
level the store wrote, and how many days the current stock lasts at the
rate the item was actually used.
"""
from datetime import datetime, timedelta

#: The window the rate is read over, in days.
WINDOW_DAYS = 90
#: What a "month" is when the rate is shown per month.
MONTH_DAYS = 30


def _is_use(m):
    if (m.qty or 0) >= 0 or m.kind != "out":
        return False
    return m.document is None or m.document.kind == "issue"


def usage(item, since, until):
    """``(used, wasted)`` in stock units between two moments."""
    used = wasted = 0
    for m in item.movements:
        if not (since <= m.created_at < until):
            continue
        if _is_use(m):
            used += -(m.qty or 0)
        elif m.kind == "waste" and (m.qty or 0) < 0:
            wasted += -(m.qty or 0)
    return used, wasted


def stockouts(item, since, until):
    """Every stretch the item stood at zero or below that overlaps the
    window: ``[{"start", "end" (None while still out), "days"}]``."""
    # An item that has never had stock has not "run out" — it starts
    # counting from the first time it was held.
    balance = item.opening_stock or 0
    out, start = [], None
    for m in sorted(item.movements, key=lambda x: (x.created_at, x.id or 0)):
        before = balance
        balance += m.qty or 0
        if before > 0 >= balance:
            start = m.created_at
        elif before <= 0 < balance and start is not None:
            out.append((start, m.created_at))
            start = None
    if start is not None:
        out.append((start, None))
    rows = []
    for s, e in out:
        if (e or until) < since or s >= until:
            continue
        lo, hi = max(s, since), min(e or until, until)
        rows.append({"start": s, "end": e, "days": max(0, (hi - lo).days)})
    return rows


def report(days=WINDOW_DAYS, now=None):
    """Every active item with its use per month over the window, its waste,
    its stock now, the level the store wrote, how many days the stock lasts
    at that rate, and its stock-outs in the window — out now first, then
    the most stock-outs."""
    from app.models import StoreItem

    now = now or datetime.utcnow()
    since = now - timedelta(days=days)
    rows = []
    for item in StoreItem.query.filter_by(is_active=True).order_by(StoreItem.name).all():
        used, wasted = usage(item, since, now)
        per_day = used / days if days else 0
        stock = item.current_stock
        outs = stockouts(item, since, now)
        rows.append({"item": item, "used": used, "wasted": wasted,
                     "per_month": round(per_day * MONTH_DAYS, 1),
                     "stock": stock, "reorder": item.reorder_level or 0,
                     "cover_days": int(stock / per_day) if per_day and stock > 0 else None,
                     "stockouts": outs, "out_days": sum(o["days"] for o in outs),
                     "out_now": stock <= 0})
    rows.sort(key=lambda r: (not r["out_now"], -len(r["stockouts"]), r["item"].name))
    return {"rows": rows, "days": days,
            "out_now": [r for r in rows if r["out_now"]],
            "events": sum(len(r["stockouts"]) for r in rows),
            "low": [r for r in rows if not r["out_now"] and r["stock"] <= r["reorder"]]}


__all__ = ["MONTH_DAYS", "WINDOW_DAYS", "report", "stockouts", "usage"]
