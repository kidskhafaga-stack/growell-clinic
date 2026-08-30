"""Three things the vaccination certificate knew and did not print.

From a doctor's screenshot of one child's certificate — sixteen doses across
seven vaccines, and the hexavalent row reading:

    DOSE 4   BRAND —   GIVEN 2025-05-10

*«ليه السداسي مش موجود البراند؟ وليه مش ظاهر البوستر — لازم نميز البوستر،
والجرعة الرابعة دي بوستر بتاعت السداسي.»*

**The product was missing because there are two places a dose row is built.**
The per-dose brand went into the one that walks the schedule; the other builds
the doses a course does *not* contain — a booster past the end of a three-dose
series, which is exactly the row here. So the rows a doctor looks at hardest
were the rows that printed a dash.

**The booster was missing because nothing rendered it.** The plan works it out
on every dose and has for a long time; the certificate never asked. And on a
course whose schedule stops at three, a recorded fourth was not being counted
as a booster at all: `is_booster` looked the number up in the schedule, did
not find it, and said no. On a fixed course there is nothing else an extra
dose can be.

**And two columns were printed empty from top to bottom.** A record built from
what a family carried in names no doctor and no lot number; drawing them
anyway gives the certificate two rulings of em-dashes, which reads as a
document nobody finished.
"""
import re
from datetime import date

import pytest


def _vaccine(clinic, code, name, doses):
    from app.models import Vaccine, VaccineBrand, VaccineBrandDose

    with clinic["app"].app_context():
        db = clinic["db"]
        vaccine = Vaccine(code=code, name_ar=name, is_mandatory=False)
        db.session.add(vaccine)
        db.session.flush()
        brand = VaccineBrand(vaccine_id=vaccine.id, name=f"{code}xim",
                             price=0, doses_per_vial=1, is_default=True)
        db.session.add(brand)
        db.session.flush()
        for number, months in doses:
            db.session.add(VaccineBrandDose(brand_id=brand.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.commit()
        return vaccine.id, brand.id


def _give(clinic, vaccine_id, brand_id, dose_number, when, **extra):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=vaccine_id,
            brand_id=brand_id, dose_number=dose_number, given_date=when,
            event_type="given", **extra))
        clinic["db"].session.commit()


def _cert(clinic):
    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/vaccinations/{clinic['ids']['child']}/certificate").get_data(
            as_text=True)
    return page, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


@pytest.fixture
def hexa(clinic):
    """The reported course: three scheduled doses, a fourth one recorded."""
    vaccine_id, brand_id = _vaccine(clinic, "HEXA", "السداسي",
                                    [(1, 2), (2, 4), (3, 6)])
    _give(clinic, vaccine_id, brand_id, 4, date(2025, 5, 10))
    return vaccine_id, brand_id


# ------------------------------------------------------------ the product --
def test_a_dose_past_the_schedule_still_names_its_product(clinic, hexa):
    """The dash in the screenshot. The record knows the brand; the dose
    builder for off-schedule doses was never told to carry it."""
    _page, text = _cert(clinic)
    assert "HEXAxim" in text


def test_the_scheduled_doses_name_theirs_too(clinic):
    """The other builder, so the fix to one is not a regression in the other."""
    vaccine_id, brand_id = _vaccine(clinic, "PCV9", "المكورات",
                                    [(1, 2), (2, 4)])
    _give(clinic, vaccine_id, brand_id, 1, date(2024, 1, 17))
    _page, text = _cert(clinic)
    assert "PCV9xim" in text


# ------------------------------------------------------------ the booster --
def test_a_fourth_dose_of_a_three_dose_course_is_a_booster(clinic, hexa):
    """`is_booster` looked the number up in the schedule, did not find it and
    said no. On a fixed course there is nothing else an extra dose can be."""
    from app.models import VaccineBrand
    from app.utils.dose_labels import is_booster

    _vid, brand_id = hexa
    with clinic["app"].app_context():
        brand = clinic["db"].session.get(VaccineBrand, brand_id)
        assert is_booster(brand, 4) is True
        assert is_booster(brand, 2) is False


def test_the_certificate_marks_it(clinic, hexa):
    """Worked out for a long time, printed never — the row arrived as a bare
    "4" and left the reader to know what that meant."""
    _page, text = _cert(clinic)
    assert "منشّطة" in text


def test_a_primary_dose_is_not_marked(clinic):
    """The mark means something only if it is not on everything."""
    vaccine_id, brand_id = _vaccine(clinic, "PCV8", "المكورات",
                                    [(1, 2), (2, 4)])
    _give(clinic, vaccine_id, brand_id, 1, date(2024, 1, 17))
    _page, text = _cert(clinic)
    assert "منشّطة" not in text


def test_a_dose_inside_a_gap_in_the_schedule_is_not_a_booster(clinic):
    """A number the schedule does not list is not automatically a booster.

    Mutation testing walked past this: every other test here uses a number
    the schedule either has or sits past the end of, so "past the last dose"
    and "not in the list at all" gave the same answer. A catalogue with a gap
    — doses 1 and 3 written, 2 never filled in — separates them, and a
    recorded dose 2 is a primary dose nobody typed, not a booster.
    """
    from app.models import VaccineBrand
    from app.utils.dose_labels import is_booster

    _vid, brand_id = _vaccine(clinic, "GAP1", "بفجوة", [(1, 2), (3, 6)])
    with clinic["app"].app_context():
        brand = clinic["db"].session.get(VaccineBrand, brand_id)
        assert is_booster(brand, 2) is False
        assert is_booster(brand, 4) is True


def test_a_season_is_not_a_booster(clinic):
    """Influenza numbers doses across a lifetime, so a fifth winter is dose 5
    — a fifth season, not a booster. The off-schedule path refuses repeating
    courses before it ever asks."""
    from app.models import Vaccine

    vaccine_id, brand_id = _vaccine(clinic, "FLU9", "الإنفلونزا",
                                    [(1, 6), (2, 7)])
    with clinic["app"].app_context():
        vaccine = clinic["db"].session.get(Vaccine, vaccine_id)
        vaccine.is_seasonal = True
        clinic["db"].session.commit()
    _give(clinic, vaccine_id, brand_id, 5, date(2026, 1, 5))

    _page, text = _cert(clinic)
    assert "منشّطة" not in text


# ------------------------------------------------------------ the columns --
def test_columns_nothing_can_fill_are_not_drawn(clinic, hexa):
    """Two rulings of em-dashes down a certificate read as a document nobody
    finished."""
    _page, text = _cert(clinic)
    assert "رقم اللوط" not in text


def test_a_column_with_something_in_it_is_drawn(clinic):
    """And they come back the moment a dose has one — the certificate must
    not quietly drop a lot number somebody recorded."""
    vaccine_id, brand_id = _vaccine(clinic, "PCV7", "المكورات",
                                    [(1, 2), (2, 4)])
    _give(clinic, vaccine_id, brand_id, 1, date(2024, 1, 17),
          lot_number="LOT-77")
    _page, text = _cert(clinic)
    assert "رقم اللوط" in text
    assert "LOT-77" in text


def test_a_dose_given_elsewhere_keeps_its_column(clinic):
    """"Given elsewhere" lives in the doctor column, and it is the whole
    reason a family carries the paper. Dropping the column because no doctor
    of this clinic is named would delete it."""
    vaccine_id, brand_id = _vaccine(clinic, "PCV6", "المكورات",
                                    [(1, 2), (2, 4)])
    _give(clinic, vaccine_id, brand_id, 1, date(2024, 1, 17),
          given_outside=True, outside_place="وحدة صحية")
    _page, text = _cert(clinic)
    assert "وحدة صحية" in text
