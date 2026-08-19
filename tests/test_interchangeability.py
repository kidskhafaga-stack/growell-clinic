"""Switching product mid-course, and what each leaflet says about arriving.

Interchangeability is not symmetric, so the question has a direction. Read
**as destination**: the next dose is this brand and the earlier ones were not
— what does *this* brand's label say about children arriving at it? Every SmPC
is written that way, which is why one column is enough and why it is named for
the direction rather than the pair.

Four states, and the one that matters most is the one that does not exist:
**``none`` is not the value for "limited evidence"**. Turning a reservation
into a prohibition is as wrong as turning it into silence, and four states
exist so neither has to happen — the same reasoning that gave `available_now`
three rather than two.

    Vaxneuvance   full         switch in at any point
    Prevenar 13   full         switch in at any point
    Prevenar 20   conditional  the label does not establish it under 15 months
    Synflorix     limited      thin data; finishing on one product is preferred

The program never substitutes a brand by itself — the doctor records what was
given, and stock and billing follow that record. So "no automatic
substitution" is not a restriction to enforce anywhere; what a thin evidence
base earns is a note where somebody is deciding, and never a silent yes.
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


def _course(seeded, tag, age_years, doses):
    """A child whose PCV course is `doses` as [(brand_name, age_months)]."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brands = {b.name: b for b in
                  VaccineBrand.query.filter_by(vaccine_id=pcv.id).all()}
        dob = local_today() - timedelta(days=int(age_years * 365.25))
        kid = Patient(patient_number=f"IX{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, (name, months) in enumerate(doses, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brands[name].id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(months * 30.4))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        return row, kid.id


_PREV_TWO = [("Prevenar 13", 2), ("Prevenar 13", 4)]


# ------------------------------------------------------------ the four states

def test_the_catalogue_carries_the_destination_rule(seeded):
    from app.models import VaccineBrand

    with seeded["app"].app_context():
        got = {b.name: (b.interchange_to, b.interchange_flag_under_months)
               for b in VaccineBrand.query.filter(VaccineBrand.name.in_(
                   ["Vaxneuvance", "Prevenar 13", "Prevenar 20", "Synflorix"]))}

    assert got == {
        "Vaxneuvance": ("full", None),
        "Prevenar 13": ("full", None),
        "Prevenar 20": ("conditional", 15),
        "Synflorix": ("limited", None),
    }


def test_limited_evidence_is_never_recorded_as_a_prohibition(seeded):
    """The distinction the four states exist for."""
    from app.models import VaccineBrand

    with seeded["app"].app_context():
        assert VaccineBrand.query.filter_by(
            name="Synflorix").first().interchange_to != "none"


# --------------------------------------------------------- what it changes

def test_switching_to_a_full_product_says_nothing(seeded):
    """Vaxneuvance's leaflet allows switching in; there is nothing to warn."""
    row, _ = _course(seeded, "a", 0.85, _PREV_TWO + [("Vaxneuvance", 9)])

    assert row["mixed"] is None


def test_a_course_that_never_switched_says_nothing(seeded):
    """Otherwise the note is on every child and means nothing."""
    row, _ = _course(seeded, "b", 0.85, _PREV_TWO)

    assert row["mixed"] is None


def test_switching_to_a_conditional_product_under_the_age_is_flagged(seeded):
    """Prevenar 20's own reservation, at the age the label states it."""
    row, _ = _course(seeded, "c", 0.85, _PREV_TWO + [("Prevenar 20", 9)])

    assert row["mixed"] is not None
    assert row["mixed"]["level"] == "conditional"
    assert row["mixed"]["reason"] == "under_age"
    assert row["mixed"]["months"] == 15


def test_the_same_switch_after_the_age_is_not_flagged(seeded):
    """The other half. Without it "conditional" would just mean "always warn",
    and a reservation that fires when it does not apply is one people learn to
    dismiss.
    """
    row, _ = _course(seeded, "d", 2.0, _PREV_TWO + [("Prevenar 20", 20)])

    assert row["mixed"] is None


def test_switching_to_a_limited_product_is_always_flagged(seeded):
    """Thin data, at any age — the note is the whole point of the state."""
    row, _ = _course(seeded, "e", 0.85, _PREV_TWO + [("Synflorix", 9)])

    assert row["mixed"]["level"] == "limited"


def test_the_destination_decides_not_the_source(seeded):
    """The direction the column is named for.

    Prevenar 13 is `full` and Synflorix is `limited`. Asking the product being
    left would call this switch unremarkable; asking the one being arrived at
    is what the leaflets actually describe.
    """
    to_limited, _ = _course(seeded, "f", 0.85, _PREV_TWO + [("Synflorix", 9)])
    from_limited, _ = _course(
        seeded, "g", 0.85,
        [("Synflorix", 2), ("Synflorix", 4), ("Prevenar 13", 9)])

    assert to_limited["mixed"] is not None, "arriving at the thin one is quiet"
    assert from_limited["mixed"] is None, "leaving it was treated as arriving"


# ------------------------------------------------------------- on the screen

def test_the_file_shows_the_note_where_the_decision_is_made(seeded):
    from app.i18n import t

    _row, patient_id = _course(seeded, "h", 0.85, _PREV_TWO + [("Synflorix", 9)])

    page = seeded["sign_in"]("doc").get(f"/vaccinations/{patient_id}",
                                        follow_redirects=True).data.decode()

    with seeded["app"].test_request_context("/"):
        assert t("vmix.limited") in page


def test_a_plain_course_carries_no_note_on_the_screen(seeded):
    _row, patient_id = _course(seeded, "i", 0.85, _PREV_TWO)

    page = seeded["sign_in"]("doc").get(f"/vaccinations/{patient_id}",
                                        follow_redirects=True).data.decode()

    assert "bi-shuffle" not in page


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vmix"]
        for key in ("title", "limited", "conditional", "under_age", "none"):
            assert key in block, f"{lang} is missing vmix.{key}"


def test_a_reseed_keeps_a_clinic_correction(seeded):
    """A clinic that decides differently keeps its decision."""
    from app.extensions import db
    from app.models import VaccineBrand

    from app.utils.vaccines import seed_vaccines

    with seeded["app"].app_context():
        brand = VaccineBrand.query.filter_by(name="Synflorix").first()
        brand.interchange_to = "full"
        db.session.commit()

        seed_vaccines()
        db.session.commit()

        assert VaccineBrand.query.filter_by(
            name="Synflorix").first().interchange_to == "full"


def test_a_whole_course_on_a_limited_product_is_not_a_mixed_series(seeded):
    """Nothing switched, so there is nothing to say — even though the product
    itself carries the thinnest evidence about being switched *to*.

    The two are different questions and were briefly answered by the same
    check: a child on Synflorix from the first dose was told their series was
    mixed. Caught by mutation, not by reading.
    """
    row, patient_id = _course(seeded, "j", 0.85,
                              [("Synflorix", 2), ("Synflorix", 4)])

    assert row["mixed"] is None, \
        "a course that never changed product was flagged as mixed"

    page = seeded["sign_in"]("doc").get(f"/vaccinations/{patient_id}",
                                        follow_redirects=True).data.decode()
    assert "bi-shuffle" not in page
