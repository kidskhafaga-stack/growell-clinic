"""Reports module: read-only financial / operational / inventory summaries,
plus analytical (research) and staff-performance dashboards with export."""
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime

from flask import Response, g, render_template, request

from app.blueprints.reports import reports_bp
from app.models import (
    Appointment,
    Diagnosis,
    Invoice,
    Patient,
    PatientVaccine,
    Payment,
    Service,
    User,
    VaccineBrand,
    Vaccine,
    Visit,
)
from app.utils.decorators import module_required
from app.utils.clock import local_today

MODULE = "reports"

AGE_BUCKETS = ["<1", "1-2", "2-5", "5-12", "12+"]


def _age_bucket(patient):
    years = patient.age_parts[0]
    if years < 1:
        return "<1"
    if years < 2:
        return "1-2"
    if years < 5:
        return "2-5"
    if years < 12:
        return "5-12"
    return "12+"


def _range():
    today = local_today()
    def parse(name, default):
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return default
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return default
    return parse("date_from", today.replace(day=1)), parse("date_to", today)


@reports_bp.route("/")
@module_required(MODULE)
def index():
    return render_template("reports/index.html")


@reports_bp.route("/financial")
@module_required(MODULE)
def financial():
    date_from, date_to = _range()
    invoices = (
        Invoice.query.filter(Invoice.invoice_date >= date_from,
                             Invoice.invoice_date <= date_to)
        .order_by(Invoice.invoice_date).all()
    )
    billed = round(sum(i.total for i in invoices), 2)
    collected = round(sum(i.paid for i in invoices), 2)
    totals = {
        "count": len(invoices),
        "billed": billed,
        "collected": collected,
        "outstanding": round(billed - collected, 2),
        "discounts": round(sum(i.discount_total for i in invoices), 2),
        "doctor_share": round(sum(i.doctor_share_total for i in invoices), 2),
    }

    by_day = defaultdict(float)
    for i in invoices:
        by_day[i.invoice_date] += i.total
    by_day = sorted(by_day.items())

    # Payment methods (by payment date in range).
    by_method = defaultdict(float)
    payments = (
        Payment.query.filter(Payment.paid_at >= datetime.combine(date_from, datetime.min.time()),
                             Payment.paid_at <= datetime.combine(date_to, datetime.max.time())).all()
    )
    for p in payments:
        by_method[p.method] += (p.amount or 0)

    return render_template(
        "reports/financial.html", date_from=date_from, date_to=date_to,
        totals=totals, by_day=by_day,
        by_method=sorted(by_method.items(), key=lambda kv: -kv[1]),
    )


@reports_bp.route("/income")
@module_required(MODULE)
def income():
    """Income statement (F3): revenue vs expenses from the journal, per
    account, for a period — the first true P&L, powered by the auto entries."""
    from app.models import Account, JournalEntry, JournalLine
    from app.extensions import db
    from app.utils.accounting import ensure_seeded

    ensure_seeded()
    date_from, date_to = _range()
    rows = (
        db.session.query(Account, db.func.sum(JournalLine.debit),
                         db.func.sum(JournalLine.credit))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(JournalEntry.entry_date >= date_from,
                JournalEntry.entry_date <= date_to,
                Account.type.in_(["revenue", "expense"]))
        .group_by(Account.id).order_by(Account.code).all()
    )
    revenue, expenses = [], []
    for acc, total_d, total_c in rows:
        if acc.type == "revenue":
            amount = round((total_c or 0) - (total_d or 0), 2)
            if amount:
                revenue.append((acc, amount))
        else:
            amount = round((total_d or 0) - (total_c or 0), 2)
            if amount:
                expenses.append((acc, amount))
    total_rev = round(sum(a for _, a in revenue), 2)
    total_exp = round(sum(a for _, a in expenses), 2)
    return render_template(
        "reports/income.html", date_from=date_from, date_to=date_to,
        revenue=revenue, expenses=expenses, total_rev=total_rev,
        total_exp=total_exp, net=round(total_rev - total_exp, 2),
    )


AGING_BUCKETS = [(0, 30), (31, 60), (61, 90), (91, None)]


@reports_bp.route("/ar-aging")
@module_required(MODULE)
def ar_aging():
    """AR aging (أعمار الديون): every unpaid balance bucketed by how long it
    has been outstanding, grouped per patient — the collection to-do list."""
    today = local_today()
    open_invoices = [i for i in Invoice.query
                     .filter(Invoice.status.in_(["unpaid", "partial"])).all()
                     if i.balance > 0.009]
    per_patient = {}
    totals = [0.0] * len(AGING_BUCKETS)
    for inv in open_invoices:
        age = (today - inv.invoice_date).days if inv.invoice_date else 0
        idx = next(i for i, (lo, hi) in enumerate(AGING_BUCKETS)
                   if age >= lo and (hi is None or age <= hi))
        row = per_patient.setdefault(inv.patient_id, {
            "patient": inv.patient, "buckets": [0.0] * len(AGING_BUCKETS),
            "total": 0.0, "count": 0,
        })
        row["buckets"][idx] = round(row["buckets"][idx] + inv.balance, 2)
        row["total"] = round(row["total"] + inv.balance, 2)
        row["count"] += 1
        totals[idx] = round(totals[idx] + inv.balance, 2)
    rows = sorted(per_patient.values(), key=lambda r: -r["total"])
    return render_template(
        "reports/ar_aging.html", rows=rows, totals=totals,
        grand=round(sum(totals), 2), today=today,
    )


def _as_of():
    """Single ``?as_of=`` cut-off date for the cumulative statements
    (trial balance / balance sheet); defaults to today."""
    raw = (request.args.get("as_of") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    return local_today()


def _ledger_movements(as_of):
    """Cumulative (debit_sum, credit_sum) per account up to and including
    ``as_of``, keyed by Account — the raw material for both statements."""
    from app.extensions import db
    from app.models import Account, JournalEntry, JournalLine
    from app.utils.accounting import ensure_seeded

    ensure_seeded()
    rows = (
        db.session.query(Account, db.func.sum(JournalLine.debit),
                         db.func.sum(JournalLine.credit))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(JournalEntry.entry_date <= as_of)
        .group_by(Account.id).order_by(Account.code).all()
    )
    return [(acc, round(d or 0, 2), round(c or 0, 2)) for acc, d, c in rows]


@reports_bp.route("/trial-balance")
@module_required(MODULE)
def trial_balance():
    """Trial balance (ميزان المراجعة): every account's net balance on its
    natural side as of a date. Total debits must equal total credits — the
    books' self-check, straight from the auto-posted journal."""
    as_of = _as_of()
    rows = []
    total_d = total_c = 0.0
    for acc, d, c in _ledger_movements(as_of):
        net = round(d - c, 2)
        if abs(net) < 0.005:
            continue
        # Placement is purely by the sign of net movement: a net debit
        # (net>0) sits in the debit column, a net credit in the credit column.
        on_debit = net > 0
        amount = abs(net)
        rows.append({"acc": acc,
                     "debit": amount if on_debit else 0.0,
                     "credit": amount if not on_debit else 0.0})
        total_d += amount if on_debit else 0.0
        total_c += amount if not on_debit else 0.0
    return render_template(
        "reports/trial_balance.html", rows=rows, as_of=as_of,
        total_debit=round(total_d, 2), total_credit=round(total_c, 2),
        balanced=abs(total_d - total_c) < 0.01,
    )


@reports_bp.route("/balance-sheet")
@module_required(MODULE)
def balance_sheet():
    """Balance sheet (الميزانية العمومية): assets vs liabilities + equity as
    of a date. Retained earnings for the period (revenue − expenses) is folded
    into equity so the sheet balances against the auto-posted journal."""
    as_of = _as_of()
    assets, liabilities, equity = [], [], []
    net_income = 0.0
    for acc, d, c in _ledger_movements(as_of):
        if acc.type == "asset":
            bal = round(d - c, 2)
            if abs(bal) >= 0.005:
                assets.append((acc, bal))
        elif acc.type == "liability":
            bal = round(c - d, 2)
            if abs(bal) >= 0.005:
                liabilities.append((acc, bal))
        elif acc.type == "equity":
            bal = round(c - d, 2)
            if abs(bal) >= 0.005:
                equity.append((acc, bal))
        elif acc.type == "revenue":
            net_income += round(c - d, 2)
        elif acc.type == "expense":
            net_income -= round(d - c, 2)
    net_income = round(net_income, 2)
    total_assets = round(sum(b for _, b in assets), 2)
    total_liab = round(sum(b for _, b in liabilities), 2)
    total_equity = round(sum(b for _, b in equity) + net_income, 2)
    total_le = round(total_liab + total_equity, 2)
    return render_template(
        "reports/balance_sheet.html", as_of=as_of,
        assets=assets, liabilities=liabilities, equity=equity,
        net_income=net_income, total_assets=total_assets,
        total_liab=total_liab, total_equity=total_equity, total_le=total_le,
        balanced=abs(total_assets - total_le) < 0.01,
    )


@reports_bp.route("/vat")
@module_required(MODULE)
def vat_summary():
    """Output-VAT summary (ملخص ض.ق.م): the tax collected on tax invoices in a
    period — the output side of the VAT return. Input VAT (on purchases) is not
    tracked yet, so VAT payable here equals output VAT."""
    from app.utils.einvoice import get_config as eta_config

    date_from, date_to = _range()
    cfg = eta_config()
    rate = cfg["vat_rate"]

    invoices = (Invoice.query
                .filter(Invoice.invoice_date >= date_from,
                        Invoice.invoice_date <= date_to)
                .order_by(Invoice.invoice_date).all())

    taxable_base = exempt_base = output_vat = 0.0
    tax_count = 0
    by_month = defaultdict(lambda: {"base": 0.0, "vat": 0.0, "count": 0})
    for inv in invoices:
        base = inv.total
        if inv.is_tax:
            vat = round(base * rate / 100.0, 2)
            taxable_base += base
            output_vat += vat
            tax_count += 1
            key = inv.invoice_date.strftime("%Y-%m")
            by_month[key]["base"] = round(by_month[key]["base"] + base, 2)
            by_month[key]["vat"] = round(by_month[key]["vat"] + vat, 2)
            by_month[key]["count"] += 1
        else:
            exempt_base += base

    totals = {
        "taxable_base": round(taxable_base, 2),
        "exempt_base": round(exempt_base, 2),
        "output_vat": round(output_vat, 2),
        "gross": round(taxable_base + output_vat, 2),
        "tax_count": tax_count,
        "rate": rate,
    }
    months = sorted(by_month.items())
    return render_template(
        "reports/vat_summary.html", date_from=date_from, date_to=date_to,
        totals=totals, months=months,
    )


def _apply_print_lang():
    """Per-print language choice (?lang=ar|en) so a statement can be handed to
    the family in either language regardless of the staff UI language."""
    lang = request.args.get("lang")
    if lang in ("ar", "en"):
        from app.i18n import get_direction

        g.lang = lang
        g.direction = get_direction(lang)


def _delta(e):
    """Signed effect of an event on the running balance (owed by the patient)."""
    return e["amount"] if e["kind"] in ("invoice", "refund") else -e["amount"]


@reports_bp.route("/statement/<int:patient_id>")
@module_required(MODULE)
def patient_statement(patient_id):
    """Printable patient statement (كشف حساب): invoices and payments in
    chronological order with a running balance. Supports an optional date range
    (?from=&to=) with a carried-forward opening balance, and a per-print
    language choice (?lang=)."""
    from datetime import date as _date

    from app.extensions import db

    _apply_print_lang()
    patient = db.get_or_404(Patient, patient_id)

    def _parse(name):
        raw = (request.args.get(name) or "").strip()
        try:
            return _date.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    date_from = _parse("from")
    date_to = _parse("to")

    events = []
    for inv in Invoice.query.filter_by(patient_id=patient.id).all():
        events.append({"date": inv.invoice_date, "kind": "invoice",
                       "ref": inv.invoice_number, "amount": inv.total})
        for pay in inv.payments:
            events.append({
                "date": pay.paid_at.date() if pay.paid_at else inv.invoice_date,
                "kind": "refund" if pay.kind == "refund" else "payment",
                "ref": inv.invoice_number, "amount": pay.amount or 0,
            })
    events.sort(key=lambda e: (e["date"] or local_today(), e["kind"]))

    # Opening balance = net of everything strictly before the range start; the
    # in-range rows then continue the running balance from there.
    opening = 0.0
    if date_from:
        opening = round(sum(_delta(e) for e in events
                            if e["date"] and e["date"] < date_from), 2)
    shown = [e for e in events
             if (not date_from or (e["date"] and e["date"] >= date_from))
             and (not date_to or (e["date"] and e["date"] <= date_to))]

    balance = opening
    for e in shown:
        balance = round(balance + _delta(e), 2)
        e["balance"] = balance
    summary = {
        "billed": round(sum(e["amount"] for e in shown if e["kind"] == "invoice"), 2),
        "paid": round(sum(e["amount"] for e in shown if e["kind"] == "payment"), 2),
        "refunded": round(sum(e["amount"] for e in shown if e["kind"] == "refund"), 2),
        "balance": balance,
    }
    return render_template("reports/statement.html", patient=patient,
                           events=shown, summary=summary,
                           opening=opening, date_from=date_from, date_to=date_to,
                           today=local_today())


@reports_bp.route("/operational")
@module_required(MODULE)
def operational():
    date_from, date_to = _range()

    appts = Appointment.query.filter(Appointment.appt_date >= date_from,
                                     Appointment.appt_date <= date_to).all()
    by_status = defaultdict(int)
    for a in appts:
        by_status[a.status] += 1

    new_patients = Patient.query.filter(
        Patient.created_at >= datetime.combine(date_from, datetime.min.time()),
        Patient.created_at <= datetime.combine(date_to, datetime.max.time())).count()
    visits = Visit.query.filter(Visit.visit_date >= date_from,
                                Visit.visit_date <= date_to).count()
    doses = PatientVaccine.query.filter(PatientVaccine.given_date >= date_from,
                                        PatientVaccine.given_date <= date_to).count()

    # --- GAHAR quality indicators ----------------------------------------
    total = len(appts)

    def _pct(n):
        return round(100.0 * n / total, 1) if total else 0.0

    def _avg_minutes(pairs):
        vals = [(b - a).total_seconds() / 60.0 for a, b in pairs
                if a and b and b >= a]
        return round(sum(vals) / len(vals), 1) if vals else None

    quality = {
        "completion_pct": _pct(by_status.get("completed", 0)),
        "cancellation_pct": _pct(by_status.get("cancelled", 0)),
        "no_show_pct": _pct(by_status.get("no_show", 0)),
        "avg_wait": _avg_minutes([(a.checked_in_at, a.started_at) for a in appts]),
        "avg_consult": _avg_minutes([(a.started_at, a.completed_at) for a in appts]),
    }
    # The same period, read properly: one "average wait" spans two queues with
    # two different owners — the front desk's and the doctor's door — and a
    # clinic cannot act on the sum of them. Medians, because one record left
    # open over lunch redraws a mean. The GAHAR averages above stay as they
    # are; that indicator set is defined as an average and changing what it
    # means under the same name would be worse than showing both.
    from app.utils.waiting import summarise
    timing = summarise(appts)
    invoices = Invoice.query.filter(Invoice.invoice_date >= date_from,
                                    Invoice.invoice_date <= date_to).all()
    unpaid = sum(1 for i in invoices if i.status in ("unpaid", "partial"))
    quality["unpaid_pct"] = round(100.0 * unpaid / len(invoices), 1) if invoices else 0.0

    return render_template(
        "reports/operational.html", date_from=date_from, date_to=date_to,
        by_status=sorted(by_status.items(), key=lambda kv: -kv[1]),
        appts_total=len(appts), new_patients=new_patients,
        visits=visits, doses=doses, quality=quality, timing=timing,
    )


@reports_bp.route("/inventory")
@module_required(MODULE)
def inventory():
    brands = (
        VaccineBrand.query.join(Vaccine).filter(Vaccine.is_mandatory.is_(False))
        .order_by(Vaccine.sort_order, VaccineBrand.name).all()
    )
    rows, total_units, total_value = [], 0, 0.0
    alerts = {"expired": 0, "near_expiry": 0, "low": 0, "out": 0}
    for b in brands:
        stock = b.stock
        cost = b.purchase_price or 0
        value = round(stock * cost, 2)
        total_units += stock
        total_value += value
        for batch in b.batches:
            s = batch.status
            if s in alerts:
                alerts[s] += 1
        rows.append({"brand": b, "stock": stock, "value": value})

    return render_template(
        "reports/inventory.html", rows=rows, alerts=alerts,
        total_units=total_units, total_value=round(total_value, 2),
    )


# ====================================================== analytics ==========
def _analytics_rows(date_from, date_to):
    """Case rows in range: (date, file/anon, age_label, age_bucket, gender,
    dx_type, code, title) joined diagnosis → visit → patient."""
    q = (Diagnosis.query.join(Visit, Diagnosis.visit_id == Visit.id)
         .filter(Visit.visit_date >= date_from, Visit.visit_date <= date_to)
         .order_by(Visit.visit_date))
    rows = []
    for dx in q.all():
        p = dx.visit.patient
        if p is None:
            continue
        years, months = p.age_parts
        rows.append({
            "date": dx.visit.visit_date.isoformat(),
            "file": p.patient_number,
            "age": f"{years}y {months}m" if years else f"{months}m",
            "bucket": _age_bucket(p),
            "gender": p.gender,
            "dx_type": dx.dx_type,
            "code": dx.code or "",
            "title": dx.title,
        })
    return rows


@reports_bp.route("/analytics")
@module_required(MODULE)
def analytics():
    date_from, date_to = _range()
    rows = _analytics_rows(date_from, date_to)
    top_dx = Counter(r["title"] for r in rows).most_common(15)
    by_gender = Counter(r["gender"] for r in rows)
    by_age = Counter(r["bucket"] for r in rows)
    age_rows = [(b, by_age.get(b, 0)) for b in AGE_BUCKETS]
    return render_template(
        "reports/analytics.html", date_from=date_from, date_to=date_to,
        total=len(rows), top_dx=top_dx,
        by_gender=sorted(by_gender.items()), age_rows=age_rows,
    )


@reports_bp.route("/analytics/export")
@module_required(MODULE)
def analytics_export():
    date_from, date_to = _range()
    rows = _analytics_rows(date_from, date_to)
    headers = ["date", "file", "age", "bucket", "gender", "dx_type", "code", "title"]
    fmt = (request.args.get("fmt") or "csv").lower()
    fname = f"analytics_{date_from}_{date_to}"

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            fmt = "csv"  # fall back if openpyxl is unavailable
        else:
            wb = Workbook(); ws = wb.active; ws.title = "Cases"
            ws.append(headers)
            for r in rows:
                ws.append([r[h] for h in headers])
            buf = io.BytesIO(); wb.save(buf); buf.seek(0)
            return Response(
                buf.read(),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={fname}.xlsx"})

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    w.writerows(rows)
    return Response(
        "﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={fname}.csv"})


# ================================================ staff performance =========
@reports_bp.route("/discounts")
@module_required(MODULE)
def discounts():
    """Who actually got a discount, how much, and who gave it.

    The discounts screen says what the clinic *offers*. This says what it
    **gave away** — a different question, and the one with money in it. A
    clinic can have four named discounts and no idea that one of them is
    costing it more than the other three together, or that most of what went
    out was not a named discount at all: it was typed line by line by
    whoever was on the till.

    That last distinction is the point of the split below. A rule the clinic
    decided on and a number somebody entered by hand are the same amount of
    money and completely different problems.
    """
    from app.models import Invoice, InvoiceItem, User

    date_from, date_to = _range()
    rows = (Invoice.query
            .filter(Invoice.invoice_date >= date_from,
                    Invoice.invoice_date <= date_to,
                    Invoice.status != "cancelled")
            .order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all())

    given, gross_total, by_rule, by_user = [], 0.0, {}, {}
    for invoice in rows:
        amount = invoice.discount_total
        if amount <= 0:
            continue
        gross_total += amount
        # Named or hand-typed. An invoice carries the rule it was billed
        # under; a line discounted without one was somebody's decision at the
        # counter, and that is worth being able to total on its own.
        label = invoice.discount_name or None
        slot = by_rule.setdefault(label or "", {"name": label, "total": 0.0,
                                                "count": 0})
        slot["total"] += amount
        slot["count"] += 1
        who = invoice.creator
        entry = by_user.setdefault(invoice.created_by or 0,
                                   {"user": who, "total": 0.0, "count": 0})
        entry["total"] += amount
        entry["count"] += 1
        given.append({"invoice": invoice, "amount": round(amount, 2),
                      "rule": label,
                      "gross": round(sum(i.gross for i in invoice.items), 2)})

    for slot in by_rule.values():
        slot["total"] = round(slot["total"], 2)
    for entry in by_user.values():
        entry["total"] = round(entry["total"], 2)

    billed = round(sum(sum(i.gross for i in inv.items) for inv in rows), 2)
    return render_template(
        "reports/discounts.html", rows=given,
        by_rule=sorted(by_rule.values(), key=lambda r: -r["total"]),
        by_user=sorted(by_user.values(), key=lambda r: -r["total"]),
        total=round(gross_total, 2), billed=billed,
        # What share of everything billed was given away. A number nobody can
        # put in context is a number nobody acts on.
        share=round(gross_total * 100.0 / billed, 1) if billed else 0,
        date_from=date_from, date_to=date_to)


@reports_bp.route("/staff")
@module_required(MODULE)
def staff():
    date_from, date_to = _range()
    start_dt = datetime.combine(date_from, datetime.min.time())
    end_dt = datetime.combine(date_to, datetime.max.time())

    doctors = User.query.filter_by(role="doctor").order_by(User.full_name).all()
    rows = []
    for doc in doctors:
        visits = Visit.query.filter(
            Visit.doctor_id == doc.id,
            Visit.visit_date >= date_from, Visit.visit_date <= date_to).count()
        invs = Invoice.query.filter(
            Invoice.doctor_id == doc.id,
            Invoice.invoice_date >= date_from, Invoice.invoice_date <= date_to).all()
        billed = round(sum(i.total for i in invs), 2)
        collected = round(sum(i.paid for i in invs), 2)
        commission = round(sum(i.doctor_share_total for i in invs), 2)
        rows.append({
            "doctor": doc, "visits": visits, "invoices": len(invs),
            "billed": billed, "collected": collected, "commission": commission,
        })
    rows.sort(key=lambda r: -r["collected"])
    totals = {
        "visits": sum(r["visits"] for r in rows),
        "billed": round(sum(r["billed"] for r in rows), 2),
        "collected": round(sum(r["collected"] for r in rows), 2),
        "commission": round(sum(r["commission"] for r in rows), 2),
    }
    return render_template(
        "reports/staff.html", date_from=date_from, date_to=date_to,
        rows=rows, totals=totals)


@reports_bp.route("/staff/<int:doctor_id>")
@module_required(MODULE)
def staff_statement(doctor_id):
    """Printable account statement for one doctor: case counts + doctor share
    broken down by service (how many exams / consultations / etc.)."""
    from app.extensions import db

    doctor = db.get_or_404(User, doctor_id)
    date_from, date_to = _range()

    # The same calculation the doctor's own screen reads. It was written out
    # here first; keeping a second copy of it would be two answers to "what am
    # I owed", which is the one number a program must never be vague about.
    from app.utils import doctor_work
    from flask import g

    work = doctor_work.summary(doctor_id, date_from, date_to,
                               getattr(g, "lang", "ar"))
    breakdown = [{"label": r["label"], "count": r["count"],
                  "gross": r["gross"], "doctor": r["share"]}
                 for r in work["services"]]
    totals = {
        "visits": Visit.query.filter(
            Visit.doctor_id == doctor_id,
            Visit.visit_date >= date_from,
            Visit.visit_date <= date_to).count(),
        "cases": work["cases"],
        "billed": work["money"]["billed"],
        "collected": work["money"]["collected"],
        "commission": work["money"]["share"],
    }
    return render_template(
        "reports/staff_statement.html", doctor=doctor,
        date_from=date_from, date_to=date_to,
        breakdown=breakdown, totals=totals)


@reports_bp.route("/vaccines")
@module_required(MODULE)
def vaccines():
    """Vaccine profit/loss: per brand, doses given in range with revenue, cost,
    doctor fees and the clinic's margin — so the clinic sees if it profits."""
    date_from, date_to = _range()
    given = PatientVaccine.query.filter(
        PatientVaccine.event_type == "given",
        PatientVaccine.given_outside.is_(False),
        PatientVaccine.given_date >= date_from,
        PatientVaccine.given_date <= date_to).all()

    grouped = {}
    for pv in given:
        b = pv.brand
        if b is None:
            continue
        grouped.setdefault(b.id, {"brand": b, "count": 0})["count"] += 1

    rows = []
    for g in grouped.values():
        b, n = g["brand"], g["count"]
        rows.append({
            "brand": b, "count": n,
            "revenue": round((b.price or 0) * n, 2),
            "cost": round((b.purchase_price or 0) * n, 2),
            "doctor": round((b.doctor_fee or 0) * n, 2),
            "margin": round(b.clinic_margin * n, 2),
        })
    rows.sort(key=lambda r: -r["margin"])
    totals = {k: round(sum(r[k] for r in rows), 2)
              for k in ("revenue", "cost", "doctor", "margin")}
    totals["count"] = sum(r["count"] for r in rows)
    return render_template(
        "reports/vaccines.html", date_from=date_from, date_to=date_to,
        rows=rows, totals=totals)
