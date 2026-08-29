"""A vaccination that happened, which no screen in the program would show.

Reported from a clinic, on the hexavalent: *"كان في حالة واحدة جرعة ٤ بس في
السداسي جرعة منشطة. السيستم كان حاسبها الجرعة الأولى، ولما عدّلتها إنها
الرابعة اختفت خالص"*.

**Both halves of that are the same fault.** The plan walks the *course* — the
brand's dose rows, or the age band that replaced them — and looks each number
up among the doses on file. A recorded dose whose number the course does not
contain is never looked up, so it is never drawn. The row sits in the
database and nothing in the program mentions it: not the file, not the
certificate, not the visit panel, not the counts.

Filed as dose 1 it was wrong but visible. Corrected to dose 4 — the true
number — it vanished. And adding a fourth row to the catalogue afterwards did
not bring it back, because the course for a child who has already started is
the one their brand or their band fixed, not the one the catalogue holds now.

**The schedule decides what to offer; the record decides what to show.** A
vaccination that happened is not the schedule's to disown. It comes back
marked, so a screen can say what it is — a booster past the end of the
schedule, or a number somebody can now see to correct — rather than the
program deciding on its own that it never happened.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hexa(clinic):
    """A three-dose course, and a child whose booster was recorded as dose 4."""
    from app.extensions import db
    from app.models import (Patient, PatientVaccine, Vaccine, VaccineBrand,
                            VaccineBrandDose, VaccineInventory)
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        today = local_today()
        vaccine = Vaccine(code="HEXA", name_ar="السداسي", is_mandatory=False)
        db.session.add(vaccine)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=vaccine.id, name="Hexaxim", price=900,
                             doses_per_vial=1)
        db.session.add(brand)
        db.session.flush()
        for number, months in ((1, 2), (2, 4), (3, 6)):
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.add(VaccineInventory(brand_id=brand.id, lot_number="H1",
                                        qty_received=9, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        child = Patient(patient_number="HX1", full_name="طفل السداسي",
                        gender="male",
                        date_of_birth=today - timedelta(days=560),
                        is_active=True)
        db.session.add(child)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=child.id, vaccine_id=vaccine.id, brand_id=brand.id,
            dose_number=4, given_date=today - timedelta(days=10),
            lot_number="BOOST", event_type="given", given_outside=False))
        db.session.commit()
        clinic["vaccine"] = vaccine.id
        clinic["brand"] = brand.id
        clinic["child"] = child.id
    return clinic


def _course(hexa, patient_id=None):
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with hexa["app"].app_context():
        patient = hexa["db"].session.get(Patient, patient_id or hexa["child"])
        plan = patient_plan(patient)
        return next(item for item in plan
                    if item["vaccine"].code == "HEXA")


# --------------------------------------------------------- the dose is there

def test_the_dose_that_vanished_is_on_the_plan(hexa):
    """The report, as the test that would have caught it."""
    numbers = [d["dose_number"] for d in _course(hexa)["doses"]]

    assert 4 in numbers, f"dose 4 vanished — the plan shows {numbers}"


def test_it_is_marked_as_given_not_as_something_due(hexa):
    """It happened. Whatever the schedule thinks of the number, every screen
    reads this word."""
    dose = next(d for d in _course(hexa)["doses"] if d["dose_number"] == 4)

    assert dose["status"] == "done"
    assert dose["given_date"] is not None
    assert dose["lot_number"] == "BOOST", "the record's own details are lost"


def test_it_is_marked_as_outside_the_schedule(hexa):
    """Half a fix would be worse: a fourth dose of three, drawn as if the
    course had always had four, tells the reader nothing about why."""
    course = _course(hexa)
    dose = next(d for d in course["doses"] if d["dose_number"] == 4)

    assert dose["off_schedule"] is True
    for other in course["doses"]:
        if other["dose_number"] != 4:
            assert not other.get("off_schedule"), \
                "an ordinary scheduled dose is marked as outside the schedule"


def test_the_count_counts_it(hexa):
    """"1 / 3" beside four rows is a card arguing with itself."""
    course = _course(hexa)

    assert course["total"] == 4
    assert sum(1 for d in course["doses"] if d["status"] == "done") == 1


def test_a_child_whose_only_dose_is_off_schedule_has_started_the_course(hexa):
    """The same fault reached further than the list. "Has this clinic begun
    this course" is read off the rendered doses — so a child whose only dose
    was invisible read as never vaccinated, and everything that hangs on
    *started* hung off a false answer."""
    course = _course(hexa)

    assert course["started"] is True


def test_the_screen_shows_it(hexa):
    page = hexa["sign_in"]("boss").get(
        f"/vaccinations/{hexa['child']}").get_data(as_text=True)

    assert "vaccinations.off_schedule" not in page, \
        "the strings are keys, not translations"
    assert "BOOST" in page, "the dose is still missing from the record screen"
    assert "خارج الجدول" in page, \
        "the screen draws it as an ordinary fourth dose of three"


# ------------------------------------------- and it does not invent anything

def test_a_normal_course_gains_nothing(hexa):
    """The rule adds recorded doses, never rows of its own. A course with
    nothing unusual on it must come out exactly as before."""
    from app.extensions import db
    from app.models import PatientVaccine

    with hexa["app"].app_context():
        dose = PatientVaccine.query.filter_by(patient_id=hexa["child"]).first()
        dose.dose_number = 2
        db.session.commit()

    course = _course(hexa)

    assert [d["dose_number"] for d in course["doses"]] == [1, 2, 3]
    assert not any(d.get("off_schedule") for d in course["doses"])


def test_a_refusal_is_not_promoted_to_a_dose(hexa):
    """Only what was *given*. A refusal or a delay recorded against a number
    off the end of the schedule is not a vaccination, and drawing it as one
    would put a dose in the child's record that never went in."""
    from app.extensions import db
    from app.models import PatientVaccine
    from app.utils.clock import local_today

    with hexa["app"].app_context():
        PatientVaccine.query.filter_by(patient_id=hexa["child"]).delete()
        db.session.add(PatientVaccine(
            patient_id=hexa["child"], vaccine_id=hexa["vaccine"],
            brand_id=hexa["brand"], dose_number=5, event_type="refused",
            given_date=local_today()))
        db.session.commit()

    numbers = [d["dose_number"] for d in _course(hexa)["doses"]]

    assert 5 not in numbers, "a refusal was drawn as a dose that was given"


def test_two_records_on_one_number_do_not_double_the_row(hexa):
    """A duplicate is a data problem with its own screens; it must not become
    two identical pills in the child's file on top of that."""
    from app.extensions import db
    from app.models import PatientVaccine
    from app.utils.clock import local_today

    with hexa["app"].app_context():
        db.session.add(PatientVaccine(
            patient_id=hexa["child"], vaccine_id=hexa["vaccine"],
            brand_id=hexa["brand"], dose_number=4,
            given_date=local_today(), event_type="given"))
        db.session.commit()

    numbers = [d["dose_number"] for d in _course(hexa)["doses"]]

    assert numbers.count(4) == 1, f"dose 4 was drawn twice — {numbers}"


def test_another_childs_dose_is_not_borrowed(hexa):
    """The rows are read per patient; a filter that slipped would put one
    child's booster on another child's record."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.clock import local_today

    with hexa["app"].app_context():
        other = Patient(patient_number="HX2", full_name="طفل تاني",
                        gender="female",
                        date_of_birth=local_today() - timedelta(days=560),
                        is_active=True)
        db.session.add(other)
        db.session.flush()
        other_id = other.id
        db.session.commit()

    numbers = [d["dose_number"] for d in _course(hexa, other_id)["doses"]]

    assert 4 not in numbers, "another child's off-schedule dose was borrowed"


def test_a_course_that_repeats_every_winter_is_left_alone(hexa):
    """The regression this fix caused on its way in, pinned where the fix is.

    Influenza numbers doses across a lifetime — a fifth winter is dose 5 —
    while the season's course has slots one and two, and the seasonal path
    deliberately renumbers into them. On a repeatable course "a number the
    schedule does not contain" describes every past winter, not a booster, so
    sweeping them in listed three previous seasons as this season's doses and
    told a child vaccinated three weeks ago that they still needed a shot.
    """
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine
    from app.utils.vaccines import _doses_off_the_schedule

    with hexa["app"].app_context():
        vaccine = db.session.get(Vaccine, hexa["vaccine"])
        brand = vaccine.brands[0]
        rows = PatientVaccine.query.filter_by(patient_id=hexa["child"]).all()
        assert rows, "the fixture's booster is missing"

        # The same dose, the same rows: only the kind of course differs.
        assert _doses_off_the_schedule(vaccine, brand, rows, []), \
            "the once-in-a-lifetime course lost its off-schedule dose"
        for flag in ("is_seasonal", "on_demand"):
            setattr(vaccine, flag, True)
            assert _doses_off_the_schedule(vaccine, brand, rows, []) == [], \
                f"a {flag} course had a past dose swept into this course"
            setattr(vaccine, flag, False)


def test_a_band_that_narrowed_the_course_is_left_alone(hexa):
    """The second regression this fix caused on its way in, pinned here.

    An age band is a deliberate statement about which doses a child's course
    consists of — "switching in at 12–23 months is two doses", or a guideline
    that schedules nothing for a product at three months. The doses outside it
    are not lost; they are the history that *picked* the band. Adding them
    back as course slots turned a two-dose switch course into three and put a
    dose under a guideline that schedules none.

    So the rule applies where the fault was: a course taken straight from the
    brand's own dose rows, where a number past the end of that list has
    nowhere else in the program to live.
    """
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine
    from app.utils.vaccines import _doses_off_the_schedule

    with hexa["app"].app_context():
        vaccine = db.session.get(Vaccine, hexa["vaccine"])
        brand = vaccine.brands[0]
        rows = PatientVaccine.query.filter_by(patient_id=hexa["child"]).all()

        # Same vaccine, same rows: only whether a band decided the course.
        assert _doses_off_the_schedule(vaccine, brand, rows, [], band=None), \
            "the brand's own course lost its off-schedule dose"
        assert _doses_off_the_schedule(vaccine, brand, rows, [],
                                       band={"catch_up": False}) == [], \
            "a band's narrowed course had a dose swept back into it"


def test_a_dose_of_a_different_vaccine_is_not_borrowed(hexa):
    """The rows this child has are *every* vaccine they ever had. A course
    that swept them all in would file a pneumococcal dose under the
    hexavalent — and the child's record would show a vaccination they never
    had of a product they never took."""
    from app.extensions import db
    from app.models import PatientVaccine
    from app.utils.clock import local_today

    with hexa["app"].app_context():
        # Dose 9, so it lands outside every schedule and can only appear
        # through the rule under test.
        db.session.add(PatientVaccine(
            patient_id=hexa["child"], vaccine_id=hexa["ids"]["pcv"],
            brand_id=hexa["ids"]["brand"], dose_number=9,
            given_date=local_today(), event_type="given"))
        db.session.commit()

    numbers = [d["dose_number"] for d in _course(hexa)["doses"]]

    assert 9 not in numbers, \
        "a dose of another vaccine was drawn into this course"
