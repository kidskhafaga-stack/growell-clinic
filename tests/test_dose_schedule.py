"""When the next dose falls due.

The bug these were written for: a child whose first dose came a year late got a
second dose "due" fifteen months *before* the first one happened, and the whole
course read as overdue. The chaining that was supposed to prevent that was
guarded on ``vaccine.min_interval_days``, which is NULL on nearly every vaccine
— it is only filled in when the source schedule happened to state one — so the
guard meant the chaining never ran and every dose kept its raw age-based date.

The thread running through all of these: **a due date is a promise to a
family.** "Come back on the 26th" has to be a date that could be true. A dose
due before the dose it follows is not a scheduling inaccuracy, it is the screen
telling reception to call a parent about something impossible, and after the
second such call nobody trusts the list.

Nothing here is about being clever with intervals. It is about the floor: the
next dose comes *after* the last one.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def kid(clinic):
    """A three-year-old, and a two-dose optional vaccine with stock."""
    from app.models import (Patient, Vaccine, VaccineBrand, VaccineBrandDose,
                            VaccineInventory)

    with clinic["app"].app_context():
        child = Patient(patient_number="PK1", full_name="طفل الجدول",
                        gender="male", is_active=True,
                        date_of_birth=date.today() - timedelta(days=365 * 3))
        clinic["db"].session.add(child)
        clinic["db"].session.flush()

        vac = Vaccine(code="OPTX", name_ar="تطعيم اختياري", is_mandatory=False)
        clinic["db"].session.add(vac)
        clinic["db"].session.flush()
        brand = VaccineBrand(vaccine_id=vac.id, name="BrandX", price=500,
                             doses_per_vial=1)
        clinic["db"].session.add(brand)
        clinic["db"].session.flush()
        for number, months in ((1, 2), (2, 4), (3, 6)):
            clinic["db"].session.add(VaccineBrandDose(
                brand_id=brand.id, dose_number=number, age_months=months))
        clinic["db"].session.add(VaccineInventory(
            brand_id=brand.id, lot_number="LX", qty_received=10, qty_used=0,
            expiry_date=date(2030, 1, 1)))
        clinic["db"].session.commit()
        clinic["kid"] = child.id
        clinic["vac"] = vac.id
        clinic["brand"] = brand.id
    return clinic


def _give(kid, dose_number, when, vaccine_id=None, brand_id=None):
    from app.models import PatientVaccine

    with kid["app"].app_context():
        kid["db"].session.add(PatientVaccine(
            patient_id=kid["kid"], vaccine_id=vaccine_id or kid["vac"],
            brand_id=brand_id or kid["brand"], dose_number=dose_number,
            given_date=when, event_type="given"))
        kid["db"].session.commit()


def _doses(kid, code="OPTX"):
    """The plan's dose rows for one vaccine, keyed by dose number."""
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with kid["app"].app_context():
        child = kid["db"].session.get(Patient, kid["kid"])
        for row in patient_plan(child):
            if row["vaccine"].code == code:
                return {d["dose_number"]: d for d in row["doses"]}
    return {}


def _d(iso):
    return date.fromisoformat(iso) if iso else None


# ------------------------------------------------------------- the floor ---
def test_the_next_dose_never_falls_due_before_the_last_one_was_given(kid):
    """The bug, stated as the rule it broke. Everything else here is detail."""
    given_on = date.today()
    _give(kid, 1, given_on)

    doses = _doses(kid)
    assert _d(doses[2]["due_date"]) > given_on


def test_no_dose_in_the_course_falls_due_before_its_predecessor(kid):
    """Not just dose 2 — the whole chain, because a fix that only pushed the
    next one would leave dose 3 sitting in the past."""
    _give(kid, 1, date.today())

    doses = _doses(kid)
    assert _d(doses[3]["due_date"]) > _d(doses[2]["due_date"])


def test_a_dose_given_a_year_late_pushes_the_rest_forward(kid):
    """The reported case: dose 1 was due at two months and given at eighteen."""
    given_on = date.today()
    _give(kid, 1, given_on)

    doses = _doses(kid)
    assert _d(doses[2]["due_date"]) == given_on + timedelta(days=28)
    assert _d(doses[3]["due_date"]) == given_on + timedelta(days=56)


def test_the_rest_of_the_course_stops_reading_as_overdue(kid):
    """A dose given today leaving the next one "overdue since 2023" is the
    version of this bug a parent sees."""
    _give(kid, 1, date.today())

    doses = _doses(kid)
    assert doses[2]["status"] != "overdue"
    assert doses[3]["status"] != "overdue"


def test_a_vaccine_with_its_own_interval_uses_that_and_not_the_floor(kid):
    """The floor is a fallback, never an override — a vaccine whose schedule
    states 60 days must not be brought forward to 28."""
    from app.models import Vaccine

    with kid["app"].app_context():
        kid["db"].session.get(Vaccine, kid["vac"]).min_interval_days = 60
        kid["db"].session.commit()
    given_on = date.today()
    _give(kid, 1, given_on)

    doses = _doses(kid)
    assert _d(doses[2]["due_date"]) == given_on + timedelta(days=60)


def test_an_interval_of_zero_still_gets_the_floor(kid):
    """Zero in the column means "nobody filled this in", not "same day"."""
    from app.models import Vaccine

    with kid["app"].app_context():
        kid["db"].session.get(Vaccine, kid["vac"]).min_interval_days = 0
        kid["db"].session.commit()
    given_on = date.today()
    _give(kid, 1, given_on)

    doses = _doses(kid)
    assert _d(doses[2]["due_date"]) == given_on + timedelta(days=28)


# ------------------------------------------- what must NOT have changed ----
def test_an_on_time_child_keeps_the_age_based_dates(kid):
    """The floor must only ever push a date later. A schedule whose own gaps
    are wider than the floor is the normal case and has to come through
    untouched, or every clinic's schedule quietly becomes 28-day spacing."""
    from app.models import Patient
    from app.utils.vaccines import add_months

    with kid["app"].app_context():
        dob = kid["db"].session.get(Patient, kid["kid"]).date_of_birth

    doses = _doses(kid)                      # nothing given at all
    assert _d(doses[1]["due_date"]) == add_months(dob, 2)
    assert _d(doses[2]["due_date"]) == add_months(dob, 4)
    assert _d(doses[3]["due_date"]) == add_months(dob, 6)


def test_a_given_dose_keeps_the_date_it_was_actually_due(kid):
    """"Was due in March, given in July" is how somebody sees it was late.
    Rewriting the due date to the given date would erase the delay."""
    from app.models import Patient
    from app.utils.vaccines import add_months

    given_on = date.today()
    _give(kid, 1, given_on)
    with kid["app"].app_context():
        dob = kid["db"].session.get(Patient, kid["kid"]).date_of_birth

    doses = _doses(kid)
    assert _d(doses[1]["due_date"]) == add_months(dob, 2)
    assert doses[1]["given_date"] == given_on.isoformat()


def test_the_doctors_own_appointment_still_wins(kid):
    """Their patient, their timing. A computed floor must not overrule a date
    the doctor typed in."""
    from app.models import PatientVaccine

    given_on = date.today()
    _give(kid, 1, given_on)
    wanted = given_on + timedelta(days=90)
    with kid["app"].app_context():
        kid["db"].session.add(PatientVaccine(
            patient_id=kid["kid"], vaccine_id=kid["vac"], brand_id=kid["brand"],
            dose_number=2, given_date=wanted, event_type="planned"))
        kid["db"].session.commit()

    assert _d(_doses(kid)[2]["due_date"]) == wanted


# ------------------------------------------ what this does and does not fix -
def test_a_course_given_today_leaves_the_visit_panel_unalarmed(kid):
    """What the doctor sees. Before the fix, a dose given this morning left the
    next one flagged as a late catch-up in the same visit."""
    from app.models import Patient
    from app.utils.vaccines import visit_vaccine_panel

    _give(kid, 1, date.today())
    with kid["app"].app_context():
        child = kid["db"].session.get(Patient, kid["kid"])
        offered = visit_vaccine_panel(child)["give_now"]
        mine = [e for e in offered if e["vaccine"].code == "OPTX"]
        assert mine and mine[0]["overdue"] is False


def test_an_unvaccinated_child_is_still_offered_everything_due(kid):
    """**This is not the fix's job, and the test exists to say so.**

    A three-year-old with an empty history genuinely is behind on every
    optional vaccine, so all of them are offered — the count is honest, and the
    dose-chaining fix does not and should not reduce it. Whether that list wants
    grouping or a catch-up priority is a separate policy question about the
    panel, not a bug in the schedule.
    """
    from app.models import Patient
    from app.utils.vaccines import visit_vaccine_panel

    with kid["app"].app_context():
        child = kid["db"].session.get(Patient, kid["kid"])
        offered = visit_vaccine_panel(child)["give_now"]
        mine = [e for e in offered if e["vaccine"].code == "OPTX"]
        assert len(mine) == 1                      # one entry, its first dose
        assert mine[0]["dose"]["dose_number"] == 1
        assert mine[0]["dose"]["status"] == "overdue"
