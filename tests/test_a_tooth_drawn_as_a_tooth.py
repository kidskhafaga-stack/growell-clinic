"""The chart draws teeth, not numbered squares.

Reported looking at it: *"ليه منظر كده ليه مش بشكل كل سن ودرس؟ فى اشكال بتبقى
بنفس منظر السن ونميز المنظر من سن اللبنى على الدائم"*.

A square tells you nothing until you have read its number, which is the
opposite of what a chart is for — a dentist should see the shape of the arch
and find the tooth in it, the way they do on paper.

The interesting part is not the drawing. It is that **the shape cannot be
chosen from the last digit alone**: position 4 in a permanent quadrant is a
premolar, and position 4 in a *primary* quadrant is a molar, because the
primary set has no premolars at all. A chart that reads the digit and stops
draws a child's mouth with four teeth that are not in it — an adult chart
shrunk down, which is exactly what a paediatric program must not ship.
"""
import pytest

from app.models.dental import (PERMANENT_TEETH, PRIMARY_TEETH, TOOTH_KINDS,
                               is_primary, tooth_kind, tooth_position)


# ------------------------------------------------------- what a tooth is ----
@pytest.mark.parametrize("tooth,expected", [
    (11, "incisor"), (12, "incisor"), (21, "incisor"), (41, "incisor"),
    (13, "canine"), (23, "canine"), (33, "canine"),
    (14, "premolar"), (15, "premolar"), (24, "premolar"),
    (16, "molar"), (17, "molar"), (18, "molar"), (48, "molar"),
])
def test_a_permanent_tooth_is_named_correctly(tooth, expected):
    assert tooth_kind(tooth) == expected


@pytest.mark.parametrize("tooth,expected", [
    (51, "incisor"), (52, "incisor"), (61, "incisor"), (81, "incisor"),
    (53, "canine"), (63, "canine"), (73, "canine"),
    # The whole point of the function.
    (54, "molar"), (55, "molar"), (64, "molar"), (85, "molar"),
])
def test_a_primary_tooth_is_named_correctly(tooth, expected):
    assert tooth_kind(tooth) == expected


def test_the_primary_set_has_no_premolars_at_all():
    """Twenty teeth, not twenty-eight. The two premolars that eventually stand
    at positions 4 and 5 erupt *underneath* the primary molars and replace
    them — they are not present in a child's first set."""
    assert not any(tooth_kind(t) == "premolar" for t in PRIMARY_TEETH)


def test_the_permanent_set_has_exactly_eight_premolars():
    """Two per quadrant, four quadrants. A count, because "no premolars in the
    primary set" would also be satisfied by a function that never returns
    premolar for anything."""
    premolars = [t for t in PERMANENT_TEETH if tooth_kind(t) == "premolar"]
    assert len(premolars) == 8
    assert all(tooth_position(t) in (4, 5) for t in premolars)


def test_the_same_position_answers_differently_in_the_two_sets():
    """The trap this function exists for, stated directly."""
    assert tooth_position(14) == tooth_position(54)
    assert tooth_kind(14) != tooth_kind(54)


def test_every_tooth_gets_one_of_the_four_kinds():
    for tooth in PERMANENT_TEETH + PRIMARY_TEETH:
        assert tooth_kind(tooth) in TOOTH_KINDS, tooth


def test_the_counts_come_out_right():
    """Twenty primary and thirty-two permanent, each with the shape mix a
    mouth actually has."""
    assert len(PRIMARY_TEETH) == 20
    assert len(PERMANENT_TEETH) == 32
    assert sum(1 for t in PRIMARY_TEETH if tooth_kind(t) == "molar") == 8
    assert sum(1 for t in PRIMARY_TEETH if tooth_kind(t) == "incisor") == 8
    assert sum(1 for t in PRIMARY_TEETH if tooth_kind(t) == "canine") == 4


# ------------------------------------------------------------ the drawing ---
@pytest.fixture
def chart(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


def _page(kit):
    return kit["sign_in"]("doc").get(
        f"/dentistry/patient/{kit['ids']['child']}").get_data(as_text=True)


def test_every_tooth_is_drawn(chart):
    page = _page(chart)
    assert page.count("<svg") >= len(PERMANENT_TEETH) + len(PRIMARY_TEETH)


@pytest.mark.parametrize("path,kind", [
    ("M9 4 Q16 1 23 4", "incisor"),
    ("M10 5 Q16 2 22 5", "canine"),
    ("M7 8 Q16 3 25 8", "premolar"),
    ("M5 8 Q16 3 27 8", "molar"),
])
def test_all_four_shapes_are_on_the_page(chart, path, kind):
    """A chart drawing one outline for everything is the numbered squares
    again with rounder corners."""
    assert path in _page(chart), kind


def test_the_two_sets_are_drawn_at_different_sizes(chart):
    """*"ونميز المنظر من سن اللبنى على الدائم"* — between six and twelve a
    child has both sets at once, and telling them apart is most of what the
    chart is for at that age."""
    page = _page(chart)
    assert 'width="32" height="36"' in page      # permanent
    assert 'width="26" height="30"' in page      # primary


# ------------------------------------------- and what was found on them ----
def _record(kit, tooth, condition):
    from app.models.dental import ToothFinding
    from app.utils.clock import local_today

    with kit["app"].app_context():
        kit["db"].session.add(ToothFinding.record(
            patient_id=kit["ids"]["child"], tooth=tooth,
            condition=condition, found_on=local_today()))
        kit["db"].session.commit()


@pytest.mark.parametrize("condition,mark", [
    ("caries", 'fill="#b45309"'),
    ("filled", 'fill="#64748b"'),
    ("crown", 'fill="#facc15"'),
])
def test_the_finding_colours_the_tooth(chart, condition, mark):
    _record(chart, 16, condition)
    assert mark in _page(chart)


def test_a_missing_tooth_is_struck_through_and_not_removed(chart):
    """The space is part of the chart. An empty slot would read as a tooth
    nobody has looked at, which is a different thing from one that is gone."""
    _record(chart, 54, "extracted")
    page = _page(chart)
    assert "M6 6 L26 30" in page          # the cross
    assert page.count("<svg") >= len(PERMANENT_TEETH) + len(PRIMARY_TEETH)


def test_a_tooth_nobody_looked_at_is_not_drawn_as_sound(chart):
    """The chart must not make "not examined" look like "fine"."""
    blank = _page(chart)
    _record(chart, 11, "sound")
    marked = _page(chart)
    assert blank != marked, "recording a tooth as sound changed nothing"


def test_the_condition_is_still_written_in_words(chart):
    """The drawing adds; it does not replace. A picture carrying the only copy
    of the information makes every reader learn a legend first."""
    _record(chart, 16, "caries")
    page = _page(chart)
    assert "dental.c_caries" not in page
    from app.i18n import translate
    # the word itself, not the key
    assert page.count("<svg") and ("تسوس" in page or "aries" in page)
