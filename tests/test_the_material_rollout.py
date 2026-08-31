"""Markup in a grammar whose stylesheet was never loaded.

The clinic is being moved onto one visual language, screen by screen — the
booking form first, then the visit record, the settings update panel, and the
till. The grammar is `md-section` / `md-section-head` / `md-step` and it lives
in `app/static/css/material.css`.

**The stylesheet is not global, and that is deliberate**: `.md` scopes it so a
screen opts in and nothing else on the way changes. Which means a screen can
be written entirely in the grammar and look like nothing at all — the classes
are inert without the link, and `--md-surface-1` is defined *on* `.md`, so
even the section backgrounds resolve to nothing outside it.

That is how the till screen shipped: three numbered sections, correct markup,
no stylesheet, no `.md` scope. The step number rendered as a bare digit
instead of a filled circle. The tests written with it asserted the markup was
present — which it was — and passed while the screen looked exactly as it had
before.

So this file asserts the wiring rather than the markup, and it asserts it on
the **rendered page**, because that is the only place the two have to meet.
"""
import pathlib
import re

import pytest

# The classes that do nothing without material.css.
GRAMMAR = re.compile(r'class="[^"]*\bmd-(section|section-head|step|sub|field|btn)\b')
STYLESHEET = "css/material.css"

_CLASS_ATTR = re.compile(r'class="([^"]*)"')


def opens_the_scope(text):
    """Whether anything carries the bare ``md`` class.

    Checked by splitting the attribute into tokens rather than with a word
    boundary. ``\bmd\b`` matches the ``md`` inside ``md-section`` — a hyphen
    is a word boundary — so the obvious regex is true of every file that
    merely uses the grammar, and the check it was supposed to perform never
    happened. Mutation testing walked straight through it.
    """
    return any("md" in value.split() for value in _CLASS_ATTR.findall(text))


TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "app" / "templates"


def _templates_using_the_grammar():
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        if GRAMMAR.search(text):
            yield path.relative_to(TEMPLATES), text


def test_every_screen_written_in_the_grammar_loads_it():
    """The static half: a template using the classes must link the file.

    Cheap, total, and it catches the mistake at the moment somebody makes it
    rather than when a person opens the screen and says it looks wrong.
    """
    unwired = [str(name) for name, text in _templates_using_the_grammar()
               if STYLESHEET not in text]
    assert unwired == [], (
        "these use the Material grammar without loading material.css, "
        f"so none of it applies: {unwired}")


def test_every_screen_written_in_the_grammar_opens_the_scope():
    """The second half, and the one that is easy to miss.

    Linking the stylesheet is not enough: the tokens the sections are built
    from — surface tint, elevation, shape — are declared **on `.md`**. A page
    with the link but no `.md` ancestor gets sections with no background and
    no shadow, which reads as a styling bug rather than a missing class.
    """
    scopeless = [str(name) for name, text in _templates_using_the_grammar()
                 if not opens_the_scope(text)]
    assert scopeless == [], (
        "these carry Material markup with no `.md` scope, so the tokens it "
        f"is built from are undefined: {scopeless}")


def test_the_rollout_has_actually_reached_somewhere():
    """A guard over an empty set passes for ever. If this ever finds nothing,
    the pattern above has stopped matching and both tests above are green
    because they are asking about nothing."""
    assert len(list(_templates_using_the_grammar())) >= 4


# ------------------------------------------------- and on the real pages ---
@pytest.fixture
def booked(clinic):
    from datetime import time

    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        appointment = Appointment(
            patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
            appt_date=local_today(), appt_time=time(10, 0),
            appt_type="new", status="scheduled")
        clinic["db"].session.add(appointment)
        clinic["db"].session.commit()
        clinic["ids"]["appt"] = appointment.id
    return clinic


@pytest.mark.parametrize("screen", ["till", "booking"])
def test_the_page_a_person_opens_carries_the_stylesheet(booked, screen):
    """Rendered, not read off disk.

    A template can link the file and still not deliver it — a `{% block head %}`
    the parent does not render, a base template that dropped the block. The
    only proof is the bytes the browser receives.
    """
    desk = booked["sign_in"]("desk")
    url = (f"/finance/checkout/{booked['ids']['appt']}" if screen == "till"
           else "/appointments/new")
    page = desk.get(url)
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "md-step" in body, f"the {screen} screen lost its Material markup"
    assert STYLESHEET in body, f"the {screen} screen does not deliver material.css"
    assert opens_the_scope(body), \
        f"the {screen} screen has no `.md` scope, so the tokens are undefined"
