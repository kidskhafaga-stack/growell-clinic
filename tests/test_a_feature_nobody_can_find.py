"""A switch that is off, and a screen that never mentions it exists.

Reported by the person who paid for the feature: *"انا مش لاقي اقتراح التشخيص
فى الزيارة بالذكاء الصناعي"*. Nothing was broken. The suggestion button has two
gates — a configured AI provider, and a switch that is deliberately off until a
clinic turns it on — and when either was shut the visit screen showed **nothing
at all**: no button, no note, no hint that there was anything to look for.

The reasoning for that silence was written down and was half right: *"there is
nothing a doctor mid-consultation could do about either"*. True of a doctor.
False of the person who owns the clinic, who is the one who goes looking for a
feature they asked for — and who can open Settings → AI and fix it in ten
seconds if anything tells them to.

So the silence is kept for the audience it was meant for and lifted for the
audience it was hurting. And the note says **which** of the two gates is shut,
because "not configured" is the clinic's IT and "switched off" is the clinic's
policy, and sending somebody to the wrong one wastes the trip.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The button's own markup, not the CSS rule or the function definition that
# carry the same words further down the same file. Three separate tests in this
# suite have been fooled by matching a class name that also appears in a
# `<style>` block, so this one matches the opening tag exactly.
BUTTON = '<div class="dx-ai__head">'

# The note carries which gate is shut as an attribute, so a test can name the
# state instead of fishing for a phrase. Written after a mutation slipped
# through: collapsing both messages into one still passed, because the word
# "provider" appears elsewhere on the visit screen — in the sentence about
# where the AI summary is sent.
SWITCH_OFF = 'data-dx-off="switch"'
NO_PROVIDER = 'data-dx-off="provider"'


def _visit(kit, who="boss"):
    return kit["sign_in"](who).get(
        f"/visits/{kit['ids']['visit']}/record").get_data(as_text=True)


def _configure_provider(kit):
    from app.models import Setting

    with kit["app"].app_context():
        Setting.set("ai_enabled", "1")
        Setting.set("ai_provider", "gemini")
        Setting.set("ai_base_url", "https://example.invalid")
        Setting.set("ai_model", "gemini-2.0-flash")
        Setting.set("ai_api_key", "k")
        kit["db"].session.commit()


def _switch_on(kit):
    from app.models import Setting

    with kit["app"].app_context():
        Setting.set("ai_dx_suggest", "1")
        kit["db"].session.commit()


# ------------------------------------------------------ nothing is broken ---

def test_with_both_gates_open_the_button_is_there(clinic):
    """First, the thing that was never wrong. The report was that the feature
    was missing; it was not, and saying so is part of the answer."""
    _configure_provider(clinic)
    _switch_on(clinic)

    assert BUTTON in _visit(clinic)


# ---------------------------------------------------- and now it says so ----

def test_an_owner_is_told_the_switch_is_off(clinic):
    """The bug. A clinic with AI configured and the suggestion switched off
    used to see an empty space where the feature was."""
    _configure_provider(clinic)

    page = _visit(clinic)

    assert BUTTON not in page, "the button is showing with the switch off"
    assert SWITCH_OFF in page, "nothing on the screen says the feature exists"
    assert "?tab=ai" in page, "the note does not lead anywhere"


def test_and_told_when_it_is_the_provider_that_is_missing(clinic):
    """The other gate, and a different errand: no provider is the clinic's IT,
    a switch left off is the clinic's policy. Sending somebody to the wrong
    one wastes the trip."""
    _switch_on(clinic)

    page = _visit(clinic)

    assert BUTTON not in page
    assert NO_PROVIDER in page, \
        "the note does not say the provider is what is missing"
    assert SWITCH_OFF not in page, \
        "it says the switch is off, and the switch is on"


def test_the_two_notes_are_not_the_same_sentence(clinic):
    """Guarding the guard: one message for both states would pass the two
    tests above while telling half the clinics to do the wrong thing — and it
    did, until this test stopped fishing for a word and read the state off the
    note itself."""
    _configure_provider(clinic)
    with_provider = _visit(clinic)

    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("ai_enabled", "0")
        Setting.set("ai_dx_suggest", "1")
        clinic["db"].session.commit()
    without_provider = _visit(clinic)

    assert SWITCH_OFF in with_provider and NO_PROVIDER not in with_provider
    assert NO_PROVIDER in without_provider and SWITCH_OFF not in without_provider

    def sentence(page, marker):
        start = page.index(marker)
        return page[start:page.index("</p>", start)]

    assert sentence(with_provider, SWITCH_OFF) != \
        sentence(without_provider, NO_PROVIDER), \
        "the same sentence is shown whichever gate is shut"


# ------------------------------------------- and still nothing to a doctor ---

@pytest.mark.parametrize("who", ["doc", "desk"])
def test_a_doctor_mid_consultation_is_not_told_to_go_and_fix_settings(clinic, who):
    """The original reasoning, kept. A note about a screen they cannot open is
    an interruption in the middle of seeing a child, and it is not theirs to
    act on."""
    _configure_provider(clinic)

    page = _visit(clinic, who)

    assert BUTTON not in page
    assert "?tab=ai" not in page, \
        f"{who} is being sent to a settings screen they cannot open"


def test_nobody_is_told_anything_when_it_is_all_working(clinic):
    """A note that stays up after the thing is fixed is noise, and noise is
    how the next real note gets ignored."""
    _configure_provider(clinic)
    _switch_on(clinic)

    page = _visit(clinic)

    assert BUTTON in page
    assert "?tab=ai" not in page, "the note is still up with the feature on"
