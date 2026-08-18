"""A trade name that no longer exists, kept so old records can name it.

Reported from the clinic's own files: patients had the whole-cell pentavalent
years ago under a commercial name that is not made any more, and because it
was not in the catalogue those doses were filed against the **government**
pentavalent instead — the nearest thing available. The record says a
government unit gave it. Nobody did.

So the catalogue gains the brand and marks it discontinued. That is a
different thing from deleting it and a different thing from stocking it:

  * it **can be named** on a dose that already happened, which is the point;
  * it is **never offered** for a new one, because nobody can buy it.

**It is a brand, not a vaccine.** Quinvaxem is DTwP-HepB-Hib — the same
antigens as the government pentavalent, in a bought vial instead of a
supplied one. Giving it a vaccine of its own would split one child's course in
two and restart the dose numbering, which is the mistake `dose_infer` was
written to avoid: doses are numbered per vaccine, never per brand, because a
child who had three of one brand and a fourth of another has had four.

``registered_in_egypt`` is left unknown rather than asserted. The evidence
here is a clinic's own patients, which proves the doses happened and says
nothing about a registration file — and a three-valued answer exists precisely
so "nobody has checked" does not have to be written down as "no".
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

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
    return clinic


def _brand(name):
    from app.models import VaccineBrand

    return VaccineBrand.query.filter_by(name=name).first()


def test_the_brand_exists_to_be_named(seeded):
    with seeded["app"].app_context():
        brand = _brand("Quinvaxem")

        assert brand is not None, "there is still no way to name the real brand"
        assert brand.manufacturer == "Crucell"
        assert "DTwP" in (brand.valency or ""), brand.valency


def test_it_hangs_off_the_same_vaccine_as_the_government_one(seeded):
    """Not a vaccine of its own: same antigens, so one child's course stays
    one course and the dose numbers keep counting."""
    from app.models import Vaccine

    with seeded["app"].app_context():
        penta = Vaccine.query.filter_by(code="PENTA").first()

        assert _brand("Quinvaxem").vaccine_id == penta.id


def test_it_is_marked_discontinued_and_not_available(seeded):
    with seeded["app"].app_context():
        brand = _brand("Quinvaxem")

        assert brand.is_discontinued is True
        assert brand.available_now is False


def test_registration_is_left_unknown_rather_than_claimed(seeded):
    """The evidence is a clinic's patients, not a regulator's file."""
    with seeded["app"].app_context():
        assert _brand("Quinvaxem").registered_in_egypt is None


def test_it_is_never_offered_for_a_new_dose(seeded):
    """The whole difference between keeping a name and stocking a product."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccine_sale import sellable

    with seeded["app"].app_context():
        kid = Patient(patient_number="Q1", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=200),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()

        offered = {o["brand"].name for o in sellable(kid)
                   if o.get("brand") is not None}

    assert "Quinvaxem" not in offered


def test_an_old_dose_can_be_recorded_against_it(seeded):
    """The reason it is here at all — and the course still reads as one
    course, numbered across both brands."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        penta = Vaccine.query.filter_by(code="PENTA").first()
        quin = _brand("Quinvaxem")
        gov = _brand("حكومي")
        kid = Patient(patient_number="Q2", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=900),
                      is_active=True)
        db.session.add(kid)
        db.session.flush()
        # Two doses of the discontinued brand, then one of the government
        # supply — the real shape of these files.
        for number, brand in ((1, quin), (2, quin), (3, gov)):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=penta.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=kid.date_of_birth + timedelta(days=60 * number)))
        db.session.commit()

        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PENTA")
        done = [d for d in row["doses"] if d["status"] == "done"]

    assert len(done) == 3, \
        f"the course split across brands instead of counting three: {done}"


def test_a_clinic_that_brings_one_back_keeps_its_decision(seeded):
    """Set when the row is created and never backfilled — the same promise the
    out-of-stock flag needed after a re-seed undid it once."""
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines

    with seeded["app"].app_context():
        brand = _brand("Quinvaxem")
        brand.is_discontinued = False
        db.session.commit()

        seed_vaccines()
        db.session.commit()

        assert _brand("Quinvaxem").is_discontinued is False
