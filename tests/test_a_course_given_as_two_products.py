"""A course that changed product, and the card that printed only the last one.

Reported from a clinic, on the pneumococcal: *"الحالة دي واخده ٣ جرعات
Synflorix وجرعة منشطة Prevenar. الكلام ده مش ظاهر — شكله إنه واخد كله
بريفينار."*

Which is exactly what it did. ``chosen_brand`` answers a different question —
*which product is this child on now*, so the next dose is offered as the right
one — and the card printed that answer over the whole course. The dose rows
underneath carried a date and nothing else, though every one of them knows its
own product: ``pv.brand`` sits in the loop that draws them.

So a record of three Synflorix and one Prevenar read as four Prevenar. Not a
missing feature — a card stating something the record does not say, on the
page a family is handed as their vaccination certificate.

A card names one product only when one product is the truth. Otherwise the
doses name themselves.
"""
from datetime import date, timedelta

import pytest


def _pneumo(clinic):
    """A vaccine with two brands on the same four-dose schedule.

    Two brands is the whole point: with one, the card cannot be wrong.
    """
    from app.models import Vaccine, VaccineBrand, VaccineBrandDose

    with clinic["app"].app_context():
        db = clinic["db"]
        vaccine = Vaccine(code="PCV2", name_ar="المكورات الرئوية",
                          name_en="Pneumococcal", is_mandatory=False)
        db.session.add(vaccine)
        db.session.flush()
        brands = {}
        for name in ("Synflorix", "Prevenar 13"):
            brand = VaccineBrand(vaccine_id=vaccine.id, name=name, price=900,
                                 doses_per_vial=1,
                                 is_default=(name == "Synflorix"))
            db.session.add(brand)
            db.session.flush()
            for number, months in ((1, 2), (2, 4), (3, 6), (4, 12)):
                db.session.add(VaccineBrandDose(
                    brand_id=brand.id, dose_number=number, age_months=months))
            brands[name] = brand.id
        db.session.commit()
        return vaccine.id, brands


def _give(clinic, vaccine_id, brand_id, dose_number, when):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=vaccine_id,
            brand_id=brand_id, dose_number=dose_number, given_date=when,
            event_type="given"))
        clinic["db"].session.commit()


def _card(clinic, vaccine_id):
    from app.models import Patient
    from app.utils.vaccines import certificate_cards, patient_plan

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        cards = certificate_cards(patient_plan(patient))
        return next((c for c in cards if c["vaccine"].id == vaccine_id), None)


@pytest.fixture
def mixed(clinic):
    """The reported case: three Synflorix, then a Prevenar booster."""
    vaccine_id, brands = _pneumo(clinic)
    start = date(2024, 1, 17)
    for number, brand, day in ((1, "Synflorix", 0), (2, "Synflorix", 59),
                               (3, "Synflorix", 143),
                               (4, "Prevenar 13", 355)):
        _give(clinic, vaccine_id, brands[brand], number,
              start + timedelta(days=day))
    return vaccine_id, brands


@pytest.fixture
def single(clinic):
    """The ordinary case: one product all the way through."""
    vaccine_id, brands = _pneumo(clinic)
    start = date(2024, 1, 17)
    for number, day in ((1, 0), (2, 59), (3, 143), (4, 355)):
        _give(clinic, vaccine_id, brands["Synflorix"], number,
              start + timedelta(days=day))
    return vaccine_id, brands


# ------------------------------------------------------- the dose knows ----
def test_each_dose_carries_the_product_it_was_given_as(clinic, mixed):
    """The fact that was in the loop and never put on the row."""
    vaccine_id, _brands = mixed
    names = [d["brand_name"] for d in _card(clinic, vaccine_id)["doses"]]
    assert names == ["Synflorix", "Synflorix", "Synflorix", "Prevenar 13"]


def test_the_booster_is_not_relabelled_as_the_rest(clinic, mixed):
    """The specific misreading: the last dose's product printed over the
    first three."""
    vaccine_id, _brands = mixed
    doses = _card(clinic, vaccine_id)["doses"]
    assert doses[0]["brand_name"] != doses[3]["brand_name"]


# ---------------------------------------------------- what the card says ---
def test_a_mixed_course_names_no_single_product(clinic, mixed):
    """The header is where the untruth was printed."""
    vaccine_id, _brands = mixed
    card = _card(clinic, vaccine_id)
    assert card["mixed"] is True
    assert card["brand"] is None


def test_a_mixed_course_lists_the_products_it_used(clinic, mixed):
    """Saying nothing would trade one wrong answer for no answer. The card
    says both, in the order they were used."""
    vaccine_id, _brands = mixed
    assert _card(clinic, vaccine_id)["brands"] == ["Synflorix", "Prevenar 13"]


def test_a_single_product_course_still_names_it(clinic, single):
    """The common case must not lose its label to fix the rare one."""
    vaccine_id, _brands = single
    card = _card(clinic, vaccine_id)
    assert card["mixed"] is False
    assert card["brand"] is not None
    assert card["brand"].name == "Synflorix"


# ------------------------------------------------------------ on screen ----
def test_the_profile_shows_both_products(clinic, mixed):
    """All of it is worth nothing if the page still prints one name."""
    vaccine_id, _brands = mixed
    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "Synflorix" in page
    assert "Prevenar 13" in page


def test_every_dose_names_its_product_even_on_a_single_product_course(
        clinic, single):
    """Asked for directly by the doctor: the trade name on every dose, the
    generic name at the top.

    The trade name is a fact about the dose, not about the course, and it is
    the level a doctor reads it at — which of these four was Synflorix is a
    question the row has to answer on its own, whether or not the course
    happened to change product.
    """
    vaccine_id, _brands = single
    boss = clinic["sign_in"]("boss")
    page = boss.get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert page.count("Synflorix") == 4


def test_the_certificate_prints_a_mixed_course_without_breaking(clinic, mixed):
    """The page a family is handed.

    Its card header read the course's single product with no guard, so the
    moment a mixed course stopped having one, printing the certificate for
    this child would have failed outright — a fix to a cosmetic untruth
    turning into a page that will not open.
    """
    vaccine_id, _brands = mixed
    boss = clinic["sign_in"]("boss")
    reply = boss.get(
        f"/vaccinations/{clinic['ids']['child']}/certificate")
    assert reply.status_code == 200
    page = reply.get_data(as_text=True)
    assert "Synflorix" in page
    assert "Prevenar 13" in page
