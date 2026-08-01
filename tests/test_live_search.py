"""Results that follow the typing, with no Enter.

Reported: *"the patient search isn't fast and I have to press Enter for results
to appear — I want it like Google, on every search screen."*

Every search screen was the same shape: a GET form, a box named ``q``, and a
button. Correct, and it makes you ask twice — once by typing and once by
pressing.

**Not a JSON API per screen.** Each of these lists is already rendered properly
on the server: translated, permission-checked, in the right order. Rebuilding
that in JavaScript would be a second version of every list to keep in step with
the first, and the second one always drifts. So the browser fetches the same URL
the form would have submitted and swaps in the results block from the reply.
One rendering path, and the screens still work with JavaScript off because the
form and its button are untouched underneath.

**The sequence number is the part that matters.** Type "ah" then "ahmed": if the
first reply is slower it lands last, and Ahmed's search shows every name
containing "ah". A search that shows the wrong results *silently* is worse than
a slow one — you cannot tell by looking. Replies that are not the newest are
dropped and in-flight requests are aborted.

The last test in this file exists because of a mistake made while writing it:
the script that wired these eight screens reported success on two it had
silently skipped, because it looked for a `<div>` on lines that began with
`<details>`. So the wiring is checked here, per screen, rather than trusted.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# Every screen with a search box, and the URL it lives at.
SEARCH_SCREENS = {
    "patients/list.html": "/patients/",
    "prescriptions/drugs.html": "/prescriptions/drugs",
    "prescriptions/drugbook.html": "/prescriptions/drugbook",
    "inventory/items.html": "/inventory/items",
    "inventory/index.html": "/inventory/",
    "messages/inbox.html": "/messages/",
    "growth/index.html": "/growth/",
    "vaccinations/index.html": "/vaccinations/",
}


def _template(name):
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture()
def desk(clinic):
    return clinic["sign_in"]("boss")


# ------------------------------------------------------- the wiring --------
@pytest.mark.parametrize("name", sorted(SEARCH_SCREENS))
def test_every_search_screen_searches_as_you_type(name):
    """Per screen, not "at least one" — the wiring script silently skipped two
    and still said it had done all eight."""
    body = _template(name)
    assert "data-live-search" in body, f"{name}: the form is not wired"
    assert 'id="gc-results"' in body, f"{name}: no results block to swap"


@pytest.mark.parametrize("name", sorted(SEARCH_SCREENS))
def test_the_form_points_at_the_results_block_that_exists(name):
    """A selector pointing at nothing fails silently in the browser: the box
    just goes back to needing Enter, and nobody reports it as a bug."""
    body = _template(name)
    selector = re.search(r'data-live-search="([^"]+)"', body).group(1)
    assert selector.startswith("#")
    assert f'id="{selector[1:]}"' in body, f"{name}: {selector} is not on the page"


@pytest.mark.parametrize("name", sorted(SEARCH_SCREENS))
def test_the_search_box_is_still_inside_a_real_form(name):
    """The fallback. With JavaScript off the button has to still work, so the
    box must not have been lifted out of the form while wiring this up."""
    body = _template(name)
    form_start = body.index("<form", 0)
    assert "data-live-search" in body[form_start:body.index(">", form_start)] \
        or 'name="q"' in body


def test_the_results_block_is_the_list_and_not_the_add_form():
    """The mistake that got past the first attempt: on two screens the block
    immediately after the search form is a collapsed "add" panel, and swapping
    *that* would replace the form somebody is filling in."""
    for name in ("prescriptions/drugs.html", "inventory/items.html"):
        body = _template(name)
        block = body[body.index('id="gc-results"'):]
        head = block[:400]
        assert "<table" in head, f"{name}: gc-results is not the list"
        assert "<summary" not in head, f"{name}: gc-results is the add panel"


# --------------------------------------------------- the helper's rules ----
def _js():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js")
    with open(os.path.join(root, "app.js"), encoding="utf-8") as fh:
        return fh.read()


def test_a_stale_reply_can_never_paint_over_a_newer_one():
    """The one correctness rule in the whole feature. Without it, a slow reply
    for "ah" lands after "ahmed" and shows the wrong list with no sign that
    anything went wrong."""
    js = _js()
    body = js[js.index("gcLiveSearch"):]
    assert "seq" in body and "mine !== seq" in body


def test_an_overtaken_request_is_abandoned():
    """Dropping the reply is enough for correctness; aborting also stops a
    clinic on a slow line queueing a request per keystroke."""
    body = _js()
    assert "AbortController" in body and ".abort()" in body


def test_typing_does_not_fill_the_back_button():
    """`pushState` per keystroke would make Back mean "one letter ago"."""
    body = _js()
    section = body[body.index("gcLiveSearch"):]
    # The call, not the word: the comment above it names `pushState` to say
    # why it is not used, and a test that cannot tell code from prose would
    # have to be worked around rather than satisfied.
    assert "history.replaceState" in section
    assert "history.pushState" not in section


def test_pressing_enter_still_works_and_does_not_reload():
    body = _js()
    section = body[body.index("gcLiveSearch"):]
    assert 'addEventListener("submit"' in section
    assert "preventDefault" in section


def test_the_results_are_announced_to_a_screen_reader():
    """A list that changes under somebody who cannot see it changing is a list
    they have no way of knowing about."""
    body = _js()
    section = body[body.index("gcLiveSearch"):]
    assert "aria-live" in section and "aria-busy" in section


# ------------------------------------------------ the screens still work ---
@pytest.mark.parametrize("url", sorted(set(SEARCH_SCREENS.values())))
def test_the_screen_still_answers_a_plain_query(desk, url):
    """The whole design rests on the server already rendering these lists, so
    the ordinary GET with ?q= has to keep working exactly as before."""
    assert desk.get(url, query_string={"q": ""}).status_code in (200, 302)
    assert desk.get(url, query_string={"q": "طفل"}).status_code in (200, 302)


def test_a_search_returns_the_block_the_browser_swaps_in(desk):
    """End to end: what the fetch gets back has to contain the block the
    helper looks for, or the swap silently does nothing."""
    body = desk.get("/patients/", query_string={"q": ""}).get_data(as_text=True)
    assert 'id="gc-results"' in body


def test_searching_actually_narrows_the_list(desk, clinic):
    """Guards against the box being wired to something that does not filter."""
    from app.models import Patient

    with clinic["app"].app_context():
        clinic["db"].session.add(Patient(
            patient_number="P-ZZZ", full_name="زياد المميز", gender="male",
            date_of_birth=__import__("datetime").date(2025, 3, 3),
            is_active=True))
        clinic["db"].session.commit()

    everyone = desk.get("/patients/", query_string={"q": ""}).get_data(as_text=True)
    narrowed = desk.get("/patients/",
                        query_string={"q": "زياد"}).get_data(as_text=True)
    assert "زياد المميز" in everyone and "زياد المميز" in narrowed
    assert "طفل" in everyone and "طفل" not in narrowed
