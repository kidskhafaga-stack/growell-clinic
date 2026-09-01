"""One table of what is normal for a child of this age.

The age-banded heart and respiratory rate ranges used to live as a JavaScript
object inside the visit screen's Alpine component. That was fine while the
only thing judging a reading was the box being typed into.

It stops being fine the moment anything on the server needs the same judgement
— triage at the nursing station, an emergency screen deciding who is sickest,
a report. Each of those would have carried its own copy, and a second copy is
free to disagree with the first: a child amber on one screen and green on
another, with each screen individually correct and nobody able to say which
was right.

So the table moved into Python and the screen is handed it. Most of what is
below is about that staying true.
"""
import os
import re

import pytest

from app.utils import vital_bands as vb

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


# ---------------------------------------------------------- the judgement ---
@pytest.mark.parametrize("kind,months,value,expected", [
    # A newborn's pulse. 110 is ordinary; 170 is worth a look; 200 is not.
    ("hr", 2, 110, vb.NORMAL),
    ("hr", 2, 170, vb.BORDERLINE),
    ("hr", 2, 200, vb.ABNORMAL),
    # The same number at a different age is a different answer — which is the
    # entire reason this table is banded rather than a single range. A pulse of
    # 95 is slow for a two-month-old and unremarkable for a ten-year-old.
    ("hr", 2, 95, vb.BORDERLINE),
    ("hr", 120, 95, vb.NORMAL),
    ("rr", 6, 40, vb.NORMAL),
    ("rr", 6, 60, vb.BORDERLINE),
    ("rr", 6, 80, vb.ABNORMAL),
    # And two that do not move with age.
    ("temp", 6, 37.0, vb.NORMAL),
    ("temp", 6, 37.8, vb.BORDERLINE),
    ("temp", 6, 39.0, vb.ABNORMAL),
    ("spo2", 6, 98, vb.NORMAL),
    ("spo2", 6, 93, vb.BORDERLINE),
    ("spo2", 6, 85, vb.ABNORMAL),
])
def test_a_reading_lands_where_it_should(kind, months, value, expected):
    assert vb.band(kind, months, value) == expected


def test_a_teenager_still_gets_an_answer(vb_kinds=("hr", "rr")):
    """The open-ended last row. A fifteen-year-old is still a paediatric
    patient, and a table that ran out at twelve would show them no colour at
    all — which reads as "checked and fine"."""
    for kind in vb_kinds:
        assert vb.band(kind, 190, 75) != vb.UNKNOWN


@pytest.mark.parametrize("value", [None, "", "abc"])
def test_nothing_measured_is_unknown_and_not_normal(value):
    """A fourth answer on purpose. "We have no opinion" and "this is normal"
    are different things to show a nurse, and folding them together is how a
    program reassures somebody about a number it never checked."""
    assert vb.band("hr", 6, value) == vb.UNKNOWN


def test_a_reading_with_no_range_is_unknown_and_not_normal():
    assert vb.band("blood_glucose", 6, 5) == vb.UNKNOWN


def test_an_unknown_age_gives_no_opinion_on_an_age_banded_reading():
    """A pulse means nothing without an age. Better to say so than to pick a
    band."""
    assert vb.band("hr", None, 100) == vb.UNKNOWN


def test_an_unknown_age_still_answers_the_ones_that_do_not_need_it():
    assert vb.band("temp", None, 39.0) == vb.ABNORMAL


# ----------------------------------------------------------- a whole set ----
class _Vitals:
    def __init__(self, **kwargs):
        self.temperature_c = kwargs.get("temperature_c")
        self.pulse_bpm = kwargs.get("pulse_bpm")
        self.resp_rate = kwargs.get("resp_rate")
        self.spo2 = kwargs.get("spo2")


def test_what_was_not_measured_is_still_listed(clinic):
    """A set that quietly omits the readings nobody took looks like a child
    who was fully assessed."""
    seen = vb.read(_Vitals(pulse_bpm=110), age_months=2)
    assert set(seen) == {"temp", "hr", "rr", "spo2"}
    assert seen["rr"][1] == vb.UNKNOWN
    assert seen["hr"][1] == vb.NORMAL


def test_the_worst_reading_wins(clinic):
    got, kinds = vb.worst(
        _Vitals(pulse_bpm=110, resp_rate=80, temperature_c=37.8), 2)
    assert got == vb.ABNORMAL
    assert kinds == ["rr"]


def test_the_verdict_says_which_reading_caused_it(clinic):
    """A colour nobody can account for gets ignored by the second day."""
    got, kinds = vb.worst(_Vitals(pulse_bpm=170), 2)
    assert got == vb.BORDERLINE
    assert kinds == ["hr"]


def test_nothing_measured_at_all_is_unknown_not_normal(clinic):
    got, kinds = vb.worst(_Vitals(), 2)
    assert got == vb.UNKNOWN
    assert kinds == []


def test_no_vitals_row_at_all_does_not_raise(clinic):
    assert vb.worst(None, 2)[0] == vb.UNKNOWN


# ------------------------------------------------- and only one of them -----
def test_the_numbers_are_written_down_in_exactly_one_place():
    """The point of the whole move, and the only reliable moment to catch a
    second copy is when somebody adds it.

    Searched for as the table's own distinctive rows rather than for a single
    number: `160` appears in stylesheets and in unrelated code, but the
    sequence 100,160,90,180 is this table and nothing else."""
    rows = [(100, 160, 90, 180), (30, 55, 25, 65)]
    offenders = []
    for folder, _dirs, files in os.walk(ROOT):
        if any(part in folder for part in
               (".git", "__pycache__", "node_modules", "instance")):
            continue
        for name in files:
            if not name.endswith((".py", ".html", ".js")):
                continue
            path = os.path.join(folder, name)
            if os.path.abspath(path) in (
                    os.path.abspath(vb.__file__.replace(".pyc", ".py")),
                    os.path.abspath(__file__)):
                continue
            try:
                body = open(path, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError):
                continue
            for row in rows:
                pattern = r"[,\[\(]\s*".join(str(n) for n in row)
                if re.search(pattern, body):
                    offenders.append(f"{os.path.relpath(path, ROOT)}: {row}")
    assert not offenders, (
        "the age bands are written down more than once: "
        + ", ".join(offenders))


def test_the_screen_is_handed_the_table_rather_than_holding_one(clinic):
    """It must arrive from the server. A screen that fell back to its own
    hard-coded copy when the server sent nothing would pass every test above
    and still be a second table."""
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "vitalBands" in page
    assert '"hr"' in page or "'hr'" in page
    # The numbers are on the page — sent, not written into the template.
    assert "100" in page and "160" in page


def test_the_screen_still_colours_a_reading(clinic):
    """The behaviour the move must not have cost."""
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "vitalClass('hr'" in page
    assert "vitalRange(kind)" in page
