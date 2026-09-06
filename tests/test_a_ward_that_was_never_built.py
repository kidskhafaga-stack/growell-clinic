"""A sentence on every child's file, about a ward that does not exist.

Reported from a screen: **"مفيش سرير فاضي دلوقتي."** sitting in the column of
buttons on a patient's profile, in an outpatient clinic that has never made a
single bed.

The cause is one empty list standing for two different facts. ``free_beds()``
returns nothing both when every bed is taken and when there are no beds at
all, and the profile printed the same line for both. They are not the same
news: *all the beds are taken* is worth telling somebody who is looking at a
child and thinking about admitting them; *you switched the module on and never
built a ward* is not news at all, and printing it for ever on every file is
how a screen teaches people to stop reading it.

The other branches of that block all produce an **action** — go to the stay,
or admit to a named bed. This one produced a sentence, which is why it read as
a stray label rather than as information.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward_on(clinic):
    """The beds module switched on, and nothing built behind it."""
    from app.models import Setting

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        db.session.commit()
    return clinic


def _sentence():
    """The wording itself, read from the locale rather than through ``t`` —
    which needs a request behind it and this assertion does not."""
    import json
    import os

    path = os.path.join(os.path.dirname(__file__), "..", "app", "i18n",
                        "locales", "ar.json")
    with open(os.path.abspath(path), encoding="utf-8") as fh:
        return json.load(fh)["beds"]["no_free_bed"]


def _profile(fx):
    return fx["sign_in"]("boss").get(
        f"/patients/{fx['ids']['child']}").get_data(as_text=True)


def _build_ward(fx):
    """A unit, a space and exactly one bed."""
    from app.models import Bed, Space, Unit

    db = fx["db"]
    with fx["app"].app_context():
        unit = Unit(name="الحضانة", kind="ward", is_active=True)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", is_active=True)
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير ١", is_active=True)
        db.session.add(bed)
        db.session.commit()
        fx["bed"] = bed.id
    return fx


def test_a_clinic_with_no_ward_is_not_told_its_ward_is_full(ward_on):
    """The report, as an assertion."""
    assert _sentence() not in _profile(ward_on)


def test_a_free_bed_offers_the_admission_instead_of_a_sentence(ward_on):
    """The branch that produces an action rather than a line of prose."""
    fx = _build_ward(ward_on)
    page = _profile(fx)
    assert _sentence() not in page
    assert "bed_id" in page, "a free bed offers no way to admit to it"


def test_a_ward_whose_beds_are_all_taken_does_say_so(ward_on):
    """The other half, and the reason this is a condition and not a deletion:
    somebody looking at a child and wondering where the admit button went is
    owed the answer."""
    from app.models import Bed, Patient
    from app.utils import beds as ward

    fx = _build_ward(ward_on)
    db = fx["db"]
    with fx["app"].app_context():
        other = Patient(patient_number="P-Z", full_name="طفل تاني",
                        gender="male", date_of_birth=date(2024, 1, 1),
                        is_active=True)
        db.session.add(other)
        db.session.flush()
        ward.admit(other, db.session.get(Bed, fx["bed"]))
        db.session.commit()
        assert ward.free_beds() == []

    assert _sentence() in _profile(fx)


def test_the_module_off_says_nothing_either_way(clinic):
    assert _sentence() not in _profile(clinic)


def test_the_two_empty_lists_are_told_apart(ward_on):
    """The fault itself: one empty list stood for two facts. The context now
    carries whether a ward exists, separately from whether any of it is free.
    """
    from app.blueprints.patients.routes import _ward_context

    with ward_on["app"].app_context():
        bare = _ward_context(ward_on["ids"]["child"])
        assert bare["free_beds"] == [] and bare["has_beds"] is False

    _build_ward(ward_on)
    with ward_on["app"].app_context():
        built = _ward_context(ward_on["ids"]["child"])
        assert built["free_beds"] and built["has_beds"] is True
