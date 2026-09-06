"""Writing a prescription the way a doctor actually writes one.

A paediatrician writes "every eight hours" forty times a day. Typed by hand it
comes out differently every time — «كل 8 ساعات», «كل ٨ ساعات», «tds», «3x» —
which is slow to write, inconsistent on the printed page, and impossible to
count afterwards.

So the writer accepts the shorthand doctors already use on paper and expands it
into one settled Arabic phrasing:

    1x3   → قرص كل ٨ ساعات
    5ml*2 → ٥ مل كل ١٢ ساعة
    q8h   → كل ٨ ساعات
    5d    → ٥ أيام
    1w    → أسبوع

Nothing is forced: text that isn't shorthand is returned exactly as it was
typed, because a doctor writing a real sentence must never have it rewritten
underneath them.
"""
import re

# The Arabic-Indic digits a printed prescription uses.
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"


def ar_number(value):
    """12 → ١٢. Numbers on a prescription are read by a parent, not a parser."""
    return "".join(_AR_DIGITS[int(c)] if c.isdigit() else c for c in str(value))


def _to_western(text):
    """Arabic-Indic digits back to ASCII, so shorthand can be typed either way."""
    table = {ord(d): str(i) for i, d in enumerate(_AR_DIGITS)}
    table.update({ord("٫"): ord("."), ord("،"): ord(",")})
    return (text or "").translate(table)


# --------------------------------------------------------------- plurals --
def ar_plural(count, one, two, few, many):
    """Arabic counts its nouns in four shapes, and getting it wrong reads
    like a machine wrote the prescription."""
    count = int(count)
    if count == 1:
        return one
    if count == 2:
        return two
    if 3 <= count % 100 <= 10:
        return f"{ar_number(count)} {few}"
    return f"{ar_number(count)} {many}"


def days_phrase(n):
    return ar_plural(n, "يوم واحد", "يومين", "أيام", "يوم")


def weeks_phrase(n):
    return ar_plural(n, "أسبوع", "أسبوعين", "أسابيع", "أسبوع")


def months_phrase(n):
    return ar_plural(n, "شهر", "شهرين", "شهور", "شهر")


# ------------------------------------------------------------- frequency --
# What a dose interval is called once it is settled. ``per_day`` is kept
# because it is the number the dosing check needs, and free text can't give it.
FREQUENCIES = [
    (1, "مرة واحدة يومياً"),
    (2, "كل ١٢ ساعة"),
    (3, "كل ٨ ساعات"),
    (4, "كل ٦ ساعات"),
    (6, "كل ٤ ساعات"),
]
_PER_DAY = dict(FREQUENCIES)

# The abbreviations that arrive from a medical education, plus the ones people
# type because they are faster.
_WORDS = {
    "od": 1, "qd": 1, "sid": 1, "daily": 1, "يوميا": 1, "يومياً": 1,
    "bd": 2, "bid": 2, "twice": 2,
    "tds": 3, "tid": 3, "thrice": 3,
    "qds": 4, "qid": 4,
}
# Instructions rather than intervals: they replace the frequency wholesale.
_PHRASES = {
    "prn": "عند اللزوم",
    "sos": "عند اللزوم",
    "عند اللزوم": "عند اللزوم",
    "nocte": "قبل النوم",
    "hs": "قبل النوم",
    "mane": "صباحاً",
    "stat": "جرعة واحدة فوراً",
}

_UNIT_CHARS = r"[A-Za-z\u0600-\u06FF]"
# "1x3" and "3x" are both written; so is "5ml*2".
_TIMES_RE = re.compile(
    rf"^\s*(?:(\d+(?:\.\d+)?)\s*({_UNIT_CHARS}*)\s*)?[x*×]\s*(\d+)\s*$")
_TIMES_TRAILING_RE = re.compile(r"^\s*(\d+)\s*[x*×]\s*$")
_EVERY_RE = re.compile(r"^\s*q\s*(\d+)\s*h?\s*$", re.I)
_EVERY_AR_RE = re.compile(r"^\s*كل\s*(\d+)\s*(?:ساعة|ساعات|س)?\s*$")

# What "1" means when it precedes the ×: a tablet unless the unit says otherwise.
_UNITS = {
    "": "قرص", "t": "قرص", "tab": "قرص", "ق": "قرص",
    "c": "كبسولة", "cap": "كبسولة", "ك": "كبسولة",
    "ml": "مل", "مل": "مل", "م": "مل",
    "sp": "معلقة", "معلقة": "معلقة",
    "d": "نقطة", "نقطة": "نقطة",
}


def _hours_phrase(hours):
    """"كل ٨ ساعات" — and "مرة واحدة يومياً" when it is simply daily."""
    hours = int(hours)
    if hours >= 24:
        return "مرة واحدة يومياً"
    return f"كل {ar_plural(hours, 'ساعة', 'ساعتين', 'ساعات', 'ساعة')}"


def _amount_phrase(number, unit):
    """"٥ مل", "قرص", "قرصين" — the amount taken each time."""
    name = _UNITS.get((unit or "").strip().lower())
    if name is None:
        return None
    if name in ("قرص", "كبسولة", "معلقة", "نقطة"):
        two = {"قرص": "قرصين", "كبسولة": "كبسولتين",
               "معلقة": "معلقتين", "نقطة": "نقطتين"}[name]
        try:
            return ar_plural(float(number), name, two, name, name) \
                if float(number).is_integer() else f"{ar_number(number)} {name}"
        except (TypeError, ValueError):
            return name
    return f"{ar_number(number)} {name}"


def parse_frequency(text):
    """``{"per_day": n, "text": "…"}`` for shorthand, else None.

    ``per_day`` is the part that matters beyond printing: free text can't tell
    a dosing check how many times a day the child takes something.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    low = _to_western(raw).strip().lower().rstrip(".")

    if low in _PHRASES:
        return {"per_day": None, "text": _PHRASES[low], "amount": None}
    if low in _WORDS:
        per_day = _WORDS[low]
        return {"per_day": per_day, "text": _PER_DAY.get(per_day, raw),
                "amount": None}

    match = _EVERY_RE.match(low) or _EVERY_AR_RE.match(_to_western(raw).strip())
    if match:
        hours = int(match.group(1))
        return {"per_day": (24 // hours) if 0 < hours <= 24 else None,
                "text": _hours_phrase(hours), "amount": None}

    trailing = _TIMES_TRAILING_RE.match(low)
    if trailing:
        low = f"x{trailing.group(1)}"
    match = _TIMES_RE.match(low)
    if match:
        number, unit, times = match.group(1), match.group(2), int(match.group(3))
        if times < 1 or times > 12:
            return None
        text_out = _PER_DAY.get(times) or f"{ar_number(times)} مرات يومياً"
        amount = _amount_phrase(number or 1, unit) if number or unit == "" else None
        return {"per_day": times, "text": text_out, "amount": amount}
    return None


def expand_frequency(text):
    """The settled phrasing for a frequency — or the text untouched."""
    parsed = parse_frequency(text)
    return parsed["text"] if parsed else (text or "")


# -------------------------------------------------------------- duration --
_DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(d|day|days|w|wk|week|weeks|m|mo|month|months|"
    r"ي|يوم|أيام|ايام|أ|اسبوع|أسبوع|أسابيع|اسابيع|ش|شهر|شهور)?\s*$", re.I)
_DAY_WORDS = {"d", "day", "days", "ي", "يوم", "أيام", "ايام"}
_WEEK_WORDS = {"w", "wk", "week", "weeks", "أ", "اسبوع", "أسبوع", "أسابيع",
               "اسابيع"}
_MONTH_WORDS = {"m", "mo", "month", "months", "ش", "شهر", "شهور"}


def expand_duration(text):
    """``5d`` → «٥ أيام», ``2w`` → «أسبوعين». Plain text is left alone."""
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _DURATION_RE.match(_to_western(raw))
    if not match:
        return raw
    count = int(match.group(1))
    unit = (match.group(2) or "d").strip().lower()
    if unit in _WEEK_WORDS:
        return weeks_phrase(count)
    if unit in _MONTH_WORDS:
        return months_phrase(count)
    if unit in _DAY_WORDS:
        return days_phrase(count)
    return raw


def duration_days(text):
    """A written duration in days, or ``None`` when it is not a length of time.

    The inverse of :func:`expand_duration`, and it lives beside it for one
    reason: **that function's output is this function's input.** The screen
    expands shorthand on save, so what is stored is «٥ أيام» and «أسبوعين»,
    not ``5d`` — a parser written anywhere else would be reading a format it
    does not own and would rot the first time the wording changed. The two
    are tested against each other rather than against a list of examples.

    Weeks are seven days and months are thirty. That is arithmetic, not a
    clinical claim: nothing here decides what a course *should* be, only how
    long the one on the paper is.

    ``None`` for anything else — "حتى التحسن", "when needed", empty — and that
    is a distinct answer from zero, because "no end written" is the thing a
    caller most needs to be able to see.
    """
    raw = _to_western((text or "").strip())
    if not raw:
        return None
    # The wordless shapes Arabic uses for one and two, which carry no digit.
    bare = {"يوم واحد": 1, "يوم": 1, "يومين": 2,
            "أسبوع": 7, "اسبوع": 7, "أسبوعين": 14, "اسبوعين": 14,
            "شهر": 30, "شهرين": 60}
    if raw in bare:
        return bare[raw]
    match = _DURATION_RE.match(raw)
    if not match:
        return None
    count = int(match.group(1))
    unit = (match.group(2) or "d").strip().lower()
    if unit in _WEEK_WORDS:
        return count * 7
    if unit in _MONTH_WORDS:
        return count * 30
    if unit in _DAY_WORDS:
        return count
    return None


# ------------------------------------------------------------------ dose --
_DOSE_RE = re.compile(rf"^\s*(\d+(?:[.,]\d+)?)\s*({_UNIT_CHARS}*)\s*$")


def expand_dose(text):
    """``5ml`` → «٥ مل», ``1t`` → «قرص». Anything else is returned as typed."""
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _DOSE_RE.match(_to_western(raw).replace(",", "."))
    if not match:
        return raw
    phrase = _amount_phrase(match.group(1), match.group(2))
    return phrase or raw


def expand_line(line):
    """Expand a whole written line in place → the same dict.

    Used on save so the stored prescription is consistent however it was
    typed, including from a screen that never ran the browser-side expansion.
    """
    if not isinstance(line, dict):
        return line
    parsed = parse_frequency(line.get("frequency"))
    if parsed:
        line["frequency"] = parsed["text"]
        # "1x3" says the amount as well as the interval — don't lose the "1".
        if parsed.get("amount") and not (line.get("dose") or "").strip():
            line["dose"] = parsed["amount"]
    line["dose"] = expand_dose(line.get("dose"))
    line["duration"] = expand_duration(line.get("duration"))
    return line
