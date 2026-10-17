"""The consumption board — what was used, what it cost, and when.

Asked as *«نعمل لوحة استهلاك استهلكت اد ايه وداش بورد في الفترات الزمنية»*
for the store as a whole, the medicines, the laboratory's consumables and
the assistant. It is the third of the boards (`med_board`, `admin_board`)
and keeps their two rules:

* **any stretch of time, beside the same stretch just before** — the window
  is ``med_board.window``, so a preset, typed dates, and the comparison all
  behave as they do on the other boards;
* **numbers, not verdicts** — nothing here says a department used "too
  much"; there is no target the program made up.

**Nothing new is stored.** The store already keeps every movement with its
item, its quantity, its unit cost, the department it was charged to and the
moment; the assistant already keeps every call's tokens (``AiUsage``).

* **Use** is what `stock_watch` calls use: an ``out`` that is an issue (or
  was written before documents existed) — never a transfer between
  warehouses, never a return to a supplier. **Waste** (expired, damaged) is
  counted apart: it is a loss, not use.
* **Its value** is the movement's own unit cost — the same figure the
  journal posted as cost of goods (``accounting.post_store_doc``), so this
  board and the books cannot disagree. A movement written without a cost is
  counted in quantity and said to be unpriced, never priced by a guess.
* **Medicines** are the items the store calls ``drug``; **the laboratory's
  consumables** are what a test took when it was run (``lab_stock.take``,
  one issue per order, referenced ``LAB-<order>``), so each test's
  consumables can stand beside its price.
* **The assistant** is reported in calls and tokens. Its money is on the
  vendor's bill: no provider sends a price with a reply, and a price the
  program typed in itself would be a number nobody gave it.
"""
from collections import defaultdict
from datetime import timedelta

from app.extensions import db

PARTS = ("store", "drugs", "lab", "ai")
#: How many items the "most used" table lists.
TOP = 30


# ----------------------------------------------------------------- shared ---
def _span(w, before=False):
    from app.utils import med_board

    if before:
        return med_board.utc(w["prev_from"], w["prev_to"])
    return med_board.utc(w["from"], w["to"])


def _bucketer(w):
    from app.utils.admin_board import _step

    step = _step(w["days"])
    d_from = w["from"]

    def bucket(day):
        if step == "day":
            return day
        if step == "week":
            return d_from + timedelta(days=((day - d_from).days // 7) * 7)
        return day.replace(day=1)

    points = {}
    cursor = d_from
    while cursor <= w["to"]:
        points.setdefault(bucket(cursor), {"start": bucket(cursor)})
        cursor += timedelta(days=1)
    return step, bucket, points


def change(now, before):
    """Percent change, or ``None`` when there is nothing to compare with."""
    if not before or now is None:
        return None
    return round((now - before) * 100 / abs(before))


# ------------------------------------------------------------------ store ---
def _movements(start, end, item_type=None, centre_id=None, warehouse_id=None,
               lab_only=False):
    """Use and waste lines in ``[start, end)``: one tuple per movement."""
    from app.models import StockMovement, StoreDocument, StoreItem

    q = (db.session.query(StockMovement.item_id, StockMovement.kind, StockMovement.qty,
                          StockMovement.unit_cost, StockMovement.cost_centre_id,
                          StockMovement.created_at, StoreDocument.kind,
                          StoreDocument.reference)
         .join(StoreItem, StoreItem.id == StockMovement.item_id)
         .outerjoin(StoreDocument, StoreDocument.id == StockMovement.document_id)
         .filter(StockMovement.created_at >= start, StockMovement.created_at < end,
                 StockMovement.qty < 0,
                 StockMovement.kind.in_(("out", "waste"))))
    if item_type:
        q = q.filter(StoreItem.item_type == item_type)
    if centre_id:
        q = q.filter(StockMovement.cost_centre_id == centre_id)
    if warehouse_id:
        q = q.filter(StockMovement.warehouse_id == warehouse_id)
    if lab_only:
        q = q.filter(StoreDocument.reference.like("LAB-%"))
    out = []
    for item_id, kind, qty, cost, centre, at, doc_kind, ref in q.all():
        if kind == "out" and doc_kind not in (None, "issue"):
            continue
        out.append({"item_id": item_id, "waste": kind == "waste", "qty": -(qty or 0),
                    "value": (-(qty or 0)) * cost if cost is not None else None,
                    "centre": centre, "at": at, "ref": ref or ""})
    return out


def _sum(rows):
    used = [r for r in rows if not r["waste"]]
    wasted = [r for r in rows if r["waste"]]
    return {"value": round(sum(r["value"] or 0 for r in used), 2),
            "waste": round(sum(r["value"] or 0 for r in wasted), 2),
            "lines": len(used),
            "items": len({r["item_id"] for r in used}),
            "unpriced": sum(1 for r in rows if r["value"] is None)}


def store(w, item_type=None, centre_id=None, warehouse_id=None, lab_only=False):
    """The store's (or the medicines', or the lab's) use in window ``w``."""
    from app.models import CostCentre, StoreItem
    from app.utils.clock import local_date

    now_rows = _movements(*_span(w), item_type, centre_id, warehouse_id, lab_only)
    before_rows = _movements(*_span(w, True), item_type, centre_id, warehouse_id, lab_only)
    now, before = _sum(now_rows), _sum(before_rows)

    # By department — what each part of the clinic used, beside before.
    centres = {c.id: c for c in CostCentre.query.all()}
    by_centre = defaultdict(lambda: {"now": 0.0, "before": 0.0, "lines": 0})
    for rows, key in ((now_rows, "now"), (before_rows, "before")):
        for r in rows:
            if r["waste"]:
                continue
            line = by_centre[r["centre"]]
            line[key] += r["value"] or 0
            if key == "now":
                line["lines"] += 1
    departments = sorted(
        [{"centre": centres.get(cid), "now": round(v["now"], 2),
          "before": round(v["before"], 2), "lines": v["lines"]}
         for cid, v in by_centre.items()],
        key=lambda d: -d["now"])

    # By kind of item — only on the whole store's view.
    ids = {r["item_id"] for r in now_rows + before_rows}
    items = ({i.id: i for i in StoreItem.query.filter(StoreItem.id.in_(ids)).all()}
             if ids else {})
    by_type = defaultdict(lambda: {"now": 0.0, "before": 0.0})
    if not item_type:
        for rows, key in ((now_rows, "now"), (before_rows, "before")):
            for r in rows:
                if not r["waste"]:
                    item = items.get(r["item_id"])
                    by_type[(item.item_type if item else None) or ""][key] += r["value"] or 0
    types = sorted([{"type": k, "now": round(v["now"], 2), "before": round(v["before"], 2)}
                    for k, v in by_type.items()], key=lambda d: -d["now"])

    # The items used most — by value, then by quantity.
    per_item = defaultdict(lambda: {"qty": 0, "value": 0.0, "waste_qty": 0,
                                    "before": 0.0, "unpriced": False})
    for r in now_rows:
        line = per_item[r["item_id"]]
        if r["waste"]:
            line["waste_qty"] += r["qty"]
            continue
        line["qty"] += r["qty"]
        line["value"] += r["value"] or 0
        line["unpriced"] = line["unpriced"] or r["value"] is None
    for r in before_rows:
        if not r["waste"] and r["item_id"] in per_item:
            per_item[r["item_id"]]["before"] += r["value"] or 0
    total = now["value"] or 0
    top = sorted([{"item": items.get(iid), "qty": v["qty"], "value": round(v["value"], 2),
                   "before": round(v["before"], 2), "waste_qty": v["waste_qty"],
                   "unpriced": v["unpriced"],
                   "share": round(v["value"] * 100 / total, 1) if total else None}
                  for iid, v in per_item.items() if v["qty"] or v["waste_qty"]],
                 key=lambda d: (-d["value"], -d["qty"]))[:TOP]

    # Over time, in the board's own steps.
    step, bucket, points = _bucketer(w)
    for p in points.values():
        p.update(value=0.0, waste=0.0)
    for r in now_rows:
        day = local_date(r["at"])
        point = points.get(bucket(day))
        if point is not None:
            point["waste" if r["waste"] else "value"] += r["value"] or 0
    trend = sorted(points.values(), key=lambda p: p["start"])
    for p in trend:
        p["value"], p["waste"] = round(p["value"], 2), round(p["waste"], 2)

    return {"now": now, "before": before, "departments": departments,
            "types": types, "top": top, "step": step, "trend": trend,
            "rows": now_rows}


# -------------------------------------------------------------------- lab ---
def lab(w):
    """The laboratory's consumables: the store's view of what tests took,
    and each test's runs and consumables beside its price."""
    from app.models import Investigation, VisitInvestigation

    data = store(w, lab_only=True)
    cost_by_order = defaultdict(float)
    for r in data["rows"]:
        ref = r["ref"][4:]
        if ref.isdigit() and not r["waste"]:
            cost_by_order[int(ref)] += r["value"] or 0
    start, end = _span(w)
    orders = (db.session.query(VisitInvestigation.id, VisitInvestigation.investigation_id)
              .filter(VisitInvestigation.consumed_at >= start,
                      VisitInvestigation.consumed_at < end).all())
    per_test = defaultdict(lambda: {"runs": 0, "cost": 0.0})
    for oid, tid in orders:
        line = per_test[tid]
        line["runs"] += 1
        line["cost"] += cost_by_order.get(oid, 0.0)
    tests = {t.id: t for t in Investigation.query.filter(
        Investigation.id.in_([k for k in per_test if k])).all()} if per_test else {}
    rows = []
    for tid, v in per_test.items():
        test = tests.get(tid)
        price = test.service.price if test is not None and test.service is not None else None
        each = round(v["cost"] / v["runs"], 2) if v["runs"] else None
        rows.append({"test": test, "runs": v["runs"], "cost": round(v["cost"], 2),
                     "each": each, "price": price,
                     "share": (round(each * 100 / price, 1)
                               if each is not None and price else None)})
    rows.sort(key=lambda d: (-d["cost"], -d["runs"]))
    data["tests"] = rows[:TOP]
    data["runs"] = sum(v["runs"] for v in per_test.values())
    return data


# --------------------------------------------------------------------- ai ---
def _ai_rows(start, end):
    from app.models import AiUsage

    return (db.session.query(AiUsage.feature, AiUsage.user_id, AiUsage.created_at,
                             AiUsage.prompt_tokens, AiUsage.completion_tokens)
            .filter(AiUsage.created_at >= start, AiUsage.created_at < end).all())


def ai(w):
    """The assistant: calls and tokens, by what it was used for and by whom."""
    from app.models import User
    from app.utils.clock import local_date

    now_rows, before_rows = _ai_rows(*_span(w)), _ai_rows(*_span(w, True))

    def total(rows):
        return {"calls": len(rows),
                "tokens": sum((p or 0) + (c or 0) for _f, _u, _a, p, c in rows)}

    by_feature = defaultdict(lambda: {"calls": 0, "tokens": 0, "before": 0})
    by_user = defaultdict(lambda: {"calls": 0, "tokens": 0})
    for f, u, _a, p, c in now_rows:
        line = by_feature[f or "chat"]
        line["calls"] += 1
        line["tokens"] += (p or 0) + (c or 0)
        by_user[u]["calls"] += 1
        by_user[u]["tokens"] += (p or 0) + (c or 0)
    for f, _u, _a, p, c in before_rows:
        by_feature[f or "chat"]["before"] += (p or 0) + (c or 0)
    users = {u.id: u for u in User.query.filter(
        User.id.in_([k for k in by_user if k])).all()} if by_user else {}
    step, bucket, points = _bucketer(w)
    for p in points.values():
        p.update(tokens=0, calls=0)
    for _f, _u, at, p, c in now_rows:
        point = points.get(bucket(local_date(at)))
        if point is not None:
            point["tokens"] += (p or 0) + (c or 0)
            point["calls"] += 1
    return {"now": total(now_rows), "before": total(before_rows),
            "features": sorted([{"feature": k, **v} for k, v in by_feature.items()
                                if v["calls"] or v["before"]],
                               key=lambda d: (-d["tokens"], -d["before"])),
            "users": sorted([{"user": users.get(k), **v} for k, v in by_user.items()],
                            key=lambda d: -d["tokens"]),
            "step": step, "trend": sorted(points.values(), key=lambda p: p["start"])}


# ----------------------------------------------------------------- access ---
def parts_for(user):
    """The parts this person may see — each behind the module it reports on."""
    from app.utils.facility import module_enabled

    allowed = []
    store_ok = user.can_open("inventory") or (user.can_open("reports")
                                              and user.can("finance_manage"))
    if store_ok and module_enabled("inventory"):
        allowed += ["store", "drugs"]
    if user.can_open("labs") or (store_ok and module_enabled("labs")):
        allowed.append("lab")
    if user.can_open("ai"):
        allowed.append("ai")
    return allowed


__all__ = ["PARTS", "ai", "change", "lab", "parts_for", "store"]
