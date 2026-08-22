"""The pneumococcal catch-up, as the guideline that states it states it.

Three things are being held here, and they came from three different
instructions.

**A catch-up is read from the age the child is now.** Not from "how many doses
does the course have, minus how many are on file" — that arithmetic is what
had a sixteen-year-old owing the rest of a baby's series. A healthy child who
reaches two years after an earlier dose is not behind in an infant course;
they are a two-year-old, and the guideline says what a two-year-old with that
history needs.

**Every rule is tagged with the reference that states it.** The five-year end
of the routine course used to be tagged `manufacturer`, which is to say it
applied to every clinic whichever guideline it had chosen, because that was
the only tag they would all read. It is a statement by a guideline. It now
lives in the guideline sets, and a clinic that follows one of them gets it
because it follows one of them.

**Where the reference does not reach, nothing is invented.** Fourteen months
old with one dose given at thirteen months is the case: the catch-up table
states what a child of that age with *no* valid doses needs, and says nothing
about that one. The course comes back empty and the record is marked for
clinical review — an empty course that means "nothing owed" and an empty
course that means "the reference did not answer" are different sentences and
the family gets the right one.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


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


def _child(seeded, profile, age_months, dose_ages):
    """A child of `age_months` whose PCV doses were given at `dose_ages`.

    Returns ``(review reason, [(dose number, status, due date)])``.
    """
    from app.extensions import db
    from app.models import (Patient, PatientVaccine, Setting, Vaccine,
                            VaccineBrand)
    from app.utils.vaccines import patient_plan

    _COUNTER[0] += 1
    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", profile)
        pcv = Vaccine.query.filter_by(code="PCV").first()
        # Prevenar 13 is the catalogue's default here and carries no bands of
        # its own, so the guideline's rows are what answer — which is the
        # thing under test.
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        dob = local_today() - timedelta(days=int(age_months * 30.44))
        kid = Patient(patient_number=f"CU{_COUNTER[0]}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, age in enumerate(dose_ages, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(age * 30.44))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        return row.get("review"), [(d["dose_number"], d["status"],
                                    d.get("due_date")) for d in row["doses"]]


def _owed(doses):
    from app.utils.vaccines import GIVEABLE

    return [n for n, status, _due in doses if status in GIVEABLE]


def _pending(doses):
    """Everything not already given — owed now or coming later."""
    return [n for n, status, _due in doses if status != "done"]


# ------------------------------------------------- the end of the course

@pytest.mark.parametrize("profile", ["egypt", "cdc"])
@pytest.mark.parametrize("age_months", [72, 120, 192])
def test_the_routine_course_has_ended_by_five(seeded, profile, age_months):
    """The reported bug, in the two profiles that now state the rule.

    A child of ten with three infant doses was being carried in the reminder
    list owing a fourth. Nobody gives a healthy ten-year-old the rest of a
    baby's pneumococcal series.
    """
    review, doses = _child(seeded, profile, age_months, [2, 4, 6])

    assert review is None, f"a plain record was flagged instead of read: {review}"
    assert _owed(doses) == [], \
        f"a healthy {age_months // 12}-year-old is still being chased: {doses}"


@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_the_doses_already_given_survive_the_end_of_the_course(seeded, profile):
    """A shut course still has to show what happened.

    Written as a catch-up with nothing in it rather than as an empty course,
    because an empty one dropped the record: a six-year-old's certificate lost
    the pneumococcal dose they were actually given.
    """
    _review, doses = _child(seeded, profile, 72, [2, 4, 6])

    assert [n for n, status, _due in doses if status == "done"] == [1, 2, 3], \
        f"the doses the child had disappeared with the course: {doses}"


# ------------------------------------------------------- the catch-up itself

@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_a_child_of_seven_to_eleven_months_with_nothing_needs_three(
        seeded, profile):
    review, doses = _child(seeded, profile, 9, [])

    assert review is None
    assert len(doses) == 3, f"the 7–11 month catch-up is not three doses: {doses}"


@pytest.mark.parametrize("profile", ["egypt", "cdc"])
@pytest.mark.parametrize("age_months", [7, 9, 11])
def test_the_last_dose_of_that_catch_up_is_never_before_the_first_birthday(
        seeded, profile, age_months):
    """The condition asked for by name: the final dose at twelve months or
    later, however early the catch-up begins.

    A course started at seven months and spaced only by its intervals lands
    the third dose at nine months, which does not count. The dose's own
    recommended age is the floor and the intervals are what push it later.
    """
    from datetime import date

    review, doses = _child(seeded, profile, age_months, [])
    assert review is None
    last_due = doses[-1][2]
    assert last_due is not None, f"the last dose has no date: {doses}"

    first_birthday = local_today() - timedelta(
        days=int(age_months * 30.44)) + timedelta(days=365)
    assert date.fromisoformat(str(last_due)) >= first_birthday, \
        (f"the catch-up's last dose falls at {last_due}, before the first "
         f"birthday on {first_birthday}")


@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_a_child_of_twelve_to_twenty_three_months_with_nothing_needs_two(
        seeded, profile):
    review, doses = _child(seeded, profile, 14, [])

    assert review is None
    assert len(doses) == 2, f"the 12–23 month catch-up is not two doses: {doses}"


@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_two_to_four_years_and_incomplete_is_one_more_dose(seeded, profile):
    """And *one more* — added to what is on file, not a one-dose course whose
    single slot the child's infant dose already fills, which reads as nothing
    owed."""
    review, doses = _child(seeded, profile, 36, [2, 4, 6])

    assert review is None
    assert len(_owed(doses)) == 1, f"not one additional dose: {doses}"
    assert [n for n, status, _d in doses if status == "done"] == [1, 2, 3]


@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_a_complete_four_dose_child_is_owed_nothing(seeded, profile):
    review, doses = _child(seeded, profile, 36, [2, 4, 6, 12])

    assert review is None
    assert _owed(doses) == [], f"a complete course was reopened: {doses}"


# ------------------------------------------- mid-series is not a catch-up

@pytest.mark.parametrize("profile", ["egypt", "cdc"])
@pytest.mark.parametrize("age_months,given", [(9, [2, 4]), (14, [2])])
def test_a_child_who_started_as_an_infant_stays_on_the_infant_series(
        seeded, profile, age_months, given):
    """The trap the ordering of the bands exists for.

    A nine-month-old two doses into a series begun at two months is not the
    "7–11 months, unvaccinated" case — they are mid-course. Matching the
    infant band on the age at the *first* dose keeps them there; putting it
    last keeps a three-year-old who began at two months off it.
    """
    review, doses = _child(seeded, profile, age_months, given)

    assert review is None
    assert len(doses) == 4, \
        f"a child mid-series was moved onto a shorter course: {doses}"
    assert _pending(doses) == list(range(len(given) + 1, 5))


# ------------------------------------------------ and where it does not reach

@pytest.mark.parametrize("profile", ["egypt", "cdc"])
def test_a_child_who_began_a_catch_up_is_owed_the_rest_of_it(seeded, profile):
    """Fourteen months old, one dose, given at thirteen.

    This one was written the other way round first, and the reversal is worth
    recording rather than quietly rewriting. The instruction was *do not guess
    the partial case*, and the bands were built to match on the age **today**
    with a cap of zero doses already given — read as "this is what a child of
    this age with an empty record needs".

    That broke the commonest case there is. A child given the first dose of
    the 7–11 month catch-up stopped matching the band the moment they had it,
    matched nothing else, and came back as *clinical review required* for the
    ordinary act of beginning a course. Three older tests caught it.

    And there is no honest line between the two: a nine-month-old with one
    dose given at nine months and a fourteen-month-old with one dose given at
    thirteen are the same shape. Either both are mid-course or both are
    unknowable, and flagging every child who has started is not a defensible
    reading of "do not guess".

    So the bands are matched on the age at the **first dose** — the course a
    child who started here follows — which with an empty record is the same
    thing, because the age at a first dose that has not happened is the age
    today. Not guessing still means something: a record no band can reach at
    all comes back as clinical review by name, which is what the next test
    holds.
    """
    review, doses = _child(seeded, profile, 14, [13])

    assert review is None, \
        f"a child part-way through a stated course was flagged: {review}"
    assert [n for n, status, _d in doses if status == "done"] == [1]
    assert len(_owed(doses)) == 1, \
        f"not the rest of the two-dose course: {doses}"


def test_a_record_no_band_can_reach_is_still_a_question(seeded):
    """"Do not guess" kept where it belongs.

    The CDC does speak about Bexsero and does not schedule a healthy
    twelve-year-old for it, so a twelve-year-old with a dose on file is a
    record its reference cannot carry forward. That comes back as clinical
    review rather than as a number from no guideline at all.
    """
    from app.extensions import db
    from app.models import (Patient, PatientVaccine, Setting, Vaccine,
                            VaccineBrand)
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", "cdc")
        menb = Vaccine.query.filter_by(code="MENB").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=menb.id,
                                             name="Bexsero").first()
        dob = local_today() - timedelta(days=int(12 * 365.25))
        kid = Patient(patient_number="CUsilent", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=menb.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(11 * 365.25))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "MENB")

    assert row.get("review") == "guideline_silent", \
        f"a record the reference cannot reach was answered anyway: {row}"


def test_an_unstarted_course_at_an_unscheduled_age_is_not_a_puzzle(seeded):
    """Silence with nothing on file is not a question.

    A sixteen-year-old who has never had a pneumococcal dose is not a record
    the guideline failed on — they are simply not due one. Flagging them would
    put the clinical-review badge on every teenager in the register, and a
    flag that fires on the ordinary case is worse than no flag.
    """
    review, doses = _child(seeded, "egypt", 192, [])

    assert review is None, f"an empty record was flagged: {review}"
    assert _owed(doses) == []


# ------------------------------------------------------- whose rule it is

def test_the_five_year_rule_is_no_longer_everybody_s(seeded):
    """It was tagged `manufacturer`, which every clinic reads whichever
    guideline it follows — so a rule from one reference was being applied to
    clinics that had chosen another. That was the instruction: move it.
    """
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        generic = VaccineScheduleTemplate.query.filter_by(
            vaccine_id=pcv.id, brand_id=None, is_active=True).all()
        sources = {t.source for t in generic
                   if t.start_age_min_months is not None
                   or t.start_age_max_months is not None}

    assert "manufacturer" not in sources, \
        f"a guideline's rule is still tagged as a leaflet's: {sources}"
    assert {"egypt", "cdc"} <= sources


def test_a_clinic_that_already_had_the_old_rows_stops_reading_them(seeded):
    """Seeding only ever adds — it keys on (vaccine, code, source) — so
    correcting a tag in the catalogue does nothing to the installs that
    already have the row. The upgrade has to retire it, or the ceiling goes on
    being everybody's rule for ever."""
    from app.extensions import db
    from app.models import Vaccine, VaccineScheduleDose, VaccineScheduleTemplate
    from app.utils.vaccines import retag_moved_bands

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        stale = VaccineScheduleTemplate(
            vaccine_id=pcv.id, code="PCV-ROUTINE-END", source="manufacturer",
            label="old", is_active=True, is_seeded=True,
            start_age_min_months=60, match_age_on="today", starts_fresh=True)
        db.session.add(stale)
        db.session.commit()
        stale_id = stale.id

        assert retag_moved_bands() >= 1
        db.session.commit()
        assert db.session.get(VaccineScheduleTemplate, stale_id).is_active is False

        # A second upgrade has nothing left to do.
        assert retag_moved_bands() == 0
        db.session.rollback()

        # And a row the doctor authored is not the program's to retire.
        mine = VaccineScheduleTemplate(
            vaccine_id=pcv.id, code="PCV-ROUTINE-END", source="custom",
            label="mine", is_active=True, is_seeded=False,
            start_age_min_months=60)
        db.session.add(mine)
        db.session.flush()
        db.session.add(VaccineScheduleDose(
            template_id=mine.id, dose_number=1, recommended_age_months=60))
        db.session.commit()
        mine_id = mine.id
        retag_moved_bands()
        db.session.commit()
        assert db.session.get(VaccineScheduleTemplate, mine_id).is_active is True
