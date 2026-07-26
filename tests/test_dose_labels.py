"""Which dose was given, and what happens after it.

A vaccination record is only useful if it says *which* dose. Everything
downstream depends on it: what the parent is told, when the next reminder
falls, whether the course is finished at all. And a dose the child had
somewhere else has to be recordable — otherwise the schedule is wrong for
years — without touching the fridge or the till.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.dose_labels import (dose_choices, dose_label,  # noqa: E402
                                   is_booster, next_dose, next_dose_text)


class FakeDose:
    def __init__(self, number, age_months, booster=False):
        self.dose_number = number
        self.age_months = age_months
        self.is_booster = booster


class FakeBrand:
    def __init__(self, doses):
        self.doses = doses


class FakeVaccine:
    def __init__(self, seasonal=False):
        self.is_seasonal = seasonal


class FakeChild:
    date_of_birth = date(2025, 1, 1)


# A pentavalent-shaped course: three primary doses then a booster at 18 months.
COURSE = FakeBrand([FakeDose(1, 2), FakeDose(2, 4), FakeDose(3, 6),
                    FakeDose(4, 18)])


# ------------------------------------------------------------- the label --
def test_each_dose_is_named_not_numbered():
    assert dose_label(1) == "الجرعة الأولى"
    assert dose_label(2) == "الجرعة الثانية"
    assert dose_label(3) == "الجرعة الثالثة"
    assert dose_label(9) == "الجرعة رقم 9"
    assert dose_label(2, "en") == "second dose"


def test_the_booster_is_called_a_booster():
    """"Dose four" means nothing to a parent; "the booster" does."""
    assert dose_label(4, brand=COURSE) == "الجرعة المنشّطة"
    assert dose_label(4, "en", brand=COURSE) == "booster"
    # …and the primary doses are not.
    assert dose_label(3, brand=COURSE) == "الجرعة الثالثة"


def test_a_booster_is_the_last_dose_a_year_after_the_one_before():
    """Inferred the way a paediatrician would, when the schedule doesn't say."""
    assert is_booster(COURSE, 4) is True
    assert is_booster(COURSE, 3) is False
    # A two-dose course a month apart has no booster in it.
    close = FakeBrand([FakeDose(1, 2), FakeDose(2, 3)])
    assert is_booster(close, 2) is False
    # A single-dose vaccine certainly doesn't.
    assert is_booster(FakeBrand([FakeDose(1, 9)]), 1) is False


def test_the_schedule_can_simply_say_so():
    marked = FakeBrand([FakeDose(1, 2), FakeDose(2, 4, booster=True)])
    assert is_booster(marked, 2) is True


def test_a_seasonal_dose_is_named_by_its_season():
    flu = FakeVaccine(seasonal=True)
    assert dose_label(3, vaccine=flu, on_date=date(2026, 10, 1)) == "جرعة موسم 2026"


# -------------------------------------------------------- what comes next --
def test_the_next_dose_is_a_date():
    info = next_dose(FakeChild(), FakeVaccine(), COURSE, 1)
    assert info["kind"] == "date"
    assert info["number"] == 2
    assert info["date"] == date(2025, 5, 1)      # born Jan, dose 2 at 4 months


def test_after_the_last_dose_the_course_is_finished_not_unknown():
    """"Finished" and "we don't know" have to be different answers. A dash for
    both tells a parent nothing and tells the reminder engine less."""
    assert next_dose(FakeChild(), FakeVaccine(), COURSE, 4)["kind"] == "complete"
    assert "اكتمل" in next_dose_text(FakeChild(), FakeVaccine(), COURSE, 4)


def test_a_seasonal_vaccine_comes_back_next_season():
    flu = FakeVaccine(seasonal=True)
    info = next_dose(FakeChild(), flu, COURSE, 1, on_date=date(2026, 10, 1))
    assert info["kind"] == "seasonal"
    assert info["year"] == 2027
    assert "2027" in next_dose_text(FakeChild(), flu, COURSE, 1,
                                    on_date=date(2026, 10, 1))


def test_without_a_birth_date_we_say_we_do_not_know():
    class NoBirthday:
        date_of_birth = None

    info = next_dose(NoBirthday(), FakeVaccine(), COURSE, 1)
    assert info["kind"] == "unknown"
    assert info["number"] == 2                   # …but still which dose it is


def test_the_message_line_names_the_dose_and_the_date():
    line = next_dose_text(FakeChild(), FakeVaccine(), COURSE, 3)
    assert "الجرعة المنشّطة" in line and "2026-07-01" in line


# ------------------------------------------------------------- the picker --
def test_the_picker_offers_every_dose_and_marks_what_is_done():
    options = dose_choices(FakeVaccine(), COURSE, given_numbers={1, 2})
    assert [o["number"] for o in options] == [1, 2, 3, 4]
    assert [o["given"] for o in options] == [True, True, False, False]
    assert options[3]["booster"] is True
    assert options[1]["label"] == "الجرعة الثانية"


def test_a_vaccine_with_no_schedule_can_still_be_recorded():
    """A seasonal vaccine, or a brand the clinic hasn't filled in, must not
    become unrecordable."""
    options = dose_choices(FakeVaccine(seasonal=True), FakeBrand([]),
                           given_numbers={1, 2})
    assert len(options) == 1
    assert options[0]["number"] == 3


# --------------------------------------------------- a dose given outside --
@pytest.fixture()
def clinic():
    """Ids rather than objects: the tests open their own app context, and a
    model loaded in the fixture's session would be mutated in one session and
    committed from another."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Patient, Vaccine, VaccineBrand,
                                VaccineBrandDose, VaccineInventory)

        vaccine = Vaccine(code="PENTA", name_ar="خماسي", is_mandatory=False)
        db.session.add(vaccine)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=vaccine.id, name="Pentaxim", price=300)
        db.session.add(brand)
        db.session.flush()
        for number, age in ((1, 2), (2, 4), (3, 6)):
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number, age_months=age))
        db.session.add(VaccineInventory(brand_id=brand.id, lot_number="B1",
                                        qty_received=10, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        child = Patient(patient_number="V1", full_name="طفل", gender="male",
                        date_of_birth=date(2025, 1, 1))
        db.session.add(child)
        db.session.commit()
        ids = {"child": child.id, "vaccine": vaccine.id, "brand": brand.id}
    yield {"app": app, "db": db, "ids": ids}


def _load(ids):
    from app.extensions import db
    from app.models import Patient, Vaccine, VaccineBrand

    return (db.session.get(Patient, ids["child"]),
            db.session.get(Vaccine, ids["vaccine"]),
            db.session.get(VaccineBrand, ids["brand"]))


def _stock_used():
    from app.models import VaccineInventory

    return VaccineInventory.query.one().qty_used or 0


def test_a_dose_given_elsewhere_is_recorded_but_takes_no_stock(clinic):
    """The first dose at a government unit has to go on the card — otherwise
    the whole schedule is wrong for years — without touching the fridge."""
    from app.utils.vaccines import administer_dose

    with clinic["app"].app_context():
        child, vaccine, brand = _load(clinic["ids"])
        before = _stock_used()
        pv, _ = administer_dose(child, vaccine, brand=brand, dose_number=1,
                                given_outside=True,
                                outside_place="وحدة صحية الهرم",
                                given_date=date(2025, 3, 1))
        clinic["db"].session.commit()
        assert pv.dose_number == 1
        assert pv.given_outside is True
        assert pv.outside_place == "وحدة صحية الهرم"
        assert pv.inventory_id is None          # nothing was drawn
        assert _stock_used() == before


def test_the_dose_the_clinic_gave_does_take_stock(clinic):
    from app.utils.vaccines import administer_dose

    with clinic["app"].app_context():
        child, vaccine, brand = _load(clinic["ids"])
        before = _stock_used()
        pv, result = administer_dose(child, vaccine, brand=brand, dose_number=2)
        assert pv is not None, f"not recorded: {result}"
        clinic["db"].session.commit()
        assert pv.inventory_id is not None
        assert _stock_used() == before + 1


def test_a_clinic_dose_cannot_claim_to_have_been_given_elsewhere(clinic):
    """The record must not say two places at once."""
    from app.utils.vaccines import administer_dose

    with clinic["app"].app_context():
        child, vaccine, brand = _load(clinic["ids"])
        pv, _ = administer_dose(child, vaccine, brand=brand, dose_number=1,
                                given_outside=False, outside_place="وحدة صحية")
        clinic["db"].session.commit()
        assert pv.outside_place is None


def test_recording_the_first_dose_outside_puts_the_second_next(clinic):
    """Which is the whole point of being able to record it."""
    from app.utils.vaccines import administer_dose, next_undone_dose_number

    with clinic["app"].app_context():
        child, vaccine, brand = _load(clinic["ids"])
        administer_dose(child, vaccine, brand=brand, dose_number=1,
                        given_outside=True, outside_place="وحدة صحية")
        clinic["db"].session.commit()
        assert next_undone_dose_number(child.id, vaccine, brand) == 2
