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
    VaccineScheduleDose,
    VaccineScheduleTemplate,
)
from app.utils.dose_labels import is_booster
from app.utils.clock import local_today

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
    "DT": "toxoid",
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
def _catalogue_load_flags():
    """Which parts of the bundled catalogue the clinic wants auto-loaded:
    the government/EPI (mandatory) set and/or the optional set. Both default ON.
    Reading is best-effort — before the settings table exists we load both."""
    try:
        from app.models import Setting
        gov = Setting.get("load_gov_vaccines", "1") != "0"
        optional = Setting.get("load_optional_vaccines", "1") != "0"
    except Exception:  # noqa: BLE001 - settings table not ready yet
        gov = optional = True
    return gov, optional


def seed_vaccines():
    """Idempotently load the bundled vaccine catalogue into the database.

    Honours the clinic's catalogue toggles: a clinic that doesn't run the
    national programme can turn the government (EPI) set off and keep only the
    optional vaccines (or vice-versa). Loading is additive/fill-only and never
    deletes what's already there — turning a set off just stops auto-loading it.
    """
    gov_on, optional_on = _catalogue_load_flags()
    with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
        data = json.load(fh)

    created = 0
    for order, v in enumerate(data["vaccines"]):
        # Skip a set the clinic chose not to load (unless the vaccine already
        # exists — then we still refresh its schedule conditions below).
        is_gov = v.get("mandatory", True)
        wanted = gov_on if is_gov else optional_on
        vaccine = Vaccine.query.filter_by(code=v["code"]).first()
        if vaccine is None and not wanted:
            continue
        # Factual prefill: vaccine platform + which body to verify against. The
        # doctor reviews/edits these; no clinical numbers are invented.
        vtype = _VACCINE_TYPE.get(v["code"])
        vref = ("برنامج التطعيم القومي المصري (EPI) — للمراجعة"
                if v.get("mandatory", True)
                else "النشرة الدوائية للمُصنّع + ACIP/WHO — للمراجعة")
        # Standard WHO/EPI + manufacturer schedule conditions bundled with the
        # catalogue (min interval, upper age, booster, catch-up rules). All
        # "for review" — the doctor confirms/edits; we never overwrite edits.
        cu = v.get("catch_up_ar")
        cu_ref = v.get("reference_ar") or vref
        if vaccine is None:
            vaccine = Vaccine(
                code=v["code"], name_ar=v["name_ar"], name_en=v.get("name_en"),
                is_mandatory=v.get("mandatory", True), sort_order=order,
                route=v.get("route"), on_demand=v.get("on_demand", False),
                is_seasonal=v.get("seasonal", False),
                vaccine_type=vtype, reference=cu_ref,
                min_interval_days=v.get("min_interval_days"),
                max_age_months=v.get("max_age_months"),
                booster_required=v.get("booster", False),
                catch_up_notes=cu,
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
                vaccine.reference = cu_ref
            # Fill schedule conditions only where the clinic hasn't set them.
            if cu and not vaccine.catch_up_notes:
                vaccine.catch_up_notes = cu
            if v.get("min_interval_days") and vaccine.min_interval_days is None:
                vaccine.min_interval_days = v["min_interval_days"]
            if v.get("max_age_months") and vaccine.max_age_months is None:
                vaccine.max_age_months = v["max_age_months"]
            if v.get("booster") and not vaccine.booster_required:
                vaccine.booster_required = True
        # Which dose of this course is the booster rather than a primary dose.
        # Stated in the catalogue rather than guessed, because the guess is
        # wrong where it matters: PCV's fourth dose falls six months after the
        # third, and the "a year later, so it is a booster" rule — right for
        # the 18-month OPV — misses it. "3+1" is what the schedule says, and a
        # course that is one *booster* short is a diary note, not a child who
        # is behind.
        booster_from = v.get("booster_from_dose")
        for b in v["brands"]:
            existing = next((br for br in vaccine.brands if br.name == b["name"]), None)
            if existing is not None:
                # Backfill the trade-name-specific catch-up onto existing rows,
                # only when the clinic hasn't set one (never clobber edits).
                if b.get("catch_up_ar") and not existing.catch_up_notes:
                    existing.catch_up_notes = b["catch_up_ar"]
                if booster_from:
                    for row in existing.doses:
                        if row.dose_number >= booster_from and not row.is_booster:
                            row.is_booster = True
                continue
            brand = VaccineBrand(
                vaccine_id=vaccine.id, name=b["name"], name_en=b.get("name_en"),
                manufacturer=b.get("manufacturer"), price=b.get("price"),
                is_default=b.get("default", False),
                catch_up_notes=b.get("catch_up_ar"),
            )
            db.session.add(brand)
            db.session.flush()
            for i, age in enumerate(b["doses_age_months"], start=1):
                db.session.add(VaccineBrandDose(
                    brand_id=brand.id, dose_number=i, age_months=age,
                    is_booster=bool(booster_from and i >= booster_from)))
    db.session.commit()
    return created


# WHO routine positions (recommended age in months, min interval days) for the
# optional vaccines where WHO's routine schedule is well established and differs
# from a common manufacturer leaflet. Authored *for the doctor to review* — the
# seed only fills a blank WHO schedule and never overwrites the doctor's edits.
_WHO_ROUTINE = {
    "ROTA": [(2, None), (4, 28)],                 # 2 doses from 6 weeks, ≥4w apart
    "PCV": [(2, None), (4, 28), (9, None)],       # WHO 2p+1
    "MEASLES": [(9, None), (15, None)],
    "MMR": [(12, None), (15, 28)],
    "HAV": [(12, None)],                          # WHO: single dose suffices
    "VARICELLA": [(12, None), (15, 84)],
    "HPV": [(108, None), (114, 180)],             # 2 doses 9–14y, ~6 months apart
    "FLU": [(6, None)],
}

# Minimum inter-dose interval (days) used to turn a routine schedule into a
# catch-up skeleton (interval-driven rather than age-driven). Conservative
# 4-week default for most; the doctor edits per current guidance.
_CATCH_UP_MIN_INTERVAL = 28


def _seed_template(vaccine, *, code, source, label, doses, is_catch_up=False,
                   sort_order=0):
    """Create one seeded schedule template if a seeded one of the same
    (code, source) isn't already there. ``doses`` is a list of
    ``(recommended_age_months, min_interval_days)`` tuples. Returns 1 if a new
    template was created, else 0. Never touches doctor-edited templates."""
    existing = VaccineScheduleTemplate.query.filter_by(
        vaccine_id=vaccine.id, code=code, source=source).first()
    if existing is not None:
        return 0
    tpl = VaccineScheduleTemplate(
        vaccine_id=vaccine.id, code=code, source=source, label=label,
        is_catch_up=is_catch_up, is_seeded=True, sort_order=sort_order,
    )
    db.session.add(tpl)
    db.session.flush()
    for i, (age, min_iv) in enumerate(doses, start=1):
        db.session.add(VaccineScheduleDose(
            template_id=tpl.id, dose_number=i,
            recommended_age_months=age, min_interval_days=min_iv,
        ))
    return 1


def seed_vaccine_schedules():
    """Auto-seed routine + catch-up schedule templates so every vaccine ships
    with an editable schedule out of the box, each tagged by its *source*:

      * national (EPI)  — for mandatory vaccines, from the government schedule
      * manufacturer    — for optional vaccines, from the default brand's leaflet
      * who             — WHO routine, for optional vaccines (curated where known)
      * a catch-up skeleton (interval-driven) for multi-dose optional vaccines

    Idempotent: only creates a template when no template of the same
    (code, source) exists, so a doctor's edits are never overwritten.
    """
    created = 0
    for vaccine in Vaccine.query.order_by(Vaccine.sort_order).all():
        brand = vaccine.default_brand
        if brand is None or not brand.doses:
            continue
        ages = [d.age_months for d in brand.doses]
        min_iv = vaccine.min_interval_days

        if vaccine.is_mandatory:
            # National EPI schedule (routine), age-driven.
            created += _seed_template(
                vaccine, code="EPI", source="national",
                label="برنامج التطعيم القومي المصري — للمراجعة",
                doses=[(a, None) for a in ages], sort_order=0)
            continue

        # Optional vaccine: manufacturer routine (from the default brand leaflet).
        created += _seed_template(
            vaccine, code="STD", source="manufacturer",
            label="جدول الشركة المنتجة — للمراجعة",
            doses=[(a, (min_iv if i else None)) for i, a in enumerate(ages)],
            sort_order=0)

        # WHO routine, where a well-established position exists; else skip (the
        # doctor can add a WHO source with the built-in editor + selector).
        who = _WHO_ROUTINE.get(vaccine.code)
        if who:
            created += _seed_template(
                vaccine, code="WHO", source="who",
                label="توصية منظمة الصحة العالمية — للمراجعة",
                doses=who, sort_order=1)

        # Catch-up skeleton for multi-dose, non-seasonal, non-on-demand vaccines.
        if len(ages) > 1 and not vaccine.is_seasonal and not vaccine.on_demand:
            cu = [(ages[0], None)] + [
                (a, (min_iv or _CATCH_UP_MIN_INTERVAL)) for a in ages[1:]]
            created += _seed_template(
                vaccine, code="CATCHUP", source="manufacturer",
                label="جدول تعويضي (Catch-up) — للمراجعة",
                doses=cu, is_catch_up=True, sort_order=2)

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


# A dose that could be given today, whoever started the course. Named once
# because it is asked in four places, and the fourth is always the one that
# gets forgotten: adding `suggested` broke the visit panel's offer list —
# an unvaccinated child was suddenly offered nothing at all — while every
# other screen looked fine.
GIVEABLE = ("overdue", "due", "suggested")


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
    today = local_today()
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
        #
        # The fallback is load-bearing, not tidiness. `min_interval_days` is
        # NULL on nearly every vaccine — it is only filled in when the source
        # schedule happened to state it — so a guard that required it meant the
        # chaining below **never ran at all**: a child whose first dose came a
        # year late got a second dose "due" months before the first one
        # happened, and the whole schedule read as overdue. 28 days is the same
        # floor the catch-up seeder already uses, so the program was carrying
        # the number and not applying it where it mattered most.
        min_iv = vaccine.min_interval_days or _CATCH_UP_MIN_INTERVAL
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
            planned = (ev.given_date if ev is not None and pv is None
                       and ev.event_type == "planned" and ev.given_date else None)
            if pv is not None:
                effective = pv.given_date
            else:
                if due and prev_date:
                    earliest = prev_date + timedelta(days=min_iv)
                    if earliest > due:
                        due = earliest
                if due and earliest_live and earliest_live > due:
                    due = earliest_live
                # The doctor's explicit appointment for this dose wins over
                # the computed schedule (their patient, their timing).
                if planned:
                    due = planned
                effective = due
            prev_date = effective
            doses.append({
                "dose_number": d.dose_number,
                "age_months": d.age_months,
                "age_label": age_label(d.age_months, lang),
                # Carried so the card can say "the booster is what is left"
                # rather than "3/4" and leave the reader to work out which of
                # the two very different jobs that is.
                "booster": is_booster(brand, d.dose_number),
                "due_date": due.isoformat() if due else None,
                "given_date": pv.given_date.isoformat() if pv else None,
                "lot_number": pv.lot_number if pv else None,
                # Who gave it, and whether it was given here at all — a
                # certificate row saying only "given" leaves the family to
                # remember which clinic, which is what the paper is for.
                "doctor": (pv.doctor.display_name(lang)
                           if pv is not None and pv.doctor else None),
                "outside": bool(pv.given_outside) if pv is not None else False,
                "outside_place": (pv.outside_place if pv is not None else None),
                # The record itself, so the file can offer to correct it — and
                # whether its number was *inferred* from an import rather than
                # observed, which is the set most likely to need correcting.
                "pv_id": pv.id if pv is not None else None,
                "imported": bool(getattr(pv, "import_batch_id", None))
                if pv is not None else False,
                "status": _status(due, pv is not None, today),
                "planned": planned is not None,
                "event_type": (ev.event_type if (ev and not pv
                               and ev.event_type != "planned") else None),
                "event_reason": (ev.refusal_reason if (ev and not pv
                                 and ev.event_type != "planned") else None),
            })
        # Has this clinic actually begun this course? Everything about
        # "late" hangs on the answer.
        #
        # The catalogue holds every vaccine the program knows, and a due date
        # projected from a birthday exists for all of them — so a healthy
        # two-year-old whose family uses the government unit for the national
        # schedule read as *overdue on 41 doses*. That number frightens a
        # parent, says nothing clinically, and is not this clinic's to make:
        # nobody here promised those doses, and "late" is a broken promise.
        #
        # A course nobody started is a **suggestion by age**, which is a
        # different sentence and belongs in a different column. Once a single
        # dose is given here, the course is ours and the next dose really can
        # be late.
        started = any(x["status"] == "done" for x in doses)
        if not started:
            for x in doses:
                if x["status"] in ("overdue", "due"):
                    x["status"] = "suggested"
        plan.append({
            "vaccine": vaccine, "brand": brand, "locked": locked,
            "doses": doses, "started": started,
            "done": sum(1 for x in doses if x["status"] == "done"),
            "total": len(doses),
        })
    return plan


# The four shelves a vaccination plan actually falls onto, in the order a
# doctor works through them. Order matters: it is the whole feature.
PLAN_GROUPS = ("started", "ready", "complete", "later")


def group_plan(plan, today=None):
    """Sort a plan onto four shelves without changing a thing in it.

    Reported: *"the ordering of the vaccine suggestions — courses that have
    started in one list and ones that never started in another"*, with the
    explicit note that this is **not a change to the rule**. So this takes the
    plan :func:`patient_plan` already built and only decides which heading each
    vaccine sits under. Nothing here computes a due date, a status or an
    interval; every one of those is read, never derived.

    That restraint is the point. A fifteen-vaccine wall of identical cards is
    unreadable not because any card is wrong but because they all look equally
    urgent, and the one thing a doctor needs first — *the courses this child is
    already in the middle of* — is somewhere down the page next to a vaccine
    due in four years.

      * ``started``  — began and not finished. The next dose is owed.
      * ``ready``    — never began and the child is old enough now.
      * ``complete`` — every dose given. Kept, because "did they have it?" is
                       a question, but collapsed: it is history, not a task.
      * ``later``    — never began and not yet due. Also collapsed, for the
                       same reason in the other direction.

    Returns ``[(key, items), …]`` in :data:`PLAN_GROUPS` order, skipping empty
    shelves so a headed section is never a heading over nothing.
    """
    today = today or local_today()
    shelves = {key: [] for key in PLAN_GROUPS}
    for item in plan:
        doses = item.get("doses") or []
        given = [d for d in doses if d["status"] == "done"]
        if given:
            shelves["started" if len(given) < len(doses) else "complete"].append(item)
        elif any(d["status"] in GIVEABLE for d in doses):
            shelves["ready"].append(item)
        else:
            shelves["later"].append(item)
    return [(key, shelves[key]) for key in PLAN_GROUPS if shelves[key]]


# Which shelves open on arrival. History and not-yet-due are both true and
# both noise at the moment somebody is deciding what to give today.
OPEN_GROUPS = {"started", "ready"}


def certificate_cards(plan):
    """The certificate as a card per vaccine, not one long list of doses.

    Reported for the certificate: *"a card per vaccine, dose rows with the date
    and the doctor and the record, a progress bar (1/2, 4/4), and counters at
    the top — years, types, total."*

    The flat table it replaced was correct and unreadable: forty rows in date
    order, so the three doses of one vaccine sat pages apart and the only way
    to answer "has this child finished the pneumococcal course?" was to read
    the whole page and count. The card carries its own ``2/3``, which is the
    entire question in two characters.

    Only vaccines with at least one given dose appear — a certificate lists
    what a child *had*. What they are due is the optional schedule table, and
    conflating the two is how a certificate comes to imply a child was given
    something they were not.
    """
    cards = []
    for item in plan:
        given = [d for d in item["doses"] if d["status"] == "done"]
        if not given:
            continue
        cards.append({
            "vaccine": item["vaccine"], "brand": item["brand"],
            "doses": given, "given": len(given), "total": item["total"],
            "complete": len(given) >= item["total"],
        })
    return cards


def certificate_totals(cards):
    """The three counters over the certificate: doses, vaccines, years covered.

    "Years" is the span the record itself covers — first dose to last — and it
    is deliberately the *record's* span rather than the child's age. A
    certificate that says "5 years" for a five-year-old with one dose in it
    would be describing the child while appearing to describe the record.
    """
    dates = sorted(d["given_date"] for card in cards for d in card["doses"]
                   if d["given_date"])
    years = 0
    if dates:
        first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        # Inclusive: a record beginning and ending in the same year covers one
        # year, not none.
        years = last.year - first.year + 1
    return {
        "doses": sum(card["given"] for card in cards),
        "vaccines": len(cards),
        "years": years,
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "complete": sum(1 for card in cards if card["complete"]),
    }


def plan_summary(plan):
    """Aggregate counts across a plan for the visual status cards.

    ``overdue`` counts only courses this clinic actually began. Everything
    else the child is old enough for is counted as ``suggested`` instead.

    The distinction is not cosmetic. The catalogue holds every vaccine the
    program knows, so a healthy two-year-old whose family uses the government
    unit for the national schedule was being told they were *late for 41
    vaccines* — a number that frightens a parent, means nothing clinically,
    and is not even this clinic's to make. "Late" is a broken promise, and a
    promise is only broken on a course somebody started here.
    """
    s = {"done": 0, "due": 0, "overdue": 0, "upcoming": 0, "suggested": 0,
         "total": 0}
    for v in plan:
        for d in v["doses"]:
            s[d["status"]] = s.get(d["status"], 0) + 1
            s["total"] += 1
    return s


def next_due_dose(plan):
    """Return the most urgent not-yet-given dose (overdue first, then due)."""
    candidates = []
    for v in plan:
        for d in v["doses"]:
            if d["status"] in GIVEABLE:
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
    today = today or local_today()
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
    today = today or local_today()
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


def immunization_compliance(lang="ar", today=None):
    """Population-level immunization compliance for the vaccines *the clinic
    actually administers* — the optional (paid) schedule.

    Mandatory EPI vaccines are deliberately excluded: they're given free at
    government units, so the clinic isn't the one keeping them on schedule and
    can't be measured on them (same reason the visit panel never suggests them).
    On-demand vaccines (rabies/travel) are situational, not schedule-based, so
    they're excluded too.

    Only patients who started at least one *optional* course with us are counted
    (we never chase a vaccine we never gave). Each is classified once —
    overdue / due-soon / up-to-date — from their plan, with a per-vaccine
    coverage tally and the most-overdue patients for follow-up. Cost scales with
    those patients: one plan computation each.
    """
    today = today or local_today()
    started_ids = {r[0] for r in (
        PatientVaccine.query.filter(PatientVaccine.event_type == "given")
        .with_entities(PatientVaccine.patient_id).distinct().all())}
    from app.models import Patient
    patients = (Patient.query.filter(Patient.is_active.is_(True),
                                     Patient.id.in_(started_ids)).all()
                if started_ids else [])

    total = up_to_date = due_soon = overdue = 0
    per_vaccine = {}          # vaccine_id -> {vaccine, doses, patients, overdue}
    overdue_patients = []
    for p in patients:
        plan = patient_plan(p, lang)
        p_over = p_due = 0
        has_optional = False
        for v in plan:
            vac = v["vaccine"]
            # Only the optional schedule the clinic runs — skip EPI/on-demand.
            if vac.is_mandatory or vac.on_demand:
                continue
            given = [d for d in v["doses"] if d["status"] == "done"]
            if not given:
                continue      # course not started here — ignore
            has_optional = True
            slot = per_vaccine.setdefault(
                vac.id,
                {"vaccine": vac, "doses": 0, "patients": 0, "overdue": 0})
            slot["doses"] += len(given)
            slot["patients"] += 1
            if any(d["status"] == "overdue" for d in v["doses"]):
                slot["overdue"] += 1
                p_over += 1
            elif any(d["status"] == "due" for d in v["doses"]):
                p_due += 1
            elif vac.is_seasonal:
                # Seasonal course with no pending dose: due again once the
                # annual recall window has passed since the last dose.
                last_iso = max((d["given_date"] for d in given
                                if d["given_date"]), default=None)
                if last_iso and (today - date.fromisoformat(last_iso)).days >= SEASONAL_RECALL_DAYS:
                    p_due += 1
        if not has_optional:
            continue          # no optional course with us — not our compliance
        total += 1
        if p_over:
            overdue += 1
            overdue_patients.append({"patient": p, "overdue": p_over})
        elif p_due:
            due_soon += 1
        else:
            up_to_date += 1

    overdue_patients.sort(key=lambda r: -r["overdue"])
    per_vaccine_rows = sorted(per_vaccine.values(), key=lambda r: -r["doses"])
    return {
        "total": total,
        "up_to_date": up_to_date,
        "due_soon": due_soon,
        "overdue": overdue,
        "rate": round(up_to_date / total * 100, 1) if total else 0.0,
        "per_vaccine": per_vaccine_rows,
        "overdue_patients": overdue_patients[:50],
    }


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
                    adverse_events=None, notes=None, outside_place=None):
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
        dose_number=dose_number, given_date=given_date or local_today(),
        doctor_id=doctor_id, lot_number=lot_number, event_type="given",
        given_outside=given_outside, adverse_events=adverse_events, notes=notes,
        # Only meaningful for a dose given elsewhere; kept off a clinic dose so
        # the record can't claim two places at once.
        outside_place=(outside_place or None) if given_outside else None,
    )
    db.session.add(pv)

    # Already paid for at the desk? Link the dose to that line now. Without
    # this the sell-forward path double-charges: the biller looks for doses
    # with no invoice, finds this one, and bills it a second time.
    try:
        from app.utils.vaccine_sale import claim_prepaid
        claim_prepaid(pv)
    except Exception:  # noqa: BLE001 - billing must never block a dose
        pass

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


def interval_warning(patient_id, vaccine, given_date=None):
    """A previous dose of *this same vaccine* given too recently.

    Reported: *"I tried it from inside the visit and added two doses in the
    same visit — shouldn't a warning come up? It has a schedule it can
    understand."* It does, and it wasn't reading it here.
    :func:`administer_dose` refused a repeat of the same dose **number** and
    nothing else, so dose 1 and then dose 2 on the same day passed every check
    it had: different number, not yet given, stock available. Two doses of one
    antigen minutes apart, recorded without a word.

    The minimum interval was already in the program — the catch-up scheduler
    reads it to work out when a dose *falls due*. It was simply never consulted
    at the moment somebody was about to give one.

    Deliberately a warning and not a block, in the same spirit as the
    brand-mix flag above it: a dose given elsewhere and entered late, or a
    correction to a mis-typed record, are both legitimate and the person
    entering them is the one who knows. What is not acceptable is silence.

    Returns ``None`` when there is nothing to say. Two *different* vaccines in
    one visit is normal practice and never warns.
    """
    on = given_date or local_today()
    last = (PatientVaccine.query
            .filter_by(patient_id=patient_id, vaccine_id=vaccine.id,
                       event_type="given")
            .filter(PatientVaccine.given_date.isnot(None))
            .order_by(PatientVaccine.given_date.desc()).first())
    if last is None:
        return None
    gap = (on - last.given_date).days
    # A dose being entered *before* one already on file is a different problem
    # (an out-of-order backfill), and guessing at it here would cry wolf on
    # every history a clinic types in from a parent's card.
    if gap < 0:
        return None
    minimum = vaccine.min_interval_days or _CATCH_UP_MIN_INTERVAL
    if gap >= minimum:
        return None
    return {"previous_date": last.given_date, "previous_dose": last.dose_number,
            "days": gap, "minimum": minimum}


def plan_dose(patient, vaccine, dose_number, on_date):
    """Record the doctor's chosen appointment for a not-yet-given dose.

    Stored as a ``planned`` event row; ``patient_plan`` then uses this date as
    the dose's due date instead of the computed schedule. Re-planning the same
    dose updates the row; giving the dose later supersedes it naturally.
    """
    brand, _ = chosen_brand(patient.id, vaccine)
    if brand is None:
        brand = vaccine.default_brand
    if brand is None:
        return None
    row = (PatientVaccine.query
           .filter_by(patient_id=patient.id, vaccine_id=vaccine.id,
                      dose_number=dose_number, event_type="planned").first())
    if row is None:
        row = PatientVaccine(patient_id=patient.id, vaccine_id=vaccine.id,
                             brand_id=brand.id, dose_number=dose_number,
                             event_type="planned", given_outside=False)
        db.session.add(row)
    row.given_date = on_date
    return row


def visit_given_summary(patient, on_date, lang="ar"):
    """Doses administered here on ``on_date`` framed for the prescription:
    trade name, dose X of N and where the course goes next (next dose with
    its expected date / seasonal recall / course complete)."""
    plan = patient_plan(patient, lang)
    today_iso = on_date.isoformat()
    out = []
    for v in plan:
        vac, brand = v["vaccine"], v["brand"]
        given_today = [d for d in v["doses"]
                       if d["given_date"] == today_iso]
        if not given_today:
            continue
        upcoming = [d for d in v["doses"] if d["status"] != "done"]
        if upcoming:
            nxt = {"kind": "dose", "dose_number": upcoming[0]["dose_number"],
                   "date": upcoming[0]["due_date"]}
        elif vac.is_seasonal:
            nxt = {"kind": "seasonal",
                   "date": (on_date + timedelta(days=SEASONAL_RECALL_DAYS)).isoformat()}
        else:
            nxt = {"kind": "none", "date": None}
        for d in given_today:
            out.append({"vaccine": vac, "brand": brand,
                        "dose_number": d["dose_number"], "total": v["total"],
                        "next": nxt})
    return out


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
    today = local_today()
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
        nxt = next((d for d in v["doses"] if d["status"] in GIVEABLE), None)
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
