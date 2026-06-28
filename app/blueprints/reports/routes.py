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
    today = datetime.utcnow().date()
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

    return render_template(
        "reports/operational.html", date_from=date_from, date_to=date_to,
        by_status=sorted(by_status.items(), key=lambda kv: -kv[1]),
        appts_total=len(appts), new_patients=new_patients,
        visits=visits, doses=doses,
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
    invs = Invoice.query.filter(
        Invoice.doctor_id == doctor_id,
        Invoice.invoice_date >= date_from,
        Invoice.invoice_date <= date_to).all()

    groups = {}
    for inv in invs:
        for it in inv.items:
            key = it.service_id or 0
            g = groups.get(key)
            if g is None:
                label = it.service.display_name(getattr(g, "lang", "ar")) \
                    if it.service else (it.description or "—")
                g = groups[key] = {"label": label, "count": 0,
                                   "gross": 0.0, "doctor": 0.0}
            g["count"] += it.quantity or 1
            g["gross"] += it.net
            g["doctor"] += it.commission_amount or 0

    breakdown = sorted(
        ({"label": g["label"], "count": g["count"],
          "gross": round(g["gross"], 2), "doctor": round(g["doctor"], 2)}
         for g in groups.values()),
        key=lambda r: -r["doctor"])

    totals = {
        "visits": Visit.query.filter(
            Visit.doctor_id == doctor_id,
            Visit.visit_date >= date_from,
            Visit.visit_date <= date_to).count(),
        "cases": sum(r["count"] for r in breakdown),
        "billed": round(sum(i.total for i in invs), 2),
        "collected": round(sum(i.paid for i in invs), 2),
        "commission": round(sum(i.doctor_share_total for i in invs), 2),
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
