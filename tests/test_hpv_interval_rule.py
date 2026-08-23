"""A dose count that depends on something that already happened.

Two doses are enough for HPV from nine to fourteen — **if the second comes
five to thirteen months after the first**. Given sooner, the course is three.

That is a different kind of rule from everything else here. An age band is
decided once, when the course starts, and holds. This one cannot be: nobody
knows at the first dose whether the second will arrive on time, so the
schedule has to change afterwards, in response to what the family actually
did.

    12y, nothing yet              2 doses
    12y, dose 1 only              2
    12y, dose 2 after 7 months    2
    12y, dose 2 after 2 months    3    ← the count changed retrospectively
    16y, anything                 3

**Before the second dose, the expectation applies.** A course is two doses
until the second one turns up early, so the band that exists to catch a short
gap waits for its evidence. Reversed — and it was, in the first version — every
child in the age range was shown the three-dose course before anything had
gone wrong.

Expressed as two numbers on the schedule row, the same shape as the age band,
so the threshold is a setting rather than a constant in the engine.
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

    from app.models import Setting

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        # These use pneumococcal as the vehicle for something else — a
        # duplicated dose, an interval rule, a progress bar — and the Egyptian
        # profile deliberately computes no pneumococcal schedule at all, so
        # there would be no course here to measure any of it against. The
        # leaflet is followed instead: the vehicle has to be a course that
        # exists.
        Setting.set("vaccine_guideline_profile", "manufacturer")
        db.session.commit()
    return clinic


def _doses(seeded, tag, age_years, started_at=None, gap_days=None):
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=hpv.id,
                                             name="Gardasil 9").first()
        dob = local_today() - timedelta(days=int(age_years * 365.25))
        kid = Patient(patient_number=f"HV{tag}", full_name="طفلة",
                      gender="female", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        if started_at is not None:
            first = dob + timedelta(days=int(started_at * 365.25))
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=hpv.id, brand_id=brand.id,
                dose_number=1, event_type="given", given_date=first))
            if gap_days is not None:
                db.session.add(PatientVaccine(
                    patient_id=kid.id, vaccine_id=hpv.id, brand_id=brand.id,
                    dose_number=2, event_type="given",
                    given_date=first + timedelta(days=gap_days)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "HPV")
        return len(row["doses"])


# ------------------------------------------- the expectation, before evidence

def test_a_child_in_the_age_range_expects_two(seeded):
    assert _doses(seeded, "a", 12.5) == 2


def test_one_dose_given_still_expects_two(seeded):
    """The second has not happened, so nothing has gone wrong yet.

    The first version of this rule had it the other way round and showed the
    three-dose course to every child in the range from the start.
    """
    assert _doses(seeded, "b", 12.5, started_at=12.0) == 2


# --------------------------------------------------- the count moves after

def test_a_second_dose_on_time_keeps_it_at_two(seeded):
    assert _doses(seeded, "c", 13.5, started_at=12.0, gap_days=210) == 2


def test_a_second_dose_too_soon_makes_it_three(seeded):
    """The rule itself. Two months apart is not a two-dose course."""
    assert _doses(seeded, "d", 13.0, started_at=12.0, gap_days=60) == 3


def test_the_boundary_is_where_the_leaflet_puts_it(seeded):
    """Five months, either side of it."""
    assert _doses(seeded, "e", 14.0, started_at=12.0, gap_days=149) == 3
    assert _doses(seeded, "f", 14.0, started_at=12.0, gap_days=151) == 2


# ------------------------------------------------- the age rule still holds

def test_starting_at_fifteen_is_three_whatever_the_gap(seeded):
    assert _doses(seeded, "g", 16.5, started_at=16.0) == 3
    assert _doses(seeded, "h", 17.0, started_at=16.0, gap_days=210) == 3


def test_a_vaccine_with_no_gap_rule_is_untouched(seeded):
    """Most courses do not care how far apart the first two doses landed."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        # Under a year: from two the pneumococcal has an age-based catch-up,
        # and a control that has moved onto it is no longer a control.
        dob = local_today() - timedelta(days=300)
        kid = Patient(patient_number="HVpcv", full_name="طفل", gender="male",
                      date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, days in ((1, 60), (2, 75)):     # deliberately close
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=days)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")

    assert len(row["doses"]) == 4


# ------------------------------------------------------ it is a setting

def test_the_threshold_is_a_row_not_a_constant(seeded):
    """So a revised leaflet is an edit, not a release."""
    from app.models import VaccineScheduleTemplate

    with seeded["app"].app_context():
        two = VaccineScheduleTemplate.query.filter_by(code="HPV2").first()
        short = VaccineScheduleTemplate.query.filter_by(
            code="HPV2-SHORT").first()

        assert two.first_gap_min_days == 150
        assert short.first_gap_max_days == 150
        assert short.first_gap_min_days is None


def test_the_engine_holds_no_hpv_threshold_of_its_own(seeded):
    """The number lives in one place. Two would eventually disagree."""
    import ast

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "app/utils/vaccines.py"),
              encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    picker = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_pick_band")
    numbers = {n.value for n in ast.walk(picker)
               if isinstance(n, ast.Constant) and isinstance(n.value, int)}

    assert 150 not in numbers, \
        "the gap threshold was copied into the engine as well as the data"
