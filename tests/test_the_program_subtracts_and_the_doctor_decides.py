"""Four-limb blood pressure and pre/post-ductal saturation.

Asked for while checking the specialty was covered: *"الضغط في الأربع أطراف
والتشبّع قبل/بعد القناة، والبرنامج يحسب الفرق"*.

**The subtraction is the easy half.** These tests are almost entirely about the
other half — which published threshold each answer falls on, and, for the
saturations, refusing to apply a newborn screening algorithm to a child it was
not written for.

Two rules, from outside this program:

* **Coarctation.** The legs normally read the same as the arms or higher. An
  upper-limb systolic more than 20 mmHg above the lower limb is the usual
  threshold for looking further.
* **CCHD screening** (AAP/AHA 2011). Pass: ≥95% in either limb *and* ≤3%
  between them. Fail: anything under 90%. Otherwise repeat in an hour.

Nothing here diagnoses. It subtracts, names the threshold, and stops.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils import cardio  # noqa: E402


# ------------------------------------------------ the arm-to-leg gradient

def test_the_legs_reading_lower_is_the_finding():
    """The whole point. In coarctation the legs read lower than the arms, so
    the gradient is arm minus leg and a positive number is the direction that
    matters."""
    seen = cardio.four_limb(right_arm=120, right_leg=85)

    assert seen["gradient"] == 35
    assert "gradient" in seen["flags"]


def test_legs_higher_than_arms_is_normal_and_not_flagged():
    """A healthy child's legs read the same or a little higher. Flagging that
    would make the alarm meaningless within a week."""
    seen = cardio.four_limb(right_arm=95, right_leg=105)

    assert seen["gradient"] == -10
    assert seen["flags"] == []


def test_the_threshold_is_twenty_and_it_is_exclusive():
    """Twenty exactly is not over twenty. A boundary that flags at the
    threshold turns every textbook-normal child into a referral."""
    assert "gradient" not in cardio.four_limb(right_arm=120, right_leg=100)["flags"]
    assert "gradient" in cardio.four_limb(right_arm=121, right_leg=100)["flags"]


def test_the_right_arm_is_the_reference():
    """The right subclavian leaves the aorta proximal to where most
    coarctations sit, so the right arm is the reading to compare against."""
    seen = cardio.four_limb(right_arm=130, left_arm=100, right_leg=100)

    assert seen["arm_side"] == "right"
    assert seen["gradient"] == 30


def test_the_higher_leg_is_used_so_the_gradient_is_the_conservative_one():
    """A screen that reports the largest difference it can find among four
    readings is a screen that cries wolf. Using the higher leg makes the
    gradient the smaller number."""
    seen = cardio.four_limb(right_arm=120, right_leg=80, left_leg=105)

    assert seen["leg_side"] == "left"
    assert seen["gradient"] == 15
    assert seen["flags"] == []


def test_a_difference_between_the_arms_is_its_own_finding():
    """A coarctation beyond the left subclavian shows as the right arm higher
    than the left. Averaging the arms together would hide exactly that."""
    seen = cardio.four_limb(right_arm=130, left_arm=100, right_leg=125)

    assert seen["arm_difference"] == 30
    assert "arms" in seen["flags"]


def test_one_limb_is_a_blood_pressure_and_not_a_gradient():
    """Inventing a gradient from a single reading is how a screen makes a
    claim nobody measured."""
    assert cardio.four_limb(right_arm=120) is None
    assert cardio.four_limb(right_leg=90) is None
    assert cardio.four_limb() is None


def test_an_arm_reading_is_still_used_when_only_the_left_was_taken():
    """One cuff, one arm, and the screen says which arm it used rather than
    refusing to answer."""
    seen = cardio.four_limb(left_arm=120, right_leg=90)

    assert seen["arm_side"] == "left" and seen["gradient"] == 30


def test_nonsense_in_a_box_is_a_blank_and_never_a_zero():
    """A zero is a real measurement and a very alarming one."""
    assert cardio.four_limb(right_arm="abc", right_leg=90) is None
    assert cardio.four_limb(right_arm=120, right_leg="") is None


# ------------------------------------- the newborn saturation screen

def _newborn():
    return 1


def test_a_clear_pair_passes():
    seen = cardio.ductal(pre=99, post=98, age_days=_newborn())

    assert seen["result"] == "pass"
    assert seen["difference"] == 1


def test_anything_under_ninety_fails_wherever_it_was_measured():
    assert cardio.ductal(pre=88, post=99, age_days=1)["result"] == "fail"
    assert cardio.ductal(pre=99, post=88, age_days=1)["result"] == "fail"


def test_ninety_exactly_is_not_a_fail():
    """"Under 90" is under 90. The protocol's boundary is not a matter of
    taste, and moving it by one either way changes who gets an echo."""
    assert cardio.ductal(pre=90, post=90, age_days=1)["result"] != "fail"
    assert cardio.ductal(pre=89.9, post=99, age_days=1)["result"] == "fail"


def test_a_spread_over_three_is_a_repeat_however_high_the_numbers():
    """Two healthy-looking saturations four points apart is the finding the
    spread rule exists for."""
    seen = cardio.ductal(pre=99, post=95, age_days=1)

    assert seen["result"] == "repeat"
    assert seen["reason"] == "spread"


def test_three_exactly_is_within_the_spread():
    assert cardio.ductal(pre=98, post=95, age_days=1)["result"] == "pass"


def test_both_in_the_nineties_but_under_ninety_five_is_a_repeat():
    seen = cardio.ductal(pre=93, post=93, age_days=1)

    assert seen["result"] == "repeat"
    assert seen["reason"] == "borderline"


def test_the_difference_keeps_its_sign():
    """Post-ductal *above* pre-ductal is reversed differential cyanosis. Rare,
    and not the same finding as the ordinary way round — an absolute value
    would erase the distinction."""
    seen = cardio.ductal(pre=92, post=98, age_days=1)

    assert seen["difference"] == -6
    assert seen["result"] == "repeat"


def test_one_limb_gives_no_difference():
    seen = cardio.ductal(pre=98, age_days=1)

    assert seen["difference"] is None


def test_but_one_limb_under_ninety_still_fails():
    """Holding its tongue until the other limb is measured would be the screen
    staying quiet at the worst possible moment."""
    assert cardio.ductal(pre=85, age_days=1)["result"] == "fail"


# ------------------------------- and it is a newborn screen, deliberately

def test_the_screen_is_not_applied_to_an_older_child():
    """Printing "fail" against a five-year-old is putting a word on a number
    the word does not belong to: the algorithm was written and validated for
    newborns before discharge."""
    seen = cardio.ductal(pre=88, post=99, age_days=5 * 365)

    assert seen["result"] is None
    assert seen["newborn"] is False


def test_but_the_difference_is_still_computed_at_any_age():
    """A post-ductal saturation well below the pre-ductal means something at
    any age. Withholding the subtraction because the label does not apply
    would be throwing away the measurement."""
    seen = cardio.ductal(pre=99, post=89, age_days=5 * 365)

    assert seen["difference"] == 10


def test_a_file_with_no_birth_date_gets_no_screening_verdict():
    """Without an age the program cannot know which population the child is
    in, and guessing "newborn" would be the unsafe guess."""
    seen = cardio.ductal(pre=88, post=99, age_days=None)

    assert seen["result"] is None and seen["newborn"] is False


def test_the_newborn_window_reaches_a_baby_seen_late():
    """A fortnight, on purpose: a baby brought in at ten days for the first
    time is still the baby the screen was written for."""
    assert cardio.ductal(pre=88, post=99, age_days=10)["result"] == "fail"
    assert cardio.ductal(pre=88, post=99, age_days=40)["result"] is None


# ---------------------------------------------------- reading a panel

def test_it_reads_the_panel_by_the_codes_the_panel_uses(clinic):
    """The field codes and the reader must be the same names. A rename on one
    side leaves the screen quietly showing nothing, with no error anywhere."""
    from app.utils import panels

    codes = {f["code"] for f in panels.all_panels()["cardiology"]["fields"]}

    for needed in ("bp_right_arm", "bp_left_arm", "bp_right_leg", "bp_left_leg",
                   "spo2_pre_ductal", "spo2_post_ductal"):
        assert needed in codes, f"the panel has no {needed} to read"


def test_read_gives_both_halves_or_the_half_it_has(clinic):
    class _Baby:
        date_of_birth = date.today() - timedelta(days=2)

    seen = cardio.read({"bp_right_arm": 120, "bp_right_leg": 90,
                        "spo2_pre_ductal": 99, "spo2_post_ductal": 90},
                       _Baby(), date.today())

    assert seen["four_limb"]["gradient"] == 30
    assert seen["ductal"]["result"] == "repeat"


def test_a_panel_with_neither_measured_answers_with_nothing(clinic):
    seen = cardio.read({}, None, None)

    assert seen["four_limb"] is None
    assert seen["ductal"]["difference"] is None
    assert seen["ductal"]["result"] is None


def test_the_thresholds_are_named_so_they_can_be_argued_with(clinic):
    """A number a doctor is shown next to the word "coarctation" has to be
    traceable to a published rule, not to whatever seemed sensible on the
    afternoon it was written."""
    seen = cardio.four_limb(right_arm=120, right_leg=90)

    assert seen["threshold"] == 20
    assert cardio.ductal(pre=99, post=98, age_days=1)["thresholds"] == {
        "fail_below": 90, "pass_at": 95, "spread": 3}
