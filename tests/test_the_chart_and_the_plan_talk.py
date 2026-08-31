"""The chart and the plan knew about the same tooth and never mentioned it.

A dentist looked at 55, wrote *caries, occlusal* on the chart, and then went
to the treatment plan and typed the tooth number again from memory. Two
screens holding one fact, joined by a person retyping it — which is how a plan
comes to say 54 about a tooth the chart says nothing about, and how nobody can
answer "is everything I found actually on a plan?" without reading both and
comparing.

**The fact travels; the treatment does not.** The chart can hand a tooth and
a face to the plan. It does not name a procedure, and the code that decides
which teeth are outstanding says so in as many words: caries can be a filling,
a pulpotomy or an extraction depending on how deep it has gone and how long
the tooth has left, and that is a judgement made in front of the child. A
program that read "caries" and wrote "filling" would be prescribing from a
keyword, and would be wrong on exactly the cases that matter most.

So the chart marks what is outstanding, offers it, and stops.
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


def _find(clinic, tooth, condition, surface="occlusal"):
    from app.models import ToothFinding

    with clinic["app"].app_context():
        clinic["db"].session.add(ToothFinding(
            patient_id=clinic["ids"]["child"], tooth=tooth, surface=surface,
            condition=condition, found_on=date(2026, 8, 1)))
        clinic["db"].session.commit()


def _draft(clinic):
    from app.models import TreatmentPlan

    with clinic["app"].app_context():
        plan = TreatmentPlan(patient_id=clinic["ids"]["child"], title="خطة")
        clinic["db"].session.add(plan)
        clinic["db"].session.commit()
        return plan.id


def _chart_page(clinic, boss):
    return boss.get(
        f"/dentistry/patient/{clinic['ids']['child']}").get_data(as_text=True)


# ------------------------------------------------- what counts as outstanding
def test_a_decayed_tooth_is_outstanding(dental):
    from app.models.dental import chart_for, outstanding

    _find(dental, 55, "caries")
    with dental["app"].app_context():
        assert 55 in outstanding(chart_for(dental["ids"]["child"]))


def test_a_tooth_that_was_treated_is_not(dental):
    """The chart holds the latest per surface, so a surface that was decayed
    and is now filled has been dealt with. Reading the history instead would
    keep every treated tooth outstanding for ever."""
    from app.models.dental import chart_for, outstanding

    _find(dental, 55, "caries")
    _find(dental, 55, "filled")
    with dental["app"].app_context():
        assert 55 not in outstanding(chart_for(dental["ids"]["child"]))


def test_a_healthy_tooth_is_not_outstanding(dental):
    """"Sound" means somebody looked and found nothing — a fact worth
    recording and not a job."""
    from app.models.dental import chart_for, outstanding

    _find(dental, 55, "sound")
    with dental["app"].app_context():
        assert outstanding(chart_for(dental["ids"]["child"])) == {}


def test_it_never_says_what_to_do(dental, boss):
    """The line this must not cross, tested on what actually arrives.

    A tooth handed from the chart to the plan brings its number and its face
    and **no procedure and no price**: caries is a filling, a pulpotomy or an
    extraction depending on how deep it has gone and how long the tooth has
    left, and a program answering that from a keyword would be prescribing.

    Asserted on the form the dentist is given, because that is where a
    helpful suggestion would appear if anybody ever added one.
    """
    plan_id = _draft(dental)
    _find(dental, 55, "caries")
    page = boss.get(
        f"/dentistry/plan/{plan_id}?tooth=55&surface=occlusal").get_data(
            as_text=True)

    form = page.split('name="description"')[1][:120]
    assert "value=" not in form, f"a procedure was suggested: {form!r}"
    price = page.split('name="price"')[1][:120]
    assert "value=" not in price, f"a price was suggested: {price!r}"


# ------------------------------------------------------------ the offer -----
def test_the_chart_offers_an_outstanding_tooth_to_the_draft(dental, boss):
    """The retyping this removes."""
    plan_id = _draft(dental)
    _find(dental, 55, "caries")
    page = _chart_page(dental, boss)
    # The whole link, not "55 appears somewhere" — the number is printed on
    # every tooth in the chart, so a looser search passes with no link at all.
    assert f"/dentistry/plan/{plan_id}?tooth=55&amp;surface=occlusal" in page


def test_it_offers_nothing_when_there_is_no_draft(dental, boss):
    """A button that opens a form is worse than no button, and one that
    silently starts a plan leaves drafts behind every time somebody clicks to
    see what it does."""
    _find(dental, 55, "caries")
    page = _chart_page(dental, boss)
    assert "tooth=55" not in page


def test_a_tooth_already_on_a_plan_is_not_offered_again(dental, boss):
    """It is marked instead, so a dentist can see at a glance what is
    accounted for rather than adding 55 twice."""
    from app.models import TreatmentPlanItem

    plan_id = _draft(dental)
    _find(dental, 55, "caries")
    with dental["app"].app_context():
        dental["db"].session.add(TreatmentPlanItem(
            plan_id=plan_id, tooth=55, description="حشو", price=300))
        dental["db"].session.commit()

    page = _chart_page(dental, boss)
    assert "tooth=55" not in page
    assert "في الخطة" in page


# ----------------------------------------------------- what arrives there ---
def test_the_plan_arrives_with_the_tooth_chosen(dental, boss):
    plan_id = _draft(dental)
    _find(dental, 55, "caries")
    page = boss.get(
        f"/dentistry/plan/{plan_id}?tooth=55&surface=occlusal").get_data(
            as_text=True)
    assert '<option value="55" selected>' in page


def test_the_plan_shows_what_the_chart_found(dental, boss):
    """So the dentist is not reading one screen and typing into another, and
    the plan line and the chart cannot quietly disagree about which tooth is
    being talked about."""
    plan_id = _draft(dental)
    _find(dental, 55, "caries")
    page = boss.get(f"/dentistry/plan/{plan_id}?tooth=55").get_data(as_text=True)
    assert "تسوس" in page


def test_the_plan_still_opens_with_no_tooth_named(dental, boss):
    """Most lines are added by hand, and a scale-and-polish has no tooth at
    all."""
    plan_id = _draft(dental)
    page = boss.get(f"/dentistry/plan/{plan_id}").get_data(as_text=True)
    assert "<option value=\"\">—</option>" in page


def test_a_tooth_that_does_not_exist_is_ignored(dental, boss):
    """The number arrives in an address anybody can edit.

    And the face goes with it. Carried separately, a surface would sit in the
    form with no tooth chosen and then submit against whichever tooth the
    dentist picks by hand — a fact half-carried, which is worse than one not
    carried at all. Mutation testing found this: dropping the tooth check
    alone changed nothing anybody could see, because 99 is not in the list of
    options either way.
    """
    plan_id = _draft(dental)
    page = boss.get(
        f"/dentistry/plan/{plan_id}?tooth=99&surface=occlusal").get_data(
            as_text=True)
    assert 'value="99" selected' not in page
    assert 'name="surface"' not in page


def test_a_face_the_tooth_does_not_have_is_ignored(dental, boss):
    """A lower incisor has no biting table. A surface arriving for one is a
    place that does not exist, and the chart already refuses to store it."""
    plan_id = _draft(dental)
    page = boss.get(
        f"/dentistry/plan/{plan_id}?tooth=31&surface=occlusal").get_data(
            as_text=True)
    assert '<option value="31" selected>' in page
    assert 'name="surface"' not in page
