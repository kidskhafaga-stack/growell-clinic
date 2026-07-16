"""Vaccination scheduling engine and schedule-data seeding.

Computes each patient's vaccination plan (due dates and visual status) from the
chosen brand's dose schedule, suggests the next due dose, and locks a vaccine to
a single brand once any dose has been given (no mixing brands).
"""
import calendar
import json
import os
from datetime import date, timedelta

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

# A seasonal vaccine (e.g. flu) taken here is due again after about a year.
SEASONAL_RECALL_DAYS = 330

# Two injectable/intranasal live vaccines not given the same day must be at
# least this far apart (ACIP). Oral live vaccines (rotavirus, OPV) are exempt.
LIVE_SPACING_DAYS = 28

# Well-established vaccine platform per code — factual, not clinical guidance.
# Used only to prefill the catalogue's "type" field (editable afterwards).
_VACCINE_TYPE = {
    "BCG": "live", "HBV0": "recombinant", "OPV": "live", "IPV": "inactivated",
    "PENTA": "combination", "DTP_B": "combination", "MEASLES": "live",
    "MMR": "live", "ROTA": "live", "PCV": "conjugate", "VARICELLA": "live",
    "HAV": "inactivated", "FLU": "inactivated", "HEXA": "combination",
    "PENTAXIM": "combination", "MMRV": "live", "MENACWY": "conjugate",
    "MENB": "recombinant", "HPV": "recombinant", "TYPHOID": "conjugate",
    "RABIES": "inactivated", "YELLOWFEVER": "live", "CHOLERA": "inactivated",
}


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
        # Factual prefill: vaccine platform + which body to verify against. The
        # doctor reviews/edits these; no clinical numbers are invented.
        vtype = _VACCINE_TYPE.get(v["code"])
        vref = ("برنامج التطعيم القومي المصري (EPI) — للمراجعة"
                if v.get("mandatory", True)
                else "النشرة الدوائية للمُصنّع + ACIP/WHO — للمراجعة")
        if vaccine is None:
            vaccine = Vaccine(
                code=v["code"], name_ar=v["name_ar"], name_en=v.get("name_en"),
                is_mandatory=v.get("mandatory", True), sort_order=order,
                route=v.get("route"), on_demand=v.get("on_demand", False),
                is_seasonal=v.get("seasonal", False),
                vaccine_type=vtype, reference=vref,
            )
            db.session.add(vaccine)
            db.session.flush()
            created += 1
        else:
            if v.get("route") and not vaccine.route:
                vaccine.route = v["route"]  # backfill route on existing entries
            if v.get("on_demand") and not vaccine.on_demand:
                vaccine.on_demand = True    # backfill situational flag
            if v.get("seasonal") and not vaccine.is_seasonal:
                vaccine.is_seasonal = True  # backfill seasonal flag
            if vtype and not vaccine.vaccine_type:
                vaccine.vaccine_type = vtype
            if not vaccine.reference:
                vaccine.reference = vref
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

    all_vaccines = Vaccine.query.order_by(Vaccine.sort_order).all()
    # Injectable/intranasal live vaccines (oral live are exempt) and the latest
    # date each was given — used for the 28-day live-vaccine spacing rule.
    live_ids = {v.id for v in all_vaccines
                if (v.vaccine_type == "live" and (v.route or "") != "oral")}
    live_given = {}
    for (vid, _dn), gpv in given_index.items():
        if vid in live_ids and gpv.given_date:
            cur = live_given.get(vid)
            if cur is None or gpv.given_date > cur:
                live_given[vid] = gpv.given_date

    plan = []
    for vaccine in all_vaccines:
        brand, locked = chosen_brand(patient.id, vaccine)
        if brand is None:
            continue
        # Catch-up: a not-yet-given dose can't fall due before the minimum gap
        # after the previous dose. We chain forward from each dose's effective
        # date (actual date if given, else its projected due date) so a child who
        # started late gets correctly-spaced due dates — not the raw age dates.
        min_iv = vaccine.min_interval_days
        # Live-vaccine spacing: keep 28 days from another live parenteral vaccine
        # the child already got (can't co-administer with a past dose anymore).
        earliest_live = None
        if vaccine.id in live_ids:
            others = [dt for vid2, dt in live_given.items() if vid2 != vaccine.id]
            if others:
                earliest_live = max(others) + timedelta(days=LIVE_SPACING_DAYS)
        prev_date = None
        doses = []
        for d in brand.doses:
            pv = given_index.get((vaccine.id, d.dose_number))
            ev = events_index.get((vaccine.id, d.dose_number))
            due = add_months(dob, d.age_months) if dob else None
            if pv is not None:
                effective = pv.given_date
            else:
                if due and prev_date and min_iv:
                    earliest = prev_date + timedelta(days=min_iv)
                    if earliest > due:
                        due = earliest
                if due and earliest_live and earliest_live > due:
                    due = earliest_live
                effective = due
            prev_date = effective
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


def seasonal_recall(patient, vaccine, today=None):
    """For a seasonal vaccine the child already took here, whether a new annual
    dose is due now. Returns ``(due, last_given_date, next_dose_number)`` — due
    once ~11 months have passed since the last dose, regardless of the fixed
    schedule (each season is a fresh dose).
    """
    today = today or date.today()
    given = (PatientVaccine.query
             .filter_by(patient_id=patient.id, vaccine_id=vaccine.id, event_type="given")
             .all())
    if not given:
        return False, None, None
    last = max(g.given_date for g in given)
    nxt = max(g.dose_number for g in given) + 1
    return (today - last).days >= SEASONAL_RECALL_DAYS, last, nxt


def patient_due_reminders(patient, lang="ar", today=None):
    """Everything worth reminding this patient about, limited to courses started
    *with us* (≥1 dose given) — we never chase a vaccine we never gave:

      * a late/due next dose of a started course (incl. boosters), and
      * a seasonal vaccine's annual recall once ~11 months have passed.

    Returns a list of dicts ``{vaccine, brand, dose_number, due_date, status}``
    sorted most-urgent first (``status`` is overdue / due / seasonal).
    """
    today = today or date.today()
    plan = patient_plan(patient, lang)
    out = []
    for v in plan:
        vac, brand = v["vaccine"], v["brand"]
        done = [d for d in v["doses"] if d["status"] == "done"]
        if not done:                       # course never started here
            continue
        if vac.is_seasonal:
            last_iso = max((d["given_date"] for d in done if d["given_date"]), default=None)
            if last_iso and (today - date.fromisoformat(last_iso)).days >= SEASONAL_RECALL_DAYS:
                out.append({"vaccine": vac, "brand": brand,
                            "dose_number": max(d["dose_number"] for d in done) + 1,
                            "due_date": None, "status": "seasonal"})
            continue
        nxt = next((d for d in v["doses"] if d["status"] in ("overdue", "due")), None)
        if nxt:
            out.append({"vaccine": vac, "brand": brand, "dose_number": nxt["dose_number"],
                        "due_date": nxt["due_date"], "status": nxt["status"]})
    out.sort(key=lambda r: (0 if r["status"] == "overdue" else 1, r["due_date"] or ""))
    return out


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


def administer_dose(patient, vaccine, *, brand=None, dose_number=None, doctor_id=None,
                    given_date=None, lot_number=None, given_outside=False,
                    adverse_events=None, notes=None):
    """Record a *given* dose with first-expiry-first-out stock deduction.

    Shared by the vaccinations module and in-visit administration so the lock,
    double-record guard, stock deduction and doctor credit stay identical.
    Does **not** commit — the caller owns the transaction. Returns
    ``(patient_vaccine, error_key)`` where ``error_key`` is one of
    ``None`` / ``"no_brand"`` / ``"all_done"`` / ``"dose_exists"``.
    """
    # Resolve the brand. An explicitly requested brand is always honoured — the
    # doctor may deliberately mix brands across doses (e.g. PCV13 primary +
    # PPSV23 booster); callers warn on a mix. With no request, a non-seasonal
    # course keeps its locked brand; seasonal vaccines and first doses use the
    # default.
    locked_brand, is_locked = chosen_brand(patient.id, vaccine)
    if brand is None:
        brand = locked_brand if (is_locked and not vaccine.is_seasonal) else vaccine.default_brand
    if brand is None:
        return None, "no_brand"

    if dose_number is None:
        if vaccine.is_seasonal:
            last = (PatientVaccine.query
                    .filter_by(patient_id=patient.id, vaccine_id=vaccine.id, event_type="given")
                    .order_by(PatientVaccine.dose_number.desc()).first())
            dose_number = (last.dose_number + 1) if last else 1
        else:
            dose_number = next_undone_dose_number(patient.id, vaccine, brand)
    if dose_number is None:
        return None, "all_done"

    if PatientVaccine.query.filter_by(
            patient_id=patient.id, vaccine_id=vaccine.id,
            dose_number=dose_number, event_type="given").first():
        return None, "dose_exists"

    # A prior refusal/delay for this dose no longer applies once it's given.
    PatientVaccine.query.filter(
        PatientVaccine.patient_id == patient.id,
        PatientVaccine.vaccine_id == vaccine.id,
        PatientVaccine.dose_number == dose_number,
        PatientVaccine.event_type != "given",
    ).delete(synchronize_session=False)

    pv = PatientVaccine(
        patient_id=patient.id, vaccine_id=vaccine.id, brand_id=brand.id,
        dose_number=dose_number, given_date=given_date or date.today(),
        doctor_id=doctor_id, lot_number=lot_number, event_type="given",
        given_outside=given_outside, adverse_events=adverse_events, notes=notes,
    )
    db.session.add(pv)

    # Deduct one patient-dose from the soonest-expiry batch for clinic-provided
    # (optional) vaccines. Doses given elsewhere never touch stock.
    if not vaccine.is_mandatory and not given_outside:
        batches = brand.available_batches
        if batches:
            batch = batches[0]
            batch.qty_used = (batch.qty_used or 0) + 1
            pv.inventory_id = batch.id
            if not pv.lot_number:
                pv.lot_number = batch.lot_number
    return pv, brand


def visit_vaccine_panel(patient, lang="ar"):
    """Vaccine snapshot for the visit tab, framed as *what can I give now* —
    no "overdue" alarms (we can't know what was given elsewhere).

    Returns dict with:
      * ``received``  — vaccines the child already has doses of (neutral history)
      * ``give_now``  — optional, age-appropriate vaccines in stock (administer)
      * ``out_of_stock`` — optional, age-appropriate but no stock (schedule / PO)
    Mandatory (EPI) and on-demand (rabies/travel) vaccines are excluded from the
    suggestions; the doctor adds those deliberately.
    """
    today = date.today()
    plan = patient_plan(patient, lang)
    received, give_now, out_of_stock = [], [], []
    for v in plan:
        vac, brand = v["vaccine"], v["brand"]
        given = [d for d in v["doses"] if d["status"] == "done"]
        if given:
            # Upcoming doses (with their expected dates) so the doctor sees
            # the whole course at a glance; seasonal courses recur yearly, so
            # their "next" is a projected annual recall instead.
            upcoming = [d for d in v["doses"] if d["status"] != "done"]
            next_seasonal = None
            if vac.is_seasonal and not upcoming:
                last_iso = max((d["given_date"] for d in given
                                if d["given_date"]), default=None)
                if last_iso:
                    next_seasonal = (date.fromisoformat(last_iso)
                                     + timedelta(days=SEASONAL_RECALL_DAYS)).isoformat()
            received.append({"vaccine": vac, "brand": brand, "doses": given,
                             "upcoming": upcoming, "total": v["total"],
                             "seasonal": vac.is_seasonal,
                             "next_seasonal": next_seasonal})
        if vac.is_mandatory or vac.on_demand:
            continue
        # Seasonal vaccines taken here recur every year instead of following the
        # fixed schedule — once ~11 months pass, offer the next yearly dose.
        if vac.is_seasonal and given:
            last_iso = max((d["given_date"] for d in given if d["given_date"]), default=None)
            if (last_iso and brand is not None
                    and (today - date.fromisoformat(last_iso)).days >= SEASONAL_RECALL_DAYS):
                batch = brand.available_batches[0] if brand.available_batches else None
                entry = {"vaccine": vac, "brand": brand,
                         "dose": {"dose_number": max(d["dose_number"] for d in given) + 1,
                                  "due_date": None, "given_date": None,
                                  "status": "due", "age_label": ""},
                         "stock": brand.stock, "batch": batch, "price": brand.price,
                         "started": True, "overdue": False, "seasonal": True}
                (give_now if brand.stock > 0 else out_of_stock).append(entry)
            continue
        # Offer the first not-yet-given dose that's age-appropriate now
        # (its recommended age has arrived / is within the due window).
        nxt = next((d for d in v["doses"] if d["status"] in ("overdue", "due")), None)
        if not nxt or brand is None:
            continue
        batch = brand.available_batches[0] if brand.available_batches else None
        entry = {"vaccine": vac, "brand": brand, "dose": nxt,
                 "stock": brand.stock, "batch": batch, "price": brand.price,
                 # Other in-stock brands of the same vaccine, so the doctor can
                 # deliberately switch type (e.g. a different PCV for the booster).
                 "in_stock_brands": [b for b in vac.active_brands if b.stock > 0],
                 # A course we started here can be genuinely "late"; one we never
                 # gave is only an offer (we don't know what was taken elsewhere).
                 "started": len(given) > 0,
                 "overdue": len(given) > 0 and nxt["status"] == "overdue",
                 "seasonal": False}
        (give_now if brand.stock > 0 else out_of_stock).append(entry)
    return {"received": received, "give_now": give_now, "out_of_stock": out_of_stock}
