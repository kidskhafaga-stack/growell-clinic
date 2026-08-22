"""A childhood course that stops being a childhood course.

From the audit of the long reminder screen, and answered by the doctor
directly: *"PCV → age-based catch-up rule, not PCV → continue the infant
series up to sixteen years. A healthy child who reaches twenty-four months
after an earlier dose is not treated as though still in the infant series."*

The measurement it came from: a child with one pneumococcal dose as a baby
read `overdue` on doses 2, 3 and 4 at three years old, at ten, and at sixteen
— dated 2011 — because `Prevenar 13` carries no finish ceiling and the course
was matched on the age at the **first** dose. Rotavirus had exactly this shape
until its ceiling was filled in.

**Matched on today's age, which is the opposite of HPV, and deliberately.**
HPV locks at the first dose so that a birthday between doses cannot add a
third. A catch-up re-reads the child every time, because that is what a
catch-up is. Both are now stated per band rather than assumed.

**Only the ceiling is here.** The middle of the catch-up — one dose to
complete for a healthy child of two to four — is deliberately absent: a
one-dose course has its single slot filled by the infant dose the child
already had, so "one more" comes out as "nothing owed". That needs the engine
to treat a catch-up's doses as *additional* to what is on file, which is a
change to make deliberately rather than to guess at.
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

    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _child(clinic, years, tag, doses=((1, 2),)):
    """`doses` as [(number, age_in_months)] of the default pneumococcal."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine

    with clinic["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        dob = local_today() - timedelta(days=int(years * 365.25))
        kid = Patient(patient_number=f"RC{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, months in doses:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id,
                brand_id=pcv.default_brand.id, dose_number=number,
                event_type="given",
                given_date=dob + timedelta(days=int(months * 30.44))))
        db.session.commit()
        return kid.id


def _pcv(clinic, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        plan = patient_plan(db.session.get(Patient, patient_id))
        return next(v for v in plan if v["vaccine"].code == "PCV")


# ------------------------------------------------------ the reported screen

def test_a_sixteen_year_old_is_not_chased_for_a_babys_course(seeded):
    """The row that was on the screen: doses 2, 3 and 4 overdue since 2011."""
    from app.utils.vaccine_due import due_list

    kid_id = _child(seeded, 16, "16")

    assert _pcv(seeded, kid_id)["doses"] == []

    with seeded["app"].app_context():
        chased = [r for r in due_list()
                  if r["patient"].id == kid_id and r["vaccine"].code == "PCV"]

    assert not chased


@pytest.mark.parametrize("years", [5.1, 6, 10, 16])
def test_the_routine_course_is_over_from_five(seeded, years):
    assert _pcv(seeded, _child(seeded, years, str(years)))["doses"] == []


# --------------------------------------------- and nothing below it moved

@pytest.mark.parametrize("years,expected", [(0.25, 4), (0.5, 4), (1.2, 4),
                                            (3, 4), (4.9, 4)])
def test_every_child_under_five_is_scheduled_exactly_as_before(seeded, years,
                                                               expected):
    """The half that matters most. A ceiling put one band too low silently
    stops vaccinating toddlers, and it would look like a tidier screen."""
    assert len(_pcv(seeded, _child(seeded, years, f"u{years}"))["doses"]) == expected


def test_a_baby_is_still_chased_for_the_doses_they_owe(seeded):
    from app.utils.vaccine_due import due_list

    kid_id = _child(seeded, 1.2, "baby")

    with seeded["app"].app_context():
        chased = [r for r in due_list()
                  if r["patient"].id == kid_id and r["vaccine"].code == "PCV"]

    assert chased, "a one-year-old stopped being chased for their series"


def test_it_reads_the_age_now_and_not_the_age_they_started_at(seeded):
    """The mechanism, stated where it can be seen.

    Both of these children started at two months. One is four, one is six, and
    a band matched on the first dose cannot tell them apart — which is exactly
    how the sixteen-year-old was still in a baby's course.
    """
    four = _pcv(seeded, _child(seeded, 4, "m4"))
    six = _pcv(seeded, _child(seeded, 6, "m6"))

    assert len(four["doses"]) == 4
    assert six["doses"] == []


def test_hpv_still_locks_at_the_first_dose(seeded):
    """The rule this must not have broken. A girl who begins at fourteen and
    eleven months keeps two doses after her fifteenth birthday — the thing the
    doctor was most careful about — and it is the same function deciding."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        dob = local_today() - timedelta(days=int(15.1 * 365.25))
        girl = Patient(patient_number="RChpv", full_name="طفلة",
                       gender="female", date_of_birth=dob, is_active=True)
        db.session.add(girl)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=girl.id, vaccine_id=hpv.id,
            brand_id=hpv.default_brand.id, dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(14.9 * 365.25))))
        db.session.commit()

        row = next(v for v in patient_plan(girl) if v["vaccine"].code == "HPV")

    assert len(row["doses"]) == 2, \
        "matching on today's age has reached HPV and added a third dose"


# ------------------------------------------------------- it is a row, editable

def test_the_ceiling_is_a_row_a_clinic_can_change(seeded):
    """Every clinical number in this engine is data on a screen. A clinic that
    vaccinates a child of six on indication edits or deletes this row; nobody
    recompiles anything."""
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        row = VaccineScheduleTemplate.query.filter_by(
            vaccine_id=pcv.id, code="PCV-ROUTINE-END").first()

        assert row is not None, "the ceiling is not a row at all"
        assert row.start_age_min_months == 60
        assert row.match_age_on == "today"
        assert row.doses == []


def test_it_applies_whatever_guideline_the_clinic_follows(seeded):
    """Tagged with the leaflet set on purpose, and this is why.

    The engine loads the leaflet set *plus* the chosen profile's, so a row
    tagged with one profile is invisible to every clinic following another —
    and this clinic follows the default. Tagged the other way, the fix would
    have changed nothing on the screen that reported it.
    """
    from app.extensions import db
    from app.models import Setting

    for profile in ("manufacturer", "cdc", "who"):
        with seeded["app"].app_context():
            Setting.set("vaccine_guideline_profile", profile)
            db.session.commit()

        assert _pcv(seeded, _child(seeded, 8, f"g{profile}"))["doses"] == [], \
            f"the ceiling disappears for a clinic following {profile}"


def test_a_profile_band_does_not_blank_the_babies(seeded):
    """Measured, not reasoned about, and it is why this is one lone band.

    A band whose source *is* the chosen profile makes that profile
    authoritative for the whole vaccine, and its silence about an age then
    means "no course". Seeded under `cdc`, this ceiling blanked the infant
    series for every baby in a clinic following the CDC.
    """
    from app.extensions import db
    from app.models import Setting

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", "cdc")
        db.session.commit()

    assert len(_pcv(seeded, _child(seeded, 0.25, "cdcbaby"))["doses"]) == 4


def test_the_new_column_is_registered_for_an_existing_database(seeded):
    from app.utils.schema import ADDITIONS

    assert ("vaccine_schedule_templates", "match_age_on") in {
        (table, column) for table, column, *_ in ADDITIONS}
