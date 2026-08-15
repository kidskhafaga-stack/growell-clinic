"""Raw-data export: download operational records as CSV or Excel.

Read-only. Each dataset is a flat list of dict rows with a fixed header order;
``export_response`` turns one into a downloadable CSV (UTF-8 BOM, so Arabic
opens correctly in Excel) or an ``.xlsx`` workbook.

**Every dataset takes a date range**, which is the difference between a feature
and a button. Without one the only export available is *everything ever*, and
an accountant who wants last month gets the whole history and filters it in
Excel — so the clinic does the work the program was asked to do, and does it
somewhere nobody can check. Each dataset therefore declares which column is
"its" date, and the range is applied in the query rather than after it.

The counts on the screen are counted the same way, because a screen offering
"invoices (1,240)" next to a one-month range is stating something untrue about
the file it is about to hand you.
"""
import csv
import io
from datetime import date, datetime

from flask import Response


def _fmt_dt(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _fmt_d(value):
    return value.isoformat() if value else ""


def parse_date(raw):
    """A date off the form, or None. Never raises — a mistyped range must
    fall back to "everything", not to an error page over a download."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _between(query, column, start, end, is_datetime=False):
    """Apply the range to ``column``. The end is inclusive — somebody typing
    31 January means the 31st, and an exclusive bound would silently drop the
    last day of every month anybody ever exports."""
    if start:
        query = query.filter(column >= start)
    if end:
        if is_datetime:
            query = query.filter(column < datetime.combine(
                end, datetime.max.time()).replace(microsecond=0))
        else:
            query = query.filter(column <= end)
    return query


# ---------------------------------------------------------------- rows -----
def _patients_query(start, end):
    from app.models import Patient
    return _between(Patient.query.order_by(Patient.id),
                    Patient.created_at, start, end, is_datetime=True)


# Everything the clinic types into a patient file, in the order the file
# itself asks for it. The ten columns this used to carry left out the
# allergies, the chronic conditions, the guardian and their phone, the family,
# the notes and the archive reason — asked about in exactly those words:
# *"why am I entering it at all, then?"*
#
# Two of them are not stored columns and are here because a spreadsheet cannot
# work them out: ``age`` (the file shows it everywhere and a date of birth in
# a cell does not) and ``guardian_phone`` (which lives on the parent, not the
# child, and is the number a clinic actually rings).
PATIENT_COLUMNS = [
    "file_no", "reference_no", "name", "name_en", "gender",
    "date_of_birth", "age", "national_id", "blood_type",
    "own_phone", "contact_phone",
    "guardian_name", "guardian_relation", "guardian_phone",
    "family", "allergies", "chronic_diseases", "notes",
    "whatsapp_opt_out", "active", "archived_at", "archive_reason",
    "created_at", "updated_at",
]


def _age_text(patient):
    """Years and months, the way the file states an age."""
    try:
        years, months, _ = patient.age_parts
    except Exception:                    # noqa: BLE001 — an export never raises
        return ""
    return f"{years}y {months}m"


def _patients_rows(start=None, end=None):
    for p in _patients_query(start, end).all():
        guardian = None
        try:
            guardian = p.primary_guardian
        except Exception:                # noqa: BLE001
            guardian = None
        family = getattr(getattr(p, "family", None), "family_name", "") or ""
        yield {
            "file_no": p.patient_number,
            "reference_no": p.reference_number or "",
            "name": p.full_name,
            "name_en": p.full_name_en or "",
            "gender": p.gender,
            "date_of_birth": _fmt_d(p.date_of_birth),
            "age": _age_text(p),
            "national_id": p.national_id or "",
            "blood_type": p.blood_type or "",
            "own_phone": p.own_phone or "",
            "contact_phone": p.contact_phone or "",
            "guardian_name": getattr(guardian, "full_name", "") or "",
            "guardian_relation": getattr(guardian, "relation", "") or "",
            "guardian_phone": getattr(guardian, "phone", "") or "",
            "family": family,
            "allergies": p.allergies or "",
            "chronic_diseases": p.chronic_diseases or "",
            "notes": p.notes or "",
            "whatsapp_opt_out": "1" if p.wa_opt_out else "0",
            "active": "1" if p.is_active else "0",
            "archived_at": _fmt_dt(p.archived_at),
            "archive_reason": p.archive_reason or "",
            "created_at": _fmt_dt(p.created_at),
            "updated_at": _fmt_dt(p.updated_at),
        }


def _invoices_query(start, end):
    from sqlalchemy.orm import joinedload

    from app.models import Invoice
    # The patient's name is on every row, so without this the export is one
    # query per invoice — which is fine at fifty and a minute of staring at a
    # blank tab at ten thousand.
    return _between(Invoice.query.options(joinedload(Invoice.patient))
                    .order_by(Invoice.id), Invoice.invoice_date, start, end)


def _invoices_rows(start=None, end=None):
    for inv in _invoices_query(start, end).all():
        yield {
            "invoice_no": inv.invoice_number, "date": _fmt_d(inv.invoice_date),
            "patient": inv.patient.full_name if inv.patient else "",
            "total": inv.total, "paid": round(inv.total - inv.balance, 2),
            "balance": inv.balance, "status": inv.status,
        }


def _appointments_query(start, end):
    from sqlalchemy.orm import joinedload

    from app.models import Appointment
    return _between(Appointment.query
                    .options(joinedload(Appointment.patient),
                             joinedload(Appointment.doctor))
                    .order_by(Appointment.id),
                    Appointment.appt_date, start, end)


def _appointments_rows(start=None, end=None):
    for a in _appointments_query(start, end).all():
        yield {
            "date": _fmt_d(a.appt_date),
            "time": a.appt_time.strftime("%H:%M") if a.appt_time else "",
            "patient": a.patient.full_name if a.patient else "",
            "doctor": a.doctor.full_name if a.doctor else "",
            "type": a.appt_type, "status": a.status,
            "reason": a.reason or "",
        }


def _vaccinations_query(start, end):
    from sqlalchemy.orm import joinedload

    from app.models import PatientVaccine
    q = (PatientVaccine.query
         .options(joinedload(PatientVaccine.patient),
                  joinedload(PatientVaccine.vaccine),
                  joinedload(PatientVaccine.brand))
         .filter(PatientVaccine.event_type == "given")
         .order_by(PatientVaccine.id))
    return _between(q, PatientVaccine.given_date, start, end)


def _vaccinations_rows(start=None, end=None):
    for pv in _vaccinations_query(start, end).all():
        yield {
            "patient": pv.patient.full_name if pv.patient else "",
            "vaccine": pv.vaccine.name_ar if pv.vaccine else "",
            "brand": pv.brand.name if pv.brand else "",
            "dose_number": pv.dose_number,
            "given_date": _fmt_d(pv.given_date),
            "lot_number": pv.lot_number or "",
            "given_outside": "1" if pv.given_outside else "0",
        }


def _visits_query(start, end):
    from sqlalchemy.orm import joinedload

    from app.models import Visit
    return _between(Visit.query
                    .options(joinedload(Visit.patient), joinedload(Visit.doctor))
                    .order_by(Visit.id), Visit.visit_date, start, end)


def _visits_rows(start=None, end=None):
    for v in _visits_query(start, end).all():
        yield {
            "date": _fmt_d(v.visit_date),
            "patient": v.patient.full_name if v.patient else "",
            "file_no": v.patient.patient_number if v.patient else "",
            "doctor": v.doctor.full_name if v.doctor else "",
            "status": v.status,
            # The note itself is not exported: a spreadsheet of clinical notes
            # is a patient file leaving the building in a form nothing tracks.
            "has_complaint": "1" if (v.chief_complaint or "").strip() else "0",
        }


def _payments_query(start, end):
    from sqlalchemy.orm import joinedload

    from app.models import Payment
    return _between(Payment.query
                    .options(joinedload(Payment.invoice))
                    .order_by(Payment.id),
                    Payment.paid_at, start, end, is_datetime=True)


def _payments_rows(start=None, end=None):
    for p in _payments_query(start, end).all():
        inv = p.invoice
        yield {
            "paid_at": _fmt_dt(p.paid_at),
            "invoice_no": inv.invoice_number if inv else "",
            "patient": inv.patient.full_name if inv and inv.patient else "",
            # A refund is money out. Exporting it with the same sign as money
            # in is how a day's takings come out too high in somebody's sheet.
            "amount": -p.amount if p.kind == "refund" else p.amount,
            "kind": p.kind, "method": p.method,
        }


def _expenses_query(start, end):
    from app.models import Expense
    return _between(Expense.query.order_by(Expense.id),
                    Expense.expense_date, start, end)


def _expenses_rows(start=None, end=None):
    for e in _expenses_query(start, end).all():
        yield {
            "date": _fmt_d(e.expense_date), "category": e.category,
            "description": e.description or "", "amount": e.amount,
            "recurring": "1" if e.is_recurring else "0",
        }


# Registry: kind -> (header order, row generator, query builder, date label).
# Adding a dataset is one entry, and the range comes with it for free.
DATASETS = {
    "patients": (PATIENT_COLUMNS,
                 _patients_rows, _patients_query, "created_at"),
    "visits": (["date", "patient", "file_no", "doctor", "status",
                "has_complaint"], _visits_rows, _visits_query, "visit_date"),
    "invoices": (["invoice_no", "date", "patient", "total", "paid", "balance",
                  "status"], _invoices_rows, _invoices_query, "invoice_date"),
    "payments": (["paid_at", "invoice_no", "patient", "amount", "kind",
                  "method"], _payments_rows, _payments_query, "paid_at"),
    "expenses": (["date", "category", "description", "amount", "recurring"],
                 _expenses_rows, _expenses_query, "expense_date"),
    "appointments": (["date", "time", "patient", "doctor", "type", "status",
                      "reason"], _appointments_rows, _appointments_query,
                     "appt_date"),
    "vaccinations": (["patient", "vaccine", "brand", "dose_number",
                      "given_date", "lot_number", "given_outside"],
                     _vaccinations_rows, _vaccinations_query, "given_date"),
}


def dataset_count(kind, start=None, end=None):
    """Rows this dataset would export for the range, or None if unknown.

    Counted through the same query the export runs. Counting it any other way
    is how a screen comes to promise one number and hand over a file with a
    different one in it.
    """
    entry = DATASETS.get(kind)
    if entry is None:
        return None
    # ``.count()`` and not ``with_entities(func.count())``: these queries carry
    # joinedload options, and swapping the entity out drops the FROM clause
    # with it — SQLAlchemy then emits a bare ``SELECT count(*)``, which is
    # valid SQL returning **1** for every dataset regardless of what is in it.
    # A count that is wrong without failing is the worst kind on this screen,
    # because the number is the only thing anybody checks it against.
    return entry[2](start, end).order_by(None).count()


def datasets_for(start=None, end=None):
    """What the screen shows: every dataset with its count *in the range*."""
    return [{"kind": kind, "count": dataset_count(kind, start, end),
             "date_field": entry[3]}
            for kind, entry in DATASETS.items()]


def export_response(kind, fmt="csv", start=None, end=None):
    """Build a downloadable Response for ``kind`` in ``csv`` or ``xlsx``.
    Returns ``None`` for an unknown dataset."""
    entry = DATASETS.get(kind)
    if entry is None:
        return None
    headers, rowgen = entry[0], entry[1]
    rows = list(rowgen(start, end))
    fname = _filename(kind, start, end)

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


def _filename(kind, start, end):
    """The range goes in the name. Four files called ``invoices_export`` in a
    downloads folder are four files nobody can tell apart a week later."""
    parts = [kind]
    if start or end:
        parts.append((start or date.min).isoformat())
        parts.append((end or date.today()).isoformat())
    else:
        parts.append("all")
    return "_".join(parts)
