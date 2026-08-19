"""The message for a vaccine nobody promised — asked as a question.

Two sentences that must never become one.

``vaccine_due`` chases a dose this clinic committed to: somebody started the
course or agreed a plan, the date passed, and the message says so. It is a
reminder about a promise.

``vaccine_suggested`` is about a vaccine the child is merely old enough for.
Nobody here undertook anything, most of the optional schedule is not on the
national programme, and the family may well be getting it somewhere else.
Sent in the same words as the first, it reads as a bill for something never
ordered — and the clinic that sends it is the one families stop reading.

So it says what changed (an age), what the vaccine is for (the catalogue's own
line, not the clinic's opinion of it), that it is optional and not government,
and that the door is open. It asks; it does not chase.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_it_is_a_type_of_its_own(clinic):
    from app.models.message import SYSTEM_TEMPLATE_TYPES

    assert "vaccine_suggested" in SYSTEM_TEMPLATE_TYPES


def test_it_is_not_the_chasing_message(clinic):
    """The distinction the whole file is about."""
    from app.models.message import TEMPLATE_DEFAULTS

    assert (TEMPLATE_DEFAULTS["vaccine_suggested"]
            != TEMPLATE_DEFAULTS["vaccine_due"])


def test_it_asks_rather_than_demands(clinic):
    """No due date, no booking instruction, nothing owed."""
    body = None
    from app.models.message import TEMPLATE_DEFAULTS

    body = TEMPLATE_DEFAULTS["vaccine_suggested"]

    for owed in ("مستحق", "متأخر", "{due_date}", "برجاء الحجز"):
        assert owed not in body, f"the suggestion reads as a demand: {owed}"


def test_it_says_the_thing_the_family_does_not_know(clinic):
    """An age, and what the vaccine is for. Without those it is an advert."""
    from app.models.message import TEMPLATE_DEFAULTS, TEMPLATE_VARIABLES

    body = TEMPLATE_DEFAULTS["vaccine_suggested"]

    assert "{vaccine}" in body and "{patient}" in body
    assert "{about}" in body, "the message never says what the vaccine is for"
    assert "age" in TEMPLATE_VARIABLES["vaccine_suggested"]


def test_it_says_it_is_optional_and_not_the_government_schedule(clinic):
    """The sentence that stops a parent thinking they are in trouble."""
    from app.models.message import TEMPLATE_DEFAULTS

    body = TEMPLATE_DEFAULTS["vaccine_suggested"]

    assert "اختياري" in body
    assert "الحكومي" in body or "الجدول" in body


def test_every_placeholder_it_uses_is_declared(clinic):
    """A body with an undeclared field renders as literal braces to a family."""
    import re

    from app.models.message import TEMPLATE_DEFAULTS, TEMPLATE_VARIABLES

    used = set(re.findall(r"\{(\w+)\}",
                          TEMPLATE_DEFAULTS["vaccine_suggested"]))
    declared = set(TEMPLATE_VARIABLES["vaccine_suggested"])

    assert used <= declared, f"undeclared fields: {sorted(used - declared)}"


def test_it_is_offered_on_the_templates_screen(clinic):
    """A template nobody can edit is one the clinic cannot make its own."""
    from app.models.message import OCCASION_TYPES

    assert "vaccine_suggested" in OCCASION_TYPES
