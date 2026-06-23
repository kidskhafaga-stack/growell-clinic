"""Vaccination scheduling engine and schedule-data seeding.

Computes each patient's vaccination plan (due dates and visual status) from the
chosen brand's dose schedule, suggests the next due dose, and locks a vaccine to
a single brand once any dose has been given (no mixing brands).
"""
import calendar
import json
import os
from datetime import date

from app.extensions import db
from app.models import (
    PatientVaccine,
    Vaccine,
    VaccineBrand,
    VaccineBrandDose,
)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "egypt_vaccines.json")

# How soon before the due date a dose is flagged as "due now".
DUE_WINDOW_DAYS = 30


def add_months(d, months):
    """Return ``d`` shifted by ``months`` (clamping day to month length)."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def age_label(months, lang="ar"):
    if months == 0:
        return "عند الميلاد" if lang == "ar" else "At birth"
    if months < 12:
        return (f"{months} شهر" if lang == "ar" else f"{months} mo")
    years = months // 12
    rem = months % 12
    if lang == "ar":
        return f"{years} سنة" + (f" {rem} شهر" if rem else "")
    return f"{years}y" + (f" {rem}m" if rem else "")


# ----------------------------------------------------------- seeding -------
def seed_vaccines():
    """Idempotently load the bundled vaccine catalogue into the database."""
    with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
        data = json.load(fh)

    created = 0
    for order, v in enumerate(data["vaccines"]):
        vaccine = Vaccine.query.filter_by(code=v["code"]).first()
        if vaccine is None:
            vaccine = Vaccine(
                code=v["code"], name_ar=v["name_ar"], name_en=v.get("name_en"),
                is_mandatory=v.get("mandatory", True), sort_order=order,
                route=v.get("route"),
            )
            db.session.add(vaccine)
            db.session.flush()
            created += 1
        elif v.get("route") and not vaccine.route:
            vaccine.route = v["route"]  # backfill route on existing entries
        for b in v["brands"]:
            if any(br.name == b["name"] for br in vaccine.brands):
                continue
            brand = VaccineBrand(
                vaccine_id=vaccine.id, name=b["name"], name_en=b.get("name_en"),
                manufacturer=b.get("manufacturer"), price=b.get("price"),
                is_default=b.get("default", False),
            )
            db.session.add(brand)
            db.session.flush()
            for i, age in enumerate(b["doses_age_months"], start=1):
                db.session.add(VaccineBrandDose(brand_id=brand.id, dose_number=i, age_months=age))
    db.session.commit()
    return created


# -------------------------------------------------------- computation ------
def chosen_brand(patient_id, vaccine):
    """The brand locked for this patient/vaccine, or the default brand.

    Only an actually-given dose locks the brand; a refused/delayed event does
    not commit the patient to a brand.
    """
    pv = (
        PatientVaccine.query.filter_by(patient_id=patient_id, vaccine_id=vaccine.id,
                                       event_type="given")
        .order_by(PatientVaccine.dose_number)
        .first()
    )
    if pv:
        return pv.brand, True  # locked
    return vaccine.default_brand, False


def _status(due_date, given, today):
    if given:
        return "done"
    if due_date is None:
        return "upcoming"
    if due_date < today:
        return "overdue"
    if (due_date - today).days <= DUE_WINDOW_DAYS:
        return "due"
    return "upcoming"


def patient_plan(patient, lang="ar"):
    """Build the full vaccination plan for a patient.

    Returns a list of per-vaccine dicts with the chosen brand and a list of
    dose dicts {dose_number, age_months, age_label, due_date, given_date,
    lot_number, status}.
    """
    today = date.today()
    dob = patient.date_of_birth
    given_index = {}
    events_index = {}   # (vaccine_id, dose_number) -> refused/delayed event
    for pv in PatientVaccine.query.filter_by(patient_id=patient.id).all():
        if (pv.event_type or "given") == "given":
            given_index[(pv.vaccine_id, pv.dose_number)] = pv
        else:
            events_index[(pv.vaccine_id, pv.dose_number)] = pv

    plan = []
    for vaccine in Vaccine.query.order_by(Vaccine.sort_order).all():
        brand, locked = chosen_brand(patient.id, vaccine)
        if brand is None:
            continue
        doses = []
        for d in brand.doses:
            pv = given_index.get((vaccine.id, d.dose_number))
            ev = events_index.get((vaccine.id, d.dose_number))
            due = add_months(dob, d.age_months) if dob else None
            doses.append({
                "dose_number": d.dose_number,
                "age_months": d.age_months,
                "age_label": age_label(d.age_months, lang),
                "due_date": due.isoformat() if due else None,
                "given_date": pv.given_date.isoformat() if pv else None,
                "lot_number": pv.lot_number if pv else None,
                "status": _status(due, pv is not None, today),
                "event_type": ev.event_type if (ev and not pv) else None,
                "event_reason": ev.refusal_reason if (ev and not pv) else None,
            })
        plan.append({
            "vaccine": vaccine, "brand": brand, "locked": locked,
            "doses": doses,
            "done": sum(1 for x in doses if x["status"] == "done"),
            "total": len(doses),
        })
    return plan


def plan_summary(plan):
    """Aggregate counts across a plan for the visual status cards."""
    s = {"done": 0, "due": 0, "overdue": 0, "upcoming": 0, "total": 0}
    for v in plan:
        for d in v["doses"]:
            s[d["status"]] += 1
            s["total"] += 1
    return s


def next_due_dose(plan):
    """Return the most urgent not-yet-given dose (overdue first, then due)."""
    candidates = []
    for v in plan:
        for d in v["doses"]:
            if d["status"] in ("overdue", "due"):
                candidates.append((d["due_date"], v["vaccine"], v["brand"], d))
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0] or "")
    return candidates[0]


def next_undone_dose_number(patient_id, vaccine, brand):
    """The next dose number to administer for a vaccine/brand."""
    given = {
        pv.dose_number
        for pv in PatientVaccine.query.filter_by(
            patient_id=patient_id, vaccine_id=vaccine.id, event_type="given"
        ).all()
    }
    for d in brand.doses:
        if d.dose_number not in given:
            return d.dose_number
    return None
