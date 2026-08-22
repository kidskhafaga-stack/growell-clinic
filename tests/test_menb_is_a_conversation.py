"""MenB for a healthy adolescent is a decision, not a due date.

The reference, as supplied: for healthy adolescents of sixteen to twenty-three
the CDC's position is **shared clinical decision-making** — two doses six
months apart, preferred at sixteen to eighteen, given because a doctor and a
family talked about it and not because a birthday arrived.

The program already had a word for that. A course this clinic never began and
never agreed to is a *suggestion by age*: it sits on the plan, it can be
offered at a visit, and it cannot be late — because "late" is a broken promise
and nobody made one. It becomes due, and can become overdue, the moment the
doctor and the family agree on it, which is exactly what shared decision-making
means when it is written down.

So there is no new status here and no new flag. What changed is the band: the
CDC's MenB row said "from ten years" and now says sixteen to twenty-three,
which is what the reference says.

**What is deliberately absent.** A child of ten or more at increased risk is a
real recommendation and not one this program can compute: the schedule depends
on the indication and on the product, and may be a three-dose primary series.
The catalogue cannot know why a child is at risk, and inventing a course for
one that a doctor has not stated would be the worst kind of wrong — confident,
dated, and about a child who needed something else.
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


def _teenager(seeded, profile, age_years, given_years=(), agreed=False):
    """Returns ``(doses, [(number, status)])`` for a child on Bexsero."""
    from app.extensions import db
    from app.models import (Patient, PatientVaccine, Setting, Vaccine,
                            VaccineBrand)
    from app.utils.vaccines import patient_plan

    _COUNTER[0] += 1
    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", profile)
        menb = Vaccine.query.filter_by(code="MENB").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=menb.id,
                                             name="Bexsero").first()
        dob = local_today() - timedelta(days=int(age_years * 365.25))
        kid = Patient(patient_number=f"MB{_COUNTER[0]}", full_name="مراهق",
                      gender="female", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, when in enumerate(given_years, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=menb.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(when * 365.25))))
        db.session.commit()
        plan = patient_plan(kid, agreed={menb.id} if agreed else None)
        row = next(v for v in plan if v["vaccine"].code == "MENB")
        return [(d["dose_number"], d["status"]) for d in row["doses"]]


# ------------------------------------------------------- the band itself

def test_sixteen_to_twenty_three_is_two_doses_six_months_apart(seeded):
    from datetime import date

    doses = _teenager(seeded, "cdc", 16.2)
    assert len(doses) == 2, f"not the two-dose series: {doses}"

    # And the six months between them, read off the seeded rows rather than
    # off a date the engine happened to compute for one child.
    from app.models import Vaccine, VaccineScheduleDose, VaccineScheduleTemplate

    with seeded["app"].app_context():
        menb = Vaccine.query.filter_by(code="MENB").first()
        tpl = VaccineScheduleTemplate.query.filter_by(
            vaccine_id=menb.id, source="cdc", is_active=True).first()
        rows = VaccineScheduleDose.query.filter_by(
            template_id=tpl.id).order_by(
                VaccineScheduleDose.dose_number).all()

    assert [r.recommended_age_months for r in rows] == [192, 198], \
        "the series does not begin at sixteen and continue six months later"
    assert rows[1].min_interval_days == 180, \
        f"the interval is not six months: {rows[1].min_interval_days}"
    assert date  # the import is the reference for the reader, not a use


def test_it_is_a_suggestion_until_somebody_agrees_to_it(seeded):
    """Nothing about it is late, because nobody promised it."""
    from app.utils.vaccines import GIVEABLE

    doses = _teenager(seeded, "cdc", 17.0)

    assert [status for _n, status in doses] == ["suggested", "suggested"], \
        f"a shared decision was written as a due date: {doses}"
    # Still offerable at a visit — a suggestion the clinic cannot act on is
    # not a suggestion.
    assert all(status in GIVEABLE for _n, status in doses)


def test_agreeing_to_it_is_what_makes_it_due(seeded):
    """The agreement is the promise, and a promise is what can be broken."""
    doses = _teenager(seeded, "cdc", 17.0, agreed=True)
    states = {status for _n, status in doses}

    assert states & {"due", "overdue"}, \
        f"agreeing to the course did not make any of it owed: {doses}"


def test_the_second_dose_is_owed_once_the_first_is_given(seeded):
    """Starting a course is agreeing to it in the plainest way there is."""
    doses = _teenager(seeded, "cdc", 17.5, given_years=(16.5,))

    assert doses[0][1] == "done"
    assert doses[1][1] in ("due", "overdue"), \
        f"the second dose of a started series is not owed: {doses}"


# ------------------------------------------------------ and what it is not

def test_a_healthy_twelve_year_old_is_not_scheduled_for_it(seeded):
    """The band used to begin at ten. The reference's routine recommendation
    begins at sixteen; below that it is risk-based, and a risk this program
    cannot see is not a schedule it may write."""
    doses = _teenager(seeded, "cdc", 12.0)

    assert doses == [], f"a twelve-year-old was scheduled anyway: {doses}"


def test_the_egyptian_clinic_still_follows_the_label(seeded):
    """MenB is not in the Egyptian programme, so the European label answers —
    and it schedules Bexsero from two months, which is the whole reason a
    clinic gets to choose a reference at all."""
    doses = _teenager(seeded, "egypt", 0.5)

    assert doses, "the leaflet stopped answering for a product Egypt does " \
                  "not schedule"
