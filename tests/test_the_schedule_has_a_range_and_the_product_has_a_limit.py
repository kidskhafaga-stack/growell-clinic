"""Two ceilings that were wearing one name.

`VaccineBrand.max_age_final_dose_days` is a fact about a **product**: past it
the vial may not be given, and the dose reads `expired` — "انتهت مدته". The
infant hexavalent at twenty-nine is that.

`Vaccine.scope_max_age_days` is a fact about a **reference**: past it the
schedule this clinic follows simply stops covering the patient, and the dose
reads `out_of_scope` — "خارج نطاق الجدول". MMR at twenty-nine is that, and the
difference is not decorative: CDC's position is that anyone twelve months or
older who is due an MMR should have one, so calling it expired would be the
program telling somebody a window had shut when it had not.

The distinction came out of a review of the four vaccines still without an
upper age. It proposed eighteen years for MMR, IPV and MenACWY from CDC's
child-and-adolescent schedule, and then said the thing that mattered: *"الـ18
هو فقط سقف محرك الـpediatric catch-up"* — the ceiling of a paediatric
catch-up engine, not a limit on the vaccine. Same number, two meanings, and
the wrong column costs somebody a vaccine.

**What is written, and what deliberately is not.**

MMR and MenACWY carry eighteen years. BCG carries nothing, which the review
itself recommended: WHO gives it as an infant dose and neither WHO nor the
ministry publishes a number that could serve as a catch-up ceiling.

OPV and IPV also carry nothing, and that is a departure from the review worth
recording. Its own OPV number — under five — is drawn from the ministry's
*campaign* targeting, which is a statement about who is swept up in a
national round, not about the age at which a child stops being caught up. A
six-year-old behind on polio is a real clinical question and "outside the
schedule" is the wrong sentence for it. The review made the better point
itself: OPV and IPV are one polio series in the Egyptian programme and want
one engine, not two independent ceilings. Until that exists, neither gets a
number.

**And scope never un-promises.** A course started here, or agreed with the
family, keeps its remaining doses however far outside the reference's range
the patient has travelled. That is the same line drawn for stale dates one
commit earlier, and it is the line that makes this safe: the reference's range
governs what is *suggested*, never what was *promised*.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402

# 18 × 365.25 — the range of CDC's child and adolescent immunization schedule.
EIGHTEEN_YEARS = 6575


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


_COUNTER = [0]


def _statuses(seeded, years, code, agreed_codes=()):
    """The dose statuses of one course for somebody of `years`."""
    from app.extensions import db
    from app.models import Patient, Vaccine
    from app.utils.vaccines import patient_plan

    _COUNTER[0] += 1
    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(years * 365.25))
        person = Patient(patient_number=f"SC{_COUNTER[0]}", full_name="مريض",
                         gender="female", date_of_birth=dob, is_active=True)
        db.session.add(person)
        db.session.commit()
        agreed = [Vaccine.query.filter_by(code=c).first().id
                  for c in agreed_codes]
        row = next(v for v in patient_plan(person, agreed=agreed)
                   if v["vaccine"].code == code)
        return [d["status"] for d in row["doses"]]


# ------------------------------------------------ the two sentences are two

def test_a_reference_that_stops_is_not_a_product_that_expired(seeded):
    """The whole point of the second column, on one patient.

    Both of these courses are shut for a twenty-nine-year-old and they are shut
    for different reasons, so they say different things. Asserting them
    together is deliberate: a change that collapsed the two back into one
    status would satisfy either half alone.
    """
    assert set(_statuses(seeded, 29, "HEXA")) == {"expired"}, \
        "the infant hexavalent is licensed to under-sevens — that is expiry"
    assert set(_statuses(seeded, 29, "MMR")) == {"out_of_scope"}, \
        ("MMR has no upper age; the paediatric schedule does. Calling it "
         "expired tells an adult a window shut that never did")


@pytest.mark.parametrize("code", ["MMR", "MENACWY"])
@pytest.mark.parametrize("years,inside", [(17, True), (18.5, False)])
def test_the_range_ends_at_eighteen(seeded, code, years, inside):
    """Both sides of the boundary, so "there is a ceiling" and "the ceiling is
    in the right place" fail separately."""
    statuses = _statuses(seeded, years, code)

    if inside:
        assert "out_of_scope" not in statuses, \
            f"a {years}-year-old is inside the schedule's range and lost {code}"
    else:
        assert set(statuses) == {"out_of_scope"}, \
            f"a {years}-year-old is past the range and still carries {code}"


# --------------------------------------------------- scope never un-promises

def test_a_course_started_here_is_finished_here(seeded):
    """An adult whose first MMR was given at this clinic at five.

    The reference's range is a statement about who it describes, not a licence
    to abandon a series somebody began. CDC completes the two-dose series at
    any age, and dropping the second dose because the patient turned eighteen
    would be this clinic quietly breaking its own promise.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import GIVEABLE, patient_plan

    with seeded["app"].app_context():
        mmr = Vaccine.query.filter_by(code="MMR").first()
        brand = (VaccineBrand.query.filter_by(vaccine_id=mmr.id)
                 .order_by(VaccineBrand.id).first())
        dob = local_today() - timedelta(days=int(20 * 365.25))
        grown = Patient(patient_number="SCstarted", full_name="مريض",
                        gender="female", date_of_birth=dob, is_active=True)
        db.session.add(grown)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=grown.id, vaccine_id=mmr.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(5 * 365.25))))
        db.session.commit()
        row = next(v for v in patient_plan(grown) if v["vaccine"].code == "MMR")

    assert [d["dose_number"] for d in row["doses"]
            if d["status"] in GIVEABLE], \
        "the second dose of a series this clinic began was dropped"
    assert not [d for d in row["doses"] if d["status"] == "out_of_scope"], \
        "a promised course was called out of scope"


def test_an_agreement_is_a_promise_too(seeded):
    """The same rule one step earlier. An agreed course can be *late* before a
    single dose exists — that is already how the engine treats it — so the
    reference's range must not quietly take it back either."""
    statuses = _statuses(seeded, 20, "MMR", agreed_codes=("MMR",))

    assert "out_of_scope" not in statuses, \
        f"a course the doctor and the family agreed on was withdrawn: {statuses}"


# ---------------------------------------- only what a named source supports

def test_only_the_two_reviewed_vaccines_carry_a_range(seeded):
    """The guard, and the reason this column is nearly always NULL.

    A blank here means "nothing published says where this stops", never
    "nobody got round to it". A number appearing on a third vaccine because it
    tidied a screen is the failure this pins.
    """
    from app.models import Vaccine

    with seeded["app"].app_context():
        scoped = {v.code: v.scope_max_age_days for v in Vaccine.query.all()
                  if v.scope_max_age_days}

    assert scoped == {"MMR": EIGHTEEN_YEARS, "MENACWY": EIGHTEEN_YEARS}, \
        f"the set of vaccines carrying a schedule range changed: {scoped}"


@pytest.mark.parametrize("code,why", [
    ("BCG", "WHO gives it as an infant dose and publishes no catch-up ceiling"),
    ("OPV", "the ministry's under-five number is campaign targeting, not "
            "catch-up scope"),
    ("IPV", "polio is one series with OPV and wants one engine, not two "
            "independent ceilings"),
])
def test_the_ones_left_blank_are_left_blank_on_purpose(seeded, code, why):
    """Named individually so that filling one in is a deliberate act with a
    test to change, rather than a quiet edit to a JSON file."""
    from app.models import Vaccine

    with seeded["app"].app_context():
        vaccine = Vaccine.query.filter_by(code=code).first()
        assert vaccine is not None, f"{code} is not in the catalogue"
        assert vaccine.scope_max_age_days is None, \
            f"{code} was given a range, but {why}"


# -------------------------------------------------------- what the screen says

def test_out_of_scope_shuts_the_course_without_claiming_it_expired(seeded):
    """It joins the shut statuses — nothing owed, nothing offered, and kept off
    the certificate's suggestion table — while keeping its own words."""
    from app.utils.vaccines import GIVEABLE, SHUT

    assert "out_of_scope" in SHUT
    assert "out_of_scope" not in GIVEABLE

    assert not set(_statuses(seeded, 29, "MMR")) & set(GIVEABLE)


def test_the_page_says_which_of_the_two_it_is(seeded):
    """Both badges on one screen, in the patient's own language. A shelf that
    said only "not for this age" would leave a doctor unable to tell a vial
    that cannot be used from a reference that stops."""
    import json

    from app.extensions import db
    from app.models import Patient

    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(29 * 365.25))
        grown = Patient(patient_number="SCpage", full_name="مريض",
                        gender="female", date_of_birth=dob, is_active=True)
        db.session.add(grown)
        db.session.commit()
        pid = grown.id

    page = seeded["sign_in"]("boss").get(
        f"/vaccinations/{pid}").get_data(as_text=True)

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        words = json.load(fh)["vstatus"]

    assert words["out_of_scope"] in page, \
        "the screen never says a course is outside the schedule's range"
    assert words["expired"] in page, \
        "the screen stopped distinguishing a product that cannot be given"


# ------------------------------------------------- and both paths carry it

def test_the_register_wide_sweep_reads_the_same_column(seeded):
    """The file and the work-list compute the same schedule through two
    loaders, and a fact one of them does not load is a disagreement waiting to
    be found in front of a family. The flat loader has been where that went
    wrong before."""
    from app.models import Vaccine
    from app.utils.vaccines import _catalogue_rows

    with seeded["app"].app_context():
        vaccines, _brands, _by_vaccine = _catalogue_rows()
        mmr = Vaccine.query.filter_by(code="MMR").first()
        assert vaccines[mmr.id]["scope_max_age"] == EIGHTEEN_YEARS, \
            "the sweep's loader does not carry the schedule's range"


def test_when_both_apply_the_product_answers_first(seeded):
    """A dose past both ceilings gets the stronger sentence.

    Nothing in the catalogue carries both today — the two live on different
    vaccines — so this is asserted on the rule directly rather than through a
    patient. Without it the ordering is a comment: swapping the two branches
    passes every other test in this file, and the day a product acquires both
    a licensed limit and a schedule range, an adult would be told the
    reference had stopped covering them when the truer answer is that the vial
    may not be given to them at all.
    """
    from datetime import date

    from app.utils.vaccines import _status

    dob = date(2000, 1, 1)
    today = date(2026, 1, 1)

    assert _status(date(2000, 3, 1), False, today,
                   closed_after=dob + timedelta(days=2557),
                   scope_after=dob + timedelta(days=EIGHTEEN_YEARS)) == "expired"
    # And each alone still says its own thing.
    assert _status(date(2000, 3, 1), False, today,
                   scope_after=dob + timedelta(days=EIGHTEEN_YEARS)) \
        == "out_of_scope"
    assert _status(date(2000, 3, 1), False, today,
                   closed_after=dob + timedelta(days=2557)) == "expired"


def test_a_clinic_that_upgrades_gets_the_column_and_its_values(seeded):
    """The delivery path, because a new column has been shipped empty here
    before.

    `max_age_final_dose_days` was added by a migration, filled by nobody, and
    a clinic that pulled the code and restarted kept scheduling rotavirus with
    no ceiling — children of ten in the reminder list for a course no clinic
    can give. The lesson was written down then: a column a migration adds is a
    column that migration should fill.

    So the whole of `upgrade-db` is exercised against an install from before
    this column existed: the schema pass re-adds it, and the catalogue seeder —
    which fills blanks only, so a clinic's own edit survives — puts the values
    in.
    """
    from sqlalchemy import text

    from app.extensions import db
    from app.models import Vaccine
    from app.utils.schema import apply_schema
    from app.utils.vaccines import seed_vaccines

    with seeded["app"].app_context():
        db.session.execute(
            text("ALTER TABLE vaccines DROP COLUMN scope_max_age_days"))
        db.session.commit()
        columns = [row[1] for row in
                   db.session.execute(text("PRAGMA table_info(vaccines)"))]
        assert "scope_max_age_days" not in columns, \
            "the before-state could not be reproduced"

        apply_schema(report=lambda _m: None)
        db.session.commit()
        columns = [row[1] for row in
                   db.session.execute(text("PRAGMA table_info(vaccines)"))]
        assert "scope_max_age_days" in columns, \
            "upgrade-db does not add the column at all"

        seed_vaccines()
        db.session.commit()
        filled = {v.code: v.scope_max_age_days for v in Vaccine.query.all()
                  if v.scope_max_age_days}

    assert filled == {"MMR": EIGHTEEN_YEARS, "MENACWY": EIGHTEEN_YEARS}, \
        f"the column arrived empty on a clinic that upgraded: {filled}"


def test_the_rule_itself_lives_in_one_function(seeded):
    """Both loaders hand it to the same place, so the rule cannot be written
    twice and drift."""
    from datetime import date

    from app.utils.vaccines import course_dates

    dob = date(2000, 1, 1)
    today = date(2026, 1, 1)
    timings = course_dates(dob, [(1, 12)], {}, {}, 28, None, None, today,
                           scope_after=dob + timedelta(days=EIGHTEEN_YEARS))

    assert timings[1][1] == "out_of_scope", \
        f"course_dates ignored the range it was handed: {timings}"
