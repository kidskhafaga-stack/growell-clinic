"""What counts as normal for a child of this age, in one place.

These numbers existed already — as a JavaScript object called ``_peds`` inside
the visit screen's Alpine component, which is where the colour on the pulse box
comes from. That was fine while the only thing that needed them was the box
being typed into.

It stops being fine the moment anything on the server needs the same judgement:
triage at the nursing station, a report, an emergency screen deciding who is
sickest. Any of those would have had to carry a second copy of the table, and a
second copy is free to disagree with the first — so a child could be amber on
one screen and green on another, with each screen individually correct.

So the table lives here, and the visit screen is handed it rather than holding
it. There is a test that the numbers appear in exactly one place in the
repository, because a second copy is the failure and the only reliable moment
to catch it is when somebody adds it.

**Four numbers per band, not two.** ``[ok_low, ok_high, warn_low, warn_high]``:
inside the first pair is normal, inside the second is tolerated, outside both
is abnormal. Two bands rather than one because a respiratory rate of 42 in a
two-year-old is worth a second look and is not the same event as 65.

**Nothing here is a diagnosis** and nothing here decides anything. It says
where a reading sits against the usual range for the age. A well child runs
fast when they have been crying, and a very sick one can be deceptively normal
for a while; the colour is a prompt to look, which is all the screen has ever
claimed it was.
"""
NORMAL, BORDERLINE, ABNORMAL, UNKNOWN = "ok", "warn", "bad", "unknown"

# Age is in **months**, and each row reads "up to and including this age".
# The last row's 9999 is the open-ended one — a fifteen-year-old is still a
# paediatric patient and still needs an answer.
BY_AGE = {
    "hr": [
        # (up to months, ok_low, ok_high, warn_low, warn_high)
        (3,    100, 160,  90, 180),
        (12,    90, 160,  80, 180),
        (36,    80, 140,  70, 160),
        (72,    70, 120,  60, 140),
        (144,   65, 110,  55, 130),
        (9999,  60, 100,  50, 120),
    ],
    "rr": [
        (12,    30,  55,  25,  65),
        (36,    24,  40,  20,  50),
        (72,    22,  34,  18,  42),
        (144,   18,  30,  14,  36),
        (9999,  12,  20,  10,  26),
    ],
}

# Two that do not move with age. Kept beside the others rather than special-
# cased at each call site: "what is the range for this reading" should have one
# answer regardless of whether age happens to enter into it.
FIXED = {
    "temp": (36.0, 37.5, 35.5, 38.0),
    "spo2": (95, 100, 91, 100),
}


def band_for(kind, age_months):
    """The four limits for this reading, or ``None`` when there are none.

    ``(ok_low, ok_high, warn_low, warn_high)``.

    ``None`` means this program has no range for that reading — which a caller
    must render as "no opinion", never as normal. A missing range shown in
    green is the program asserting something it was never told.
    """
    if kind in FIXED:
        return FIXED[kind]
    rows = BY_AGE.get(kind)
    if not rows or age_months is None:
        return None
    for limit, ok_low, ok_high, warn_low, warn_high in rows:
        if age_months <= limit:
            return (ok_low, ok_high, warn_low, warn_high)
    return None


def band(kind, age_months, value):
    """Where this reading sits: ``ok`` / ``warn`` / ``bad`` / ``unknown``.

    ``unknown`` for a missing value, an unreadable one, or a reading this
    program has no range for. It is deliberately a fourth answer rather than
    being folded into ``ok``: "we have no opinion" and "this is normal" are
    different things to show a nurse, and collapsing them is how a program
    reassures somebody about a number it never actually checked.
    """
    if value is None or value == "":
        return UNKNOWN
    try:
        reading = float(value)
    except (TypeError, ValueError):
        return UNKNOWN
    limits = band_for(kind, age_months)
    if limits is None:
        return UNKNOWN
    ok_low, ok_high, warn_low, warn_high = limits
    if ok_low <= reading <= ok_high:
        return NORMAL
    if warn_low <= reading <= warn_high:
        return BORDERLINE
    return ABNORMAL


# What a set of vitals is read as, and under which key. `weight_kg` and the
# rest are not here: they are growth, judged against a centile curve over time
# and not against a band, and `app/utils/growth.py` already does that properly.
READINGS = (("temp", "temperature_c"), ("hr", "pulse_bpm"),
            ("rr", "resp_rate"), ("spo2", "spo2"))


def read(vitals, age_months):
    """``{kind: (value, band)}`` for one set of vitals — the server's view.

    Returns every reading including the ones not taken, each as ``unknown``,
    so a caller can tell "measured and normal" from "never measured". A
    screen that silently omits what was not taken looks like a child who was
    fully assessed.
    """
    out = {}
    for kind, attribute in READINGS:
        value = (getattr(vitals, attribute, None)
                 if vitals is not None else None)
        out[kind] = (value, band(kind, age_months, value))
    return out


def worst(vitals, age_months):
    """The most abnormal band in a set, and which readings are in it.

    Returns ``(band, [kind, …])``. The kinds travel with the verdict because a
    colour nobody can account for gets ignored by the second day — a nurse
    seeing amber needs to know it is the respiratory rate, not to go hunting.
    """
    seen = read(vitals, age_months)
    for level in (ABNORMAL, BORDERLINE):
        kinds = [kind for kind, (_value, got) in seen.items() if got == level]
        if kinds:
            return level, kinds
    measured = [kind for kind, (_v, got) in seen.items() if got == NORMAL]
    return (NORMAL, measured) if measured else (UNKNOWN, [])
