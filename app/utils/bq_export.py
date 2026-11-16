"""Counts for BigQuery — aggregated, and shut until the hospital decides.

``REPORTS_PLAN.md`` ت-٥: «(اختياري لمجموعات الفروع) تصدير لـBigQuery — أرقام
مجمّعة بس (من غير أسماء ولا أرقام ملفات)، بقرار المستشفى وبعد الرأي القانوني».
And the same plan says why it is shut: health data is sensitive under Egypt's
data-protection law (151/2020), whose conditions on moving it abroad are a
legal question for the hospital, not a programming one.

So:

* **It is shut** until the administrator writes down the hospital's
  decision and the legal opinion it rests on (each a reference that can be
  checked), signed and dated. Withdrawing it shuts it again. Every export
  is in the activity log.
* **Only counts per day leave**: visits, new files, bookings by status,
  diagnoses by ICD chapter (the code's first letter — never the code), doses
  given per vaccine, money taken per method, and — where the wards are —
  admissions and discharges. No name, no file number, no date of birth, no
  free text.
* **Small numbers are held back.** A count of people under the clinic's
  threshold (five unless it says otherwise) leaves as ``null`` with
  ``suppressed = true``: in a small clinic «one child with this diagnosis
  on this day» can be a child somebody recognises. Money is not a count of
  people and is not held back.
* **The program sends nothing.** It hands the administrator one file to
  load, in the shape Google's own documentation describes (read from
  docs.cloud.google.com on 16 November 2026): newline-delimited JSON, «Each
  JSON object must be on a separate line in the file»; a JSON schema file,
  «a JSON array» of columns whose «name and type fields are required»; and
  ``bq load --source_format=NEWLINE_DELIMITED_JSON dataset.table ./data.json
  ./schema.json``. Moving data out of the building stays a person's act.
"""
import io
import json
import zipfile
from datetime import datetime, timedelta

from app.models import Setting

DECISION_KEY = "bqx_decision"
MIN_CELL_KEY = "bqx_min_cell"
SITE_KEY = "bqx_site"
DEFAULT_MIN_CELL = 5
MAX_DAYS = 366

#: The table's columns — BigQuery's own type names (INT64, NUMERIC, STRING,
#: DATE, BOOL) and modes; names are letters, digits and underscores.
SCHEMA = [
    {"name": "day", "type": "DATE", "mode": "REQUIRED",
     "description": "The clinic's own calendar day"},
    {"name": "site", "type": "STRING", "mode": "REQUIRED",
     "description": "The label the administrator gave this clinic"},
    {"name": "measure", "type": "STRING", "mode": "REQUIRED"},
    {"name": "dimension", "type": "STRING", "mode": "NULLABLE"},
    {"name": "value", "type": "NUMERIC", "mode": "NULLABLE",
     "description": "Null when held back"},
    {"name": "suppressed", "type": "BOOL", "mode": "REQUIRED"},
]

#: Counts of people (held back when small) and the one that is not.
PEOPLE_MEASURES = ("visits", "new_files", "bookings", "diagnoses",
                   "doses_given", "admissions", "discharges")
MONEY_MEASURES = ("money_taken",)


class ExportClosed(PermissionError):
    """The hospital's decision is not on record."""


# --------------------------------------------------------- the decision ---
def decision():
    raw = Setting.get(DECISION_KEY, "") or ""
    try:
        got = json.loads(raw) if raw else None
    except ValueError:
        got = None
    return got if isinstance(got, dict) and got.get("on") else None


def is_open():
    return decision() is not None


def decide(form, user, now=None):
    """Open it, with the two references the plan asks for."""
    hospital = (form.get("hospital_ref") or "").strip()[:200]
    legal = (form.get("legal_ref") or "").strip()[:200]
    if not hospital or not legal:
        raise ValueError("bqx.err_refs")
    Setting.set(DECISION_KEY, json.dumps({
        "on": True, "hospital_ref": hospital, "legal_ref": legal,
        "by": getattr(user, "id", None),
        "at": (now or datetime.utcnow()).isoformat(timespec="minutes"),
    }, ensure_ascii=False))


def withdraw():
    Setting.set(DECISION_KEY, "")


def min_cell():
    try:
        n = int(Setting.get(MIN_CELL_KEY, "") or DEFAULT_MIN_CELL)
    except ValueError:
        n = DEFAULT_MIN_CELL
    return max(n, 1)


def site():
    return (Setting.get(SITE_KEY, "") or "").strip() or "site"


# ------------------------------------------------------------ counting ---
def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _local_day(moment):
    from app.utils.clock import to_local

    local = to_local(moment) if moment else None
    return (local or moment).date() if moment else None


def counts(start, end):
    """``{(day, measure, dimension): value}`` for the clinic's days
    ``start``..``end``, both included."""
    from app.extensions import db
    from app.models import (Admission, Appointment, Diagnosis, Patient,
                            PatientVaccine, Payment, Vaccine, Visit)
    from app.utils.facility import module_enabled
    from app.utils.live import day_bounds

    lo, _ = day_bounds(start)
    _, hi = day_bounds(end)
    out = {}

    def add(day, measure, dim, value=1):
        if day is None or day < start or day > end:
            return
        key = (day, measure, dim)
        out[key] = out.get(key, 0) + value

    for (d, ch) in db.session.query(Visit.visit_date, Visit.channel).filter(
            Visit.visit_date >= start, Visit.visit_date <= end):
        add(d, "visits", ch or "clinic")
    for (at,) in db.session.query(Patient.created_at).filter(
            Patient.created_at >= lo, Patient.created_at <= hi):
        add(_local_day(at), "new_files", None)
    for (d, status) in db.session.query(Appointment.appt_date,
                                        Appointment.status).filter(
            Appointment.appt_date >= start, Appointment.appt_date <= end):
        add(d, "bookings", status)
    for (d, code) in (db.session.query(Visit.visit_date, Diagnosis.code)
                      .join(Visit, Diagnosis.visit_id == Visit.id)
                      .filter(Visit.visit_date >= start,
                              Visit.visit_date <= end)):
        # The ICD chapter's letter, never the code: «J» is a chapter, «J45.9»
        # on one day in a small clinic can be one child.
        chapter = (code or "").strip()[:1].upper()
        add(d, "diagnoses", chapter if chapter.isalpha() else "none")
    for (d, vcode) in (db.session.query(PatientVaccine.given_date, Vaccine.code)
                       .join(Vaccine, PatientVaccine.vaccine_id == Vaccine.id)
                       .filter(PatientVaccine.event_type == "given",
                               PatientVaccine.given_date >= start,
                               PatientVaccine.given_date <= end)):
        add(d, "doses_given", vcode)
    for (at, amount, method, kind) in db.session.query(
            Payment.paid_at, Payment.amount, Payment.method, Payment.kind
    ).filter(Payment.paid_at >= lo, Payment.paid_at <= hi):
        sign = -1 if (kind or "payment") == "refund" else 1
        add(_local_day(at), "money_taken", method or "cash",
            round(sign * float(amount or 0), 2))
    if module_enabled("beds"):
        for (at,) in db.session.query(Admission.admitted_at).filter(
                Admission.admitted_at >= lo, Admission.admitted_at <= hi):
            add(_local_day(at), "admissions", None)
        for (at,) in db.session.query(Admission.discharged_at).filter(
                Admission.discharged_at >= lo, Admission.discharged_at <= hi):
            add(_local_day(at), "discharges", None)
    return out


def rows(start, end):
    """The table's rows, small counts held back."""
    if not is_open():
        raise ExportClosed()
    if end < start or (end - start).days >= MAX_DAYS:
        raise ValueError("bqx.err_period")
    k = min_cell()
    label = site()
    out = []
    for (day, measure, dim), value in sorted(
            counts(start, end).items(),
            key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")):
        held = measure in PEOPLE_MEASURES and 0 < value < k
        out.append({"day": day.isoformat(), "site": label,
                    "measure": measure, "dimension": dim,
                    "value": None if held else value,
                    "suppressed": held})
    return out


def bundle(start, end):
    """One zip: ``data.json`` (one object per line), ``schema.json``, and a
    README with the ``bq load`` line."""
    data = rows(start, end)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("data.json", "".join(
            json.dumps(r, ensure_ascii=False) + "\n" for r in data))
        z.writestr("schema.json", json.dumps(SCHEMA, indent=2) + "\n")
        z.writestr("README.txt", README.format(
            site=site(), start=start.isoformat(), end=end.isoformat(),
            k=min_cell(), n=len(data)))
    return buf.getvalue(), len(data)


README = """PediaPro — aggregated counts for BigQuery
site: {site}   days: {start} .. {end}   rows: {n}

Only counts per day: no names, no file numbers, no dates of birth, no text.
Counts of people under {k} are held back (value null, suppressed true).

Load (Google BigQuery documentation, "Loading data from local files"):

  bq load \\
    --source_format=NEWLINE_DELIMITED_JSON \\
    mydataset.mytable \\
    ./data.json \\
    ./schema.json

Moving these numbers out of the building rests on the hospital's decision
and its legal opinion, recorded in the program by the administrator.
"""
