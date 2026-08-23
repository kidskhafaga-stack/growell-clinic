"""A second opinion that knows it is a second opinion.

Asked for after the difference was spelled out: *"اعمله وضع مناقشة منفصل —
تشخيص تفريقي وخطة علاج."*

**Separate, and that is the whole design.** The assistant that already reads a
child's file is locked to the record — *never estimate, infer or fill in a
date, a dose or a diagnosis that is not written here* — because its job is
letters and summaries, and a rounded date in a letter reads as competence. A
differential asks the model to go beyond the record on purpose. Those two
instructions cannot share a prompt, so they do not share a route, a switch or
a card.

The tests below are mostly about what this mode is **not** allowed to become:

* it cannot be reached by turning on the other one;
* it never gives a dose, because there is already a dose tool with its own
  conservatism and two roads to one number is how a nurse ends up reading the
  wrong one;
* it sends exactly what the letter writer sends and not a word more, because
  "what did we send about this child" has to have one answer;
* and the screen says it is a suggestion, rather than trusting the model to
  have said so.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_with_child(clinic):
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        kid = Patient(patient_number="DX-1", full_name="طفل المناقشة",
                      gender="male", date_of_birth=date(2022, 5, 1),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()
        clinic["kid_id"] = kid.id
    return clinic


def _switch(clinic, **flags):
    from app.extensions import db
    from app.models import Setting

    with clinic["app"].app_context():
        for key, on in flags.items():
            Setting.set(key, "1" if on else "0")
        db.session.commit()


def _url(clinic):
    return f"/ai/patient/{clinic['kid_id']}/discuss"


# ------------------------------------------------------------ the two switches

def test_it_is_off_until_a_clinic_says_otherwise(clinic_with_child):
    """A suggestion about what a child might have is not a feature to arrive
    switched on."""
    from app.utils.ai import discussion_enabled

    with clinic_with_child["app"].app_context():
        assert discussion_enabled() is False


def test_turning_on_the_letter_writer_does_not_turn_this_on(clinic_with_child):
    """The failure this switch exists to prevent.

    A clinic enables patient context because it wants "when did he last come"
    answered and a school letter drafted. Acquiring a differential engine as a
    side effect of that is not a decision anybody made.
    """
    _switch(clinic_with_child, ai_patient_context=True, ai_discussion=False)

    reply = clinic_with_child["sign_in"]("boss").post(
        _url(clinic_with_child), json={"messages": [{"role": "user",
                                                     "content": "رأيك إيه؟"}]})

    assert reply.status_code == 403
    assert reply.get_json()["error"] == "discussion_disabled"


def test_and_it_cannot_be_reached_with_patient_context_off(clinic_with_child):
    """The record still leaves the building here. The other switch governs
    that and still does — this mode is an addition on top of it, not a way
    round it."""
    _switch(clinic_with_child, ai_patient_context=False, ai_discussion=True)

    reply = clinic_with_child["sign_in"]("boss").post(
        _url(clinic_with_child), json={"messages": [{"role": "user",
                                                     "content": "رأيك إيه؟"}]})

    assert reply.status_code == 403
    assert reply.get_json()["error"] == "patient_context_disabled"


def test_the_refusal_names_the_right_switch(clinic_with_child):
    """Two switches, two sentences. Pointing somebody at the wrong one costs
    them a settings screen and a guess."""
    from app.utils.ai import error_sentence

    with clinic_with_child["app"].app_context():
        off = error_sentence("discussion_disabled")
        other = error_sentence("patient_context_disabled")

    assert off and off != other, \
        "the two switches share one message, so neither says which to look for"
    assert "ai.err" not in off, "the sentence is a translation key, not a sentence"


def test_a_stranger_cannot_discuss_a_case(clinic_with_child):
    _switch(clinic_with_child, ai_patient_context=True, ai_discussion=True)

    reply = clinic_with_child["app"].test_client().post(
        _url(clinic_with_child), json={"messages": [{"role": "user", "content": "x"}]})

    assert reply.status_code in (301, 302, 401, 403)


# ------------------------------------------------------- what the prompt says

def test_the_prompt_forbids_a_dose():
    """There is already a dose tool, with its own prompt and its own "the
    treating doctor verifies". A second, less careful road to the same number
    is how a program ends up with two answers to "how much"."""
    from app.utils.ai_discuss import SYSTEM

    lowered = SYSTEM.lower()
    assert "no doses" in lowered, "the prohibition is not stated as a rule"
    assert "never state a dose" in lowered
    assert "frequency" in lowered and "duration" in lowered, \
        "a dose has more than one number and only one of them is forbidden"


def test_the_prompt_asks_for_the_dangerous_answers_first():
    """For a paediatric clinic the most useful thing a second opinion can say
    is what must not be missed, and a list that opens with the most likely
    diagnosis buries it under the reassuring one."""
    from app.utils.ai_discuss import SYSTEM

    must_not_miss = SYSTEM.index("MUST NOT MISS")
    differential = SYSTEM.index("DIFFERENTIAL")

    assert must_not_miss < differential, \
        "the reassuring answer is being asked for before the dangerous one"


def test_the_prompt_asks_what_the_record_is_missing():
    """The heading that makes this worth having. "I would need to know whether
    he has been vomiting" is a question a doctor can act on; a differential
    built silently on its absence is not."""
    from app.utils.ai_discuss import SYSTEM

    assert "WHAT THE RECORD DOES NOT SAY" in SYSTEM


def test_reasoning_past_the_record_is_allowed_but_inventing_it_is_not():
    """The line this mode lives on. It may reason outward from the file —
    that is the feature — and may not assert a fact about this child that the
    file does not hold."""
    from app.utils.ai_discuss import SYSTEM

    lowered = SYSTEM.lower()
    assert "do not invent the record" in lowered
    assert "you may reason beyond what is written" in lowered


def test_it_does_not_borrow_the_letter_writers_prohibition():
    """The two prompts have to differ, and in this direction.

    `ai_lookup.SYSTEM` says answer only from the record. Copying that here
    would produce a differential-shaped screen that refuses to give one, which
    is worse than not having the screen: it looks like a broken feature rather
    than a deliberate limit.
    """
    from app.utils import ai_discuss, ai_lookup

    assert ai_discuss.SYSTEM != ai_lookup.SYSTEM
    assert "Answer only from it" not in ai_discuss.SYSTEM


# --------------------------------------------- and it sends no more than before

def test_it_sends_exactly_what_the_letter_writer_sends(clinic_with_child):
    """One function assembles what leaves the clinic about a child, so "what
    did we send?" has one answer. A mode that quietly sent a richer summary
    would be a privacy decision made by whoever wrote the prompt."""
    from app.utils import ai_discuss, ai_lookup

    with clinic_with_child["app"].app_context():
        from app.extensions import db
        from app.models import Patient

        kid = db.session.get(Patient, clinic_with_child["kid_id"])
        mine = ai_discuss.brief(kid, "ar", anonymize=True)
        theirs = ai_lookup.fact_sheet(ai_lookup.facts(kid, "ar"), anonymize=True)

    assert mine == theirs, \
        "the discussion mode assembled its own, larger view of the child"


def test_the_name_is_still_removed_when_the_clinic_asked_for_that(
        clinic_with_child):
    from app.utils import ai_discuss

    with clinic_with_child["app"].app_context():
        from app.extensions import db
        from app.models import Patient

        kid = db.session.get(Patient, clinic_with_child["kid_id"])
        brief = ai_discuss.brief(kid, "ar", anonymize=True)

    assert "طفل المناقشة" not in brief, "the child's name went out anyway"
    assert "DX-1" not in brief, "the file number went out anyway"
    assert "anonymised" in brief


# ------------------------------------------------------------- and the screen

def test_the_card_appears_only_with_both_switches_on(clinic_with_child):
    from app.utils import ai as ai_utils

    client = clinic_with_child["sign_in"]("boss")
    page_url = f"/patients/{clinic_with_child['kid_id']}"

    _switch(clinic_with_child, ai_patient_context=True, ai_discussion=False)
    assert "/discuss" not in client.get(page_url).get_data(as_text=True), \
        "the discussion card is on the page with its switch off"

    # And with both on it appears — but only once the assistant is configured
    # at all, which is the same gate the existing card sits behind.
    _switch(clinic_with_child, ai_patient_context=True, ai_discussion=True)
    with clinic_with_child["app"].app_context():
        configured = ai_utils.is_ready()
    body = client.get(page_url).get_data(as_text=True)
    assert ("/discuss" in body) == configured, \
        ("the card ignores whether a provider is configured — it would offer a "
         "chat box with nothing behind it")


def test_the_screen_says_it_is_a_suggestion_without_asking_the_model(
        clinic_with_child):
    """The disclaimer is rendered by the page, not requested from the provider.

    A warning that only appears when the model remembers to write one is a
    warning that is missing on exactly the reply somebody acts on.
    """
    import json

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        words = json.load(fh)["ai"]

    assert words["discuss_disclaimer"], "there is no disclaimer to render"
    with open("app/templates/patients/profile.html", encoding="utf-8") as fh:
        page = fh.read()
    assert "ai.discuss_disclaimer" in page, \
        "the disclaimer exists and the card does not render it"


def test_both_languages_can_say_all_of_it(clinic_with_child):
    """A clinic on the English UI must not meet an Arabic-only warning, or an
    untranslated key where one should be."""
    import json

    keys = ("discuss_title", "discuss_placeholder", "discuss_disclaimer",
            "err_discussion_off")
    for lang in ("ar", "en"):
        with open(f"app/i18n/locales/{lang}.json", encoding="utf-8") as fh:
            words = json.load(fh)["ai"]
        missing = [k for k in keys if not words.get(k)]
        assert not missing, f"{lang} is missing {missing}"
