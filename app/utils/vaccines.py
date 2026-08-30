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
    VaccineCredit,
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


# Seeded bands that were tagged with the wrong reference, and where they
# belong. `_seed_template` keys on (vaccine, code, source), so re-tagging a
# band in the catalogue only ever *adds* the corrected row and leaves the old
# one applying to every clinic exactly as before — which for these two would
# have meant the five-year ceiling going on being a rule everybody got,
# whichever guideline they had chosen. A rule that moved has to move on the
# installs that already have it.
#
# Keyed by the code as it was seeded, so a clinic that renamed or edited its
# copy is left alone: only rows the program wrote are touched.
_RETAGGED_BANDS = {
    # The pneumococcal catch-up and the end of the routine course. Both were
    # tagged `manufacturer` for a mechanical reason the old comment admitted
    # to — it was the only tag every clinic would read — and both are
    # statements by a guideline, not by a leaflet. They are seeded again under
    # the references that make them; these two rows are retired.
    "PCV-CU-2Y": None,
    "PCV-ROUTINE-END": None,
    # And the CDC's MenB row, which said "from ten years" — the age the
    # *risk-based* recommendation begins, not the routine one. Its replacement
    # is seeded under a new code, so the old row has to stop applying or a
    # healthy twelve-year-old goes on being scheduled from it.
    "MENB-CDC-10Y": None,
    # The Egyptian pneumococcal table. Its numbers were ACIP's, under this
    # profile's name — see the note where it used to be. Retired rather than
    # merely deleted from the catalogue: seeding only ever adds, so a clinic
    # created last month would otherwise go on being scheduled by rows a
    # clinic created tomorrow never gets. Same program, same settings, two
    # answers depending on the install date, and no way to reproduce either.
    "PCV-EG-CU7": None,
    "PCV-EG-CU12": None,
    "PCV-EG-CU2Y": None,
    "PCV-EG-END": None,
    "PCV-EG-INF": None,
}


def retag_moved_bands():
    """Retire seeded schedule bands whose reference was corrected.

    Returns how many rows were changed. Deactivates rather than deletes: a
    clinic that has been scheduling from one of these can still see it in the
    editor, and a doctor who wants it back has a switch rather than a support
    call.

    Never touches a row a doctor authored or edited — only the ones this
    program seeded, still carrying the source it seeded them with.
    """
    changed = 0
    for code, moved_to in _RETAGGED_BANDS.items():
        for tpl in VaccineScheduleTemplate.query.filter_by(
                code=code, is_seeded=True).all():
            if moved_to is None:
                if tpl.is_active:
                    tpl.is_active = False
                    changed += 1
            elif tpl.source != moved_to:
                tpl.source = moved_to
                changed += 1
    return changed


def backfill_brand_facts():
    """Fill the blank regulatory facts on trade names that already exist.

    A column added by a migration is created empty, and nothing fills these
    until somebody re-seeds the catalogue — which happens from ``upgrade-db``
    and from a button on the vaccinations screen, and therefore not at all in
    a clinic that pulls the new code and restarts.

    Measured on a real register, and it is not cosmetic: with
    ``max_age_final_dose_days`` blank, rotavirus has no finish ceiling, so a
    child of ten who had one dose as an infant reads *overdue* instead of
    *expired* and joins the reminder list. Forty-eight of them, on one screen,
    for a course no clinic on earth can still give them.

    Narrower than :func:`seed_vaccines` on purpose. It creates nothing — no
    vaccine, no trade name, no schedule — so it cannot re-add a product a
    clinic deleted or ignore the catalogue toggles by the back door. It only
    answers the question the migration left open: this column is empty, and
    the catalogue knows what belongs in it.

    Blanks only, so a clinic that corrected a ceiling for its own stock keeps
    the correction. Returns the number of brands touched.
    """
    with open(os.path.abspath(_DATA_PATH), encoding="utf-8") as fh:
        data = json.load(fh)

    filled = 0
    for v in data["vaccines"]:
        vaccine = Vaccine.query.filter_by(code=v["code"]).first()
        if vaccine is None:
            continue                # this clinic does not carry it
        for b in v["brands"]:
            brand = next((br for br in vaccine.brands if br.name == b["name"]),
                         None)
            if brand is None:
                continue            # not stocked here, and not ours to add
            before = {f: getattr(brand, f, None) for f in _BRAND_FACTS}
            _fill_brand_facts(brand, b)
            if any(getattr(brand, f, None) != before[f] for f in _BRAND_FACTS):
                filled += 1
    return filled


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
                scope_max_age_days=v.get("scope_max_age_days"),
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
            if (v.get("scope_max_age_days")
                    and vaccine.scope_max_age_days is None):
                vaccine.scope_max_age_days = v["scope_max_age_days"]
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
        # The CDC's routine position, which is a conversation rather than a
        # date: for a **healthy** adolescent of sixteen to twenty-three, MenB
        # is shared clinical decision-making — two doses six months apart,
        # preferred at sixteen to eighteen.
        #
        # It needs no status of its own. A course this clinic never began and
        # nobody agreed to is already a *suggestion by age*: offerable at a
        # visit, never late, because "late" is a broken promise and there is
        # no promise until the doctor and the family make one. Agreeing to it
        # is what turns it into a due date — which is what shared decision-
        # making is, written down.
        #
        # This row used to say "from ten years", and ten is where the *risk-
        # based* recommendation begins — a different thing, and not one this
        # program may compute. That schedule depends on the indication and on
        # the product and can be a three-dose primary series; the catalogue
        # cannot know why a child is at risk, and a confident dated course for
        # a child who needed something else is the worst way to be wrong. So
        # ten to fifteen is deliberately unscheduled here, and a child that age
        # with a dose already on file reaches the doctor as a question.
        #
        # Stored beside the European bands rather than replacing them: the
        # clinic picks which guideline it follows in settings, and switching
        # recomputes from the doses already on file without re-entering one.
        # An Egyptian clinic is not covered by this row at all — MenB is not
        # in the national programme, so the label answers, and the label
        # schedules Bexsero from two months.
        {"code": "MENB-CDC-16Y", "min": 192, "max": 287, "sort_order": 0,
         "brand": "Bexsero", "source": "cdc",
         "label": "CDC — 16–23 سنة (يُفضّل 16–18): قرار طبي مشترك — "
                  "جرعتان بفاصل 6 شهور — للمراجعة",
         "doses": [(192, None), (198, 180)]},
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
        # ------------------------------------------------ the catch-up rule
        #
        # Decided explicitly: *"PCV -> age-based catch-up rule, not PCV ->
        # continue the infant series up to sixteen years."* A healthy child who
        # reaches two years after an earlier dose is no longer in a baby's
        # course, and the number of doses they owe is read from the age they
        # are **now** and what they have already had.
        #
        # These rows are on the vaccine and not a trade name: a catch-up is
        # the guideline's, and it applies to whichever pneumococcal is in the
        # fridge. What a *product* licenses — its own age range and doses —
        # stays on the brand, further down, where a clinic's correction
        # already lives. Keeping those two apart was the instruction.
        #
        # **Every one of them is tagged with the guideline that says it.** The
        # ceiling used to be tagged `manufacturer`, and the comment that stood
        # here admitted why: the engine loads the leaflet set plus the chosen
        # profile's, so a row tagged `cdc` is invisible to a clinic following
        # anything else, and tagging it honestly would have changed nothing on
        # the screen that reported the bug. That was a rule about five-year-
        # olds smuggled in as a fact about a leaflet, and it applied to clinics
        # that had never chosen it. It is stated by the CDC below and by the
        # Egyptian set above it, because both references say it — and if one
        # of them ever stops saying it, one table changes and the other does
        # not, which is the entire point of a profile.
        #
        # ### Why each set is a *whole* table
        #
        # A band whose source is the chosen profile makes that profile
        # authoritative for the product, and its silence about an age then
        # means "no course at this age" rather than "ask the leaflet". Measured
        # twice: seeding the ceiling alone under `cdc` blanked the infant
        # series for every baby in a CDC clinic. So a profile that says
        # anything here has to say everything here — from the first infant
        # dose to the age the routine course ends. There is no half-table.
        #
        # ### Which age each band is matched on
        #
        # The infant series is matched on the age at the **first dose** and
        # sits last, and both halves of that are load-bearing. A nine-month-old
        # two doses into the series started at two months is not a catch-up
        # case — they are mid-course, and matching on their age today would
        # move them onto a shorter one. Matching on the start keeps them where
        # they are. Sitting last keeps a three-year-old who started at two
        # months *off* it: the catch-up bands are read first and one of them
        # answers for them.
        #
        # The catch-up bands are matched on the age **today**, which is the
        # opposite of HPV and deliberately: HPV locks at the first dose so a
        # birthday between doses cannot add a third, and a catch-up re-reads
        # the child every time, because that is what a catch-up is.
        #
        # ### What is deliberately not here
        #
        # The two late-start courses are matched on the age at the **first
        # dose**, and read as "this is the course a child who started here
        # follows" rather than "this is what a child of this age with an empty
        # record needs". With no doses on file that is the same thing, because
        # the age at a first dose that has not happened is the age today.
        #
        # Written the other way first — matched on today's age and capped at
        # zero previous doses — and it broke the commonest case there is: a
        # child given the first dose of the 7–11 month catch-up stopped
        # matching the band the moment they had it, fell through every other
        # one, and came back as "clinical review required" for the ordinary
        # act of starting a course. Three existing tests caught it. A child
        # halfway through a course the reference plainly describes is not a
        # case the reference is silent about.
        #
        # A record the reference genuinely does not reach — a first dose at an
        # age no band begins at — still falls through, and the profile being
        # authoritative turns that into clinical review by name rather than a
        # guess. That is the instruction kept where it belongs: *do not invent
        # a dose count the reference did not state.*
        #
        # Nor is a dose ever computed as "required minus recorded". Every band
        # below reads the age now, the doses on file and the intervals between
        # them, and a catch-up's doses are numbered **after** what the child
        # already has — see :func:`_catch_up_course`.

        # -------- the Egyptian programme, which is what this clinic follows
        #
        # It has no pneumococcal rows here, and that is the whole entry.
        #
        # Pneumococcal is not in the national programme, and no Egyptian
        # clinical reference states a catch-up — the Drug Authority's
        # assessment of a marketing application carries the manufacturer's own
        # table, reviewed and approved, which is the leaflet with a different
        # letterhead. So the profile does not invent one, and it does not
        # borrow another body's under its own name either. It says nothing,
        # and the loader's ordinary fallback hands the question to the
        # product's leaflet — which is what an Egyptian paediatrician is
        # working from in any case.
        #
        # **And that is not a silent fallback, which is the thing worth being
        # careful about.** Every band the leaflet answers with opens with the
        # trade name — "Prevenar 13 — بدء 7–11 شهر…" — so a doctor reading
        # "3 doses" can see whose three, on the card, without being told to go
        # and check a setting.
        #
        # An earlier version of this file put ACIP's numbers here under a bare
        # Egyptian label. That is the failure this note exists to prevent: a
        # settings screen reading "you follow the Egyptian programme" over
        # another body's rules leaves a clinic unable to audit its own
        # practice.

        # ------------------------------------------------- and the WHO's
        #
        # WHO's routine is **2p+1** — two primary doses and a booster — which
        # is a genuinely different course from the CDC's 3p+1, and the reason
        # a clinic gets to choose between them at all. The ages are the ones
        # already reviewed and seeded as this program's WHO routine; they are
        # not re-decided here.
        #
        # The end of the course is what this set was added for. The position
        # paper is *"Pneumococcal conjugate vaccines in infants and children
        # under 5 years of age"* — five is where its scope stops, and a clinic
        # following it was being handed a fourth infant dose for a healthy
        # ten-year-old because the rule lived somewhere else.
        #
        # **What is deliberately missing is the catch-up, and WHO is the one
        # who says so.** On a child of 12–23 months the position paper's own
        # words are that "current data are insufficient for a firm
        # recommendation on the optimal number of doses (1 or 2) required".
        # It recommends catch-up in the one-to-five year range and does not
        # fix the number. There is no honest way to write "1 or 2" as a course,
        # and writing either of them would be this program inventing a
        # clinical number and attributing it to WHO — which is the one thing
        # every band in this file exists not to do.
        #
        # So a child who starts in that range reaches the doctor instead: with
        # doses on file the record is marked for clinical review by name, and
        # without any it is an empty course rather than a guess. That is a
        # real gap and it is WHO's gap, not the program's.
        {"code": "PCV-WHO-END", "min": 60, "max": None, "sort_order": 0,
         "match_on": "today", "source": "who", "catch_up": True,
         "label": "WHO — 5 سنوات فأكثر: خارج نطاق التوصية (الوثيقة عن "
                  "الأطفال أقل من 5 سنوات) — للمراجعة",
         "doses": []},
        # Read **after** the infant series, which is the opposite of the two
        # sets above and follows from what the bands are. Theirs are catch-ups
        # with dose counts, so a child of three who began at two months has to
        # be caught by the catch-up before the infant band can put them back on
        # a baby's course. This one has no count at all — it is a question —
        # and a child who began under a year is not a question: they are on
        # WHO's 2p+1 and the booster is stated. So the series answers first,
        # and this catches only the children it did not reach.
        #
        # One to five years, which WHO recommends and does not quantify. The
        # band carries no doses and asks for the doctor — see `needs_review`.
        # Writing "1" or writing "2" here would be this program inventing a
        # clinical number and putting WHO's name on it.
        {"code": "PCV-WHO-CU", "min": 12, "max": 59, "sort_order": 2,
         "match_on": "today", "source": "who",
         "catch_up": True, "review": True,
         "label": "WHO — 12–59 شهر: التطعيم التعويضي موصى به، والعدد "
                  "(جرعة أو جرعتان) لم تحسمه الوثيقة — قرار الطبيب",
         "doses": []},
        {"code": "PCV-WHO-INF", "min": None, "max": 11, "sort_order": 1,
         "source": "who",
         "label": "WHO — بدء قبل 12 شهر: جرعتان أساسيتان ومنشّط "
                  "(2p+1، المنشّط 9–18 شهر) — للمراجعة",
         "doses": [(2, None), (4, 28), (9, None)]},

        # ------------------------------------------------------- the CDC's
        #
        # ACIP's catch-up for a healthy child, as supplied: three doses from
        # 7–11 months with no valid doses (≥4 weeks, then ≥8 weeks, and the
        # last of them not before the first birthday); two doses from 12–23
        # months with none (≥8 weeks); one dose from 24–59 months to complete;
        # and no routine course from five years.
        {"code": "PCV-CDC-CU7", "min": 7, "max": 11, "sort_order": 0,
         "source": "cdc",
         "label": "CDC — 7–11 شهر بدون جرعات صحيحة: 3 جرعات "
                  "(≥4 أسابيع ثم ≥8 أسابيع)، والأخيرة بعد إتمام 12 شهر "
                  "— للمراجعة",
         "doses": [(7, None), (8, 28), (12, 56)]},
        {"code": "PCV-CDC-CU12", "min": 12, "max": 23, "sort_order": 1,
         "source": "cdc",
         "label": "CDC — 12–23 شهر بدون جرعات صحيحة: جرعتان بفاصل "
                  "≥8 أسابيع — للمراجعة",
         "doses": [(12, None), (14, 56)]},
        {"code": "PCV-CDC-CU2Y", "min": 24, "max": 59, "sort_order": 2,
         "match_on": "today", "source": "cdc",
         "catch_up": True, "previous_max": 3,
         "label": "CDC — 2–4 سنوات (سليم) وأقل من 4 جرعات: جرعة واحدة "
                  "لاستكمال الناقص — للمراجعة",
         "doses": [(24, None)]},
        {"code": "PCV-CDC-END", "min": 60, "max": None, "sort_order": 3,
         "match_on": "today", "source": "cdc", "catch_up": True,
         "label": "CDC — 5 سنوات فأكثر (سليم): انتهى الجدول الروتيني — "
                  "لا جرعات إلا بقرار طبيب — للمراجعة",
         "doses": []},
        {"code": "PCV-CDC-INF", "min": None, "max": 6, "sort_order": 4,
         "source": "cdc",
         "label": "CDC — بدء قبل 7 شهور: 4 جرعات (2، 4، 6، 12–15 شهر) "
                  "— للمراجعة",
         "doses": [(2, None), (4, 28), (6, 28), (12, 56)]},

        # ----------------------------------- Prevenar 13's own catch-up
        #
        # Measured as a hole this branch opened, and the worst kind: moving
        # the guideline rules out of the leaflet set left a clinic that
        # explicitly follows the leaflet with **no** pneumococcal catch-up at
        # all, so it fell back to the brand's raw dose rows and started
        # chasing a six-year-old for three more infant doses. That is the
        # screen this whole line of work began with, arriving again by the
        # door the fix opened.
        #
        # The leaflet has never been silent about it. Pfizer's own catch-up
        # table for a previously unvaccinated child is three doses from 7–11
        # months, two from 12–23 at least two months apart, and one from two
        # years — the same table the FDA prints, and the same shape Merck
        # gives for Vaxneuvance below. It simply was not written down here.
        #
        # On the brand and not the vaccine, because that is what it is: a
        # statement about this product, in this leaflet. Synflorix stops at
        # five years and says something different, and a rule copied across
        # them would be wrong for one of them.
        #
        # The SmPC adds a sentence worth repeating: schedules for Prevenar 13
        # "should be based on official recommendations". The leaflet is what a
        # product can do, not what a country has decided to do — which is
        # exactly why these rows are tagged `manufacturer` and are not
        # borrowed by `egypt`.
        {"code": "PCV13-CU7", "previous": "none", "min": 7, "max": 11,
         "sort_order": 10, "brand": "Prevenar 13",
         "label": "Prevenar 13 — بدء 7–11 شهر بدون جرعات سابقة: 3 جرعات، "
                  "الأخيرة في السنة الثانية — للمراجعة",
         "doses": [(7, None), (8, 28), (12, 56)]},
        {"code": "PCV13-CU12", "previous": "none", "min": 12, "max": 23,
         "sort_order": 11, "brand": "Prevenar 13",
         "label": "Prevenar 13 — بدء 12–23 شهر بدون جرعات سابقة: جرعتان "
                  "بفاصل ≥شهرين — للمراجعة",
         "doses": [(12, None), (14, 56)]},
        # Two years and over, and matched on today's age with a cap on what
        # is already on file rather than on `previous: none`.
        #
        # The leaflet's row says "previously unvaccinated", and read that
        # narrowly a six-year-old with a single infant dose matches nothing —
        # and falls straight back to the four-dose infant series, which is the
        # bug. Read as what the leaflet actually does and does not ask for, it
        # is clearer: nowhere does this label tell anybody to give a
        # six-year-old the rest of a baby's course. One dose is the most it
        # asks of a child this age, and a child who has already had four is
        # complete and matches nothing here.
        {"code": "PCV13-CU2Y", "min": 24, "max": 215, "sort_order": 12,
         "match_on": "today", "brand": "Prevenar 13",
         "catch_up": True, "previous_max": 3,
         "label": "Prevenar 13 — سنتين فأكثر (حتى 17 سنة) وأقل من 4 جرعات: "
                  "جرعة واحدة — للمراجعة",
         "doses": [(24, None)]},
        # Beyond the licensed age the label has nothing to say, and saying
        # nothing is the honest answer rather than the infant series.
        {"code": "PCV13-END", "min": 216, "max": None, "sort_order": 13,
         "match_on": "today", "brand": "Prevenar 13", "catch_up": True,
         "label": "Prevenar 13 — 18 سنة فأكثر: خارج العمر المرخّص للمستحضر "
                  "— للمراجعة",
         "doses": []},

        # ------------------------------------- and the product's own leaflet
        {"code": "PCV15-INF", "min": 1, "max": 6, "sort_order": 6,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 6 أسابيع–6 شهور: 4 جرعات — للمراجعة",
         "doses": [(2, None), (4, 28), (6, 28), (12, 60)]},
        {"code": "PCV15-CU7", "previous": "none", "min": 7, "max": 11, "sort_order": 7,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 7–11 شهر بدون PCV سابق: 3 جرعات — للمراجعة",
         "doses": [(7, None), (8, 28), (12, 60)]},
        {"code": "PCV15-CU12", "previous": "none", "min": 12, "max": 23, "sort_order": 8,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء 12–23 شهر: جرعتان بفاصل ≥شهرين — للمراجعة",
         "doses": [(12, None), (14, 60)]},
        {"code": "PCV15-CU2Y", "previous": "none", "min": 24, "max": None, "sort_order": 9,
         "brand": "Vaxneuvance",
         "label": "Vaxneuvance — بدء سنتين فأكثر: جرعة واحدة — للمراجعة",
         "doses": [(24, None)]},
    ],
    # MenACWY, where the three conjugates disagree with each other about
    # nearly everything. They are licensed from different ages — 6 weeks for
    # Nimenrix, 2 months for Menveo, 9 months for Menactra — and the number of
    # doses a child needs depends on which product they are on as much as on
    # how old they were when they started. One schedule on the vaccine could
    # only ever be right for one of them, and the catalogue's Arabic prose
    # said so in three different sentences that nothing read.
    #
    # Mencevax is deliberately absent. It is a polysaccharide, one dose from
    # two years, and its `doses_change_by_start_age` is already False — so it
    # falls through to the vaccine's own schedule, which is what it wants.
    "MENACWY": [
        # Menactra: 9–23 months is two doses, ≥3 months apart; from two years
        # it is one.
        {"code": "MCV4-MENACTRA-INF", "min": 9, "max": 23, "sort_order": 0,
         "brand": "Menactra",
         "label": "Menactra — بدء 9–23 شهر: جرعتان بفاصل ≥3 شهور — للمراجعة",
         "doses": [(9, None), (12, 90)]},
        {"code": "MCV4-MENACTRA-2Y", "min": 24, "max": None, "sort_order": 1,
         "brand": "Menactra",
         "label": "Menactra — بدء سنتين فأكثر: جرعة واحدة — للمراجعة",
         "doses": [(24, None)]},

        # Menveo: a four-dose infant series from two months, a two-dose
        # catch-up for a child who reaches 7–23 months with nothing, and a
        # single dose from two years. The catch-up asks for an empty record
        # because that is what the leaflet asks: a nine-month-old already two
        # doses into the infant series is not "unvaccinated 7–23 months", and
        # moving them onto a two-dose course would shorten it by half.
        {"code": "MCV4-MENVEO-INF", "min": 1, "max": 6, "sort_order": 2,
         "brand": "Menveo",
         "label": "Menveo — بدء 2–6 شهور: 4 جرعات (2، 4، 6، 12 شهر) — للمراجعة",
         "doses": [(2, None), (4, 60), (6, 60), (12, 60)]},
        {"code": "MCV4-MENVEO-CU7", "previous": "none",
         "min": 7, "max": 23, "sort_order": 3,
         "brand": "Menveo",
         "label": "Menveo — بدء 7–23 شهر بدون جرعات سابقة: جرعتان، "
                  "الثانية في السنة الثانية وبفاصل ≥3 شهور — للمراجعة",
         "doses": [(7, None), (13, 90)]},
        {"code": "MCV4-MENVEO-2Y", "min": 24, "max": None, "sort_order": 4,
         "brand": "Menveo",
         "label": "Menveo — بدء سنتين فأكثر: جرعة واحدة — للمراجعة",
         "doses": [(24, None)]},

        # Nimenrix: from 6 weeks, and the only one of the three whose infant
        # course is two primary doses plus a booster in the second year.
        {"code": "MCV4-NIMENRIX-INF", "min": 1, "max": 5, "sort_order": 5,
         "brand": "Nimenrix",
         "label": "Nimenrix — بدء 6 أسابيع–5 شهور: جرعتان بفاصل ≥شهرين "
                  "+ منشّط عند 12 شهر — للمراجعة",
         "doses": [(2, None), (4, 60), (12, 60)]},
        {"code": "MCV4-NIMENRIX-6M", "previous": "none",
         "min": 6, "max": 11, "sort_order": 6,
         "brand": "Nimenrix",
         "label": "Nimenrix — بدء 6–11 شهر: جرعة + منشّط عند 12 شهر "
                  "بفاصل ≥شهرين — للمراجعة",
         "doses": [(6, None), (12, 60)]},
        {"code": "MCV4-NIMENRIX-12M", "min": 12, "max": None, "sort_order": 7,
         "brand": "Nimenrix",
         "label": "Nimenrix — بدء 12 شهر فأكثر: جرعة واحدة — للمراجعة",
         "doses": [(12, None)]},
    ],
    # Influenza, where "one dose a year" is right for almost everybody and
    # wrong for the child in front of you having their first ever flu shot: a
    # first-time recipient under nine needs a second dose four weeks later, in
    # the same season, and only then one a year for life.
    #
    # The catalogue said so in Arabic prose — "أول مرة تحت 9 سنوات: جرعتان
    # بفاصل 4 أسابيع، ثم جرعة واحدة سنوياً" — and every seasonal code path in
    # this module assumed a seasonal course was exactly one dose, so the
    # second one had nowhere to appear.
    #
    # Matched on the age at the first dose, like every other band, which is
    # also what the rule means: a child who begins at eight does not lose the
    # second dose by turning nine four weeks later.
    "FLU": [
        # Under nine and already has two doses behind them from earlier
        # seasons: primed, and one dose a year from here. Ordered first
        # because it is the exception to the band below it.
        {"code": "FLU-PRIMED", "min": None, "max": 107, "sort_order": 0,
         "previous_min": 2,
         "label": "تحت 9 سنوات وسبق أخذ جرعتين: جرعة واحدة سنوياً — للمراجعة",
         "doses": [(6, None)]},
        # Under nine with fewer than two doses in their whole life — none, or
        # one from any season. Two doses **this** season, four weeks apart.
        {"code": "FLU-PRIME", "min": None, "max": 107, "sort_order": 1,
         "previous_max": 1,
         "label": "تحت 9 سنوات وأقل من جرعتين في حياته: جرعتان بفاصل "
                  "≥4 أسابيع هذا الموسم — للمراجعة",
         "doses": [(6, None), (7, 28)]},
        {"code": "FLU-ANNUAL", "min": 108, "max": None, "sort_order": 2,
         "label": "9 سنوات فأكثر: جرعة واحدة سنوياً — للمراجعة",
         "doses": [(6, None)]},
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
                   first_gap_max_days=None, previous_doses_min=None,
                   previous_doses_max=None, match_age_on="start",
                   starts_fresh=False, needs_review=False):
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
        previous_doses_min=previous_doses_min,
        previous_doses_max=previous_doses_max,
        match_age_on=match_age_on,
        starts_fresh=starts_fresh,
        needs_review=needs_review,
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
                first_gap_max_days=band.get("gap_max"),
                previous_doses_min=band.get("previous_min"),
                previous_doses_max=band.get("previous_max"),
                match_age_on=band.get("match_on", "start"),
                starts_fresh=band.get("catch_up", False),
                needs_review=band.get("review", False))

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

# The window has shut: this dose can never be given now. **Two** words,
# because there are two deadlines — one for beginning a series and one for
# finishing it — and the moment the second one was introduced, every place
# that had written `== "expired"` went on offering the other half. The
# certificate did exactly that: a two-year-old was printed a rotavirus
# suggestion again, with a due date from when they were two months old.
# `out_of_scope` joins them because it shuts a course for the same practical
# purpose — nothing is owed and nothing is offered — while saying something
# different about why. A certificate that reprinted either as outstanding
# would be asking a family for a dose nobody can act on.
SHUT = ("expired", "not_eligible", "out_of_scope")


def _status(due_date, given, today, closed_after=None, cannot_start=False,
            scope_after=None):
    """What this dose is, for this child, today.

    ``closed_after`` is the last date the dose could still be given — the
    brand's ceiling projected onto this child's birthday. Past it the dose is
    **expired**, not overdue: the difference is the whole point. "Overdue" asks
    somebody to chase it, and the rotavirus series cannot be given to a
    three-year-old at all, so chasing it is asking the desk to make a call that
    ends in "no". Before this, every child past the window read as overdue on
    rotavirus for the rest of their childhood.

    ``scope_after`` is the different sentence: the last date this *schedule*
    still describes the patient — see :attr:`Vaccine.scope_max_age_days`. Past
    it a dose is **out of scope**, which is not a claim that it cannot be
    given. It says the reference this clinic follows stops here and the
    question belongs to the doctor, which for MMR and an adult is the true
    answer where "expired" would be a false one.
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
    # Read after the product's own ceiling and before everything else. A
    # patient past both is past the stronger of the two, and "this vial may
    # not be given to you" is the more useful thing to be told.
    if scope_after is not None and today > scope_after:
        return "out_of_scope"
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


# Returned in place of a band when the guideline the clinic follows speaks
# about this product and none of its bands reaches this child.
#
# It is not the same as "no course", which is what an empty band says on
# purpose — the routine schedule ends at five and nothing more is owed. This
# is the other thing entirely: the reference was asked and did not answer.
# Fourteen months old with a single dose given at thirteen is the case that
# named it; ACIP's catch-up table states what a child of that age with **no**
# valid doses needs and says nothing about that one.
#
# Both readings come out as an empty course, and telling them apart is the
# whole point. "Nothing is owed" is an answer a family can be given. "The
# reference does not reach this child" is a question for the doctor, and it
# reaches them as Clinical Review Required rather than as a quiet blank.
SILENT = {"silent": True, "doses": []}


def _course_start(bands, brand_first, given_dates):
    """Which "first dose" these bands are matched against.

    A **leaflet's** bands are about a product, so the date that decides them is
    the first dose *of that product*. A child who had two Prevenar and moved to
    Vaxneuvance moves onto the Vaxneuvance schedule that suits their age at the
    switch — they neither stay on the schedule their first needle put them on
    nor start again, because the doses already given count.

    A **guideline's** bands are about the vaccine, and the date that decides
    them is the child's first pneumococcal dose whatever was in the vial.
    Reading a guideline band against the brand's first dose is how that same
    child — two Prevenar at two and four months, Vaxneuvance at nine — came out
    as "started at nine months", matched none of the guideline's bands, and
    was handed a clinical-review flag for the ordinary act of changing
    product. Measured: three existing tests, and the case is a common one.

    For a course on one product throughout the two dates are the same, which is
    why HPV still locks at its own first dose.
    """
    course_first = min((d for d in given_dates.values() if d), default=None)
    if bands and bands[0]["brand_id"] is not None and brand_first is not None:
        return brand_first
    return course_first


def _pick_band(bands, dob, start, previous, today, first_gap=None,
               given_count=0):
    """The first band whose age range and history condition both match.

    Returns the **band**, not its doses: the caller needs to know whether it
    is a catch-up, and asking twice is how the answer to two questions comes
    from two different bands.

    Both halves, because the leaflets name them together. "Unvaccinated 7 to
    <12 months" is not an age; it is an age **and** an empty record, and a
    child switching product at nine months with two doses behind them belongs
    to neither half of it.
    """
    at_start = _months_between(dob, start or today)
    now = _months_between(dob, today)
    for band in bands:
        # Which age this band is matched on — see `match_age_on` on the model.
        months = now if band.get("match_on") == "today" else at_start
        low = band["min"] if band["min"] is not None else -10 ** 6
        high = band["max"] if band["max"] is not None else 10 ** 6
        if not low <= months <= high:
            continue
        needs = band.get("previous")
        if needs == "none" and previous:
            continue
        if needs == "some" and not previous:
            continue
        # "…and has had fewer than two before" is a real leaflet condition and
        # not expressible as none/some. Influenza needs it: under nine, a
        # child with no doses and a child with one both need two this season,
        # and a child with two needs one. A pneumococcal catch-up needs it the
        # other way — one dose to complete, but not for a child who is already
        # complete.
        #
        # Counted over the child's whole record: `previous` alone is what came
        # before *this brand*, which is zero for nearly everybody, so a
        # condition written against it would never fire. `given_count` is what
        # is on file for the course being scheduled, and the two together are
        # how many doses this child has had.
        total = previous + given_count
        if band.get("previous_max") is not None and total > band["previous_max"]:
            continue
        if band.get("previous_min") is not None and total < band["previous_min"]:
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
        return band
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


def _catch_up_course(rota, given_dates, default_doses):
    """A catch-up's doses, numbered **after** what is already on file.

    The first attempt at this emptied the slots, the way a season does. It
    scheduled correctly and was wrong everywhere else: with no given doses in
    the course, the child's file stopped showing the dose they had had, and
    the reminder path — which will not chase a course nobody started here —
    skipped them entirely. The two paths disagreed, and the test that holds
    them to the same answer is what said so.

    A season can empty its slots because last winter's dose belongs to last
    winter. A catch-up cannot: the earlier doses are part of this same course
    and stay on the record. So the catch-up's dose is simply the *next* one —
    number three for a child who has had two — which is also what it is called
    when somebody gives it.
    """
    if not given_dates:
        return rota
    offset = max(given_dates)
    ages = dict(default_doses or ())
    kept = [(number, ages.get(number, 0)) for number in sorted(given_dates)]
    return kept + [(number + offset, age) for number, age in rota]


def course_for(vaccine, brand, dob, given_dates, today=None,
                 brand_first=None, previous=0):
    """``(dose ages, the band that decided them)`` for this child's course.

    The band comes back because the caller has to know whether it is a
    catch-up — a course whose doses are additional to what is on file — and
    picking it twice is how the answer to two questions comes from two
    different bands.

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
        return default, None

    bands = _bands_for(vaccine.id, brand.id)
    if not bands:
        return default, None

    # When *this brand's* course started, not when the child's first ever dose
    # was. Stated by the doctor and it is the whole correction: a child who
    # had two Prevenar and moves to Vaxneuvance "moves to the Vaxneuvance
    # schedule that suits their age and state at the point of switching" —
    # they do not stay on the schedule their first needle put them on, and
    # they do not start again either, because the doses already given count.
    #
    # For a course on one product throughout these are the same date, which is
    # why HPV still locks at its first dose.
    # A vaccine given again every year does not have one lifelong course; it
    # has a course a season, and the band has to be matched against the season
    # being asked about. See :func:`_season_start`.
    if vaccine.is_seasonal:
        start = _season_start(given_dates, today or local_today())
    else:
        start = _course_start(bands, brand_first, given_dates)
    picked = _pick_band(bands, dob, start, previous, today or local_today(),
                        first_gap=_achieved_first_gap(given_dates),
                        given_count=len(given_dates))
    if picked is not None:
        return picked["doses"], picked
    # The guideline speaks about this product and says nothing about a child
    # this age — under the CDC, Bexsero simply is not scheduled below ten
    # years. Falling back to the brand's raw dose rows would answer with a
    # number from no guideline at all, which is worse than either. An empty
    # course is the honest reading: this reference does not schedule it.
    if any(b.get("authoritative") for b in bands):
        return [], SILENT
    return default, None


def schedule_for(vaccine, brand, dob, given_dates, today=None,
                 brand_first=None, previous=0):
    """The dose ages this child's course follows — see :func:`course_for`."""
    return course_for(vaccine, brand, dob, given_dates, today,
                      brand_first=brand_first, previous=previous)[0]


def _bands_for(vaccine_id, brand_id):
    """The bands this child's course follows, in the order that decides them.

    Four pools, most specific first:

      1. the chosen guideline, about this trade name;
      2. the chosen guideline, about the vaccine;
      3. the leaflet, about this trade name;
      4. the leaflet, about the vaccine.

    **The guideline comes before the leaflet**, and that ordering is the fix
    for a bug measured rather than argued about. It used to be brand before
    vaccine and nothing else — a trade name's schedule replaced the vaccine's,
    because a leaflet is a complete statement about that product and mixing
    half of it with a generic one is how a course ends up with a dose from
    neither. That is sound between two leaflets. It is not sound between a
    leaflet and the reference the clinic has chosen.

    Writing Pfizer's pneumococcal catch-up down — which belongs on the brand,
    and which a clinic following the leaflet needs — silently replaced the
    Egyptian and CDC tables for every child on that vial, because it is the
    default one. The five-year ceiling vanished, and a partial record the
    reference deliberately declines to guess at came back with an invented
    date. A clinic that follows the CDC wants the CDC's catch-up whichever
    vial is in the fridge; the leaflet is what answers where its reference
    says nothing about the product at all.

    Within a pool, a band with no doses is kept, and that is what makes "no
    routine course at this age" sayable. An active row with an age range and
    nothing in it has exactly one meaning — this reference schedules nothing
    here — and dropping it as malformed is what left a healthy sixteen-year-
    old being chased for the rest of a baby's pneumococcal series.
    """
    banded = _banded_templates().get(vaccine_id, [])
    if not banded:
        return []
    profile = guideline_profile()
    for ours in (True, False):
        for want_brand in (brand_id, None):
            picked = [b for b in banded
                      if (b["source"] == profile) is ours
                      and b["brand_id"] == want_brand]
            if picked:
                return picked
    return []


def guideline_profile():
    """Which published guideline this clinic follows, from settings.

    A policy, not a code path. The same product can have two published
    positions — Bexsero's course is the European label's from two months and
    the CDC's from ten years — and a clinic changing which it follows should
    change a setting, not a program.

    Unset, it is the Egyptian programme: this is an Egyptian clinic, and the
    reference it follows should not have to be chosen before the first child
    is seen. An unrecognised value falls back the same way rather than
    raising — a settings row edited by hand must not be able to stop the
    vaccination screen from rendering.
    """
    from app.models import VaccineScheduleTemplate

    try:
        from app.models import Setting
        chosen = (Setting.get("vaccine_guideline_profile", "") or "").strip()
    except Exception:  # noqa: BLE001 - settings table not ready yet
        chosen = ""
    if chosen in VaccineScheduleTemplate.GUIDELINE_PROFILES:
        return chosen
    return VaccineScheduleTemplate.DEFAULT_GUIDELINE_PROFILE


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
                # Which reference this band came from. Carried through rather
                # than inferred later: "which guideline is this clinic
                # actually being scheduled by" is a question worth being able
                # to answer from the answer itself.
                "source": template.source,
                # And what the rule says, in the words it was written in. The
                # loader carried everything needed to *apply* a band and
                # nothing needed to *explain* one, so the screens could show a
                # dose count and never whose.
                "label": template.label,
                "authoritative": template.source == profile != "manufacturer",
                "min": template.start_age_min_months,
                "max": template.start_age_max_months,
                "brand_id": template.brand_id,
                "previous": template.requires_previous_doses,
                "gap_min": template.first_gap_min_days,
                "gap_max": template.first_gap_max_days,
                "previous_min": template.previous_doses_min,
                "previous_max": template.previous_doses_max,
                "match_on": template.match_age_on or "start",
                "catch_up": bool(template.starts_fresh),
                "review": bool(template.needs_review),
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
    # More doses on file than the schedule has room for. Never asked about a
    # vaccine that repeats — four influenza doses are four winters.
    "more_than_scheduled": "جرعات أكثر مما يسمح به الجدول",
    # The child's own record contradicts the order of the schedule.
    "out_of_order": "تواريخ الجرعات مش بترتيب أرقامها",
}


def needs_clinical_review(dob, schedule, given_rows, repeatable=False):
    """Why this course cannot be scheduled, or None.

    ``given_rows`` are ``(dose_number, given_date)`` for the doses on file.
    ``repeatable`` says this vaccine is given again and again rather than as a
    course of fixed length — a seasonal one, or an on-demand one.

    Deliberately narrow. It looks for records the arithmetic cannot be run on
    at all — not for anything a doctor might want a second opinion about,
    which would put the flag on everybody and teach the clinic to ignore it.

    ``repeatable`` is that promise being kept rather than an exception to it.
    Influenza is one dose in the catalogue and a child of five has had four,
    which is not a contradiction — it is four winters. Measured before this
    argument existed: every returning influenza patient in the register read
    "clinical review required", and because the flag also stops the message,
    their annual recall went silent. A flag that fires on the ordinary case is
    worse than no flag, and here it was worse than that.
    """
    if dob is None:
        return "undated_dose" if given_rows else None
    numbers = [n for n, _d in given_rows]
    if any(d is None for _n, d in given_rows):
        return "undated_dose"
    if len(numbers) != len(set(numbers)):
        return "duplicate_dose"
    if schedule and not repeatable and len(numbers) > len(schedule):
        return "more_than_scheduled"
    ordered = [d for _n, d in sorted(given_rows, key=lambda r: r[0] or 0)]
    if any(b < a for a, b in zip(ordered, ordered[1:])):
        return "out_of_order"
    return None


def course_dates(dob, schedule, given, planned, min_interval,
                 earliest_live, closed_after, today, start_closed_after=None,
                 scope_after=None):
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
    started = any(d for d in given.values())
    cannot_start = bool(
        start_closed_after is not None
        and not started
        and today > start_closed_after)
    # Scope cannot un-promise a course somebody began. "Our schedule does not
    # describe you" is a true thing to say to an adult with an empty record;
    # said to an adult whose first MMR was given here at five it would be this
    # clinic dropping the second dose of its own series, and CDC's position is
    # that the two-dose series is completed at any age. The same line the
    # stale-date rule draws, drawn once more: a promise outlives the scope of
    # the reference that suggested it.
    if started:
        scope_after = None
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
                                         cannot_start=cannot_start,
                                         scope_after=scope_after))
    return out



def _credit_other_courses(given_index):
    """Add the doses one vaccine's course borrows from another. See
    :class:`VaccineCredit`.

    A doctor reported a child with the three government pentavalent doses and
    a hexavalent booster reading as *"Hexavalent — Dose 1, overdue since
    2024"*. The two vaccines are separate rows and nothing said one continues
    the other, so three doses that happened counted for nothing.

    The credited entry is **the real record of the dose that was given** —
    the pentavalent row, with its own date and its own product — not a
    stand-in. So the card shows what actually happened, and the fix cannot
    become the other kind of lie, a course reading as complete with nothing
    behind it.

    A dose recorded against the vaccine itself always wins. The credit fills
    a gap; it never covers something that is already there.
    """
    from app.models import VaccineCredit

    credits = VaccineCredit.query.all()
    if not credits:
        return given_index
    by_source = {}
    for credit in credits:
        by_source.setdefault(credit.from_vaccine_id, []).append(credit)
    for (vaccine_id, dose_number), pv in list(given_index.items()):
        for credit in by_source.get(vaccine_id, ()):
            if not credit.covers(dose_number):
                continue
            given_index.setdefault((credit.vaccine_id, dose_number), pv)
    return given_index

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

    # Doses given as another vaccine that this clinic has said continue this
    # one's course — the government pentavalent before a hexavalent booster.
    # Filled in after the real rows so a dose actually recorded against this
    # vaccine always wins: a credit stands in for a dose that is missing, and
    # must never overwrite one that is there.
    given_index = _credit_other_courses(given_index)

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
        # And the other kind of ceiling: how far this schedule describes
        # anybody at all. Per vaccine and not per brand, because it is a
        # property of the reference rather than of what is in the fridge —
        # CDC's child-and-adolescent schedule ends at eighteen whichever MMR
        # a clinic stocks.
        scope_after = None
        if dob and vaccine.scope_max_age_days:
            scope_after = dob + timedelta(days=vaccine.scope_max_age_days)
        # And an agreement is a promise too — the same rule that lets an
        # agreed course be *late* before a single dose exists. The doctor and
        # the family settled on this one; the reference's range is not a
        # reason to stop carrying it.
        if vaccine.id in (agreed or ()):
            scope_after = None
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
        if vaccine.is_seasonal:
            # A winter's course is that winter's. See :func:`_this_season`.
            given_dates, previous = _this_season(given_dates, today)
            if not given_dates:
                # …and a season nobody has begun begins now. Without this the
                # first dose is dated from the child's *age* — dob plus six
                # months — so a sixteen-year-old reads "dose 1, overdue since
                # 2016". Nobody can act on a missed 2016 flu season; what is
                # true is that this child needs one this winter.
                #
                # Only when the season is empty. A child half-way through
                # their priming pair is genuinely late for the second dose,
                # and that date is computed from the first one, this season.
                earliest_live = max(earliest_live or today, today)
        rota, band = course_for(vaccine, brand, dob, given_dates, today,
                                brand_first=brand_first, previous=previous)
        if band is not None and band.get("catch_up"):
            # A catch-up says how many doses are owed **now**. Its doses are
            # numbered after what is on file — see :func:`_catch_up_course` —
            # and the floor below is what makes them due now rather than at an
            # age this child passed years ago.
            rota = _catch_up_course(
                rota, given_dates,
                [(d.dose_number, d.age_months) for d in brand.doses])
            earliest_live = max(earliest_live or today, today)
        # Before anything is computed from these dates, whether they can be
        # computed from at all.
        # From the raw rows, not from `given_index`: that is keyed by
        # (vaccine, dose number) and so a duplicated number collapses into one
        # entry — the very thing being looked for disappears on the way in.
        review = needs_clinical_review(
            dob, rota,
            [(pv.dose_number, pv.given_date) for pv in rows
             if pv.vaccine_id == vaccine.id
             and (pv.event_type or "given") == "given"],
            repeatable=bool(vaccine.is_seasonal or vaccine.on_demand))
        # The reference was asked about this child and did not answer — see
        # :data:`SILENT`. Only once there is something on file: a child with no
        # doses at an age their guideline does not schedule is not a puzzle,
        # they are simply not due anything, and the vaccine already reads as a
        # suggestion for their age. It is the doses already given that make an
        # empty answer a question rather than a statement.
        if band is SILENT and given_dates and not review:
            review = "guideline_silent"
        # The reference speaks about a child this age and does not say how
        # much — see `needs_review` on the model. Unlike the silence above
        # this one applies with an empty record too, because the whole point
        # is that the guideline *does* recommend something here.
        if band is not None and band.get("review") and not review:
            review = "guideline_unsettled"
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
                               start_closed_after=start_closed_after,
                               scope_after=scope_after)

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
                # The product **this dose** was given as, which is not always
                # the card's product. A course can change brand halfway — a
                # child with three Synflorix and a Prevenar booster has one of
                # each on file — and the card named only the latest, so the
                # record read as four Prevenar. The dose knows; it was simply
                # never asked.
                "brand_name": (pv.brand.display_name(lang)
                               if pv is not None and pv.brand else None),
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
        doses.extend(_doses_off_the_schedule(vaccine, brand, rows, doses,
                                             lang, band=band))
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
        # A seasonal course is begun once, not once a winter.
        #
        # The doses above are **this** season's — see :func:`_this_season` —
        # so a child who had influenza last winter and has not come yet this
        # one has nothing marked `done`, and read from that alone their annual
        # recall came out as a suggestion by age rather than something owed.
        # It is owed. They are this clinic's patient for it, the promise was
        # made the first time somebody vaccinated them here, and a new season
        # does not unmake it.
        #
        # Measured as a disagreement between the two paths: the register-wide
        # sweep asks whether anything is on file *before* the season is
        # narrowed and so has always listed these children, while the child's
        # own file said nothing about them. Two answers to "does this child
        # need a flu vaccine", one on the work-list and one on the record the
        # family is shown.
        if not started and vaccine.is_seasonal:
            started = any(row.given_date
                          for (vid, _n), row in given_index.items()
                          if vid == vaccine.id)
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
            # Whether a schedule band actually answered for this course. The
            # "doses vary with the starting age" warning exists to admit that
            # the program does not know; once a band for this product has been
            # read out of a leaflet and seeded, it does know, and going on
            # warning turns a real caution into wallpaper.
            "banded": bool(_bands_for(vaccine.id, brand.id)) if brand else False,
            # **Which rule produced these dates, in its own words.**
            #
            # The engine has always known and never said. A doctor looking at
            # "3 doses" could not tell whether that came from the reference
            # their clinic follows, from the vial's leaflet because the
            # reference is silent about the product, or from the brand's own
            # rows because nothing banded applies — three different degrees of
            # authority, one identical number on the card.
            #
            # It matters most exactly where this program is least certain. The
            # Egyptian profile states no pneumococcal schedule, so a child's
            # pneumococcal dates come from the product's leaflet; that is a
            # sound answer and a *borrowed* one, and a fallback the reader
            # cannot see is a number from nowhere.
            "rule": (band or {}).get("label") if isinstance(band, dict) else None,
            "rule_source": ((band or {}).get("source")
                            if isinstance(band, dict) else None),
            # Set when the record cannot be scheduled from. The screens show
            # it in place of a due date, because a date computed from a
            # contradiction is worse than no date.
            "review": review,
            "agreed": vaccine.id in (agreed or ()),
            "committed": started or vaccine.id in (agreed or ()),
            "done": sum(1 for x in doses if x["status"] == "done"),
            "total": len(doses),
        })
    # Which dose dates the screens may print. Marked here rather than worked
    # out in the template so the banner and the dose rows cannot drift apart —
    # the same rule read twice in two languages is how this file has already
    # once had one screen disagree with another about the same child.
    for item in plan:
        for d in item["doses"]:
            d["stale_date"] = stale_projection(d, today)
    return plan


# The shelves a vaccination plan actually falls onto, in the order a doctor
# works through them. Order matters: it is the whole feature.
PLAN_GROUPS = ("started", "ready", "complete", "later", "closed")


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
      * ``closed``   — never began and the product's own licensed age has
                       passed. Split out of ``later`` because that shelf is
                       headed *"too early"* and these are the opposite: a
                       patient of twenty-nine was reading "not yet time" over
                       the infant hexavalent.

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
        elif doses and all(d["status"] in SHUT for d in doses):
            # Every dose past the product's own licensed age. Not "not yet".
            shelves["closed"].append(item)
        else:
            shelves["later"].append(item)
    return [(key, shelves[key]) for key in PLAN_GROUPS if shelves[key]]


# Which shelves open on arrival. History and not-yet-due are both true and
# both noise at the moment somebody is deciding what to give today.
#
# `ready` joined them on request, and the file that prompted it shows why: a
# patient with no doses on this clinic's record has *every* age-appropriate
# course on that shelf — nineteen of them on the screen reported — so the one
# thing the doctor came for, the courses already under way and owing a dose
# today, was pushed off the bottom of a wall of suggestions. Nothing is
# hidden: the counter at the top of the page still says how many there are,
# and the heading carries the count next to it. It just no longer opens over
# the answer.
OPEN_GROUPS = {"started"}


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
        # Which products this course was actually given as, in the order they
        # were used. `item["brand"]` is the *chosen* brand — the latest dose's
        # — and printing it over the whole card is how three Synflorix and a
        # Prevenar booster came to read as four Prevenar. A card names one
        # product only when one product is the truth; otherwise the doses say
        # it themselves, each for itself.
        names = []
        for dose in given:
            name = dose.get("brand_name")
            if name and name not in names:
                names.append(name)
        cards.append({
            "vaccine": item["vaccine"],
            "brand": item["brand"] if len(names) < 2 else None,
            "brands": names,
            "mixed": len(names) > 1,
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
         "expired": 0, "not_eligible": 0, "out_of_scope": 0, "national": 0,
         "on_demand": 0, "total": 0}
    for v in plan:
        for d in v["doses"]:
            s[d["status"]] = s.get(d["status"], 0) + 1
            s["total"] += 1
    return s


# The statuses that mean somebody actually promised this dose: a course
# started at this clinic, or one the doctor and the family agreed on. Only
# these have a due date that is an appointment; everything else has a date
# that is an age projected onto a birthday.
PROMISED = ("due", "overdue", "upcoming")


def stale_projection(dose, today=None):
    """Is this dose's date an age projected onto a birthday, already gone by?

    Every unpromised status — ``suggested``, ``national``, ``on_demand``, and
    the two shut windows — means, in this file's own words, that *neither is a
    course this clinic ever promised*. Its due date is not an appointment;
    nobody agreed to it. It is the age the schedule states, run through the
    patient's birthday. Which is a true fact about arithmetic and, once the
    date is behind us, a useless one about medicine.

    Reported from a real file: a woman of twenty-nine, never vaccinated at
    this clinic, whose screen offered nineteen doses and announced the next
    one as the hexavalent's first — *"at 2 months"*, dated **1997**.

    **Nothing about what is offered turns on this.** A three-year-old who
    never had varicella is still owed a catch-up, and withdrawing the offer on
    the strength of a passed date would be this program inventing an upper age
    it does not know: thirty-seven of the catalogue's forty-eight products
    carry no finish ceiling at all, and guessing one for each is exactly the
    kind of clinical number nothing in this file is allowed to make up. What
    changes is only whether a screen prints the projected date, and whether
    the "next due" banner is allowed to answer with one. The age band stays on
    every row, and it is the sentence the schedule actually makes.

    :data:`PROMISED` is the exception and it is the whole distinction. A dose
    somebody started a course for, or agreed to, has a real appointment, and
    an appointment missed in March is still an appointment — the date is
    exactly what the doctor needs.
    """
    if dose.get("given_date") or dose.get("status") in PROMISED:
        return False
    due = dose.get("due_date")
    if not due:
        return False
    return str(due) < (today or local_today()).isoformat()


def next_due_dose(plan):
    """Return the most urgent not-yet-given dose (overdue first, then due).

    A suggestion whose recommended age has already passed is never the answer.
    The banner over this reads *"the next due vaccination"*, and a dose from
    1997 is neither next nor due; with nothing else to name, the honest line is
    the one that says nothing is outstanding.
    """
    candidates = []
    for v in plan:
        for d in v["doses"]:
            if d["status"] in GIVEABLE and not stale_projection(d):
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
        # "Did this clinic take this course on" — asked of the plan, which
        # knows, rather than recomputed from the doses left in front of us.
        # For a seasonal vaccine those are **this** season's, so a child who
        # had influenza last winter had nothing marked `done` and was dropped
        # here before the annual recall below could ever be reached. For every
        # other vaccine the two questions have the same answer.
        if not v.get("committed"):
            continue
        if vac.is_seasonal:
            # The course before the recall — see the same split in `scan_due`.
            # A first influenza dose under nine owes a second four weeks
            # later, and until this was written no seasonal path could say so.
            nxt = next((d for d in v["doses"]
                        if d["status"] in ("overdue", "due")), None)
            if nxt:
                out.append({"vaccine": vac, "brand": brand,
                            "dose_number": nxt["dose_number"],
                            "due_date": nxt["due_date"], "status": nxt["status"]})
                continue
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


def _doses_off_the_schedule(vaccine, brand, rows, rendered, lang="ar",
                            band=None):
    """Recorded doses whose number the course does not contain.

    **The schedule decides what to offer; the record decides what to show.**
    The loop above walks the course — the brand's dose rows, or the age band
    that replaced them — and looks each number up among what was given. A dose
    recorded outside that range is never looked up, so it is never drawn: the
    row sits in the database and no screen in the program mentions it.

    Reported from a clinic, on the hexavalent: a booster recorded as dose 4
    against a three-dose schedule. The program had first filed it as dose 1,
    which is wrong but visible; corrected to 4, it **disappeared entirely** —
    from the file, the certificate and the panel — and adding a fourth row to
    the catalogue afterwards did not bring it back, because the course for a
    child who already started is the one their band or their brand fixed.

    A vaccination that happened is not the schedule's to disown. These rows
    carry ``off_schedule`` so a screen can say what they are — a booster, an
    extra dose, or a number somebody typed wrongly and can now see to fix —
    rather than the program deciding for itself that it never happened.

    **Not for a course that repeats.** Influenza numbers doses across a
    lifetime — a fifth winter is dose 5 — while the season's course has slots
    one and two, and :func:`_this_season` deliberately renumbers into them. On
    a repeatable course "a number the schedule does not contain" is the normal
    state of every past winter, not a booster; sweeping them in listed three
    previous seasons as this season's doses and told a child who had their
    shot three weeks ago that they still needed one. Caught by the flu tests,
    which is what they are for.

    **And not when a band chose the course.** An age band is a deliberate
    statement about which doses this child's course consists of — "switching
    in at 12–23 months is two doses", or a guideline saying nothing at all
    about a product at three months. The doses outside it are not lost: they
    are the history that *picked* the band, counted as ``previous``. Adding
    them back as course slots turned a two-dose switch course into three and
    put a dose under a guideline that schedules none. Caught by the band tests
    in CI, which is what they are for.

    So this applies where the fault was: a course taken straight from the
    brand's own dose rows, where a number past the end of that list has
    nowhere else in the program to live.
    """
    if band is not None:
        return []
    if vaccine.is_seasonal or vaccine.on_demand:
        return []
    seen = {row["dose_number"] for row in rendered}
    extra = []
    for pv in rows:
        if pv.vaccine_id != vaccine.id:
            continue
        if (pv.event_type or "given") != "given":
            continue
        if pv.dose_number in seen:
            continue
        seen.add(pv.dose_number)
        extra.append({
            "dose_number": pv.dose_number,
            # The course says nothing about this dose, so neither does this:
            # an age label invented for it would be the program guessing at a
            # schedule it has just been told it does not have.
            "age_months": None,
            "age_label": "",
            "booster": is_booster(brand, pv.dose_number),
            "due_date": None,
            "given_date": pv.given_date.isoformat() if pv.given_date else None,
            "lot_number": pv.lot_number,
            "doctor": pv.doctor.display_name(lang) if pv.doctor else None,
            "outside": bool(pv.given_outside),
            "outside_place": pv.outside_place,
            "pv_id": pv.id,
            "imported": bool(getattr(pv, "import_batch_id", None)),
            # It happened. Whatever the schedule thinks of the number, the
            # child had this dose and every screen reads this word.
            "status": "done",
            "planned": False,
            "event_type": None,
            "event_reason": None,
            # The one thing that separates it from the rest, so a screen can
            # mark it instead of quietly showing a fourth dose of three.
            "off_schedule": True,
        })
    return sorted(extra, key=lambda row: row["dose_number"])


def visit_vaccine_panel(patient, lang="ar"):
    """Vaccine snapshot for the visit tab, framed as *what can I give now* —
    no "overdue" alarms (we can't know what was given elsewhere).

    Returns dict with:
      * ``received``  — vaccines the child already has doses of (neutral history)
      * ``give_now``  — optional, age-appropriate vaccines in stock (administer)
      * ``out_of_stock`` — optional, age-appropriate but no stock (schedule / PO)
      * ``next_optional`` — the soonest optional dose still ahead, or None
    Mandatory (EPI) and on-demand (rabies/travel) vaccines are excluded from the
    suggestions; the doctor adds those deliberately.

    **``next_optional`` exists because "nothing to give" is not an answer.** A
    two-day-old genuinely has no optional vaccine within reach — the first ones
    fall due at six weeks, and the due window is thirty days — but a panel that
    says only *no optional vaccine matches this age* reads as a program that
    lost the schedule. It names the next one and its date instead, which is
    what the parent is about to ask anyway.
    """
    today = local_today()
    plan = patient_plan(patient, lang)
    received, give_now, out_of_stock = [], [], []
    ahead = []
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
        if vac.is_seasonal and given and not any(
                d["status"] in GIVEABLE for d in v["doses"]):
            # ...unless the course itself still owes a dose. The second
            # influenza dose of a first season is four weeks after the first,
            # not eleven months, and a nurse looking at this panel is the
            # person who would otherwise never be told.
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
            # Not giveable today — but if it is merely early rather than over,
            # remember when it opens. This is the whole answer for a newborn,
            # and the panel used to throw it away.
            soon = next((d for d in v["doses"]
                         if d["status"] == "upcoming" and d["due_date"]), None)
            if soon:
                ahead.append({"vaccine": vac, "dose_number": soon["dose_number"],
                              "due_date": soon["due_date"]})
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
    return {"received": received, "give_now": give_now,
            "out_of_stock": out_of_stock,
            "next_optional": min(ahead, key=lambda e: e["due_date"]) if ahead else None}


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
                # Given again and again rather than as a course of fixed
                # length, so "more doses than the schedule" is not a
                # contradiction about it.
                "repeatable": bool(v.is_seasonal or v.on_demand),
                "min_interval": v.min_interval_days or _CATCH_UP_MIN_INTERVAL,
                "scope_max_age": v.scope_max_age_days,
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
        # Which vaccines continue which. Read here, with the rest of the
        # catalogue, because the sweep walks every vaccinated patient on file
        # and a table this small must not be asked for once per child — the
        # exact shape of the work-list slowness this cache exists to hold
        # down.
        credits = {}
        for credit in VaccineCredit.query.all():
            credits.setdefault(credit.from_vaccine_id, []).append(
                (credit.vaccine_id, credit.up_to_dose))
        return vaccines, brands, by_vaccine, credits

    return remember("vaccines:catalogue_rows", load)


def _this_season(given_dates, today):
    """The doses that belong to the season being scheduled, and the count of
    those that came before it.

    Returns ``(this_season, earlier)``.

    A course a child runs once in a lifetime accumulates: dose 1 is dose 1 for
    ever. A course they run every winter does not, and treating it the same
    way is what put *"dose 2 — overdue since 2024"* on the file of a
    five-year-old whose only flu shot was two and a half years ago. Their
    2022 dose had been dropped into slot 1 of **this** season's pair, and slot
    2 dated four weeks after it.

    That child does need two doses — under nine with fewer than two in their
    life — but they need them now, four weeks apart, not a slot filled by a
    dose from before they could talk.

    So the season's slots start empty each season, and the earlier doses do
    the one job that is theirs: deciding whether this season is one dose or
    two.
    """
    dated = sorted(d for d in given_dates.values() if d)
    if not dated:
        return given_dates, 0
    if (today - dated[-1]).days >= SEASONAL_RECALL_DAYS:
        return {}, len(dated)       # last season's; this one has not begun
    cutoff = dated[-1] - timedelta(days=SEASONAL_RECALL_DAYS)
    mine = sorted(d for d in dated if d > cutoff)
    # **Renumbered.** The record numbers doses across a lifetime — a fifth
    # winter is dose 5 — while the season's course has slots one and two. Keyed
    # by the stored number, this season's dose 5 matches no slot, and a child
    # who had their flu shot three weeks ago is told they still need one. That
    # is a worse failure than the stale date this function exists to fix: it
    # sends a family in for an injection they have already had.
    return {i: d for i, d in enumerate(mine, start=1)}, len(dated) - len(mine)


def _season_start(given_dates, today):
    """The first dose of the **current** season, or None if there is none.

    A repeating vaccine does not have one lifelong course; it has a course a
    year. The band that decides how many doses a season needs therefore has to
    be matched against the season being asked about, and "the first dose ever"
    is the wrong date the moment a child has a winter behind them.

    Measured on a real file: a boy of eleven with a single influenza dose from
    January 2019 was told he owed *the second dose of his priming pair, due
    February 2019*. He does owe a flu shot — seven winters of them — but the
    priming pair belongs to the season it started in, and at eleven he needs
    one dose, not the other half of something from when he was four.

    "Current" is measured from the latest dose, using the same recall gap the
    rest of the seasonal logic runs on: doses within a season of the newest
    one are this season's, and if the newest is itself older than that, this
    season has no doses at all.
    """
    dates = sorted(d for d in given_dates.values() if d)
    if not dates:
        return None
    if (today - dates[-1]).days >= SEASONAL_RECALL_DAYS:
        return None                 # last season's; this one has not begun
    cutoff = dates[-1] - timedelta(days=SEASONAL_RECALL_DAYS)
    return next((d for d in dates if d > cutoff), None)


def _banded_for(vaccine_id, brand_id, dob, given_dates, today,
                brand_first=None, previous=0, seasonal=False):
    """The banded schedule for this course, from plain values.

    The sweep's half of :func:`schedule_for`. Same rule, same table, same
    answer — matched on the age at the first dose, today's age before there is
    one — because a listing that picks a different schedule from the child's
    own file is two programs disagreeing about a course.
    """
    if dob is None:
        return None, None
    bands = _bands_for(vaccine_id, brand_id)
    if not bands:
        return None, None
    if seasonal:
        start = _season_start(given_dates, today)
    else:
        start = _course_start(bands, brand_first, given_dates)
    picked = _pick_band(bands, dob, start, previous, today,
                        first_gap=_achieved_first_gap(given_dates),
                        given_count=len(given_dates))
    if picked is None and any(b.get("authoritative") for b in bands):
        return [], SILENT
    return (picked["doses"] if picked else None), picked


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
    vaccines, brands, by_vaccine, credits = _catalogue_rows()

    given = {}          # vaccine_id -> {dose_number: given_date}
    brand_doses = {}    # vaccine_id -> [(brand_id, given_date)]
    raw_doses = {}      # vaccine_id -> [(dose_number, given_date)], duplicates kept
    planned = {}        # vaccine_id -> {dose_number: date}
    locked = {}         # vaccine_id -> brand_id of the earliest given dose
    live_given = {}
    for vaccine_id, brand_id, dose_number, given_date, event_type in doses:
        if (event_type or "given") == "given":
            given.setdefault(vaccine_id, {})[dose_number] = given_date
            # A dose given as one vaccine that continues another's course —
            # the government pentavalent before a hexavalent booster. This
            # path is the lean twin of `patient_plan` and **must answer
            # identically**: crediting only there would leave the child's own
            # file saying "done" while the desk's work-list still called the
            # same dose overdue. `setdefault` so a dose actually recorded
            # against the target vaccine always wins.
            for target_id, up_to in credits.get(vaccine_id, ()):
                if up_to is None or (dose_number and dose_number <= up_to):
                    given.setdefault(target_id, {}).setdefault(
                        dose_number, given_date)
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
                                 raw_doses.get(vaccine_id, []),
                                 repeatable=meta.get("repeatable", False)):
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
        # The same scope ceiling the patient's own file reads. Both paths or
        # neither: a work-list that chases what the file says is nobody's to
        # chase is exactly the disagreement this pair of functions exists to
        # avoid.
        scope_after = (dob + timedelta(days=meta["scope_max_age"])
                       if dob and meta.get("scope_max_age") else None)
        earliest_live = None
        if meta["live"]:
            others = [d for vid, d in live_given.items() if vid != vaccine_id]
            if others:
                earliest_live = max(others) + timedelta(days=LIVE_SPACING_DAYS)

        brand_first = min((d for (bid, d) in brand_doses.get(vaccine_id, [])
                           if bid == brand["id"] and d), default=None)
        previous = sum(1 for (_bid, d) in brand_doses.get(vaccine_id, [])
                       if d and (brand_first is None or d < brand_first))
        if meta["seasonal"]:
            mine, previous = _this_season(mine, today)
            if not mine:
                earliest_live = max(earliest_live or today, today)
        rota, band = _banded_for(vaccine_id, brand["id"], dob, mine, today,
                                 brand_first=brand_first, previous=previous,
                                 seasonal=meta["seasonal"])
        if band is not None and band.get("catch_up"):
            rota = _catch_up_course(rota, mine, brand["doses"])
            earliest_live = max(earliest_live or today, today)
        if rota is None:
            rota = brand["doses"]
        timings = course_dates(dob, rota, mine,
                               planned.get(vaccine_id, {}),
                               meta["min_interval"], earliest_live,
                               closed_after, today,
                               start_closed_after=start_closed_after,
                               scope_after=scope_after)

        if meta["seasonal"]:
            # A seasonal course is one dose a year for almost everybody, and
            # the code here read that as "a seasonal course is one dose". It
            # is not: a child under nine having their first influenza vaccine
            # owes a second one four weeks later, in the same season. So the
            # course is asked about first and the annual recall is what
            # happens when the course has nothing pending — which for a
            # returning patient is immediately, exactly as before.
            pending = next((n for n, _age in rota
                            if timings[n][1] in ("overdue", "due")), None)
            if pending is not None:
                due, status = timings[pending]
                out.append({"vaccine": meta["obj"], "brand": brand["obj"],
                            "dose_number": pending,
                            "due_date": due.isoformat() if due else None,
                            "status": status})
                continue
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
