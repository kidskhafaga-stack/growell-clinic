"""The management board: the money and the work of each part of the clinic.

The prototype the clinic agreed is the shape; the numbers are the program's
own, **read from the places that already answer them** so no two screens can
disagree:

* revenue, costs and the net are the journal's, through the same
  ``cost_centre_report`` the cost-centre screen and the income statement add
  up to;
* what was collected is the payments, refunds taken off, by the day they were
  taken — as the financial report reads them;
* what families still owe is today's open balances, the same list as the
  debts-by-age screen — a figure for *now*, so it has no "before";
* a doctor's billing and share are their own lines on the bills
  (``InvoiceItem.earner_id``), the rule a doctor's statement uses.

Every figure sits beside the same stretch before it, and nothing here is a
judgement: a department's margin is shown, not graded.
"""
from collections import defaultdict
from datetime import timedelta

from app.extensions import db

#: A bill unpaid for longer than this many days is listed for attention.
OVERDUE_DAYS = 30


def _report(d_from, d_to):
    from app.utils import cost_centre_report
    from app.utils.accounting import ensure_seeded

    ensure_seeded()
    return cost_centre_report.report(d_from, d_to)


def collected(d_from, d_to):
    """``(total, {method: amount})`` — payments less refunds, by when taken."""
    from app.models import Payment
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    by_method = defaultdict(float)
    for method, kind, amount in (db.session.query(Payment.method, Payment.kind,
                                                  db.func.sum(Payment.amount))
                                 .filter(Payment.paid_at >= start, Payment.paid_at < end)
                                 .group_by(Payment.method, Payment.kind).all()):
        by_method[method or "cash"] += -(amount or 0) if kind == "refund" else (amount or 0)
    by_method = {m: round(v, 2) for m, v in by_method.items() if round(v, 2)}
    return round(sum(by_method.values()), 2), by_method


def owed_now(today=None):
    """``{"total", "overdue", "overdue_count"}`` — open balances as of today."""
    from app.models import Invoice
    from app.utils.clock import local_today

    today = today or local_today()
    total = overdue = 0.0
    count = 0
    for inv in Invoice.query.filter(Invoice.status.in_(["unpaid", "partial"])).all():
        balance = inv.balance
        if balance <= 0.009:
            continue
        total += balance
        if inv.invoice_date and (today - inv.invoice_date).days > OVERDUE_DAYS:
            overdue += balance
            count += 1
    return {"total": round(total, 2), "overdue": round(overdue, 2), "overdue_count": count}


def figures(d_from, d_to, report=None):
    """The headline numbers for one period."""
    from app.models import Invoice, Visit

    report = report or _report(d_from, d_to)
    money_in, _ = collected(d_from, d_to)
    bills = Invoice.query.filter(Invoice.invoice_date >= d_from,
                                 Invoice.invoice_date <= d_to).count()
    return {
        "revenue": report["revenue"], "expenses": report["expenses"],
        "net": report["net"], "collected": money_in, "bills": bills,
        "per_bill": round(report["revenue"] / bills, 2) if bills else None,
        "visits": Visit.query.filter(Visit.visit_date >= d_from,
                                     Visit.visit_date <= d_to).count(),
    }


def departments(now_report, before_report):
    """The cost-centre lines, each with its revenue the period before."""
    before = {line["centre"].id: line for line in before_report["lines"] if line["centre"]}
    out = []
    for line in now_report["lines"]:
        centre = line["centre"]
        was = before.get(centre.id) if centre else None
        out.append({**line, "before": was["revenue"] if was else 0,
                    "before_direct": was["direct"] if was else 0})
    return out


def _step(days):
    """How to bucket a trend: by day up to a month, by week to four months,
    by month beyond."""
    return "day" if days <= 31 else "week" if days <= 124 else "month"


def trend(d_from, d_to):
    """``(step, [{"start", "revenue", "expenses"}])`` from the journal."""
    from app.models import Account, JournalEntry, JournalLine

    days = (d_to - d_from).days + 1
    step = _step(days)

    def bucket(day):
        if step == "day":
            return day
        if step == "week":
            return d_from + timedelta(days=((day - d_from).days // 7) * 7)
        return day.replace(day=1)

    points = {}
    cursor = d_from
    while cursor <= d_to:
        points.setdefault(bucket(cursor), {"start": bucket(cursor), "revenue": 0.0,
                                           "expenses": 0.0})
        cursor += timedelta(days=1)
    for day, kind, debit, credit in (
            db.session.query(JournalEntry.entry_date, Account.type,
                             db.func.sum(JournalLine.debit), db.func.sum(JournalLine.credit))
            .join(JournalLine, JournalLine.entry_id == JournalEntry.id)
            .join(Account, JournalLine.account_id == Account.id)
            .filter(JournalEntry.entry_date >= d_from, JournalEntry.entry_date <= d_to,
                    Account.type.in_(["revenue", "expense"]))
            .group_by(JournalEntry.entry_date, Account.type).all()):
        point = points[bucket(day)]
        if kind == "revenue":
            point["revenue"] += (credit or 0) - (debit or 0)
        else:
            point["expenses"] += (debit or 0) - (credit or 0)
    rows = sorted(points.values(), key=lambda p: p["start"])
    for p in rows:
        p["revenue"], p["expenses"] = round(p["revenue"], 2), round(p["expenses"], 2)
    return step, rows


def attention(report, owed, today=None):
    """What wants somebody's eye — each with where to go about it."""
    from app.models.inventory import VaccineInventory

    items = []
    if owed["overdue_count"]:
        items.append({"key": "overdue", "value": owed["overdue_count"],
                      "amount": owed["overdue"], "endpoint": "reports.ar_aging",
                      "level": "bad"})
    near = sum(1 for b in VaccineInventory.query.all() if b.status == "near_expiry")
    if near:
        items.append({"key": "near_expiry", "value": near, "endpoint": "reports.inventory",
                      "level": "warn"})
    if report["revenue"] > 0 and report["shared_total"]:
        items.append({"key": "shared", "value": round(report["shared_total"] * 100
                                                      / report["revenue"]),
                      "endpoint": "reports.cost_centres", "level": "info"})
    if report["unplaced_total"]:
        items.append({"key": "unplaced", "value": report["unplaced_total"],
                      "endpoint": "reports.cost_centres", "level": "warn"})
    return items


def doctors(d_from, d_to):
    """One row per doctor with billing or visits in the period."""
    from sqlalchemy.orm import selectinload

    from app.models import Appointment, Invoice, User, Visit

    rows = defaultdict(lambda: {"visits": 0, "bills": set(), "billed": 0.0,
                                "share": 0.0, "appts": 0, "no_show": 0})
    for doc, n in (db.session.query(Visit.doctor_id, db.func.count(Visit.id))
                   .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to)
                   .group_by(Visit.doctor_id).all()):
        rows[doc]["visits"] = n
    for inv in (Invoice.query.options(selectinload(Invoice.items))
                .filter(Invoice.invoice_date >= d_from, Invoice.invoice_date <= d_to).all()):
        for item in inv.items:
            doc = item.earner_id
            if doc is None:
                continue
            r = rows[doc]
            r["bills"].add(inv.id)
            r["billed"] += item.net
            r["share"] += item.commission_amount or 0
    for doc, status, n in (db.session.query(Appointment.doctor_id, Appointment.status,
                                            db.func.count(Appointment.id))
                           .filter(Appointment.appt_date >= d_from,
                                   Appointment.appt_date <= d_to)
                           .group_by(Appointment.doctor_id, Appointment.status).all()):
        if doc is None:
            continue
        rows[doc]["appts"] += n
        if status == "no_show":
            rows[doc]["no_show"] += n
    people = {u.id: u for u in User.query.filter(User.id.in_([d for d in rows if d] or [0]))}
    out = []
    for doc, r in rows.items():
        if doc not in people or not (r["visits"] or r["bills"]):
            continue
        bills = len(r["bills"])
        out.append({
            "doctor": people[doc], "visits": r["visits"], "bills": bills,
            "billed": round(r["billed"], 2), "share": round(r["share"], 2),
            "per_bill": round(r["billed"] / bills, 2) if bills else None,
            "no_show_pct": round(r["no_show"] * 100 / r["appts"], 1) if r["appts"] else None,
        })
    out.sort(key=lambda r: (-r["billed"], r["doctor"].full_name or ""))
    return out


def board(w):
    """Everything the page shows for window ``w`` (``med_board.window``)."""
    now_report = _report(w["from"], w["to"])
    before_report = _report(w["prev_from"], w["prev_to"])
    owed = owed_now()
    _, by_method = collected(w["from"], w["to"])
    step, points = trend(w["from"], w["to"])
    return {
        "now": figures(w["from"], w["to"], now_report),
        "before": figures(w["prev_from"], w["prev_to"], before_report),
        "report": now_report, "owed": owed,
        "departments": departments(now_report, before_report),
        "methods": sorted(by_method.items(), key=lambda kv: -kv[1]),
        "step": step, "trend": points,
        "attention": attention(now_report, owed),
        "doctors": doctors(w["from"], w["to"]),
    }
