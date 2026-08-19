"""Schedules whose dose count depends on the age the course started at.

HPV is two doses from nine to fourteen and three from fifteen, and the rule
the doctor was most careful about is the second half of it: **a child who
started at fourteen and eleven months stays on two doses.** They do not gain a
third because a birthday passed between the first and the second. So the band
is matched on the age at the first dose, once, and the answer stops moving.

Before any dose exists there is nothing to match on, so the band follows
today's age — a projection of what starting now would mean, and correctly
unstable, because nothing has been promised yet.

**Which source is followed was a clinical decision, not a technical one.** The
manufacturer's leaflet is what a course runs on here and the WHO row is kept
beside it to read; both have been seeded per vaccine since the schedule
templates were built, and `source` is what the selector filters on. Only
`manufacturer` bands are followed.

**Only where somebody has read the leaflet.** HPV is seeded with bands because
the rule was written out and reviewed for this program. Bexsero also varies
with starting age and is deliberately left alone: it keeps one standard course
and shows the "varies by starting age" warning, which is honest about not
knowing rather than quietly picking a number. A vaccine with no bands falls
straight through to the brand's dose rows, so nothing else in the catalogue
changed.
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


def _girl(seeded, years, tag, started_at=None):
    """A child of `years`, optionally with her first HPV dose at `started_at`."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=hpv.id,
                                             name="Gardasil 9").first()
        dob = local_today() - timedelta(days=int(years * 365.25))
        kid = Patient(patient_number=f"AB{tag}", full_name="طفلة",
                      gender="female", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        if started_at is not None:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=hpv.id, brand_id=brand.id,
                dose_number=1, event_type="given",
                given_date=dob + timedelta(days=int(started_at * 365.25))))
        db.session.commit()
        return kid.id


def _hpv(seeded, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(db.session.get(Patient, patient_id))
        return next(v for v in plan if v["vaccine"].code == "HPV")


# ------------------------------------------------------------ the two bands

def test_a_child_under_fifteen_is_on_two_doses(seeded):
    assert len(_hpv(seeded, _girl(seeded, 12, "a"))["doses"]) == 2


def test_a_child_of_fifteen_or_over_is_on_three(seeded):
    assert len(_hpv(seeded, _girl(seeded, 16, "b"))["doses"]) == 3


# --------------------------------------------- the rule that mattered most

def test_starting_before_fifteen_keeps_two_doses_after_the_birthday(seeded):
    """Stated plainly by the doctor: completing two doses correctly before
    fifteen is enough, and turning fifteen in between changes nothing.

    Matched on today's age this child would be handed a third dose they do not
    need — a real injection, from an arithmetic slip.
    """
    row = _hpv(seeded, _girl(seeded, 15.1, "c", started_at=14.9))

    assert len(row["doses"]) == 2, \
        "a birthday between doses moved the child onto the three-dose schedule"


def test_starting_after_fifteen_really_is_three(seeded):
    """The other half — otherwise the rule could be "always two"."""
    row = _hpv(seeded, _girl(seeded, 16.2, "d", started_at=16.0))

    assert len(row["doses"]) == 3


def test_before_any_dose_the_band_follows_todays_age(seeded):
    """Nothing has been promised, so the projection moves with the child."""
    young = _hpv(seeded, _girl(seeded, 3, "e"))

    assert len(young["doses"]) == 2
    assert {d["status"] for d in young["doses"]} == {"upcoming"}


# ------------------------------------------------------ nothing else moved

def test_a_vaccine_with_no_bands_is_untouched(seeded):
    """The change has to be invisible everywhere it was not asked for."""
    from app.extensions import db
    from app.models import Patient, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    patient_id = _girl(seeded, 3, "f")
    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        expected = len(brand.doses)
        plan = patient_plan(db.session.get(Patient, patient_id))
        row = next(v for v in plan if v["vaccine"].code == "PCV")

    assert len(row["doses"]) == expected


def test_bexsero_is_left_alone_until_somebody_reads_the_leaflet(seeded):
    """It varies too, and guessing the bands would be inventing medicine."""
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        menb = Vaccine.query.filter_by(code="MENB").first()
        banded = (VaccineScheduleTemplate.query
                  .filter_by(vaccine_id=menb.id)
                  .filter(VaccineScheduleTemplate.start_age_min_months
                          .isnot(None)).count())

    assert banded == 0, "MenB was given age bands nobody verified"


# --------------------------------------------------------- which source wins

def test_only_the_manufacturer_bands_are_followed(seeded):
    """The clinic's decision: the leaflet runs the course, the WHO row is a
    reference kept beside it."""
    from app.extensions import db
    from app.models import Vaccine, VaccineScheduleDose, VaccineScheduleTemplate

    patient_id = _girl(seeded, 16, "g")
    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        # A WHO schedule with a band that would say something different.
        rogue = VaccineScheduleTemplate(
            vaccine_id=hpv.id, code="WHO-BAND", source="who",
            label="reference", is_seeded=True, sort_order=0,
            start_age_min_months=0, start_age_max_months=10 ** 4)
        db.session.add(rogue)
        db.session.flush()
        db.session.add(VaccineScheduleDose(
            template_id=rogue.id, dose_number=1, recommended_age_months=108))
        db.session.commit()

    assert len(_hpv(seeded, patient_id)["doses"]) == 3, \
        "a WHO schedule overrode the manufacturer's course"


def test_both_sources_are_still_kept_side_by_side(seeded):
    """The reference has to survive, or the decision loses its other half."""
    from app.models import VaccineScheduleTemplate

    with seeded["app"].app_context():
        sources = {t.source for t in VaccineScheduleTemplate.query.all()}

    assert {"manufacturer", "who"} <= sources


# ------------------------------------------------- the two paths still agree

def test_the_sweep_picks_the_same_schedule_as_the_file(seeded):
    """A listing that chooses a different course from the child's own file is
    two programs disagreeing about a patient."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.models.vaccine_plan import planned_by_patient
    from app.utils.vaccines import (doses_for, patient_due_reminders, scan_due)

    patient_id = _girl(seeded, 16.2, "h", started_at=16.0)
    today = local_today()
    with seeded["app"].app_context():
        kid = db.session.get(Patient, patient_id)
        by_orm = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in patient_due_reminders(
                kid, "ar", today,
                doses=doses_for([patient_id]).get(patient_id, [])))

        rows = db.session.query(
            PatientVaccine.vaccine_id, PatientVaccine.brand_id,
            PatientVaccine.dose_number, PatientVaccine.given_date,
            PatientVaccine.event_type).filter(
            PatientVaccine.patient_id == patient_id).all()
        by_flat = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in scan_due(kid.date_of_birth, rows, today,
                              agreed=planned_by_patient([patient_id])
                              .get(patient_id, set())))

    assert by_orm == by_flat, f"file says {by_orm}, sweep says {by_flat}"
