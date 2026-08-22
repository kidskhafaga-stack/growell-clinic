"""The polysaccharide pneumococcal is a different vaccine, not a PCV brand.

Pneumo 23 is PPSV23: a polysaccharide given from two years and on indication,
to children at particular risk. It was filed as a fifth trade name of the
conjugate vaccine, sitting beside Prevenar 13 and Synflorix as though a family
could choose between them.

That is not a labelling nicety, and the measurement says so. Doses count per
vaccine and the course follows the product used most recently, so a child with
three Prevenar doses and one Pneumo 23 at two years came out as:

    course: Pneumo 23 — 1 dose — complete

Three conjugate doses vanished from the count and the booster stopped being
owed. Both rules are right; the data underneath them said these were the same
vaccine, and they are not.

Split into its own vaccine and marked on-demand — which is what it is, and
which also keeps it off the routine chase list, the same way rabies is kept
off it.
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


def test_it_is_its_own_vaccine(seeded):
    from app.models import Vaccine

    with seeded["app"].app_context():
        ppsv = Vaccine.query.filter_by(code="PPSV23").first()

        assert ppsv is not None, "PPSV23 is still filed as a conjugate brand"
        assert ppsv.on_demand is True
        assert ppsv.min_age_months == 24


def test_the_conjugate_no_longer_lists_it(seeded):
    from app.models import Vaccine, VaccineBrand

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        names = {b.name for b in VaccineBrand.query.filter_by(vaccine_id=pcv.id)}

    assert "Pneumo 23" not in names
    assert {"Prevenar 13", "Synflorix", "Vaxneuvance", "Prevenar 20"} <= names


def test_a_polysaccharide_dose_does_not_take_over_the_conjugate_course(seeded):
    """The measurement this exists for.

    Three conjugate doses and one polysaccharide at two years. Before the
    split the file said "Pneumo 23, 1 dose, complete" and the booster stopped
    being owed.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        ppsv = Vaccine.query.filter_by(code="PPSV23").first()
        prevenar = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                                name="Prevenar 13").first()
        pneumo = VaccineBrand.query.filter_by(vaccine_id=ppsv.id,
                                              name="Pneumo 23").first()
        dob = local_today() - timedelta(days=int(3 * 365.25))
        kid = Patient(patient_number="PS1", full_name="طفل", gender="male",
                      date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, months in ((1, 2), (2, 4), (3, 6)):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=prevenar.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(months * 30.4))))
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=ppsv.id, brand_id=pneumo.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(24 * 30.4))))
        db.session.commit()

        plan = patient_plan(kid)
        conjugate = next(v for v in plan if v["vaccine"].code == "PCV")
        states = [d["status"] for d in conjugate["doses"]]

    assert conjugate["brand"].name == "Prevenar 13", \
        f"the conjugate course was taken over: {conjugate['brand'].name}"
    assert states.count("done") == 3, \
        f"conjugate doses were lost from the count: {states}"
    # Still owed — which is the whole claim. It reads `due` rather than
    # `overdue` because a catch-up is a course that *starts now*: this child
    # is three, the guideline's answer for a three-year-old with three doses
    # is "one more", and that one is owed from today rather than late since a
    # first birthday nobody was ever going to give it on. The distinction is
    # the catch-up model's to make; what this test holds is that a
    # polysaccharide dose does not make the conjugate booster disappear.
    from app.utils.vaccines import GIVEABLE

    assert any(state in GIVEABLE for state in states), \
        f"the booster stopped being owed once a polysaccharide was " \
        f"recorded: {states}"


def test_it_is_recorded_but_never_routinely_chased(seeded):
    """Given on indication, to children at risk. A reminder by age alone is
    the same mistake rabies was."""
    from app.extensions import db
    from app.models import Patient, Vaccine
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = Patient(patient_number="PS2", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=1200),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()

        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PPSV23")
        states = {d["status"] for d in row["doses"]}

        assert Vaccine.query.filter_by(code="PPSV23").first().on_demand
    assert "suggested" not in states and "overdue" not in states, states


def test_its_note_says_it_is_not_part_of_the_conjugate_series(seeded):
    """Written where somebody reading the catalogue will see it."""
    from app.models import Vaccine

    with seeded["app"].app_context():
        note = Vaccine.query.filter_by(code="PPSV23").first().catch_up_notes or ""

    assert "PCV" in note
