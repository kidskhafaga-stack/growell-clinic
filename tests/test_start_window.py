"""Whether a series may be *begun*, which is a different question from when.

The program asked when to give a dose and never whether it may. Rotavirus is
where that shows: the series has to be finished by 24 weeks on RotaRix, and it
also must not be *started* after about 15. Those are two deadlines, and a
child can be past the first while still inside the second.

Before this, an eighteen-week-old who had never had it was offered the course
— a first dose the label does not allow — and a three-year-old was offered it
too, held off only by the finish ceiling that arrived later.

    18 weeks, nothing yet     not_eligible, not_eligible
    18 weeks, started at 8    done, overdue        ← still inside the finish window
    30 weeks, started at 8    done, expired

The middle row is the whole reason these are separate columns. One ceiling
could not tell those two children apart, and the difference between them is a
dose that should be given and a dose that should not.

`not_eligible` is its own status rather than `expired`: expired is about
finishing something begun, this is about never beginning. Neither is in
`GIVEABLE`, so both leave the offer list and the reminders together.
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


def _rota(seeded, tag, weeks_old, started_at_weeks=None):
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                             name="RotaRix").first()
        dob = local_today() - timedelta(weeks=weeks_old)
        kid = Patient(patient_number=f"SW{tag}", full_name="رضيع",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        if started_at_weeks is not None:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=rota.id, brand_id=brand.id,
                dose_number=1, event_type="given",
                given_date=dob + timedelta(weeks=started_at_weeks)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "ROTA")
        return [d["status"] for d in row["doses"]]


# ------------------------------------------------------------ the window

def test_a_baby_inside_the_window_is_offered_it(seeded):
    """The half that proves the rule did not switch the vaccine off."""
    states = _rota(seeded, "a", 8)

    assert "not_eligible" not in states
    assert states[0] in ("suggested", "due", "overdue")


def test_a_baby_past_the_start_window_is_not(seeded):
    """Eighteen weeks, nothing given. The label does not allow beginning."""
    assert set(_rota(seeded, "b", 18)) == {"not_eligible"}


def test_an_older_child_is_not_offered_it_either(seeded):
    assert set(_rota(seeded, "c", 160)) == {"not_eligible"}


# ------------------------------------------- the two deadlines are different

def test_a_series_already_begun_carries_on_past_the_start_window(seeded):
    """The row that makes these two separate columns.

    Eighteen weeks old and started at eight: past the deadline for *starting*,
    inside the one for *finishing*. The second dose is owed, and a single
    ceiling could not tell this child from the one above.
    """
    states = _rota(seeded, "d", 18, started_at_weeks=8)

    assert states[0] == "done"
    assert "overdue" in states, \
        f"a series already begun was cut off by the start window: {states}"
    assert "not_eligible" not in states


def test_and_still_stops_at_the_finish_window(seeded):
    """Beyond 24 weeks the remaining dose expires — the other ceiling, which
    this must not have replaced."""
    states = _rota(seeded, "e", 30, started_at_weeks=8)

    assert states[0] == "done"
    assert "expired" in states


# ------------------------------------------------------------- the status

def test_it_is_not_on_the_giveable_list(seeded):
    """So it leaves the visit panel and the reminders together."""
    from app.utils.vaccines import GIVEABLE

    assert "not_eligible" not in GIVEABLE


def test_it_is_not_chased_by_the_sweep(seeded):
    from app.utils.vaccine_due import due_list

    _rota(seeded, "f", 18)

    with seeded["app"].app_context():
        codes = {r["vaccine"].code for r in due_list()}

    assert "ROTA" not in codes


def test_the_catalogue_carries_both_ceilings(seeded):
    """Two numbers per brand, because the label states two."""
    from app.models import Vaccine, VaccineBrand

    with seeded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        got = {b.name: (b.max_age_first_dose_days, b.max_age_final_dose_days)
               for b in VaccineBrand.query.filter_by(vaccine_id=rota.id)}

    assert got == {"RotaRix": (15 * 7, 24 * 7),
                   "RotaTeq": (15 * 7, 32 * 7),
                   "Rotasiil": (15 * 7, 34 * 7)}


def test_a_vaccine_with_no_start_window_is_untouched(seeded):
    """Most of the catalogue has no deadline for beginning."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = Patient(patient_number="SWpcv", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=900),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")

    assert "not_eligible" not in [d["status"] for d in row["doses"]]


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert "not_eligible" in json.load(fh)["vstatus"], \
                f"{lang} has no word for a window that never opened"
