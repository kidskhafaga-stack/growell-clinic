"""Which child in the waiting room should not still be in the waiting room.

(Named for the flags rather than for triage: ``app/utils/triage.py`` already
decides which *message* to answer first. Two different queues, two different
questions, and merging them would put a WhatsApp message and a febrile infant
through the same scoring.)

The nurse records a temperature, a pulse and an oxygen saturation, and they go
into the file. That is where they stayed. A two-month-old at 38.2 with vomiting
sat in the queue behind eight routine follow-ups because the number that made
him urgent was written down and read by nobody until his turn came.

So this reads the vitals the moment they are saved and says, in one word,
whether this child should be seen now.

**Why the thresholds are banded by age.** One number cannot do this. 38.0 in a
six-week-old is a reason to admit and investigate for sepsis; 39.0 in a
four-year-old is very often a cold. A single threshold set high enough not to
cry wolf over toddlers is a threshold that silently ignores the infants who
need it most — which is the exact failure this module exists to prevent, so it
is not a setting anybody should be able to flatten by accident.

The bands below follow ordinary paediatric practice (NICE traffic-light
guidance and the usual teaching on fever without source in infants). They are
editable per clinic, because clinics differ and a threshold nobody agrees with
is a threshold that gets ignored — but they are editable *per band*, so
lowering the tolerance for toddlers can never quietly raise it for newborns.

**It advises. It never triages.** Everything here returns a flag and its
reasons; no queue is reordered, nothing is auto-referred. A nurse or a doctor
decides. Software that silently reorders a waiting room is software nobody
trusts the second time it is wrong.
"""
import re

# (max age in months, fever °C, urgent °C) — the first band a child falls into.
#
# Under three months any fever is urgent, which is why the first band's two
# numbers are the same: there is no "watch and see" temperature in a newborn.
DEFAULT_BANDS = [
    (3, 38.0, 38.0),
    (6, 38.5, 39.0),
    (36, 38.5, 39.0),
    (9999, 38.5, 39.5),
]

# Oxygen saturation below this is urgent at any age, before any temperature is
# considered. A well-looking child at 90% is the one that gets missed.
SPO2_URGENT = 92
SPO2_WATCH = 95

# Words that turn a fever into a dehydration risk, in both languages and in the
# spellings families and nurses actually type.
RED_FLAG_WORDS = {
    "diarrhoea": ["اسهال", "إسهال", "اسهاال", "diarrh", "loose motion"],
    "vomiting": ["ترجيع", "قيء", "قيئ", "استفراغ", "vomit"],
    "drowsy": ["خمول", "خامل", "مش فايق", "lethargic", "drowsy", "unrespons"],
    "breathing": ["صعوبة تنفس", "نهجان", "زرقان", "لهث",
                  "difficulty breathing", "cyanos", "grunting"],
    "convulsion": ["تشنج", "تشنجات", "convuls", "seiz", "fit"],
    "rash": ["طفح", "بقع", "نزيف تحت الجلد", "petechia", "purpur"],
}

# The ones that stand on their own — no fever required.
STANDALONE_FLAGS = {"drowsy", "breathing", "convulsion"}


def bands():
    """The clinic's fever bands, falling back to the paediatric defaults."""
    from app.models import Setting

    out = []
    for index, (max_months, fever, urgent) in enumerate(DEFAULT_BANDS):
        def _num(name, fallback):
            raw = (Setting.get(f"triage_{name}_{index}") or "").strip()
            try:
                return float(raw) if raw else fallback
            except ValueError:
                return fallback

        out.append((max_months, _num("fever", fever), _num("urgent", urgent)))
    return out


def spo2_limits():
    """The clinic's oxygen limits, falling back to the paediatric defaults.

    The fever bands have been overridable since they were written; these two
    were constants, read straight out of the module, so a clinic could change
    what counts as a fever and not what counts as hypoxia. That was not a
    decision anybody took — it is simply where the first version stopped.

    Same shape as :func:`bands` on purpose: default in the code, override in
    the settings, and the default returned for anything unreadable.
    """
    from app.models import Setting

    def _num(key, fallback):
        try:
            raw = (Setting.get(key) or "").strip()
        except Exception:  # noqa: BLE001 — settings table may not be ready
            return fallback
        try:
            return float(raw) if raw else fallback
        except ValueError:
            return fallback

    return (_num("triage_spo2_urgent", SPO2_URGENT),
            _num("triage_spo2_watch", SPO2_WATCH))


def _age_months(patient):
    if patient is None or not getattr(patient, "date_of_birth", None):
        return None
    try:
        years, months = patient.age_parts[0], patient.age_parts[1]
        return years * 12 + months
    except Exception:                       # noqa: BLE001
        return None


def _band_for(age_months):
    table = bands()
    if age_months is None:
        # No date of birth is not a reason to apply an infant's threshold to a
        # ten-year-old, nor a ten-year-old's to an infant. The mildest band is
        # the honest choice, and the missing birthday is its own problem.
        return table[-1]
    for max_months, fever, urgent in table:
        if age_months < max_months:
            return (max_months, fever, urgent)
    return table[-1]


def _words_in(text):
    """Which red-flag words appear in a complaint, however it was typed."""
    lowered = (text or "").lower()
    # Arabic is written with and without its diacritics and with أ/ا used
    # interchangeably; folding both is the difference between catching
    # "إسهال" and catching nothing.
    folded = re.sub(r"[أإآ]", "ا", lowered)
    found = set()
    for flag, needles in RED_FLAG_WORDS.items():
        for needle in needles:
            if re.sub(r"[أإآ]", "ا", needle) in folded:
                found.add(flag)
                break
    return found


def assess(patient, vitals, complaint=""):
    """One flag for one child: ``urgent``, ``watch`` or ``None``.

    Returns ``{"level", "reasons", "temp_limit"}``. ``reasons`` are keys a
    screen translates — a badge saying only "urgent" makes a nurse re-read
    every number to find out why, which is the work this was meant to save.
    """
    age_months = _age_months(patient)
    _, fever_at, urgent_at = _band_for(age_months)
    reasons, level = [], None

    def _raise(to):
        nonlocal level
        if to == "urgent" or level is None:
            level = to

    temp = getattr(vitals, "temperature_c", None) if vitals else None
    spo2 = getattr(vitals, "spo2", None) if vitals else None
    flags = _words_in(complaint)

    # Oxygen first: it outranks a temperature, and a comfortable-looking child
    # at 90% is the one a busy room walks past.
    if spo2 is not None:
        urgent_below, watch_below = spo2_limits()
        if spo2 < urgent_below:
            reasons.append("spo2_low")
            _raise("urgent")
        elif spo2 < watch_below:
            reasons.append("spo2_borderline")
            _raise("watch")

    if temp is not None:
        if temp >= urgent_at:
            reasons.append("fever_high")
            _raise("urgent")
        elif temp >= fever_at:
            reasons.append("fever")
            _raise("watch")
        # An infant under three months with any fever at all. Stated
        # separately from the band so the screen can say *why* rather than
        # showing a number that looks unremarkable to anybody who does not
        # already know this rule.
        if age_months is not None and age_months < 3 and temp >= 38.0:
            reasons.append("infant_fever")
            _raise("urgent")

    # Fever plus fluid loss is the dehydration pair the clinic named.
    if temp is not None and temp >= fever_at:
        if {"diarrhoea", "vomiting"} <= flags:
            reasons.append("fever_gastro")
            _raise("urgent")
        elif flags & {"diarrhoea", "vomiting"}:
            reasons.append("fever_fluids")
            _raise("watch")

    # These do not wait for a thermometer.
    for flag in sorted(flags & STANDALONE_FLAGS):
        reasons.append(flag)
        _raise("urgent")
    if "rash" in flags and temp is not None and temp >= fever_at:
        reasons.append("fever_rash")
        _raise("urgent")

    return {"level": level, "reasons": reasons, "temp_limit": fever_at,
            "urgent_limit": urgent_at, "age_months": age_months}


def assess_visit(visit):
    """The same judgement for a visit, using whatever complaint it holds."""
    if visit is None:
        return {"level": None, "reasons": []}
    text = " ".join(filter(None, [
        getattr(visit, "chief_complaint", ""),
        getattr(getattr(visit, "appointment", None), "reason", ""),
    ]))
    return assess(visit.patient, getattr(visit, "vitals", None), text)
