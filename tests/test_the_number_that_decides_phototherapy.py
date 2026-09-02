"""Bilirubin against the thresholds, by the hour — and never from the model.

Phase 4 of EMERGENCY_NEWBORN_PLAN.md. The decision that shaped it was taken
before any of it was written: **this is a calculator, never the assistant.**

The number decides phototherapy or an exchange transfusion. The program
already refuses to let a model give a drug dose, for a reason written down in
`ai_discuss.py` — *a second, less careful road to the same number is how a
program ends up with two answers to "how much" and no way to know which one a
nurse read.* A bilirubin threshold is the same category.

Three properties matter more than the arithmetic:

* it **refuses rather than guesses** when an input is missing, and says which
* it will not answer at all until a clinician has accepted the table
* where it must be wrong, it is wrong **towards treating**
"""
from datetime import date, time, timedelta

import pytest

from app.utils import jaundice


@pytest.fixture
def newborn_clinic(clinic):
    """A clinic that said it sees newborns. Nothing here answers without it."""
    import json

    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("facility_capabilities", json.dumps(["newborn_care"]))
        clinic["db"].session.commit()
    return clinic


@pytest.fixture
def ready(newborn_clinic):
    """...and whose clinician has then signed off the table."""
    from app.models import Setting

    with newborn_clinic["app"].app_context():
        Setting.set(jaundice.CONFIRMED_KEY, "1")
        newborn_clinic["db"].session.commit()
    return newborn_clinic


@pytest.fixture
def baby(clinic):
    """A 38-week newborn, 48 hours old."""
    from app.models import Patient
    from app.utils.clock import local_now

    with clinic["app"].app_context():
        born = local_now().replace(tzinfo=None) - timedelta(hours=48)
        row = Patient(patient_number="J1", full_name="مولود", gender="male",
                      date_of_birth=born.date(),
                      birth_time=time(born.hour, born.minute),
                      gestation_weeks=38, gestation_days=0, is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        yield row


# ------------------------------------------ it will not answer unasked ------
def test_a_clinic_that_does_not_see_newborns_is_never_asked(clinic, baby):
    """The most important gate, and it was missing.

    A paediatric clinic whose youngest patient is three is not withholding an
    answer here — it has no question. The bilirubin table was on its settings
    screen and the calculator would have answered for it, which is the same
    fault as putting a tooth chart on every child's file: the program
    implying a clinic ought to be doing something it does not do."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set(jaundice.CONFIRMED_KEY, "1")     # even accepted
        clinic["db"].session.commit()
        answer = jaundice.assess(baby, 18.0)
    assert answer == {"ok": False, "reason": "not_offered"}


def test_the_table_is_not_on_a_settings_screen_that_has_no_use_for_it(clinic):
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "jaundice_table_confirmed" not in page


def test_it_appears_once_the_clinic_says_it_sees_newborns(newborn_clinic):
    page = newborn_clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)
    assert "jaundice_table_confirmed" in page


def test_seeing_newborns_is_not_enough_on_its_own(newborn_clinic, baby):
    """Two gates, two questions. "We see newborns" is not "a clinician has
    read this table and accepts these numbers"."""
    with newborn_clinic["app"].app_context():
        answer = jaundice.assess(baby, 18.0)
    assert answer == {"ok": False, "reason": "table_not_confirmed"}


def test_it_says_nothing_until_the_table_is_accepted(clinic, baby):
    """Not a formality. The values were transcribed by hand, and a
    transcribed clinical table presented as authoritative is the failure this
    program spends its time guarding against."""
    import json

    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("facility_capabilities", json.dumps(["newborn_care"]))
        clinic["db"].session.commit()
        answer = jaundice.assess(baby, 18.0)
    assert answer["ok"] is False
    assert answer["reason"] == "table_not_confirmed"
    assert "phototherapy" not in answer


def test_accepting_the_table_is_what_turns_it_on(ready, baby):
    with ready["app"].app_context():
        assert jaundice.assess(baby, 18.0)["ok"] is True


# --------------------------------------------- it refuses, and says which ---
def test_no_birth_time_means_no_answer(ready, baby):
    """The thresholds move by the hour in the first days. Without the hour the
    program is up to a day out, and a day crosses these curves."""
    with ready["app"].app_context():
        baby.birth_time = None
        ready["db"].session.commit()
        answer = jaundice.assess(baby, 18.0)
    assert answer == {"ok": False, "reason": "no_birth_time"}


def test_no_gestation_means_no_answer(ready, baby):
    with ready["app"].app_context():
        baby.gestation_weeks = None
        ready["db"].session.commit()
        assert jaundice.assess(baby, 18.0)["reason"] == "no_gestation"


@pytest.mark.parametrize("value", [None, "", "high", "abc"])
def test_no_bilirubin_means_no_answer(ready, baby, value):
    with ready["app"].app_context():
        assert jaundice.assess(baby, value)["reason"] == "no_bilirubin"


def test_a_very_preterm_baby_is_sent_away_rather_than_extrapolated(ready, baby):
    """Below 35 weeks the curves are not a straight line and the thresholds
    belong to a unit, not a clinic. Extending the table downwards would be the
    program inventing numbers for the babies least able to survive them."""
    with ready["app"].app_context():
        baby.gestation_weeks = 32
        ready["db"].session.commit()
        assert jaundice.assess(baby, 12.0)["reason"] == "too_preterm"

    # And at the layer underneath, which mutation testing showed this test was
    # not reaching: `assess` refuses early, so a `_row` that clamps upward
    # instead of refusing left every test green while `limits()` handed a
    # 32-week baby the 35-week numbers. Any caller that reaches past `assess`
    # — a screen, a report, the next thing built on this — would have got them.
    assert jaundice._row(32) is None
    assert jaundice.limits(32, 48) == (None, None)
    assert jaundice.limits(None, 48) == (None, None)


# ------------------------------------------------- where it must be wrong ---
def test_a_part_week_is_read_on_the_lower_curve(ready):
    """A 37+6 baby is read at 37 weeks, not 38.

    The thresholds rise with maturity, so rounding up would hand a less mature
    baby a more permissive number. Where a rule has to be wrong it is wrong
    towards treating."""
    assert jaundice._row(37.86) == "37"
    at_37, _ = jaundice.limits(37, 48)
    at_38, _ = jaundice.limits(38, 48)
    assert at_37 < at_38, "the curves do not rise with maturity"


def test_risk_factors_lower_the_thresholds(ready):
    for weeks in (35, 36, 37, 38):
        plain, _ = jaundice.limits(weeks, 48)
        with_risk, _ = jaundice.limits(weeks, 48, True)
        assert with_risk < plain, weeks


def test_exchange_is_always_above_phototherapy(ready):
    for weeks in (35, 36, 37, 38):
        for hours in (12, 24, 36, 48, 72, 96, 120, 200):
            for risk in (False, True):
                photo, exchange = jaundice.limits(weeks, hours, risk)
                assert exchange > photo, (weeks, hours, risk)


def test_the_thresholds_rise_with_the_hours(ready):
    """A baby is allowed more bilirubin at 72 hours than at 24. A table that
    fell anywhere would be transcribed wrong."""
    for weeks in (35, 36, 37, 38):
        values = [jaundice.limits(weeks, h)[0] for h in (12, 24, 48, 72, 96, 120)]
        assert values == sorted(values), weeks


def test_it_interpolates_between_the_hours_it_has(ready):
    """Blood is not drawn on the hours a table happens to list."""
    at_24, _ = jaundice.limits(38, 24)
    at_36, _ = jaundice.limits(38, 36)
    at_48, _ = jaundice.limits(38, 48)
    assert at_24 < at_36 < at_48


def test_it_stays_flat_past_the_end_of_the_curve(ready):
    """A ten-day-old is not extrapolated upwards forever."""
    assert jaundice.limits(38, 120)[0] == jaundice.limits(38, 400)[0]


# ------------------------------------------------------- what it points at --
@pytest.mark.parametrize("value,expected", [
    (5.0, "below"),
    (13.0, "close"),          # within 3 of the 15.0 phototherapy line
    (16.0, "phototherapy"),
    (25.0, "exchange"),
])
def test_it_says_which_side_of_the_lines_the_reading_is(ready, baby, value,
                                                        expected):
    with ready["app"].app_context():
        assert jaundice.assess(baby, value)["points_at"] == expected


def test_the_answer_carries_the_thresholds_it_used(ready, baby):
    """A verdict nobody can check is a verdict nobody should act on."""
    with ready["app"].app_context():
        answer = jaundice.assess(baby, 16.0)
    assert answer["phototherapy"] == 15.0
    assert answer["exchange"] == 21.5
    assert answer["hours"] == pytest.approx(48, abs=0.5)
    assert answer["weeks"] == 38
    assert answer["source"]
    assert answer["unit"] == "mg/dL"


def test_a_reading_over_the_line_is_repeated_sooner(ready, baby):
    with ready["app"].app_context():
        over = jaundice.assess(baby, 16.0)["repeat_in"]
        under = jaundice.assess(baby, 5.0)["repeat_in"]
    assert over < under


def test_an_earlier_reading_can_be_scored_at_its_own_hour(ready, baby):
    """The value belongs to the moment blood was drawn, not to the moment
    somebody typed it in."""
    with ready["app"].app_context():
        now = jaundice.assess(baby, 14.0)
        then = jaundice.assess(baby, 14.0, hours=24)
    assert then["phototherapy"] < now["phototherapy"]
    assert then["points_at"] == "phototherapy"
    assert now["points_at"] == "close"


# -------------------------------------------- and the assistant stays out ---
def test_nothing_here_reaches_the_assistant():
    """The rule this module was built around. If a threshold ever comes back
    from a model, there are two answers to the question and no way to know
    which one a nurse read."""
    import inspect

    source = inspect.getsource(jaundice)
    for forbidden in ("ai.chat", "ai_utils", "from app.utils.ai",
                      "openai", "anthropic"):
        assert forbidden not in source, forbidden


def test_the_table_names_where_it_came_from():
    assert len(jaundice.table()["source"]) > 10
    assert jaundice.table()["unit"] == "mg/dL"
