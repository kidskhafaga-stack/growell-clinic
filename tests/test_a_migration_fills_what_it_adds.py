"""A column a migration adds is a column that migration should fill.

Reported with a screenshot of the real register: **48 patients due for
rotavirus, 45 of them overdue**, including children of nine and ten. Rotavirus
cannot be given to a ten-year-old by anybody; the finish ceiling that says so
had been in the code for days and the screen went on chasing them.

The code was right. The database was empty.

`max_age_final_dose_days` and `max_age_first_dose_days` were added to
`ADDITIONS`, so an existing clinic's migration created them — and created them
*blank*. The facts that belong in them live in the bundled catalogue, and the
only thing that copies the catalogue onto trade names that already exist is a
full re-seed, which runs from `upgrade-db` and from a button on the
vaccinations screen. A clinic that pulls the new code and restarts does
neither, and its rotavirus keeps no ceiling at all.

So the diagnosis "your installation is behind, pull" was true and not enough,
and this is the half that was missing.

**Narrower than a re-seed on purpose.** This creates nothing — no vaccine, no
trade name, no schedule — so it cannot re-add a product a clinic deleted or
walk past the catalogue toggles. It answers only the question the migration
left open: this column is empty, and the catalogue knows what belongs in it.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def upgraded(clinic):
    """A clinic whose trade names predate the ceiling columns.

    Exactly what an existing installation holds after `apply_schema` added the
    columns: the rows are there, the columns are there, and the columns are
    empty.
    """
    from app.extensions import db

    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()

        from app.models import Vaccine

        rota = Vaccine.query.filter_by(code="ROTA").first()
        for brand in rota.brands:
            brand.max_age_final_dose_days = None
            brand.max_age_first_dose_days = None
        db.session.commit()
    return clinic


def _ten_year_old(clinic, tag="R1"):
    """A child who had one rotavirus dose as a baby and is now ten."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine

    with clinic["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        dob = local_today() - timedelta(days=int(10.35 * 365.25))
        kid = Patient(patient_number=tag, full_name="فارس", gender="male",
                      date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=rota.id,
            brand_id=rota.default_brand.id, dose_number=1, event_type="given",
            given_date=dob + timedelta(days=120)))
        db.session.commit()
        return kid.id


def _rota_states(clinic, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        plan = patient_plan(db.session.get(Patient, patient_id))
        row = next(v for v in plan if v["vaccine"].code == "ROTA")
        return [d["status"] for d in row["doses"]]


# ------------------------------------------------------- the reported screen

def test_the_screen_that_was_reported(upgraded):
    """A ten-year-old, chased for rotavirus, on a database whose ceilings were
    never filled. The whole report in one assertion."""
    from app.utils.vaccine_due import due_list

    kid_id = _ten_year_old(upgraded)

    assert "overdue" in _rota_states(upgraded, kid_id), \
        "the fixture is not reproducing the reported state"

    with upgraded["app"].app_context():
        from app.utils.vaccines import backfill_brand_facts

        from app.extensions import db

        backfill_brand_facts()
        db.session.commit()

    assert "expired" in _rota_states(upgraded, kid_id)

    with upgraded["app"].app_context():
        chased = [r for r in due_list()
                  if r["patient"].id == kid_id and r["vaccine"].code == "ROTA"]

    assert not chased, "a ten-year-old is still on the rotavirus reminder list"


def test_it_fills_the_ceilings_from_the_catalogue(upgraded):
    from app.extensions import db
    from app.models import Vaccine

    from app.utils.vaccines import backfill_brand_facts

    with upgraded["app"].app_context():
        assert backfill_brand_facts() >= 3
        db.session.commit()

        rota = Vaccine.query.filter_by(code="ROTA").first()
        got = {b.name: b.max_age_final_dose_days for b in rota.brands}

    assert got == {"RotaRix": 24 * 7, "RotaTeq": 32 * 7, "Rotasiil": 34 * 7}


# --------------------------------------------------- what it must not do

def test_a_clinic_correction_survives_it(upgraded):
    """The promise the catalogue already makes everywhere else: seeded facts
    fill blanks, they never overwrite what the clinic decided."""
    from app.extensions import db
    from app.models import VaccineBrand

    from app.utils.vaccines import backfill_brand_facts

    with upgraded["app"].app_context():
        brand = VaccineBrand.query.filter_by(name="RotaTeq").first()
        brand.max_age_final_dose_days = 30 * 7
        brand.available_now = False          # out of stock here
        db.session.commit()

        backfill_brand_facts()
        db.session.commit()

        brand = VaccineBrand.query.filter_by(name="RotaTeq").first()
        assert brand.max_age_final_dose_days == 30 * 7
        assert brand.available_now is False


def test_it_creates_nothing(upgraded):
    """The reason this is not simply a re-seed. A clinic that deleted a trade
    name it does not stock must not find it back after an upgrade."""
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand

    from app.utils.vaccines import backfill_brand_facts

    with upgraded["app"].app_context():
        before_v = Vaccine.query.count()
        rota = Vaccine.query.filter_by(code="ROTA").first()
        gone = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                            name="Rotasiil").first()
        db.session.delete(gone)
        db.session.commit()
        before_b = VaccineBrand.query.count()

        backfill_brand_facts()
        db.session.commit()

        assert Vaccine.query.count() == before_v
        assert VaccineBrand.query.count() == before_b, \
            "the backfill put back a trade name the clinic had removed"


def test_running_it_twice_changes_nothing(upgraded):
    """It runs on every upgrade, not once."""
    from app.extensions import db

    from app.utils.vaccines import backfill_brand_facts

    with upgraded["app"].app_context():
        assert backfill_brand_facts() > 0
        db.session.commit()
        assert backfill_brand_facts() == 0


# ------------------------------------------------------------ the wiring

def test_the_upgrade_runs_it(upgraded):
    """A backfill nothing calls is the bug it was written to fix.

    Run, not read. The first version of this searched `apply_schema`'s source
    for the function's name and passed with the call removed, because the
    import line above it still said the word. So the upgrade is actually
    performed on a database with the ceilings blank, and the ceilings are
    asked afterwards.
    """
    from app.extensions import db
    from app.models import Vaccine

    from app.utils.schema import apply_schema

    with upgraded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        assert all(b.max_age_final_dose_days is None for b in rota.brands)

        apply_schema()
        db.session.commit()

        rota = Vaccine.query.filter_by(code="ROTA").first()
        assert {b.name: b.max_age_final_dose_days for b in rota.brands} == {
            "RotaRix": 24 * 7, "RotaTeq": 32 * 7, "Rotasiil": 34 * 7}, \
            "an upgrade left the ceilings empty"


def test_a_broken_backfill_does_not_stop_the_program_starting(clinic,
                                                              monkeypatch):
    import app.utils.vaccines as vaccines

    monkeypatch.setattr(vaccines, "backfill_brand_facts",
                        lambda: (_ for _ in ()).throw(RuntimeError("gone")))

    with clinic["app"].app_context():
        from app.utils.schema import apply_schema

        apply_schema()          # must not raise
