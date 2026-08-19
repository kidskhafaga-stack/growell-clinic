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


# The regulatory / window facts the catalogue carries per trade name. Filled
# only where blank: a clinic that corrected a ceiling for its own stock keeps
# its correction across a re-seed, which is the same promise the schedules
# already make.
_BRAND_FACTS = ("manufacturer", "valency", "dose_volume",
                "max_age_final_dose_days", "max_age_first_dose_days",
                "registered_in_egypt",
                "available_now", "doses_change_by_start_age",
                "reminder_scope", "source_url",
                "interchange_to", "interchange_flag_under_months")


# The one fact whose blank really is ``False``: the column is NOT NULL with a
# default, so an untouched row and a deliberate "no" look identical. Nothing
# reads it yet — it marks which brands still need an age-banded schedule — so
# following the catalogue is right for it and wrong for all the others.
_FACTS_FILLED_OVER_FALSE = {"doses_change_by_start_age"}


def _fill_brand_facts(brand, data):
    """Copy the catalogue's facts onto a brand without clobbering edits.

    Blank means ``None``, not falsy. Counting ``False`` as blank meant a clinic
    marking a product out of stock had it declared available again by the next
    re-seed — the correction quietly undone by the thing meant to help.
    """
    for field in _BRAND_FACTS:
        value = data.get(field)
        if value is None:
            continue
        current = getattr(brand, field, None)
        blank = current is None or current == ""
        if field in _FACTS_FILLED_OVER_FALSE:
            blank = blank or current is False
        if blank:
            setattr(brand, field, value)


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
                # Both ends of the age range. `min_age_months` has been a
                # column since the medical fields were added and nothing ever
                # filled it from the catalogue — so "not before two years" was
                # written down in prose and known to nobody.
                min_age_months=v.get("min_age_months"),
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
            if v.get("min_age_months") and vaccine.min_age_months is None:
                vaccine.min_age_months = v["min_age_months"]
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
                _fill_brand_facts(existing, b)
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
                # Set at creation and never backfilled: whether a trade name
                # is still made is the catalogue's opening position, and the
                # clinic owns it afterwards. Backfilling it would undo a
                # clinic that brought one back, the same way counting False as
                # blank once undid "out of stock".
                is_discontinued=b.get("discontinued", False),
            )
            _fill_brand_facts(brand, b)
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
# Schedules whose **number of doses** depends on the age at the first dose.
#
# Only entries a doctor has reviewed and stated go here. HPV is the one: the
# rule was written out for this program and checked against the leaflet —
# 9–14 years is two doses six to twelve months apart, and from 15 it is three
# at 0, 2 and 6 months. The second half matters as much as the first: a child
# who started at fourteen and completed two doses correctly does **not** need
# a third for turning fifteen in between, which is why the band is matched on
# the age at the first dose and never on the age today.
#
# Bexsero is deliberately absent. Its dose count also varies with starting age
# and the exact bands need the GSK leaflet, so it keeps one standard course
# and carries the warning until somebody reads it.
#
# ``doses`` are ``(recommended_age_months, min_interval_days_from_previous)``.
# ``brand`` names the trade name a band belongs to; omitted, it is the
# vaccine's own and every brand follows it.
_AGE_BANDED = {
    # Bexsero, from the European label the clinic follows. The FDA licenses
    # the same product from ten years only, and a clinic following the CDC
    # will want different bands — which is exactly why these are seeded rows
    # on an editable screen and not a rule in code.
    #
    # Every band is 0.5 mL IM. The doses below are
    # ``(recommended_age_months, min_interval_days_from_previous)``.
    "MENB": [
        # The CDC licenses the same product from ten years, with two doses.
        # Stored beside the European bands rather than replacing them: the
        # clinic picks which guideline it follows in settings, and switching
        # recomputes from the doses already on file without re-entering one.
        {"code": "MENB-CDC-10Y", "min": 120, "max": None, "sort_order": 0,
         "brand": "Bexsero", "source": "cdc",
         "label": "CDC: من 10 سنوات — جرعتان بفاصل 6 شهور — للمراجعة",
         "doses": [(120, None), (126, 180)]},
        {"code": "MENB-2-5", "min": 2, "max": 5, "sort_order": 0,
         "brand": "Bexsero",
         "label": "بدء 2–5 شهور: 3 أساسية + منشّط 12–15 شهر — للمراجعة",
         "doses": [(2, None), (3, 28), (4, 28), (12, 180)]},
        {"code": "MENB-6-11", "min": 6, "max": 11, "sort_order": 1,
         "brand": "Bexsero",
         "label": "بدء 6–11 شهر: جرعتان + منشّط في السنة الثانية — للمراجعة",
         "doses": [(6, None), (8, 60), (13, 60)]},
        {"code": "MENB-12-23", "min": 12, "max": 23, "sort_order": 2,
         "brand": "Bexsero",
         "label": "بدء 12–23 شهر: جرعتان + منشّط بعد 12–23 شهر — للمراجعة",
         "doses": [(12, None), (14, 60), (26, 365)]},
        {"code": "MENB-2-10Y", "min": 24, "max": 131, "sort_order": 3,
         "brand": "Bexsero",
         "label": "بدء 2–10 سنوات: جرعتان (المنشّط عند استمرار الخطر) — للمراجعة",
         "doses": [(24, None), (25, 28)]},
        {"code": "MENB-11Y", "min": 132, "max": None, "sort_order": 4,
         "brand": "Bexsero",
         "label": "بدء 11 سنة فأكثر: جرعتان بلا منشّط روتيني — للمراجعة",
         "doses": [(132, None), (133, 28)]},
    ],
    # Vaxneuvance (PCV15), from Merck's own leaflet. On the brand and not the
    # vaccine on purpose: WHO speaks about pneumococcal conjugate as a class
    # and never about this product, and Merck's catch-up would be wrong
    # applied to Synflorix, which stops at five years.
    "PCV": [
        {"code": "PCV15-INF", "min": 1, "max": 6, "sort_order": 0,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 6 أسابيع–6 شهور: 4 جرعات — للمراجعة",
         "doses": [(2, None), (4, 28), (6, 28), (12, 60)]},
        {"code": "PCV15-CU7", "previous": "none", "min": 7, "max": 11, "sort_order": 1,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 7–11 شهر بدون PCV سابق: 3 جرعات — للمراجعة",
         "doses": [(7, None), (8, 28), (12, 60)]},
        {"code": "PCV15-CU12", "previous": "none", "min": 12, "max": 23, "sort_order": 2,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 12–23 شهر: جرعتان بفاصل ≥شهرين — للمراجعة",
         "doses": [(12, None), (14, 60)]},
        {"code": "PCV15-CU2Y", "previous": "none", "min": 24, "max": None, "sort_order": 3,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء سنتين فأكثر: جرعة واحدة — للمراجعة",
         "doses": [(24, None)]},
    ],
    "HPV": [
        {"code": "HPV2", "min": 108, "max": 179, "sort_order": 0,
         "gap_min": 150,
         "label": "9–14 سنة: جرعتان (الثانية بعد 5–13 شهر) — للمراجعة",
         "doses": [(108, None), (114, 150)]},
        # The same age, and the second dose came too soon. The leaflet says
        # such a course is not two doses but three — a rule about something
        # that already happened, which no schedule chosen at the first dose
        # could have known.
        {"code": "HPV2-SHORT", "min": 108, "max": 179, "sort_order": 1,
         "gap_max": 150,
         "label": "9–14 سنة والفاصل أقل من 5 شهور: 3 جرعات — للمراجعة",
         "doses": [(108, None), (110, 28), (114, 112)]},
        {"code": "HPV3", "min": 180, "max": None, "sort_order": 2,
         "label": "15 سنة فأكثر: 3 جرعات (0، 2، 6 شهور) — للمراجعة",
         "doses": [(180, None), (182, 28), (186, 112)]},
    ],
}


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
                   sort_order=0, start_age_min_months=None,
                   start_age_max_months=None, brand_id=None,
                   requires_previous_doses=None, first_gap_min_days=None,
                   first_gap_max_days=None):
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
        start_age_min_months=start_age_min_months,
        start_age_max_months=start_age_max_months, brand_id=brand_id,
        requires_previous_doses=requires_previous_doses,
        first_gap_min_days=first_gap_min_days,
        first_gap_max_days=first_gap_max_days,
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

        # Age-banded schedules, where the dose count itself depends on how
        # old the child was at the first dose. Seeded only where a doctor has
        # reviewed the rule and stated it — everything else keeps the single
        # standard course and shows the "varies by starting age" warning
        # instead, which is honest about not knowing rather than picking.
        for band in _AGE_BANDED.get(vaccine.code, []):
            brand_id = None
            if band.get("brand"):
                match = next((b for b in vaccine.brands
                              if b.name == band["brand"]), None)
                if match is None:
                    continue        # the trade name is not stocked here
                brand_id = match.id
            created += _seed_template(
                vaccine, code=band["code"],
                source=band.get("source", "manufacturer"),
                label=band["label"], doses=band["doses"],
                sort_order=band.get("sort_order", 0),
                start_age_min_months=band.get("min"),
                start_age_max_months=band.get("max"),
                brand_id=brand_id,
                requires_previous_doses=band.get("previous"),
                first_gap_min_days=band.get("gap_min"),
                first_gap_max_days=band.get("gap_max"))

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
def _following_dose(rows):
    """The dose whose trade name the course is following: the **latest**.

    It used to be the earliest, and that was wrong in the one case that
    matters. A child who had two Prevenar and moved to Vaxneuvance is on
    Vaxneuvance — the doses already given count, and the ones remaining follow
    the product being used now. Locked to the first dose the record showed
    them on a product they had stopped, and scheduled the wrong course with it.

    On a course that never switched — nearly all of them — the first and last
    dose are the same product and nothing changes.

    Ordered by date, with the dose number as the tie-break for two doses
    recorded on one day and for imported rows carrying no date at all.
    """
    return max(rows, key=lambda pv: (pv.given_date is not None,
                                     pv.given_date or date.min,
                                     pv.dose_number or 0))


def chosen_brand(patient_id, vaccine, given=None):
    """The brand locked for this patient/vaccine, or the default brand.

    Only an actually-given dose locks the brand; a refused/delayed event does
    not commit the patient to a brand.

    ``given`` lets a caller that has already read the patient's doses hand them
    over instead of paying for another query. `patient_plan` reads every one of
    them on its first line and then asked again here, once per vaccine — which
    is a query per patient per vaccine, for rows already sitting in memory.
    Measured on the customer-service desk, whose work-list counts walk every
    vaccinated patient on file: 6 queries per patient at 2,000 patients was
    12,005 queries and 4.4 seconds, to draw a card that said zero.
    """
    if given is None:
        # The same ordering as `_following_dose`, in SQL. Both paths have to
        # name the same product: they were briefly allowed to differ — this
        # one still took the earliest dose while the batched one had moved to
        # the latest — and a child with two doses on one day came out on two
        # different manufacturers depending on which screen asked.
        pv = (
            PatientVaccine.query.filter_by(patient_id=patient_id,
                                           vaccine_id=vaccine.id,
                                           event_type="given")
            .order_by(PatientVaccine.given_date.is_(None),
                      PatientVaccine.given_date.desc(),
                      PatientVaccine.dose_number.desc())
            .first()
        )
    else:
        rows = given.get(vaccine.id) or []
        pv = _following_dose(rows) if rows else None
    if pv:
        return pv.brand, True  # locked
    return vaccine.default_brand, False


# A dose that could be given today, whoever started the course. Named once
# because it is asked in four places, and the fourth is always the one that
# gets forgotten: adding `suggested` broke the visit panel's offer list —
# an unvaccinated child was suddenly offered nothing at all — while every
# other screen looked fine.
GIVEABLE = ("overdue", "due", "suggested")


def _status(due_date, given, today, closed_after=None, cannot_start=False):
    """What this dose is, for this child, today.

    ``closed_after`` is the last date the dose could still be given — the
    brand's ceiling projected onto this child's birthday. Past it the dose is
    **expired**, not overdue: the difference is the whole point. "Overdue" asks
    somebody to chase it, and the rotavirus series cannot be given to a
    three-year-old at all, so chasing it is asking the desk to make a call that
    ends in "no". Before this, every child past the window read as overdue on
    rotavirus for the rest of their childhood.
    """
    if given:
        return "done"
    # Never begun, and the window for beginning has shut. Distinct from
    # `expired`, which is about finishing: a child can be inside the finish
    # window and past the start one, and offering them a first dose then is
    # asking a question the label has already answered. The program used to
    # ask when to give a dose without ever asking whether it may.
    if cannot_start:
        return "not_eligible"
    if closed_after is not None and today > closed_after:
        return "expired"
    if due_date is None:
        return "upcoming"
    # A dose whose own turn falls past the ceiling can never arrive in time,
    # even though the child is still inside the window today.
    if closed_after is not None and due_date > closed_after:
        return "expired"
    if due_date < today:
        return "overdue"
    if (due_date - today).days <= DUE_WINDOW_DAYS:
        return "due"
    return "upcoming"


def _all_vaccines():
    """The vaccine catalogue, read once per request.

    A dozen rows that do not change while a page is being built, re-read for
    every patient the work list walks.
    """
    from app.utils.request_cache import remember

    return remember("vaccines:all",
                    lambda: Vaccine.query.order_by(Vaccine.sort_order).all())


def doses_for(patient_ids):
    """Every recorded dose for many patients, grouped by patient, in one query.

    The batched feed for :func:`patient_plan`. Walking a list of patients and
    letting each one read its own doses is a query apiece — fine for a file
    screen, and the whole cost of the work-list counts on a clinic with a few
    thousand vaccinated children.
    """
    if not patient_ids:
        return {}
    out = {}
    rows = (PatientVaccine.query
            .filter(PatientVaccine.patient_id.in_(list(patient_ids))).all())
    for pv in rows:
        out.setdefault(pv.patient_id, []).append(pv)
    return out


def _months_between(dob, when):
    """Whole months from a birthday to a date."""
    months = (when.year - dob.year) * 12 + (when.month - dob.month)
    return months - 1 if when.day < dob.day else months


def _pick_band(bands, dob, start, previous, today, first_gap=None):
    """The first band whose age range and history condition both match.

    Both halves, because the leaflets name them together. "Unvaccinated 7 to
    <12 months" is not an age; it is an age **and** an empty record, and a
    child switching product at nine months with two doses behind them belongs
    to neither half of it.
    """
    months = _months_between(dob, start or today)
    for band in bands:
        low = band["min"] if band["min"] is not None else -10 ** 6
        high = band["max"] if band["max"] is not None else 10 ** 6
        if not low <= months <= high:
            continue
        needs = band.get("previous")
        if needs == "none" and previous:
            continue
        if needs == "some" and not previous:
            continue
        # The gap actually achieved between the first two doses. Unknown until
        # the second one happens, so a band that asks about it simply does not
        # apply yet — the child stays on whichever band their age chose, and
        # moves only when the answer exists.
        low_gap, high_gap = band.get("gap_min"), band.get("gap_max")
        if first_gap is None:
            # The second dose has not happened, so the gap cannot disqualify
            # anything yet. The **expectation** applies — a course is two
            # doses until the second one arrives too early — so a band that
            # exists to catch a short gap waits for the evidence, while the
            # ordinary band applies now. Reversed, every child was shown the
            # exception before anything had gone wrong.
            if high_gap is not None:
                continue
        else:
            if low_gap is not None and first_gap < low_gap:
                continue
            if high_gap is not None and first_gap >= high_gap:
                continue
        return band["doses"]
    return None


def mixed_series_note(brand, previous_brand_ids, dob, switched_on):
    """What to say about a course finished on a different product.

    Returns ``None`` when there is nothing to say — no switch, or a
    destination whose leaflet allows switching in without reservation — else
    ``{"level": ..., "reason": ...}`` for the file to show.

    Read **as destination**: the question is what *this* brand's leaflet says
    about children arriving at it, not what the previous one said about
    leaving. The labels are written that way and interchangeability is not
    symmetric, so asking the source product would answer a different question.

    The program never substitutes a brand on its own — the doctor records what
    was given, and stock and billing follow that. So "no automatic
    substitution" is not a restriction to enforce; what a thin evidence base
    earns is a note where somebody is deciding, and never a silent yes.
    """
    if not previous_brand_ids or brand.id in previous_brand_ids:
        return None                     # nothing switched
    status = (brand.interchange_to or "full").strip().lower()
    if status == "full":
        return None
    if status == "none":
        return {"level": "none", "reason": "not_counted"}
    if status == "limited":
        return {"level": "limited", "reason": "thin_evidence"}
    # conditional: a reservation that only bites under a stated age, measured
    # at the switch because that is what the label describes.
    under = brand.interchange_flag_under_months
    if under and dob and switched_on:
        if _months_between(dob, switched_on) < under:
            return {"level": "conditional", "reason": "under_age",
                    "months": under}
        return None
    return {"level": "conditional", "reason": "review"}


def _achieved_first_gap(given_dates):
    """Days between the first two doses actually given, or None.

    None means "not yet known", which is different from zero and is why the
    band condition treats it as "this rule cannot decide anything".
    """
    dates = sorted(d for d in given_dates.values() if d)
    if len(dates) < 2:
        return None
    return (dates[1] - dates[0]).days


def schedule_for(vaccine, brand, dob, given_dates, today=None,
                 brand_first=None, previous=0):
    """The dose ages this child's course actually follows.

    Returns ``[(dose_number, age_months)]`` — the brand's own dose rows unless
    the vaccine carries **age-banded** schedules, in which case the band is
    matched and its doses used instead.

    Two rules, and the second is the one the doctor raised as mattering most.

    **Matched on the age at the first dose, not the age today.** A child who
    started HPV at fourteen years and eleven months is on the two-dose
    schedule; they do not jump to three because a birthday passed before the
    second one. Once a dose exists, that dose decides the band for good — so
    the answer is stable in a way that recomputing from today's age never is.

    **Before any dose, the band follows today's age**, because that is what
    starting now would mean. It is a projection and changes as the child grows,
    which is correct: nothing has been promised yet.

    A vaccine with no banded schedules falls straight through to the brand's
    doses, so this changes nothing for the catalogue as it stands. The bands
    are filled in one at a time, by somebody who has read the leaflet.
    """
    default = [(d.dose_number, d.age_months) for d in brand.doses]
    if dob is None:
        return default

    bands = _bands_for(vaccine.id, brand.id)
    if not bands:
        return default

    # When *this brand's* course started, not when the child's first ever dose
    # was. Stated by the doctor and it is the whole correction: a child who
    # had two Prevenar and moves to Vaxneuvance "moves to the Vaxneuvance
    # schedule that suits their age and state at the point of switching" —
    # they do not stay on the schedule their first needle put them on, and
    # they do not start again either, because the doses already given count.
    #
    # For a course on one product throughout these are the same date, which is
    # why HPV still locks at its first dose.
    start = brand_first
    if start is None:
        start = min((d for d in given_dates.values() if d), default=None)
    picked = _pick_band(bands, dob, start, previous, today or local_today(),
                        first_gap=_achieved_first_gap(given_dates))
    if picked is not None:
        return picked
    # The guideline speaks about this product and says nothing about a child
    # this age — under the CDC, Bexsero simply is not scheduled below ten
    # years. Falling back to the brand's raw dose rows would answer with a
    # number from no guideline at all, which is worse than either. An empty
    # course is the honest reading: this reference does not schedule it.
    if any(b.get("authoritative") for b in bands):
        return []
    return default


def _bands_for(vaccine_id, brand_id):
    """The bands this brand follows: its own if it has any, else the vaccine's.

    A trade name with its own schedule is not merely *preferred* — it replaces
    the vaccine's rather than adding to it, because a leaflet is a complete
    statement about that product and mixing half of it with a generic one is
    how a course ends up with a dose from neither.
    """
    banded = _banded_templates()
    mine = [b for b in banded.get(vaccine_id, [])
            if b["doses"] and b["brand_id"] == brand_id]
    if mine:
        return mine
    return [b for b in banded.get(vaccine_id, [])
            if b["doses"] and b["brand_id"] is None]


def guideline_profile():
    """Which published guideline this clinic follows, from settings.

    A policy, not a code path. The same product can have two published
    positions — Bexsero's course is the European label's from two months and
    the CDC's from ten years — and a clinic changing which it follows should
    change a setting, not a program.
    """
    from app.models import VaccineScheduleTemplate

    try:
        from app.models import Setting
        chosen = (Setting.get("vaccine_guideline_profile", "") or "").strip()
    except Exception:  # noqa: BLE001 - settings table not ready yet
        chosen = ""
    if chosen in VaccineScheduleTemplate.GUIDELINE_PROFILES:
        return chosen
    return "manufacturer"


def _banded_templates():
    """``{vaccine_id: [{min, max, doses}]}`` for the schedules that carry a
    band, read once per request.

    Read for the profile the clinic follows, **falling back to the
    manufacturer's** where that profile says nothing. The fallback is the load-
    bearing part: no guideline covers every product a clinic stocks, and a
    profile with a gap that silently left a vaccine unscheduled would turn
    "we follow the CDC" into "we stopped following anything for half the
    fridge". The leaflet is what a product always has.
    """
    from app.models import VaccineScheduleDose, VaccineScheduleTemplate
    from app.utils.request_cache import remember

    def load():
        out = {}
        profile = guideline_profile()
        wanted = {profile, "manufacturer"}
        rows = (VaccineScheduleTemplate.query
                .filter(VaccineScheduleTemplate.is_active.is_(True),
                        VaccineScheduleTemplate.is_catch_up.is_(False),
                        VaccineScheduleTemplate.source.in_(list(wanted)))
                .filter(db.or_(
                    VaccineScheduleTemplate.start_age_min_months.isnot(None),
                    VaccineScheduleTemplate.start_age_max_months.isnot(None)))
                .order_by(VaccineScheduleTemplate.sort_order,
                          VaccineScheduleTemplate.id).all())
        if not rows:
            return out
        doses = {}
        for row in (VaccineScheduleDose.query
                    .filter(VaccineScheduleDose.template_id.in_(
                        [t.id for t in rows]))
                    .order_by(VaccineScheduleDose.dose_number).all()):
            doses.setdefault(row.template_id, []).append(
                (row.dose_number, row.recommended_age_months))
        # The chosen profile wins wherever it speaks; the leaflet fills the
        # rest. Grouped per (vaccine, brand) so a profile covering one product
        # does not silence the leaflet's schedule for its neighbours.
        speaks = {(t.vaccine_id, t.brand_id) for t in rows
                  if t.source == profile}
        for template in rows:
            if (template.source != profile
                    and (template.vaccine_id, template.brand_id) in speaks):
                continue
            out.setdefault(template.vaccine_id, []).append({
                # This row came from the guideline the clinic follows, so its
                # silence about an age is itself an answer.
                "authoritative": template.source == profile != "manufacturer",
                "min": template.start_age_min_months,
                "max": template.start_age_max_months,
                "brand_id": template.brand_id,
                "previous": template.requires_previous_doses,
                "gap_min": template.first_gap_min_days,
                "gap_max": template.first_gap_max_days,
                "doses": doses.get(template.id, []),
            })
        return out

    return remember("vaccines:banded_templates", load)


# When the program will not answer.
#
# "Any case the engine cannot establish from age, history, intervals, brand,
# guideline and eligibility — it will not guess. It returns Clinical Review
# Required instead of producing an unverified medical reminder."
#
# Everything else in this module decides *what* to do. This decides when the
# honest answer is that nobody here can decide, which is the one output a
# schedule engine cannot produce by being clever.
REVIEW_REASONS = {
    # A dose exists with no date on it. Every interval, ceiling and window is
    # computed from dates, so one missing makes the rest arithmetic on a hole.
    # Common in imported history, which is exactly where nobody notices.
    "undated_dose": "جرعة بدون تاريخ — الفواصل والحدود كلها بتتحسب من التواريخ",
    # Two doses recorded under the same number. Either one is a duplicate or
    # a number is wrong, and the course is a different length depending which.
    "duplicate_dose": "جرعتان بنفس الرقم — الكورس طوله مختلف حسب أيهما الصحيح",
    # More doses on file than the schedule has room for.
    "more_than_scheduled": "جرعات أكثر مما يسمح به الجدول",
    # The child's own record contradicts the order of the schedule.
    "out_of_order": "تواريخ الجرعات مش بترتيب أرقامها",
}


def needs_clinical_review(dob, schedule, given_rows):
    """Why this course cannot be scheduled, or None.

    ``given_rows`` are ``(dose_number, given_date)`` for the doses on file.

    Deliberately narrow. It looks for records the arithmetic cannot be run on
    at all — not for anything a doctor might want a second opinion about,
    which would put the flag on everybody and teach the clinic to ignore it.
    """
    if dob is None:
        return "undated_dose" if given_rows else None
    numbers = [n for n, _d in given_rows]
    if any(d is None for _n, d in given_rows):
        return "undated_dose"
    if len(numbers) != len(set(numbers)):
        return "duplicate_dose"
    if schedule and len(numbers) > len(schedule):
        return "more_than_scheduled"
    ordered = [d for _n, d in sorted(given_rows, key=lambda r: r[0] or 0)]
    if any(b < a for a, b in zip(ordered, ordered[1:])):
        return "out_of_order"
    return None


def course_dates(dob, schedule, given, planned, min_interval,
                 earliest_live, closed_after, today, start_closed_after=None):
    """When each dose of one course falls due, and what it is today.

    The whole scheduling rule, in one place and over plain values: a birthday,
    ``[(dose_number, age_months)]``, and two ``{dose_number: date}`` maps for
    what was given and what the doctor pencilled in.

    It takes no model objects on purpose. The patient's own file wants the
    doctor, the lot number and the batch a dose was imported in; a sweep over
    every vaccinated child in the register wants none of that and cannot
    afford to build it. Both need the *same* dates, and two implementations of
    a schedule eventually disagree in front of a family — so the loading is
    what differs between them and this is not.

    Returns ``{dose_number: (due_date | None, status)}``.
    """
    out = {}
    prev_date = None
    # A series nobody has begun, whose window for beginning has shut. Judged
    # once for the course rather than per dose: it is the *first* dose the
    # label puts a deadline on, and once that is past none of the rest can
    # happen either.
    cannot_start = bool(
        start_closed_after is not None
        and not any(d for d in given.values())
        and today > start_closed_after)
    for dose_number, age_months in schedule:
        given_date = given.get(dose_number)
        due = add_months(dob, age_months) if dob else None
        if given_date is not None:
            effective = given_date
        else:
            # Catch-up: a not-yet-given dose cannot fall due before the minimum
            # gap after the previous one, so the chain runs forward from each
            # dose's effective date — the real one where there is one, the
            # projected one otherwise. A child who started late gets correctly
            # spaced dates rather than the raw age dates.
            if due and prev_date:
                earliest = prev_date + timedelta(days=min_interval)
                if earliest > due:
                    due = earliest
            if due and earliest_live and earliest_live > due:
                due = earliest_live
            # The doctor's explicit appointment for this dose wins over the
            # computed schedule (their patient, their timing).
            if planned.get(dose_number):
                due = planned[dose_number]
            effective = due
        prev_date = effective
        out[dose_number] = (due, _status(due, given_date is not None, today,
                                         closed_after=closed_after,
                                         cannot_start=cannot_start))
    return out


def patient_plan(patient, lang="ar", doses=None, agreed=None):
    """Build the full vaccination plan for a patient.

    Returns a list of per-vaccine dicts with the chosen brand and a list of
    dose dicts {dose_number, age_months, age_label, due_date, given_date,
    lot_number, status}.
    """
    today = local_today()
    dob = patient.date_of_birth
    given_index = {}
    events_index = {}   # (vaccine_id, dose_number) -> refused/delayed event
    given_by_vaccine = {}   # vaccine_id -> [given doses], for `chosen_brand`
    rows = (PatientVaccine.query.filter_by(patient_id=patient.id).all()
            if doses is None else doses)
    if agreed is None:
        from app.models.vaccine_plan import planned_vaccine_ids
        agreed = planned_vaccine_ids(patient.id)
    for pv in rows:
        if (pv.event_type or "given") == "given":
            given_index[(pv.vaccine_id, pv.dose_number)] = pv
            given_by_vaccine.setdefault(pv.vaccine_id, []).append(pv)
        else:
            events_index[(pv.vaccine_id, pv.dose_number)] = pv

    all_vaccines = _all_vaccines()
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
        brand, locked = chosen_brand(patient.id, vaccine,
                                     given=given_by_vaccine)
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
        # The last day this brand's series may still be completed, on this
        # child's birthday. Per brand, because that is where it differs:
        # rotavirus finishes at 24 weeks on RotaRix and 32 on RotaTeq, and
        # Synflorix stops at five years while the other pneumococcals do not.
        closed_after = None
        if dob and brand.max_age_final_dose_days:
            closed_after = dob + timedelta(days=brand.max_age_final_dose_days)
        start_closed_after = None
        if dob and brand.max_age_first_dose_days:
            start_closed_after = dob + timedelta(
                days=brand.max_age_first_dose_days)
        # Live-vaccine spacing: keep 28 days from another live parenteral vaccine
        # the child already got (can't co-administer with a past dose anymore).
        earliest_live = None
        if vaccine.id in live_ids:
            others = [dt for vid2, dt in live_given.items() if vid2 != vaccine.id]
            if others:
                earliest_live = max(others) + timedelta(days=LIVE_SPACING_DAYS)
        # Read from what the child actually has, not from the brand's dose
        # rows: an age-banded course can carry a dose number the brand list
        # does not, and building this from the rows would drop it.
        given_dates = {number: row.given_date
                       for (vid, number), row in given_index.items()
                       if vid == vaccine.id}
        planned_dates = {}
        for (vid, number), ev in events_index.items():
            if (vid == vaccine.id and number not in given_dates
                    and ev.event_type == "planned" and ev.given_date):
                planned_dates[number] = ev.given_date

        # When this brand's own doses began, and how many of the vaccine came
        # before that — a Prevenar dose is a pneumococcal dose when the next
        # one is Vaxneuvance, so history is counted per vaccine and never per
        # trade name.
        brand_first = min((row.given_date for (vid, _n), row in given_index.items()
                           if vid == vaccine.id and row.brand_id == brand.id
                           and row.given_date), default=None)
        previous = sum(1 for (vid, _n), row in given_index.items()
                       if vid == vaccine.id and row.given_date
                       and (brand_first is None
                            or row.given_date < brand_first))
        rota = schedule_for(vaccine, brand, dob, given_dates, today,
                            brand_first=brand_first, previous=previous)
        # Before anything is computed from these dates, whether they can be
        # computed from at all.
        # From the raw rows, not from `given_index`: that is keyed by
        # (vaccine, dose number) and so a duplicated number collapses into one
        # entry — the very thing being looked for disappears on the way in.
        review = needs_clinical_review(
            dob, rota,
            [(pv.dose_number, pv.given_date) for pv in rows
             if pv.vaccine_id == vaccine.id
             and (pv.event_type or "given") == "given"])
        # Did the course change product, and does the destination's leaflet
        # have anything to say about that?
        earlier_brands = {row.brand_id for (vid, _n), row in given_index.items()
                          if vid == vaccine.id and row.brand_id
                          and row.given_date
                          and (brand_first is None
                               or row.given_date < brand_first)}
        mixed = mixed_series_note(brand, earlier_brands, dob, brand_first)
        timings = course_dates(dob, rota, given_dates, planned_dates, min_iv,
                               earliest_live, closed_after, today,
                               start_closed_after=start_closed_after)

        doses = []
        by_number = {d.dose_number: d for d in brand.doses}
        for dose_number, age_months in rota:
            d = by_number.get(dose_number)
            pv = given_index.get((vaccine.id, dose_number))
            ev = events_index.get((vaccine.id, dose_number))
            due, status = timings[dose_number]
            planned = planned_dates.get(dose_number)
            doses.append({
                # From the chosen schedule, not the brand's rows: an
                # age-banded course can have a dose the brand list does not —
                # HPV is three doses started at fifteen and two before that,
                # off one set of brand rows.
                "dose_number": dose_number,
                "age_months": age_months,
                "age_label": age_label(age_months, lang),
                # Carried so the card can say "the booster is what is left"
                # rather than "3/4" and leave the reader to work out which of
                # the two very different jobs that is.
                "booster": (is_booster(brand, dose_number)
                            if d is not None else False),
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
                "status": status,
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
            # Neither of these is a course this clinic ever promised, so
            # neither can be late here **and neither is a suggestion by age**.
            #
            # The national schedule is given free at the government units. A
            # healthy two-year-old whose family uses one was carrying nine
            # government vaccines and seventeen doses in their plan — a third
            # of it — for a schedule this clinic does not give, does not stock
            # and cannot be measured on. The compliance screen already
            # excluded them for exactly that reason, and the visit panel
            # already declines to offer them; the plan and the certificate
            # were the two places still counting them.
            #
            # On-demand vaccines are the same shape for a different reason:
            # rabies is given because a dog bit somebody. Projected from a
            # birthday it came out due at birth, so every child in the
            # register was being suggested it.
            #
            # They stay in the plan rather than vanishing: the row is what the
            # doctor clicks to record a dose given at a government unit, and
            # that record is the point of the certificate.
            fallback = "suggested"
            if vaccine.is_mandatory:
                fallback = "national"
            elif vaccine.on_demand:
                fallback = "on_demand"
            # Unless the doctor and the family agreed on this one. An
            # agreement is a promise, and a promise is what makes a dose
            # capable of being late — the same rule that already applied once
            # somebody had started the course, moved one step earlier so it
            # counts from the conversation rather than from the first needle.
            #
            # It raises what was agreed and hides nothing: everything else
            # stays a suggestion for the child's age, which is what it is.
            if vaccine.id in (agreed or ()):
                fallback = None
            for x in doses:
                if fallback and x["status"] in ("overdue", "due"):
                    x["status"] = fallback
        plan.append({
            "vaccine": vaccine, "brand": brand, "locked": locked,
            "doses": doses, "started": started,
            # What the clinic has taken on: a course somebody began here, or
            # one the doctor agreed to. The certificate's "what is left" table
            # is exactly this set, and an agreed course belongs in it — that
            # is the table a family is handed.
            "mixed": mixed,
            # Set when the record cannot be scheduled from. The screens show
            # it in place of a due date, because a date computed from a
            # contradiction is worse than no date.
            "review": review,
            "agreed": vaccine.id in (agreed or ()),
            "committed": started or vaccine.id in (agreed or ()),
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
         "expired": 0, "not_eligible": 0, "national": 0, "on_demand": 0,
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


def patient_due_reminders(patient, lang="ar", today=None, doses=None,
                          agreed=None):
    """Everything worth reminding this patient about — the courses this clinic
    has taken on, which is either of two things:

      * one somebody **started** here (≥1 dose given), or
      * one the doctor and the family **agreed** on.

    Never a vaccine that is merely age-appropriate: we do not chase a course
    nobody promised.

      * a late/due next dose of such a course (incl. boosters), and
      * a seasonal vaccine's annual recall once ~11 months have passed.

    Returns a list of dicts ``{vaccine, brand, dose_number, due_date, status}``
    sorted most-urgent first (``status`` is overdue / due / seasonal).
    """
    today = today or local_today()
    plan = patient_plan(patient, lang, doses=doses, agreed=agreed)
    out = []
    for v in plan:
        vac, brand = v["vaccine"], v["brand"]
        done = [d for d in v["doses"] if d["status"] == "done"]
        # An agreed course with nothing given yet is the case a plan exists
        # for: its first dose can be late before any dose exists to start it.
        # Wiring the *status* without this left the file computing "overdue"
        # and then dropping it on the floor, which the sweep did not — caught
        # by the test that holds the two to the same answer.
        if v.get("review"):
            # The record cannot be scheduled from, so no date computed from it
            # may go out as a reminder. The file shows the flag; nothing here
            # sends anything. "It will not guess" has to mean the message too,
            # or the guess simply travels further.
            continue
        if not done and not v.get("agreed"):
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


# ─────────────────────────── the same schedule, read flat ───────────────────

def _catalogue_rows():
    """The vaccine catalogue as plain tuples, read once per request.

    Forty-odd vaccines, a hundred-odd brands and their dose rows: small,
    unchanging while a page is built, and re-read for every patient the sweep
    walks. Loaded here as columns rather than objects for the same reason the
    sweep itself is — nothing below needs a model, and building one per row is
    the cost being removed.
    """
    from app.utils.request_cache import remember

    def load():
        vaccines = {}
        for v in Vaccine.query.order_by(Vaccine.sort_order).all():
            vaccines[v.id] = {
                "id": v.id, "code": v.code, "seasonal": bool(v.is_seasonal),
                "min_interval": v.min_interval_days or _CATCH_UP_MIN_INTERVAL,
                "live": (v.vaccine_type == "live" and (v.route or "") != "oral"),
                "obj": v,
            }
        brands = {}
        for b in VaccineBrand.query.all():
            brands[b.id] = {"id": b.id, "vaccine_id": b.vaccine_id,
                            "default": bool(b.is_default),
                            "ceiling": b.max_age_final_dose_days,
                            "start_ceiling": b.max_age_first_dose_days,
                            "obj": b}
        for row in VaccineBrandDose.query.order_by(
                VaccineBrandDose.dose_number).all():
            brand = brands.get(row.brand_id)
            if brand is not None:
                brand.setdefault("doses", []).append(
                    (row.dose_number, row.age_months))
        by_vaccine = {}
        for brand in brands.values():
            by_vaccine.setdefault(brand["vaccine_id"], []).append(brand)
        return vaccines, brands, by_vaccine

    return remember("vaccines:catalogue_rows", load)


def _banded_for(vaccine_id, brand_id, dob, given_dates, today,
                brand_first=None, previous=0):
    """The banded schedule for this course, from plain values.

    The sweep's half of :func:`schedule_for`. Same rule, same table, same
    answer — matched on the age at the first dose, today's age before there is
    one — because a listing that picks a different schedule from the child's
    own file is two programs disagreeing about a course.
    """
    if dob is None:
        return None
    bands = _bands_for(vaccine_id, brand_id)
    if not bands:
        return None
    start = brand_first
    if start is None:
        start = min((d for d in given_dates.values() if d), default=None)
    picked = _pick_band(bands, dob, start, previous, today,
                        first_gap=_achieved_first_gap(given_dates))
    if picked is None and any(b.get("authoritative") for b in bands):
        return []
    return picked


def scan_due(dob, doses, today, agreed=None):
    """Every pending dose for one child, from plain values.

    ``doses`` are ``(vaccine_id, brand_id, dose_number, given_date,
    event_type)`` tuples — what the database holds, not what the ORM builds
    from it.

    The lean twin of :func:`patient_due_reminders`. It answers the same
    question and must answer it identically; what it does not do is carry the
    lot number, the doctor and the import batch that the patient's own file
    needs and a register-wide sweep does not.

    Returns ``[{vaccine, brand, dose_number, due_date, status}]``.
    """
    vaccines, brands, by_vaccine = _catalogue_rows()

    given = {}          # vaccine_id -> {dose_number: given_date}
    brand_doses = {}    # vaccine_id -> [(brand_id, given_date)]
    raw_doses = {}      # vaccine_id -> [(dose_number, given_date)], duplicates kept
    planned = {}        # vaccine_id -> {dose_number: date}
    locked = {}         # vaccine_id -> brand_id of the earliest given dose
    live_given = {}
    for vaccine_id, brand_id, dose_number, given_date, event_type in doses:
        if (event_type or "given") == "given":
            given.setdefault(vaccine_id, {})[dose_number] = given_date
            brand_doses.setdefault(vaccine_id, []).append((brand_id, given_date))
            raw_doses.setdefault(vaccine_id, []).append((dose_number, given_date))
            best = locked.get(vaccine_id)
            key = (given_date is not None, given_date or date.min,
                   dose_number or 0)
            if best is None or key > best[0]:
                locked[vaccine_id] = (key, brand_id)
            meta = vaccines.get(vaccine_id)
            if meta and meta["live"] and given_date:
                if live_given.get(vaccine_id) is None \
                        or given_date > live_given[vaccine_id]:
                    live_given[vaccine_id] = given_date
        elif event_type == "planned" and given_date:
            planned.setdefault(vaccine_id, {})[dose_number] = given_date

    out = []
    for vaccine_id, meta in vaccines.items():
        brand = _brand_for(vaccine_id, locked, brands, by_vaccine)
        if brand is None or not brand.get("doses"):
            continue
        mine = given.get(vaccine_id, {})
        if needs_clinical_review(dob, brand.get("doses"),
                                 raw_doses.get(vaccine_id, [])):
            continue        # same rule as the file: no guessing, no message
        if not mine and vaccine_id not in (agreed or ()):
            # A course nobody started **and** nobody agreed on is not "late".
            # The agreement is the other way in: it is what the doctor and the
            # family settled on, so its first dose can be overdue before any
            # dose exists to start it.
            continue
        closed_after = (dob + timedelta(days=brand["ceiling"])
                        if dob and brand["ceiling"] else None)
        start_closed_after = (dob + timedelta(days=brand["start_ceiling"])
                              if dob and brand.get("start_ceiling") else None)
        earliest_live = None
        if meta["live"]:
            others = [d for vid, d in live_given.items() if vid != vaccine_id]
            if others:
                earliest_live = max(others) + timedelta(days=LIVE_SPACING_DAYS)

        brand_first = min((d for (bid, d) in brand_doses.get(vaccine_id, [])
                           if bid == brand["id"] and d), default=None)
        previous = sum(1 for (_bid, d) in brand_doses.get(vaccine_id, [])
                       if d and (brand_first is None or d < brand_first))
        rota = _banded_for(vaccine_id, brand["id"], dob, mine, today,
                           brand_first=brand_first, previous=previous)
        if rota is None:
            rota = brand["doses"]
        timings = course_dates(dob, rota, mine,
                               planned.get(vaccine_id, {}),
                               meta["min_interval"], earliest_live,
                               closed_after, today,
                               start_closed_after=start_closed_after)

        if meta["seasonal"]:
            last = max((d for d in mine.values() if d), default=None)
            if last is None:
                continue        # agreed, never given — no annual recall yet
            if last and (today - last).days >= SEASONAL_RECALL_DAYS:
                out.append({"vaccine": meta["obj"], "brand": brand["obj"],
                            "dose_number": max(mine) + 1,
                            "due_date": None, "status": "seasonal"})
            continue
        for dose_number, _age in rota:
            due, status = timings[dose_number]
            if status in ("overdue", "due"):
                out.append({"vaccine": meta["obj"], "brand": brand["obj"],
                            "dose_number": dose_number,
                            "due_date": due.isoformat() if due else None,
                            "status": status})
                break
    out.sort(key=lambda r: (0 if r["status"] == "overdue" else 1,
                            r["due_date"] or ""))
    return out


def _brand_for(vaccine_id, locked, brands, by_vaccine):
    """The brand a given dose locked this patient to, else the default one."""
    held = locked.get(vaccine_id)
    if held is not None:
        brand = brands.get(held[1])
        if brand is not None:
            return brand
    for brand in by_vaccine.get(vaccine_id, []):
        if brand["default"]:
            return brand
    return None
