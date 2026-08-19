"""A window that shuts, and a chase that stops when it does.

Rotavirus has to be finished by 24 weeks on RotaRix, 32 on RotaTeq and 34 on
Rotasiil. Synflorix stops at five years while every other pneumococcal keeps
going. None of that reached the plan: `max_age_months` sat on the *vaccine*,
was written by the seeder, and was read by nothing.

Measured before this: a three-year-old, a six-year-old and a sixteen-year-old
were all offered rotavirus, and would have gone on being offered it for the
rest of their childhood. The clinical rule was in the catalogue the whole time
— as Arabic prose in `catch_up_ar`, for a doctor to read with their eyes.

**Expired is not overdue.** The distinction is the feature. "Overdue" asks
somebody to chase it; a course that can no longer be given at all is not a
chase, it is a call that ends in "no". `GIVEABLE` excludes it, so it leaves the
visit panel and the reminders together.

**Per brand, not per vaccine.** The ceiling differs between trade names of the
same vaccine — 24 vs 32 weeks, Synflorix vs Prevenar — so one number on the
vaccine was wrong for six of them at once.

**In days.** 24 weeks is 5.5 months; rounding to a whole month either shuts the
window two weeks early or leaves it two weeks too long, on the one vaccine
where the window is the point.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def catalogue(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
    return clinic


def _aged(clinic, years=0, months=0, tag=""):
    from app.extensions import db
    from app.models import Patient

    dob = local_today() - timedelta(days=int(years * 365.25 + months * 30.4))
    kid = Patient(patient_number=f"W{tag or years}{months}", full_name="طفل",
                  gender="female", date_of_birth=dob, is_active=True)
    db.session.add(kid)
    db.session.commit()
    return kid


def _states(plan, code):
    for v in plan:
        if v["vaccine"].code == code:
            return v["brand"], [d["status"] for d in v["doses"]]
    raise AssertionError(f"{code} is not in the plan at all")


# ------------------------------------------------------- the ceiling itself

def test_the_catalogue_carries_a_ceiling_per_brand(catalogue):
    """24 / 32 / 34 weeks — three numbers for one vaccine."""
    from app.models import Vaccine, VaccineBrand

    with catalogue["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        got = {b.name: b.max_age_final_dose_days
               for b in VaccineBrand.query.filter_by(vaccine_id=rota.id)}

    assert got == {"RotaRix": 24 * 7, "RotaTeq": 32 * 7, "Rotasiil": 34 * 7}


def test_a_baby_inside_the_window_is_still_offered_it(catalogue):
    """The half that proves the rule did not simply switch the vaccine off."""
    from app.utils.vaccines import patient_plan

    with catalogue["app"].app_context():
        _brand, states = _states(patient_plan(_aged(catalogue, months=3)), "ROTA")

    assert "expired" not in states, "rotavirus was closed on a three-month-old"
    assert states[0] in ("suggested", "due", "overdue")


def test_a_child_past_it_is_not_chased_for_ever(catalogue):
    """The bug: every child over ~6 months read as overdue on rotavirus.

    Asserted as "nothing giveable" rather than as one exact status. These
    children never started, so what stops them is the deadline for beginning
    and they read `not_eligible`; a child who *had* started and run out of
    time reads `expired`. Both are shut windows and neither is chased, which
    is what this test is about — pinning one of the two words made it fail on
    the day the other one was introduced.
    """
    from app.utils.vaccines import GIVEABLE, patient_plan

    with catalogue["app"].app_context():
        for years, months in ((0, 7), (3, 0), (16, 0)):
            kid = _aged(catalogue, years, months, tag=f"{years}-{months}")
            _brand, states = _states(patient_plan(kid), "ROTA")
            assert not set(states) & set(GIVEABLE), (
                f"a child of {years}y {months}m is still offered rotavirus: "
                f"{states}")


def test_it_is_expired_rather_than_overdue(catalogue):
    """Not a wording choice. `overdue` is what the reminders chase."""
    from app.utils.vaccines import GIVEABLE, patient_plan

    with catalogue["app"].app_context():
        _brand, states = _states(patient_plan(_aged(catalogue, 3)), "ROTA")

    assert "overdue" not in states and "suggested" not in states
    assert not set(states) & set(GIVEABLE), \
        "a shut window is still on the giveable list"


def test_the_window_shuts_on_the_right_day(catalogue):
    """In days, because 24 weeks is not a whole number of months.

    A child one day inside the window still has it; one day outside does not.
    Stored in months this pair would land on the same answer.

    Measured on a child who **started** the series, deliberately. A child who
    never started is decided earlier, by the deadline for beginning — so
    testing the finish ceiling on one of those measures the wrong window, as
    this test did until the start rule existed to separate them.
    """
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with catalogue["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                             name="RotaRix").first()
        for days, expect_open in ((24 * 7 - 1, True), (24 * 7 + 1, False)):
            kid = _aged(catalogue, tag=f"d{days}")
            kid.date_of_birth = local_today() - timedelta(days=days)
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=rota.id, brand_id=brand.id,
                dose_number=1, event_type="given",
                given_date=kid.date_of_birth + timedelta(weeks=8)))
            db.session.commit()
            _brand, states = _states(patient_plan(kid), "ROTA")
            shut = "expired" in states
            assert shut is not expect_open, (
                f"at {days} days old the finish window is "
                f"{'shut' if shut else 'open'}, expected the opposite")


# ------------------------------------------- the ceiling belongs to the brand

def test_one_brand_shuts_while_its_sibling_stays_open(catalogue):
    """Synflorix stops at five years; Prevenar 13 does not. Same vaccine.

    A ceiling on the vaccine could not express this, which is why it lived
    there unread rather than being wrong out loud.
    """
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with catalogue["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        syn = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                           name="Synflorix").first()
        assert syn.max_age_final_dose_days == 5 * 365

        kid = _aged(catalogue, 6, tag="syn")
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=pcv.id, brand_id=syn.id,
            dose_number=1, event_type="given",
            given_date=kid.date_of_birth + timedelta(days=60)))
        db.session.commit()

        brand, states = _states(patient_plan(kid), "PCV")
        assert brand.name == "Synflorix"
        assert "expired" in states, "Synflorix is still open at six"

        other = _aged(catalogue, 6, tag="prev")
        brand2, states2 = _states(patient_plan(other), "PCV")
        assert brand2.max_age_final_dose_days is None
        assert "expired" not in states2, \
            "the brand with no ceiling was closed along with its sibling"


# ------------------------------------------------ the rest of the sheet's facts

def test_rabies_is_never_a_routine_reminder(catalogue):
    """It is given because something happened. A routine reminder for it is a
    frightening message about a course nobody is on."""
    from app.models import Vaccine, VaccineBrand

    with catalogue["app"].app_context():
        rabies = Vaccine.query.filter_by(code="RABIES").first()
        scopes = {b.name: b.reminder_scope
                  for b in VaccineBrand.query.filter_by(vaccine_id=rabies.id)}

    assert set(scopes.values()) == {"event"}, scopes


def test_registered_and_available_are_different_questions(catalogue):
    """Registered is not obtainable, and neither is a default."""
    from app.models import VaccineBrand

    with catalogue["app"].app_context():
        brand = VaccineBrand.query.filter_by(name="Gardasil 9").first()

        assert brand.registered_in_egypt is True
        assert brand.available_now is True
        assert brand.manufacturer and brand.valency and brand.dose_volume
        assert brand.source_url, "the fact arrived with nowhere to check it"


def test_the_brands_that_need_an_age_banded_schedule_are_marked(catalogue):
    """Nothing reads this yet. It records which brands the plan is still wrong
    for — HPV is 2 doses or 3 depending on the age at the first one — so the
    gap sits in the data instead of in somebody's memory.
    """
    from app.models import VaccineBrand

    with catalogue["app"].app_context():
        marked = {b.name for b in VaccineBrand.query
                  .filter_by(doses_change_by_start_age=True)}

    for name in ("Gardasil 9", "Cervarix", "Synflorix", "Nimenrix"):
        assert name in marked, f"{name} is not flagged as age-banded"
    assert "Varilrix" not in marked


def test_a_reseed_keeps_a_clinic_correction(catalogue):
    """The same promise the schedules already make: seeded facts fill blanks,
    they do not overwrite what the clinic decided about its own stock."""
    from app.extensions import db
    from app.models import VaccineBrand

    from app.utils.vaccines import seed_vaccines

    with catalogue["app"].app_context():
        brand = VaccineBrand.query.filter_by(name="RotaTeq").first()
        brand.available_now = False           # out of stock here
        brand.max_age_final_dose_days = 30 * 7
        db.session.commit()

        seed_vaccines()
        db.session.commit()

        brand = VaccineBrand.query.filter_by(name="RotaTeq").first()
        assert brand.available_now is False
        assert brand.max_age_final_dose_days == 30 * 7


def test_the_status_reads_in_both_languages(catalogue):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert "expired" in json.load(fh)["vstatus"], \
                f"{lang} has no word for a shut window"
