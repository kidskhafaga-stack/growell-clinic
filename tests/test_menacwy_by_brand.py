"""Three meningococcal ACWY conjugates that agree about almost nothing.

Menactra starts at nine months, Menveo at two, Nimenrix at six weeks. From
seven to twenty-three months Menactra is two doses and Menveo is two doses on
different dates; below six months Menveo is a four-dose infant series and
Nimenrix is two primary doses plus a booster. From two years all three are one
dose. **The number of injections a child needs depends on which product is in
the fridge**, and one schedule on the vaccine could only ever have been right
for one of them.

The rule was in the catalogue the whole time, as a sentence of Arabic prose
per brand for a doctor to read with their eyes — `catch_up_ar` on each of the
three, saying three different things, read by nothing. The mechanism to fix it
(a band scoped to a `brand_id`) had also existed since the schedule templates
were built. This file is the two of them meeting.

Mencevax is deliberately not banded. It is a polysaccharide — one dose from
two years, no infant course to get wrong — so it falls through to the
vaccine's own schedule, and the test that it did is the one that proves bands
are opt-in rather than something every trade name now needs.
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


def _child(seeded, months, tag, brand=None, doses=()):
    """A child of `months`, with `doses` as [(number, age_in_months)] of
    `brand`. With no doses the brand is still handed to the plan, because the
    question "what would this product mean for this child" is one the doctor
    asks before the first injection, not after it."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    with seeded["app"].app_context():
        vac = Vaccine.query.filter_by(code="MENACWY").first()
        dob = local_today() - timedelta(days=int(months * 30.44))
        kid = Patient(patient_number=f"MC{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        if brand and doses:
            row = VaccineBrand.query.filter_by(vaccine_id=vac.id,
                                               name=brand).first()
            for number, age in doses:
                db.session.add(PatientVaccine(
                    patient_id=kid.id, vaccine_id=vac.id, brand_id=row.id,
                    dose_number=number, event_type="given",
                    given_date=dob + timedelta(days=int(age * 30.44))))
        db.session.commit()
        return kid.id


def _course(seeded, patient_id, brand=None):
    """The MenACWY row of a child's plan, optionally forcing a trade name.

    `patient_plan` follows the brand on the record and falls back to the
    vaccine's default, so a child with nothing given yet reads the default.
    Making the default the brand under test is how a first-dose question gets
    asked at all.
    """
    from app.extensions import db
    from app.models import Patient, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        if brand:
            vac = Vaccine.query.filter_by(code="MENACWY").first()
            for row in vac.brands:
                row.is_default = (row.name == brand)
            db.session.commit()
        plan = patient_plan(db.session.get(Patient, patient_id))
        return next(v for v in plan if v["vaccine"].code == "MENACWY")


# ------------------------------------------- the same child, three products

def test_the_same_infant_is_a_different_course_on_each_product(seeded):
    """The whole feature in one assertion. Three months old, nothing given.

    Menveo's infant series is four doses; Nimenrix's is two plus a booster.
    Menactra is not licensed this young at all and keeps its own single-dose
    course, which is the honest answer for a product that has nothing to say
    about a three-month-old.
    """
    counts = {}
    for brand in ("Menveo", "Nimenrix", "Menactra"):
        kid = _child(seeded, 3, f"inf{brand}")
        counts[brand] = len(_course(seeded, kid, brand=brand)["doses"])

    assert counts["Menveo"] == 4, counts
    assert counts["Nimenrix"] == 3, counts
    assert counts["Menveo"] != counts["Nimenrix"], (
        "two products with different infant series produced the same course: "
        f"{counts}")


def test_from_two_years_all_three_settle_on_one_dose(seeded):
    """The half that keeps the bands from being noise. They disagree about
    infants and agree about everybody else, and a change that made them
    disagree at thirty months would be wrong in the commonest case."""
    for brand in ("Menveo", "Nimenrix", "Menactra"):
        kid = _child(seeded, 30, f"tod{brand}")
        doses = _course(seeded, kid, brand=brand)["doses"]
        assert len(doses) == 1, f"{brand} at 30 months is {len(doses)} doses"


# ------------------------------------------------ the band reads the record

def test_menactra_in_the_second_year_is_two_doses(seeded):
    """9–23 months, three months apart. From two years it is one — so the
    same product answers differently depending only on when it was begun."""
    kid = _child(seeded, 10, "mact10")

    assert len(_course(seeded, kid, brand="Menactra")["doses"]) == 2


def test_an_infant_already_on_the_series_is_not_moved_to_the_catch_up(seeded):
    """A nine-month-old two doses into the four-dose infant series stays on
    it. Matched on today's age their course would halve overnight, and two
    injections they were promised would quietly disappear.

    What holds it is the band locking at the **first** dose, which is the same
    rule HPV rests on — not the "previously unvaccinated" condition, which is
    about arriving at this product from another one. Measured: strip that
    condition off the band and this test still passes, because the child never
    reaches it. The condition is exercised by the switch test below instead.
    """
    kid = _child(seeded, 9, "cu", brand="Menveo",
                 doses=[(1, 2), (2, 4)])

    doses = _course(seeded, kid, brand="Menveo")["doses"]

    assert len(doses) == 4, (
        "a child part-way through the infant series was moved onto the "
        f"two-dose catch-up: {len(doses)} doses")


def test_an_unvaccinated_child_of_the_same_age_does_get_the_catch_up(seeded):
    """The other side of it — otherwise the condition could be "never"."""
    kid = _child(seeded, 9, "cu2")

    assert len(_course(seeded, kid, brand="Menveo")["doses"]) == 2


def test_arriving_from_another_product_is_not_previously_unvaccinated(seeded):
    """What the leaflet's word "unvaccinated" is doing in the band.

    A nine-month-old with two Nimenrix behind them, switched to Menveo. They
    are the right age for the 7–23 month catch-up and they are not who it
    describes: two more Menveo doses would be a course invented for them out
    of a sentence about a child with an empty record.

    So no band matches, and what the file says is **not** a quiet "nothing
    further owed" — it falls to a schedule the record already contradicts, and
    the clinical-review layer says so. That is the two halves of this engine
    meeting: the leaflet has no answer for this child, and the program's reply
    is to ask a doctor rather than to pick one.

    The course length is asserted as well as the flag, and deliberately.
    Measured: with the condition stripped off the band this child lands on the
    catch-up, has three doses against a two-dose course, and is flagged for
    review just the same — so the flag alone cannot tell the two apart. What
    can is that they were never put on that course at all.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    kid = _child(seeded, 9, "sw", brand="Nimenrix", doses=[(1, 2), (2, 4)])

    with seeded["app"].app_context():
        vac = Vaccine.query.filter_by(code="MENACWY").first()
        menveo = VaccineBrand.query.filter_by(vaccine_id=vac.id,
                                              name="Menveo").first()
        db.session.add(PatientVaccine(
            patient_id=kid, vaccine_id=vac.id, brand_id=menveo.id,
            dose_number=3, event_type="given",
            given_date=db.session.get(Patient, kid).date_of_birth
            + timedelta(days=int(9 * 30.44))))
        db.session.commit()
        row = next(v for v in patient_plan(db.session.get(Patient, kid))
                   if v["vaccine"].code == "MENACWY")

    assert row["brand"].name == "Menveo", \
        "the course did not follow the product actually being used"
    assert len(row["doses"]) != 2, (
        "a child arriving from another product was put on the "
        '"previously unvaccinated" two-dose catch-up')
    assert row["review"] == "more_than_scheduled", (
        "a child no guideline describes was handed a course anyway: "
        f"review={row['review']}, {len(row['doses'])} doses")


# --------------------------------------------------- bands stay opt-in

def test_the_polysaccharide_keeps_the_plain_schedule(seeded):
    """Mencevax has no bands, so it falls through to the brand's own dose
    rows. A design where every trade name needs a band is a design where the
    next one added is silently wrong."""
    from app.models import VaccineBrand

    kid = _child(seeded, 36, "poly")
    doses = _course(seeded, kid, brand="Mencevax")["doses"]

    with seeded["app"].app_context():
        row = VaccineBrand.query.filter_by(name="Mencevax").first()
        assert row.doses_change_by_start_age is False

    assert len(doses) == 1


def test_the_bands_are_rows_a_clinic_can_edit(seeded):
    """The standing rule for this whole engine: the schedule is data on a
    screen, not a branch in the code. Asserted as "the rows exist and carry
    the brand", because a band with no `brand_id` would apply to every
    product at once — which is the bug being fixed, re-introduced."""
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        vac = Vaccine.query.filter_by(code="MENACWY").first()
        rows = VaccineScheduleTemplate.query.filter_by(vaccine_id=vac.id).all()
        banded = [r for r in rows if (r.code or "").startswith("MCV4-")]

        assert banded, "no MenACWY bands were seeded at all"
        assert all(r.brand_id for r in banded), \
            "a MenACWY band is not tied to a trade name"
        assert len({r.brand_id for r in banded}) == 3, \
            "the bands do not cover the three conjugates separately"


def test_a_reseed_keeps_a_doctors_edit(seeded):
    """Seeded rows fill blanks; they never overwrite a decision."""
    from app.extensions import db
    from app.models import VaccineScheduleTemplate

    from app.utils.vaccines import seed_vaccine_schedules

    with seeded["app"].app_context():
        row = VaccineScheduleTemplate.query.filter_by(
            code="MCV4-MENACTRA-2Y").first()
        row.label = "قرار العيادة"
        db.session.commit()

        seed_vaccine_schedules()
        db.session.commit()

        again = VaccineScheduleTemplate.query.filter_by(
            code="MCV4-MENACTRA-2Y").all()
        assert len(again) == 1, "the reseed added a second copy"
        assert again[0].label == "قرار العيادة"
