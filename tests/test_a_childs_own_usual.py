"""This child's own usual saturation — beside the rule, never instead of it.

Phase 3 of EMERGENCY_NEWBORN_PLAN.md, and the last piece of it.

A child with a cardiac shunt or chronic lung disease can live at 88% and be
entirely themselves at it. A reading of 88 means something different for them
than for the child in the next chair, and a program that cannot say so makes
the doctor hold that fact in their head.

**The dangerous version of this feature is the obvious one.** "88 is normal
for this child, so do not raise the flag" is how a deterioration goes
unnoticed in the one child least able to afford it. So the baseline never
softens a rule. The threshold decides the level, the same way for everybody,
and the baseline adds the other half of the sentence: *and this is where they
usually sit.*

Most of what is below exists to keep it that way.
"""
from datetime import timedelta

import pytest

from app.utils import red_flags
from app.utils.clock import local_today


class _V:
    def __init__(self, spo2=None, temp=None):
        self.spo2 = spo2
        self.temperature_c = temp


@pytest.fixture
def child(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        row = Patient(patient_number="B1", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=900),
                      is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        yield row


# ------------------------------------- it never softens what the rule said --
def test_a_low_reading_is_still_urgent_for_a_child_who_lives_low(
        clinic, child):
    """The whole point, stated as bluntly as it can be.

    A child whose usual saturation is 88 is *still* below the urgent
    threshold at 88 — and that is not a false alarm to be tuned away. It is
    the reading a rule exists to catch, in the patient it matters most
    in."""
    with clinic["app"].app_context():
        child.baseline_spo2 = 88
        clinic["db"].session.commit()
        verdict = red_flags.assess(child, _V(spo2=88), "")
    assert verdict["level"] == "urgent"
    assert "spo2_low" in verdict["reasons"]


def test_the_verdict_is_identical_with_and_without_a_baseline(clinic, child):
    """Recording a baseline must not change any level, anywhere. If it can,
    it is a rule and not a note."""
    with clinic["app"].app_context():
        for reading in (99, 96, 94, 91, 88, 80):
            child.baseline_spo2 = None
            clinic["db"].session.commit()
            without = red_flags.assess(child, _V(spo2=reading), "")["level"]

            child.baseline_spo2 = 88
            clinic["db"].session.commit()
            with_it = red_flags.assess(child, _V(spo2=reading), "")["level"]

            assert without == with_it, (
                f"the baseline changed the verdict at {reading}%")


# ------------------------------------------- and it says what it does say ---
def test_it_notices_a_fall_below_the_child_s_own_usual(clinic, child):
    with clinic["app"].app_context():
        child.baseline_spo2 = 96
        clinic["db"].session.commit()
        verdict = red_flags.assess(child, _V(spo2=91), "")
    assert verdict["below_own_baseline"] is True
    assert "below_own_baseline" in verdict["reasons"]


def test_a_point_or_two_of_wobble_is_not_a_finding(clinic, child):
    """A pulse oximeter moves on its own, and a note that fires on every
    reading is a note nobody reads by the second day."""
    with clinic["app"].app_context():
        child.baseline_spo2 = 96
        clinic["db"].session.commit()
        assert red_flags.assess(child, _V(spo2=95), "")[
            "below_own_baseline"] is False
        assert red_flags.assess(child, _V(spo2=94), "")[
            "below_own_baseline"] is False


def test_a_child_at_their_usual_low_number_is_not_flagged_as_fallen(clinic,
                                                                    child):
    """88 in a child who lives at 88 is urgent by the threshold and *not* a
    fall from their own baseline. Both halves of that sentence are true and
    the screen shows both."""
    with clinic["app"].app_context():
        child.baseline_spo2 = 88
        clinic["db"].session.commit()
        verdict = red_flags.assess(child, _V(spo2=88), "")
    assert verdict["level"] == "urgent"
    assert verdict["below_own_baseline"] is False


def test_no_baseline_recorded_says_nothing_either_way(clinic, child):
    with clinic["app"].app_context():
        verdict = red_flags.assess(child, _V(spo2=91), "")
    assert verdict["baseline_spo2"] is None
    assert verdict["below_own_baseline"] is False
    assert "below_own_baseline" not in verdict["reasons"]


def test_it_does_not_raise_when_there_is_no_reading(clinic, child):
    with clinic["app"].app_context():
        child.baseline_spo2 = 96
        clinic["db"].session.commit()
        verdict = red_flags.assess(child, _V(), "")
    assert verdict["below_own_baseline"] is False


# ------------------------------------------------------------- the form ----
def test_the_form_takes_it(clinic):
    page = clinic["sign_in"]("boss").get(
        "/patients/new").get_data(as_text=True)
    assert 'name="baseline_spo2"' in page
    assert "patients.baseline_spo2" not in page


def test_saving_it_keeps_it(clinic):
    from app.models import Patient

    clinic["sign_in"]("boss").post("/patients/new", data={
        "full_name": "طفل قلب", "gender": "male",
        "date_of_birth": "2024-01-01", "baseline_spo2": "88",
        "is_active": "1"}, follow_redirects=True)
    with clinic["app"].app_context():
        row = Patient.query.filter_by(full_name="طفل قلب").first()
        assert row is not None and row.baseline_spo2 == 88


def test_leaving_it_blank_stores_nothing(clinic):
    from app.models import Patient

    clinic["sign_in"]("boss").post("/patients/new", data={
        "full_name": "طفل عادي", "gender": "female",
        "date_of_birth": "2024-01-01", "baseline_spo2": "",
        "is_active": "1"}, follow_redirects=True)
    with clinic["app"].app_context():
        row = Patient.query.filter_by(full_name="طفل عادي").first()
        assert row is not None and row.baseline_spo2 is None


@pytest.mark.parametrize("bad", ["9", "140", "abc"])
def test_an_impossible_saturation_is_refused(clinic, bad):
    """A baseline of 9 would put "below their usual" on every reading this
    child ever has."""
    from app.models import Patient

    clinic["sign_in"]("boss").post("/patients/new", data={
        "full_name": f"خطأ {bad}", "gender": "male",
        "date_of_birth": "2024-01-01", "baseline_spo2": bad,
        "is_active": "1"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert Patient.query.filter_by(full_name=f"خطأ {bad}").first() is None


def test_the_reason_has_a_word_for_it(clinic):
    """The station renders `t('redflags.' ~ reason)`, and a reason with no
    entry prints its own key at a nurse."""
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    for lang in ("ar", "en"):
        assert _lookup(tables, lang, "redflags.below_own_baseline")


def test_the_column_is_in_the_upgrade_list():
    from app.utils.schema import ADDITIONS

    assert any(t == "patients" and c == "baseline_spo2"
               for t, c, _type in ADDITIONS)
