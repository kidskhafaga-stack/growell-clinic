"""Reports module: read-only financial / operational / inventory summaries."""
from collections import defaultdict
from datetime import datetime

from flask import render_template, request

from app.blueprints.reports import reports_bp
from app.models import (
    Appointment,
    Invoice,
    Patient,
    PatientVaccine,
    Payment,
    Service,
    VaccineBrand,
    Vaccine,
    Visit,
)
from app.utils.decorators import module_required

MODULE = "reports"


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
