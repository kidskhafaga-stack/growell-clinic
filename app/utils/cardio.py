"""Two paediatric cardiology numbers the program can work out, and will not
pretend to interpret beyond what the published rule says.

Asked for after checking the specialty was covered: *"الضغط في الأربع أطراف
والتشبّع قبل/بعد القناة، والبرنامج يحسب الفرق"*.

Both are subtractions. Neither is worth a module for the arithmetic — they are
here because **the subtraction is the easy half and the threshold is the half
that has to be right**, and because a number a doctor is shown next to the word
"coarctation" has to be traceable to a published rule rather than to whatever
seemed sensible on the afternoon it was written.

**The arm–leg gradient.** In a healthy child the legs read the same as the arms
or a little higher. In coarctation of the aorta the legs read *lower*, and an
upper-limb systolic exceeding the lower limb by more than 20 mmHg is the
commonly used threshold for "this needs looking at". The right arm is the
reference because the right subclavian artery leaves the aorta proximal to
where most coarctations sit; a coarctation beyond the left subclavian shows as
right arm higher than left, so that difference is reported too rather than
averaged away.

**Pre- and post-ductal saturation.** This one is not a rule of thumb: it is the
newborn CCHD screening algorithm (AAP/AHA 2011, and the protocol every unit
that screens uses), and it has three outcomes rather than two —

* **pass** — ≥95% in either limb *and* the difference ≤3%
* **fail** — anything under 90% in either limb
* **repeat** — 90–94% in both, or a difference over 3%; measured again an hour
  later, and three of these is a fail

**And it is a newborn screen.** Running the algorithm on a five-year-old and
printing "fail" would be putting a word on a number that the word does not
belong to. Past the newborn window the difference is still computed and still
shown — a post-ductal saturation well below the pre-ductal means something at
any age — but it is reported as a difference, not as a screening result.

Nothing here decides anything. It subtracts, it says which published threshold
the answer falls on, and it names the threshold so a doctor can disagree with
it. The decision, and the echo, are theirs.
"""

# The upper-to-lower limb systolic difference above which coarctation is
# usually looked for. Named rather than inlined so the number is arguable.
COARCTATION_MMHG = 20

# A difference between the arms large enough to be worth saying out loud on its
# own: a coarctation distal to the left subclavian presents this way.
ARM_DIFFERENCE_MMHG = 20

# The newborn screen's three numbers.
CCHD_FAIL_BELOW = 90
CCHD_PASS_AT_OR_ABOVE = 95
CCHD_SPREAD = 3

# How long "newborn" lasts for the purpose of the screen. The protocol is run
# at 24–48 hours before discharge; a fortnight is generous and deliberately so,
# because a baby seen at ten days for the first time is still the baby the
# screen was written for.
NEWBORN_DAYS = 14


def _number(value):
    """A reading as a float, or None. Anything unparseable is a blank, not a
    zero: a zero would be a real measurement and a very alarming one."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def four_limb(right_arm=None, left_arm=None, right_leg=None, left_leg=None):
    """The arm–leg gradient, from whichever limbs were actually measured.

    Returns ``None`` when there is nothing to compare — one arm and no leg is
    a blood pressure, not a gradient, and inventing one from a single reading
    is how a screen ends up making a claim nobody measured.

    ``{gradient, arm, leg, arm_side, leg_side, arm_difference, flags}`` — where
    ``gradient`` is *arm minus leg*, so a positive number is the direction that
    matters. The right arm is preferred as the reference and the *higher* leg
    is used, both of which make the gradient the smaller, more conservative
    number: a screen that reports the largest difference it can find out of
    four readings is a screen that cries wolf.
    """
    arms = {"right": _number(right_arm), "left": _number(left_arm)}
    legs = {"right": _number(right_leg), "left": _number(left_leg)}

    # The right arm is the reference when it is there; otherwise whatever arm
    # was measured, and the screen says which.
    arm_side = "right" if arms["right"] is not None else (
        "left" if arms["left"] is not None else None)
    have_legs = {k: v for k, v in legs.items() if v is not None}
    if arm_side is None or not have_legs:
        return None

    leg_side = max(have_legs, key=lambda side: have_legs[side])
    arm, leg = arms[arm_side], have_legs[leg_side]
    gradient = round(arm - leg, 1)

    arm_difference = None
    if arms["right"] is not None and arms["left"] is not None:
        arm_difference = round(arms["right"] - arms["left"], 1)

    flags = []
    if gradient > COARCTATION_MMHG:
        flags.append("gradient")
    if arm_difference is not None and abs(arm_difference) >= ARM_DIFFERENCE_MMHG:
        flags.append("arms")

    return {
        "gradient": gradient,
        "arm": arm, "leg": leg,
        "arm_side": arm_side, "leg_side": leg_side,
        "arm_difference": arm_difference,
        "flags": flags,
        "threshold": COARCTATION_MMHG,
    }


def ductal(pre=None, post=None, age_days=None):
    """Pre- and post-ductal saturation: the difference, and — for a newborn —
    what the screening algorithm makes of it.

    ``{pre, post, difference, result, reason, newborn, thresholds}``.

    ``result`` is ``pass`` / ``repeat`` / ``fail`` **only when this is a
    newborn**, because that is the population the algorithm was written and
    validated for. Older than that and ``result`` is ``None``: the difference
    is still computed and still worth a doctor's eye, but calling it a failed
    screen would be attaching a word to a number the word does not fit.

    One reading gives a difference of ``None`` and no result. Half of a paired
    measurement is not a paired measurement.
    """
    pre_v, post_v = _number(pre), _number(post)
    newborn = age_days is not None and age_days <= NEWBORN_DAYS

    out = {
        "pre": pre_v, "post": post_v,
        "difference": None, "result": None, "reason": None,
        "newborn": newborn,
        "thresholds": {"fail_below": CCHD_FAIL_BELOW,
                       "pass_at": CCHD_PASS_AT_OR_ABOVE,
                       "spread": CCHD_SPREAD},
    }
    if pre_v is None or post_v is None:
        # A single limb can still fail the screen outright — under 90% is a
        # fail wherever it was measured, and waiting for the other limb before
        # saying so would be the screen holding its tongue at the worst moment.
        lone = pre_v if pre_v is not None else post_v
        if newborn and lone is not None and lone < CCHD_FAIL_BELOW:
            out["result"], out["reason"] = "fail", "below_90"
        return out

    # Signed, and the sign is kept: post-ductal *above* pre-ductal is reversed
    # differential cyanosis, which is rare and is not the same finding as the
    # ordinary way round. Averaging them into an absolute value would hide it.
    out["difference"] = round(pre_v - post_v, 1)

    if not newborn:
        return out

    if pre_v < CCHD_FAIL_BELOW or post_v < CCHD_FAIL_BELOW:
        out["result"], out["reason"] = "fail", "below_90"
    elif (max(pre_v, post_v) >= CCHD_PASS_AT_OR_ABOVE
            and abs(out["difference"]) <= CCHD_SPREAD):
        out["result"], out["reason"] = "pass", "clear"
    else:
        out["result"] = "repeat"
        out["reason"] = ("spread" if abs(out["difference"]) > CCHD_SPREAD
                         else "borderline")
    return out


def age_days(patient, on_date):
    """The child's age in whole days, or None when the file has no birth date.

    Days rather than the months everything else uses, because the screen this
    serves is defined in hours: "at 24 to 48 hours, before discharge".
    """
    dob = getattr(patient, "date_of_birth", None)
    if dob is None or on_date is None:
        return None
    return (on_date - dob).days


def read(values, patient=None, on_date=None):
    """Both answers from a panel's ``{code: value}``, for the visit screen.

    Returns ``{"four_limb": …, "ductal": …}`` with either side ``None`` when
    nothing was measured for it, so the screen can show the halves it has
    without waiting for the ones it does not.
    """
    values = values or {}
    days = age_days(patient, on_date) if patient is not None else None
    return {
        "four_limb": four_limb(values.get("bp_right_arm"),
                               values.get("bp_left_arm"),
                               values.get("bp_right_leg"),
                               values.get("bp_left_leg")),
        "ductal": ductal(values.get("spo2_pre_ductal"),
                         values.get("spo2_post_ductal"), days),
    }
