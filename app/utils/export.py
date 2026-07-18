"""Raw-data export: download operational records as CSV or Excel.

Read-only. Each dataset is a flat list of dict rows with a fixed header order;
``export_response`` turns one into a downloadable CSV (UTF-8 BOM, so Arabic
opens correctly in Excel) or an ``.xlsx`` workbook.
"""
import csv
import io

from flask import Response

from app.extensions import db


def _fmt_dt(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _fmt_d(value):
    return value.isoformat() if value else ""


def _patients_rows():
    from app.models import Patient
    for p in Patient.query.order_by(Patient.id).all():
        yield {
            "file_no": p.patient_number, "name": p.full_name,
            "name_en": p.full_name_en or "", "gender": p.gender,
            "date_of_birth": _fmt_d(p.date_of_birth),
            "phone": p.contact_phone or "", "national_id": p.national_id or "",
            "blood_type": p.blood_type or "",
            "active": "1" if p.is_active else "0",
            "created_at": _fmt_dt(p.created_at),
        }


def _invoices_rows():
    from app.models import Invoice
    for inv in Invoice.query.order_by(Invoice.id).all():
        yield {
            "invoice_no": inv.invoice_number, "date": _fmt_d(inv.invoice_date),
            "patient": inv.patient.full_name if inv.patient else "",
            "total": inv.total, "paid": round(inv.total - inv.balance, 2),
            "balance": inv.balance, "status": inv.status,
        }


def _appointments_rows():
    from app.models import Appointment
    for a in Appointment.query.order_by(Appointment.id).all():
        yield {
            "date": _fmt_d(a.appt_date),
            "time": a.appt_time.strftime("%H:%M") if a.appt_time else "",
            "patient": a.patient.full_name if a.patient else "",
            "doctor": a.doctor.full_name if a.doctor else "",
            "type": a.appt_type, "status": a.status,
            "reason": a.reason or "",
        }


def _vaccinations_rows():
    from app.models import PatientVaccine
    q = (PatientVaccine.query
         .filter(PatientVaccine.event_type == "given")
         .order_by(PatientVaccine.id))
    for pv in q.all():
        yield {
            "patient": pv.patient.full_name if pv.patient else "",
            "vaccine": pv.vaccine.name_ar if pv.vaccine else "",
            "brand": pv.brand.name if pv.brand else "",
            "dose_number": pv.dose_number,
            "given_date": _fmt_d(pv.given_date),
            "lot_number": pv.lot_number or "",
            "given_outside": "1" if pv.given_outside else "0",
        }


# Registry: kind -> (header order, row generator). Adding a dataset is one entry.
DATASETS = {
    "patients": (["file_no", "name", "name_en", "gender", "date_of_birth",
                  "phone", "national_id", "blood_type", "active", "created_at"],
                 _patients_rows),
    "invoices": (["invoice_no", "date", "patient", "total", "paid", "balance",
                  "status"], _invoices_rows),
    "appointments": (["date", "time", "patient", "doctor", "type", "status",
                      "reason"], _appointments_rows),
    "vaccinations": (["patient", "vaccine", "brand", "dose_number",
                      "given_date", "lot_number", "given_outside"],
                     _vaccinations_rows),
}


def dataset_count(kind):
    """Row count for a dataset (for the UI), or None if the kind is unknown."""
    counts = {
        "patients": "Patient", "invoices": "Invoice",
        "appointments": "Appointment", "vaccinations": "PatientVaccine",
    }
    name = counts.get(kind)
    if not name:
        return None
    import app.models as models
    model = getattr(models, name)
    q = model.query
    if kind == "vaccinations":
        q = q.filter(model.event_type == "given")
    return q.count()


def export_response(kind, fmt="csv"):
    """Build a downloadable Response for ``kind`` in ``csv`` or ``xlsx``.
    Returns ``None`` for an unknown dataset."""
    entry = DATASETS.get(kind)
    if entry is None:
        return None
    headers, rowgen = entry
    rows = list(rowgen())
    fname = f"{kind}_export"

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            fmt = "csv"  # fall back if openpyxl isn't installed
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = kind[:31]
            ws.append(headers)
            for r in rows:
                ws.append([r.get(h, "") for h in headers])
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
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
