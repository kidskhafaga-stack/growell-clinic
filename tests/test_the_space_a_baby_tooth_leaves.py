"""A primary molar came out in March, and the space closed over the summer.

When a baby back tooth is lost early the teeth beside it drift into the gap,
and by the time the premolar underneath is ready to come through there is
nowhere left for it. It arrives crooked, or it does not arrive. A space
maintainer holds the gap open until it does — which is one of the defining
jobs of paediatric dentistry, and was in this program as a **price** and
nothing else: a line on an invoice, with nowhere in the child's file to say
one had been fitted and nothing anywhere to notice the space.

**This raises the question; it does not answer it.** Whether a maintainer goes
in depends on how close the premolar is to erupting, on the child's age, and
on whether the successor exists at all — read off an X-ray, in front of the
child. A program that saw "extracted" and wrote "fit a space maintainer" would
be prescribing from a keyword, exactly as one reading "caries" and writing
"filling" would be, and the line is the same line.

What it earns is that nobody has to remember. The visit where somebody would
have spotted the closing gap is the one where the child came in about
something else.
"""
from datetime import date

import pytest


@pytest.fixture
def dental(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


@pytest.fixture
def boss(dental):
    return dental["sign_in"]("boss")


def _find(clinic, tooth, condition, surface="whole", day=(2026, 8, 1)):
    """Through ``ToothFinding.record``, which is the only door the program has.

    A helper that built rows itself would be a second way of writing a
    finding, and the second way does not know where a space maintainer goes.
    That is exactly what happened: mutation testing found the maintainer
    landing on top of the extraction here while the real screen placed it
    correctly, so a test claiming the maintainer settles the space was
    proving nothing.
    """
    from app.models import ToothFinding

    with clinic["app"].app_context():
        clinic["db"].session.add(ToothFinding.record(
            patient_id=clinic["ids"]["child"], tooth=tooth, surface=surface,
            condition=condition, found_on=date(*day)))
        clinic["db"].session.commit()


def _spaces(clinic):
    from app.models.dental import chart_for, spaces_to_decide

    with clinic["app"].app_context():
        return spaces_to_decide(chart_for(clinic["ids"]["child"]))


# ------------------------------------------------------ which tooth it was --
def test_a_lost_baby_molar_raises_the_question(dental):
    _find(dental, 75, "extracted")
    assert 75 in _spaces(dental)


def test_it_names_the_tooth_that_is_coming(dental):
    """So the dentist knows which X-ray to look at. 75 is replaced by 35 —
    the numbering says so, and saying it out loud is the difference between a
    warning and a useful one."""
    _find(dental, 75, "extracted")
    assert _spaces(dental)[75] == 35


def test_a_lost_front_baby_tooth_does_not(dental):
    """A toddler who fell over. Very little space is lost at the front, and an
    appliance there is a cosmetic decision rather than a space one — raising
    it on every knocked-out incisor is how a warning becomes something people
    click past."""
    _find(dental, 51, "extracted")
    _find(dental, 61, "trauma", surface="incisal")
    assert _spaces(dental) == {}


def test_a_lost_permanent_tooth_does_not(dental):
    """Nothing is coming to replace it, which is why losing one matters more —
    and why a space maintainer is not the answer to it.

    Tested on 35, not on 36. A permanent molar is at a position no primary
    tooth occupies, so it is refused by the position rule whether or not
    anything checks the dentition — and a test using one passed with the
    primary check deleted outright. 35 is a premolar: same quadrant shape,
    same position number as the baby molar it replaced, and the only thing
    telling them apart is which dentition it belongs to.
    """
    _find(dental, 35, "extracted")
    _find(dental, 36, "extracted")
    assert _spaces(dental) == {}


def test_a_missing_tooth_counts_the_same_as_an_extracted_one(dental):
    """The space does not care who took the tooth out, or whether anybody
    did — a child arriving with the gap already there has the same gap."""
    _find(dental, 85, "missing")
    assert 85 in _spaces(dental)


# ------------------------------------------------------- when it is settled --
def test_a_fitted_maintainer_settles_it(dental):
    """The whole point of being able to record one."""
    _find(dental, 75, "extracted")
    _find(dental, 75, "space_maintainer", day=(2026, 8, 10))
    assert _spaces(dental) == {}


def test_a_successor_on_its_way_settles_it_too(dental):
    """The other answer, and the one nobody has to pay for. If 35 is already
    coming through, the space is being taken rather than lost."""
    _find(dental, 75, "extracted")
    _find(dental, 35, "erupting")
    assert _spaces(dental) == {}


def test_a_successor_still_under_the_gum_does_not(dental):
    """This is the case the whole thing exists for: the tooth is there, it is
    just not ready, and the months in between are when the space closes."""
    _find(dental, 75, "extracted")
    _find(dental, 35, "unerupted")
    assert 75 in _spaces(dental)


def test_a_healthy_baby_molar_is_not_a_space(dental):
    _find(dental, 75, "sound")
    assert _spaces(dental) == {}


# --------------------------------------------------- it never says what to do
def test_it_does_not_prescribe_the_appliance(dental, boss):
    """The line this must not cross, tested on the page a dentist reads.

    Whether a maintainer goes in is an X-ray and a judgement. The chart says a
    space is open and unaccounted for, and stops — the same line already drawn
    for caries, which can be a filling, a pulpotomy or an extraction.
    """
    _find(dental, 75, "extracted")
    page = boss.get(
        f"/dentistry/patient/{dental['ids']['child']}").get_data(as_text=True)
    for prescribing in ("ركّب حافظ", "Fit a space", "يجب تركيب"):
        assert prescribing not in page


# ------------------------------------------------------------ on the chart --
def test_the_chart_says_the_space_is_open(dental, boss):
    """A finding nobody is shown is a finding nobody acts on."""
    _find(dental, 75, "extracted")
    page = boss.get(
        f"/dentistry/patient/{dental['ids']['child']}").get_data(as_text=True)
    assert "space-open" in page


def test_the_chart_says_when_one_is_fitted(dental, boss):
    """So the next dentist can see it is being held, and by what."""
    _find(dental, 75, "extracted")
    _find(dental, 75, "space_maintainer", day=(2026, 8, 10))
    page = boss.get(
        f"/dentistry/patient/{dental['ids']['child']}").get_data(as_text=True)
    assert "space-open" not in page
    assert "حافظ مسافة" in page


def test_a_maintainer_can_be_recorded_through_the_screen(dental, boss):
    """Through the form, not the model — the condition being in a list is not
    the same as a dentist being able to choose it."""
    from app.models import ToothFinding

    boss.post(f"/dentistry/patient/{dental['ids']['child']}/record",
              data={"tooth": "75", "surface": "whole",
                    "condition": "space_maintainer",
                    "found_on": "2026-08-10"}, follow_redirects=True)
    with dental["app"].app_context():
        row = ToothFinding.query.filter_by(tooth=75).first()
        assert row is not None
        assert row.condition == "space_maintainer"


def test_it_is_a_whole_tooth_finding(dental):
    """A space maintainer is not fitted to the cheek side of a gap."""
    from app.models.dental import WHOLE_TOOTH_CONDITIONS

    assert "space_maintainer" in WHOLE_TOOTH_CONDITIONS


def test_the_tooth_is_still_gone_after_a_maintainer_goes_in(dental, boss):
    """Two facts about one position, and the chart has to hold both.

    A space maintainer is fitted where a tooth **is not**. Filed as another
    whole-tooth finding it would be the latest one on that position and would
    replace the extraction — so a tooth that is gone, and is being held open
    precisely because it is gone, would read as neither extracted nor missing.
    The one that lost would be the one that matters.
    """
    from app.models.dental import chart_for

    _find(dental, 75, "extracted")
    _find(dental, 75, "space_maintainer", day=(2026, 8, 10))
    with dental["app"].app_context():
        found = chart_for(dental["ids"]["child"])[75]
    conditions = {row.condition for row in found.values()}
    assert conditions == {"extracted", "space_maintainer"}

    page = boss.get(
        f"/dentistry/patient/{dental['ids']['child']}").get_data(as_text=True)
    assert "حافظ مسافة" in page
