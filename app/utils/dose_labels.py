"""Which dose this is, and what happens after it.

A vaccination record is only useful if it says *which* dose was given. The
schedule that follows depends on it entirely: the second dose of a course is
due in a month, the booster is due in a year, and the last dose is due never.
Recording "a dose of the pentavalent" and letting the program guess is how a
child ends up with two second doses and no third.

So the dose number is stated — first, second, third, booster — and everything
downstream reads it: what the parent is told, when the next reminder falls, and
whether the course is finished at all.

This module is only the wording and the arithmetic of "what comes next". The
recording itself, the stock deduction and the doctor's credit stay where they
were.
"""
from datetime import date

_ORDINALS_AR = {1: "الأولى", 2: "الثانية", 3: "الثالثة", 4: "الرابعة",
                5: "الخامسة", 6: "السادسة"}
_ORDINALS_EN = {1: "first", 2: "second", 3: "third", 4: "fourth",
                5: "fifth", 6: "sixth"}
# What a booster is called on a card the parent keeps.
BOOSTER_AR = "الجرعة المنشّطة"
BOOSTER_EN = "booster"


def is_booster(brand, dose_number):
    """Whether this dose is the course's booster rather than a primary dose.

    Read from the schedule when it says so; otherwise inferred the way a
    paediatrician would — the last dose of a multi-dose course that falls a
    year or more after the one before it is a booster, not a primary dose.
    """
    doses = sorted(getattr(brand, "doses", None) or [],
                   key=lambda d: d.dose_number)
    if not doses or len(doses) < 2:
        return False
    match = next((d for d in doses if d.dose_number == dose_number), None)
    if match is None:
        return False
    if getattr(match, "is_booster", False):
        return True
    if match is not doses[-1]:
        return False
    previous = doses[-2]
    gap = (match.age_months or 0) - (previous.age_months or 0)
    return gap >= 9


def dose_label(dose_number, lang="ar", brand=None, vaccine=None, on_date=None):
    """"الجرعة الثانية" / "الجرعة المنشّطة" / "جرعة موسم ٢٠٢٦"."""
    if vaccine is not None and getattr(vaccine, "is_seasonal", False):
        year = (on_date or date.today()).year
        return f"جرعة موسم {year}" if lang != "en" else f"{year} season dose"
    if brand is not None and is_booster(brand, dose_number):
        return BOOSTER_AR if lang != "en" else BOOSTER_EN
    if lang == "en":
        name = _ORDINALS_EN.get(dose_number)
        return f"{name} dose" if name else f"dose {dose_number}"
    name = _ORDINALS_AR.get(dose_number)
    return f"الجرعة {name}" if name else f"الجرعة رقم {dose_number}"


def dose_choices(vaccine, brand, given_numbers=(), lang="ar"):
    """Every dose this course has, labelled, with what is already recorded.

    The doctor picks from this rather than typing a number: it is the list
    that makes "this is the second dose, the first was at the government unit"
    a thing you can say in one action.
    """
    out = []
    doses = sorted(getattr(brand, "doses", None) or [],
                   key=lambda d: d.dose_number)
    for entry in doses:
        out.append({
            "number": entry.dose_number,
            "label": dose_label(entry.dose_number, lang, brand=brand),
            "age_months": entry.age_months,
            "given": entry.dose_number in set(given_numbers),
            "booster": is_booster(brand, entry.dose_number),
        })
    if not out:
        # A vaccine with no schedule on file (a seasonal one, or a brand the
        # clinic hasn't filled in) still needs a first dose to be recordable.
        highest = max(list(given_numbers) + [0])
        out.append({"number": highest + 1,
                    "label": dose_label(highest + 1, lang, vaccine=vaccine),
                    "age_months": None, "given": False, "booster": False})
    return out


def next_dose(patient, vaccine, brand, current_dose, on_date=None):
    """What comes after the dose just given.

    Returns ``{"kind": …, "date": …, "number": …}`` where kind is:

    * ``date``     — another dose is scheduled, here is when;
    * ``complete`` — that was the last one; the course is finished;
    * ``seasonal`` — it comes back next season, not on a fixed schedule;
    * ``unknown``  — no schedule and no birth date to count from.

    "Finished" and "we don't know" have to be different answers. Printing a
    dash for both tells a parent nothing and tells the reminder engine less.
    """
    if vaccine is not None and getattr(vaccine, "is_seasonal", False):
        year = (on_date or date.today()).year + 1
        return {"kind": "seasonal", "date": None, "number": None, "year": year}

    doses = sorted(getattr(brand, "doses", None) or [],
                   key=lambda d: d.dose_number)
    if not doses:
        return {"kind": "unknown", "date": None, "number": None}
    following = next((d for d in doses if d.dose_number > (current_dose or 0)),
                     None)
    if following is None:
        return {"kind": "complete", "date": None, "number": None}
    birth = getattr(patient, "date_of_birth", None)
    if not birth:
        return {"kind": "unknown", "date": None,
                "number": following.dose_number}
    return {"kind": "date",
            "date": _add_months(birth, following.age_months or 0),
            "number": following.dose_number}


def next_dose_text(patient, vaccine, brand, current_dose, lang="ar",
                   on_date=None):
    """The same answer as one line for a message or a screen."""
    info = next_dose(patient, vaccine, brand, current_dose, on_date)
    if info["kind"] == "complete":
        return ("اكتمل التطعيم — مفيش جرعات تانية" if lang != "en"
                else "course complete — no further doses")
    if info["kind"] == "seasonal":
        return (f"الموسم الجاي ({info['year']})" if lang != "en"
                else f"next season ({info['year']})")
    if info["kind"] == "date" and info["date"]:
        label = dose_label(info["number"], lang, brand=brand)
        return (f"{label}: {info['date'].isoformat()}" if lang != "en"
                else f"{label} on {info['date'].isoformat()}")
    return "—"


def _add_months(day, months):
    import calendar

    month = day.month - 1 + int(months or 0)
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))
