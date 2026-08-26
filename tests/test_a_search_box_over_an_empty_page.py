"""Giving a vaccine inside the visit, and a search box that could not search.

Reported from the screen: a two-day-old, the vaccinations tab of the visit, a
doctor typing a trade name into the box that says *"search a vaccine
(scientific or trade name)"* — and nothing. Under it, **Available to give now
(0)**.

**Two different faults wearing one face.**

*The count was right.* A newborn has no optional vaccine within reach: the
first fall due at six weeks and the due window is thirty days, so on day two
there is genuinely nothing to give. But the panel said only "no optional
vaccine matches this age", which reads as a program that lost the schedule.
It names the next one and its date now — the question the parent is about to
ask anyway.

*The search box was not a search.* It filtered the cards already rendered on
the page by hiding the ones that did not match. With three empty sections
there were no cards, so it could never match anything — a clinic with the
vaccine in its fridge typed the trade name and was told nothing. The whole
catalogue is rendered below now, collapsed, so the box has something to find
and a hit opens the section it is in.

*And there was no way to give it anyway.* The only deliberate-add control
listed **mandatory** vaccines. An optional vaccine given early or late, a
travel or rabies dose, a dose taken elsewhere being recorded — none of them
had a path from this tab, and the doctor had to leave the visit. The endpoint
behind that control always accepted any vaccine and any brand; only the
dropdown was narrow.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def newborn(clinic):
    """A two-day-old with an open visit, and a trade name in the catalogue."""
    from app.extensions import db
    from app.models import Patient, User, VaccineBrand, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        today = local_today()
        baby = Patient(patient_number="NB1", full_name="مولود", gender="male",
                       date_of_birth=today - timedelta(days=2), is_active=True)
        db.session.add(baby)
        db.session.flush()
        doctor = User.query.filter_by(username="doc").first()
        visit = Visit(patient_id=baby.id, doctor_id=doctor.id,
                      visit_date=today, status="open")
        db.session.add(visit)
        # A trade name that appears nowhere else on the page, so finding it
        # proves the catalogue is on the page and not that "PCV" is.
        brand = db.session.get(VaccineBrand, clinic["ids"]["brand"])
        brand.name = "Vaxneuvance"

        # A second optional vaccine, due *later* than the first. Without a
        # second one, "the soonest ahead" is a claim about a list of one and
        # naming the latest instead of the earliest would pass unnoticed.
        # Later rather than earlier on purpose: at six weeks it would fall
        # inside the thirty-day window and this child would have something to
        # give, which is not the case the file is about.
        from app.models import Vaccine, VaccineBrandDose, VaccineInventory

        rota = Vaccine(code="ROTA", name_ar="الروتا", is_mandatory=False)
        db.session.add(rota)
        db.session.flush()
        rota_brand = VaccineBrand(vaccine_id=rota.id, name="Rotarix",
                                  price=700, doses_per_vial=1)
        db.session.add(rota_brand)
        db.session.flush()
        db.session.add(VaccineBrandDose(brand_id=rota_brand.id,
                                        dose_number=1, age_months=3))
        db.session.add(VaccineInventory(brand_id=rota_brand.id,
                                        lot_number="ROT", qty_received=5,
                                        qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()
        clinic["rota"] = rota.id
        clinic["rota_name"] = rota.display_name("ar")
        clinic["baby"] = baby.id
        clinic["visit"] = visit.id
        clinic["trade_name"] = "Vaxneuvance"
    return clinic


def _panel(newborn, patient_id=None):
    from app.models import Patient
    from app.utils.vaccines import visit_vaccine_panel

    with newborn["app"].app_context():
        patient = newborn["db"].session.get(
            Patient, patient_id or newborn["baby"])
        return visit_vaccine_panel(patient)


def _tab(newborn, who="doc"):
    return newborn["sign_in"](who).get(
        f"/visits/{newborn['visit']}/record").get_data(as_text=True)


def _give(newborn, **form):
    data = {"vaccine_id": newborn["ids"]["pcv"]}
    data.update(form)
    return newborn["sign_in"]("doc").post(
        f"/visits/{newborn['visit']}/give-vaccine", data=data,
        follow_redirects=True)


# ------------------------------------------- nothing to give is not an answer

def test_a_two_day_old_is_offered_nothing_and_that_is_correct(newborn):
    """The count on the screen was right. Six weeks minus two days is well
    outside a thirty-day window, and offering a dose there would be wrong."""
    assert _panel(newborn)["give_now"] == []


def test_but_the_panel_says_when_the_first_one_is_due(newborn):
    """An empty list is a fact; a date is an answer. Without this the screen
    reads as a program that lost the schedule."""
    from app.utils.clock import local_today

    nxt = _panel(newborn)["next_optional"]

    assert nxt is not None, "the panel throws away the date it already knows"
    assert nxt["due_date"] > local_today().isoformat(), \
        "the 'next' dose is not in the future"
    assert nxt["dose_number"] == 1


def test_the_next_one_is_the_soonest_one(newborn):
    """"Next" means earliest, not first in the catalogue. Two months comes
    before three, and naming the wrong one sends a family away for the wrong
    fortnight."""
    nxt = _panel(newborn)["next_optional"]

    assert nxt["vaccine"].code == "PCV", \
        f"the panel named {nxt['vaccine'].code}, which is not the soonest"


def test_the_date_reaches_the_screen(newborn):
    page = _tab(newborn)

    assert "visits.vac_next_optional" not in page, \
        "the strings are keys, not translations"
    assert _panel(newborn)["next_optional"]["due_date"] in page


def test_a_child_with_nothing_ahead_gets_no_invented_date(newborn):
    """The other side of it: `next_optional` is None rather than a guess when
    every optional course is finished or its window has shut."""
    from app.models import Patient
    from app.utils.clock import local_today

    from app.extensions import db

    with newborn["app"].app_context():
        grown = Patient(patient_number="OLD1", full_name="كبير", gender="male",
                        date_of_birth=local_today() - timedelta(days=365 * 40),
                        is_active=True)
        db.session.add(grown)
        db.session.commit()
        grown_id = grown.id

    assert _panel(newborn, grown_id)["next_optional"] is None


# ------------------------------------ a search box needs something to search

def test_the_trade_name_is_on_the_page_for_the_box_to_find(newborn):
    """The fault, stated as the test that would have caught it. The box filters
    the cards on the page; with three empty sections there was nothing to
    filter, so a trade name the clinic stocks found nothing."""
    page = _tab(newborn)

    assert newborn["trade_name"] in page, \
        "the search box has nothing to find — it filters a page with no cards"


def test_every_vaccine_the_clinic_has_is_reachable(newborn):
    """Not only the mandatory ones, which is all the old control offered."""
    from app.models import Vaccine

    page = _tab(newborn)

    with newborn["app"].app_context():
        names = [v.display_name("ar") for v in
                 Vaccine.query.filter_by(is_discontinued=False).all()]
    for name in names:
        assert name in page, f"{name} has no way in from the visit"


def test_a_discontinued_vaccine_is_not_offered(newborn):
    """A catalogue on the page is not an excuse to offer what the clinic
    stopped giving. Scoped to the add section: the vaccine may still be named
    elsewhere on the page — in the child's own history, for one — and that is
    a record, not an offer."""
    import re

    from app.extensions import db
    from app.models import Vaccine

    with newborn["app"].app_context():
        vac = db.session.get(Vaccine, newborn["ids"]["pcv"])
        vac.is_discontinued = True
        db.session.commit()
        name = vac.display_name("ar")

    page = _tab(newborn)
    section = re.search(r'id="vacAddAny".*?</details>', page, re.S)

    assert section, "the add-any section is gone"
    assert name not in section.group(0)


# ------------------------------------------------ and it can actually be given

def test_an_optional_vaccine_not_yet_due_can_still_be_given(newborn):
    """The doctor's decision, which the tab used to have no control for. Early
    is a clinical call — the program records what was done, it does not refuse
    it."""
    from app.models import PatientVaccine

    _give(newborn)

    with newborn["app"].app_context():
        dose = PatientVaccine.query.filter_by(
            patient_id=newborn["baby"], event_type="given").first()
        assert dose is not None, "the vaccine could not be given from the visit"
        assert dose.dose_number == 1


def test_the_brand_on_the_row_is_the_brand_recorded(newborn):
    """A trade name is the whole reason the doctor was searching. Picking one
    and getting the clinic's default instead would be worse than no picker."""
    from app.extensions import db
    from app.models import (PatientVaccine, VaccineBrand, VaccineBrandDose,
                            VaccineInventory)

    with newborn["app"].app_context():
        other = VaccineBrand(vaccine_id=newborn["ids"]["pcv"],
                             name="Synflorix", price=800, doses_per_vial=1)
        db.session.add(other)
        db.session.flush()
        # A brand carries its own dose schedule here; without one there is no
        # "next dose" to give and the row would be unusable.
        for number, months in ((1, 2), (2, 4), (3, 6)):
            db.session.add(VaccineBrandDose(brand_id=other.id,
                                            dose_number=number,
                                            age_months=months))
        db.session.add(VaccineInventory(brand_id=other.id, lot_number="OTH",
                                        qty_received=5, qty_used=0,
                                        expiry_date=date(2030, 1, 1)))
        db.session.commit()
        other_id = other.id

    _give(newborn, brand_id=other_id)

    with newborn["app"].app_context():
        dose = PatientVaccine.query.filter_by(
            patient_id=newborn["baby"], event_type="given").first()
        assert dose.brand_id == other_id, \
            "the chosen brand was replaced by the default"


def test_a_dose_taken_elsewhere_is_recorded_without_touching_stock(newborn):
    """*"جرعة اتاخدت بره وبتوثّقها"* — the case the mandatory-only control was
    written for, which now covers every vaccine."""
    from app.extensions import db
    from app.models import PatientVaccine, VaccineBrand

    with newborn["app"].app_context():
        before = db.session.get(VaccineBrand, newborn["ids"]["brand"]).stock

    _give(newborn, given_outside="1")

    with newborn["app"].app_context():
        dose = PatientVaccine.query.filter_by(
            patient_id=newborn["baby"], event_type="given").first()
        assert dose.given_outside is True
        assert db.session.get(VaccineBrand, newborn["ids"]["brand"]).stock == before, \
            "a dose given elsewhere came out of this clinic's fridge"


def test_the_catalogue_does_not_cost_a_query_per_brand(newborn):
    """The whole catalogue is on this page now, and `brand.stock` sums the
    brand's batches. Left to lazy loading that is one query per brand on the
    screen a doctor keeps open all day.

    Twelve extra brands first: with the three the fixture starts with, lazy
    loading and eager loading are close enough that a ceiling cannot tell them
    apart, and a test that cannot tell them apart is not testing this."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.extensions import db
    from app.models import VaccineBrand, VaccineInventory

    with newborn["app"].app_context():
        for n in range(12):
            extra = VaccineBrand(vaccine_id=newborn["ids"]["pcv"],
                                 name=f"Brand{n}", price=100, doses_per_vial=1)
            db.session.add(extra)
            db.session.flush()
            db.session.add(VaccineInventory(brand_id=extra.id,
                                            lot_number=f"L{n}", qty_received=2,
                                            qty_used=0,
                                            expiry_date=date(2030, 1, 1)))
        db.session.commit()

    seen = []

    def record(conn, cursor, statement, params, context, many):
        if "vaccine_inventory" in statement:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        _tab(newborn)
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert len(seen) <= 6, (
        f"{len(seen)} batch queries to draw one visit tab with 15 brands on "
        "file — the brands are being loaded one at a time")


def test_a_file_with_no_birthday_does_not_take_the_tab_down(newborn):
    """Every dose of a course with no date of birth is "upcoming" with no due
    date. Sorting those to find the soonest compares None against a string,
    which is a 500 on the screen a doctor is standing in front of — so a dose
    with no date is not a candidate for "next"."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import visit_vaccine_panel

    with newborn["app"].app_context():
        # Not committed: the column is NOT NULL, and the point is the shape of
        # the value the schedule hands back, not a row on disk.
        with db.session.no_autoflush:
            patient = db.session.get(Patient, newborn["baby"])
            patient.date_of_birth = None
            panel = visit_vaccine_panel(patient)
        db.session.rollback()

    assert panel["next_optional"] is None
    assert panel["give_now"] == []
