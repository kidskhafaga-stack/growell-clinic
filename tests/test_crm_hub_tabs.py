"""Six cards in one column, and no way to say which one you came for.

Measured before this change: the customer-service hub was 1912px tall, six
cards, 28 forms, 131 fields, and **zero** tabs — on a screen that also carries
the WhatsApp connection and every word the clinic sends out under its own
name. Everything else in the program that holds this much has a tab strip;
this was the screen that never got one.

The tabs themselves are the easy part. What is worth a test is the hash.

Nine routes in this blueprint redirect back here with a fragment — `#types`,
`#custom`, `#connection` — because saving a template has to return you to the
template you saved. A fragment names a **section**, and sections now live
inside tabs, so a fragment the tab strip does not recognise drops the user on
the first tab with their edit sitting on a panel they cannot see. That is not
a visible failure; it looks exactly like the save not having worked.

The settings screen had this precise bug — three redirects to `#icd11`, no tab
named that, and the block stayed hidden — and it was fixed there with an
`inside` map. So the map is the thing under test, and it is checked against
the redirects **as the blueprint actually writes them** rather than against a
list copied by hand, because a list copied by hand is what goes stale the next
time somebody adds a redirect.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HUB = os.path.join(ROOT, "app/templates/messages/occasions.html")
ROUTES = os.path.join(ROOT, "app/blueprints/messages/routes.py")


def _hub(clinic, who="boss"):
    """The screen as the browser receives it.

    Read rendered rather than off disk: the buttons are built in a Jinja loop,
    so the source says ``tab='{{ tid }}'`` and only the response says which
    tabs there really are. Checking the source would have been checking the
    loop, not the strip.
    """
    return clinic["sign_in"](who).get("/messages/occasions").data.decode()


def _inside_map(page):
    """The fragment → tab map, read out of the script the page carries.

    Anchored on the brace, not on the word: the first `inside:` in the
    response is `break-inside:avoid` in the print CSS, and searching for the
    bare word quietly returned an empty map — which would have made every
    assertion below vacuously true.
    """
    found = re.search(r"inside:\s*\{([^}]*)\}", page)
    assert found, "the hub carries no fragment→tab map at all"
    pairs = dict(re.findall(r"(\w+)\s*:\s*'([^']+)'", found.group(1)))
    assert pairs, "the fragment→tab map parsed as empty"
    return pairs


def _tab_names(page):
    """The tabs the strip actually renders."""
    return set(re.findall(r"x-on:click=\"tab='([^']+)'\"", page))


def _redirect_fragments():
    """Every fragment this blueprint sends somebody back to."""
    with open(ROUTES, encoding="utf-8") as fh:
        src = fh.read()
    return set(re.findall(r'url_for\("messages\.occasions"\)\s*\+\s*"#(\w+)"', src))


# --------------------------------------------------------------- the shape --

def test_the_hub_has_a_tab_strip(clinic):
    page = _hub(clinic)

    assert "crmTabs()" in page, "the hub still renders as one long column"
    assert len(_tab_names(page)) >= 3, f"only these tabs exist: {_tab_names(page)}"


def test_the_three_sections_each_have_a_tab(clinic):
    tabs = _tab_names(_hub(clinic))

    assert tabs >= {"types", "templates", "connection"}, \
        f"the strip is missing one of the three: {tabs}"


# ------------------------------------------------- the part that goes wrong --

def test_every_redirect_lands_on_a_tab_that_exists(clinic):
    """The bug this file exists for.

    Saving anything here returns to a fragment. If the strip cannot map that
    fragment to a tab, the save appears to have done nothing.
    """
    page = _hub(clinic)
    inside = _inside_map(page)
    tabs = _tab_names(page)

    for frag in _redirect_fragments():
        assert frag in inside, (
            f"routes redirect to #{frag} and the hub does not know that "
            f"fragment — the save lands on the default tab and the edit is "
            f"hidden. Known: {sorted(inside)}")
        assert inside[frag] in tabs, (
            f"#{frag} maps to tab '{inside[frag]}', which no button opens")


def test_the_blueprint_really_does_redirect_with_fragments(clinic):
    """A scanner that matched nothing would pass the test above forever."""
    assert len(_redirect_fragments()) >= 3, \
        f"the redirect scan found only {_redirect_fragments()} — the regex broke"


def test_the_hash_the_watcher_writes_is_one_the_map_knows(clinic):
    """The strip rewrites the hash to the *tab* name as you click around.

    So a reload — or a bookmark taken mid-session — comes back with a tab name
    in the hash rather than a section name, and has to resolve too.
    """
    page = _hub(clinic)
    inside = _inside_map(page)

    for tab in _tab_names(page):
        assert tab in inside, (
            f"clicking '{tab}' writes #{tab}, and reloading that lands on the "
            f"default tab instead")


# ------------------------------------------------------------ the removal ---

def test_birthdays_are_not_on_the_settings_screen_any_more(clinic):
    """They are the desk's work, and this screen is one reception cannot open.

    Asserted on the send links rather than the wording: the word "birthday"
    also names a *template type*, which legitimately stays here.
    """
    page = clinic["sign_in"]("boss").get("/messages/occasions").data.decode()

    assert "/messages/occasions/birthday/" not in page, \
        "the hub still lists birthdays to send, on a screen reception cannot open"


def test_the_desk_still_has_them(clinic):
    """The other half of the move — removing them from both would be a loss."""
    from datetime import date, timedelta

    from app.extensions import db
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        kid = Patient.query.first()
        soon = local_today() + timedelta(days=2)
        kid.date_of_birth = date(2024, soon.month, soon.day)
        # The send link is only offered for a child somebody can be reached
        # about, so this needs a number to assert the link at all.
        kid.own_phone = "01000000000"
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "/messages/occasions/birthday/" in page, \
        "birthdays were taken off the hub and are not on the desk either"


def test_the_route_no_longer_builds_a_list_nothing_shows(clinic):
    import inspect

    from app.blueprints.messages import routes

    source = inspect.getsource(routes.occasions)
    assert "_upcoming_birthdays" not in source, \
        "the hub still computes the birthday list it no longer renders"


# ---------------------------------------------------------- still reachable --

def test_reception_still_cannot_open_it(clinic):
    """Tabs are a layout change and must not have moved the lock."""
    assert clinic["sign_in"]("desk").get("/messages/occasions").status_code == 403


def test_the_manager_still_can(clinic):
    assert clinic["sign_in"]("boss").get("/messages/occasions").status_code == 200
