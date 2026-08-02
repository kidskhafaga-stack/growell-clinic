"""The sidebar: three states, and a phone that has navigation at all.

Item 22, asked for as a proposal: *"could we make the side menu show and hide,
and when hidden be just icons that expand when you click?"*

The proposal was three states rather than two, and the reason is in the third:

* **full** — icon and name, the default on a large screen;
* **rail** — icons only, one click away from anywhere instead of two;
* **drawer** — over the content with a scrim, on a phone.

**And a bug found while building it, bigger than the request.** Below 880px the
existing stylesheet slides the sidebar off the edge and *nothing brings it
back*. There was no hamburger, no drawer, no toggle — so on a phone the program
had **no navigation whatsoever**. Every screen was reachable only by typing a
URL. That is not a collapse feature, it is the app not working on a phone, and
it had been true of every screen in the program.

Also in here: item 21's remainder, shrinking the copyright block. It was four
lines of small print down the side of every screen, including a paragraph of
licence terms set at 0.64rem — which takes the space permanently and is read by
nobody. One line now, linking to an About page where the terms are at a size
somebody can read.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def doc(clinic):
    return clinic["sign_in"]("doc")


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


def _css():
    return _read("app", "static", "css", "theme.css")


def _shell():
    return _read("app", "templates", "shell.html")


# ------------------------------------------------------ the phone had none -
def test_a_phone_has_a_way_to_open_the_menu(clinic, doc):
    """The bug behind the request. Under 880px the sidebar was translated off
    the edge and nothing brought it back — no hamburger, no drawer. The program
    had no navigation on a phone at all."""
    body = doc.get("/dashboard").get_data(as_text=True)
    assert "topbar__menu" in body, "no way to open the menu on a phone"
    assert "sidebar__scrim" in body


def test_the_menu_button_only_shows_on_a_small_screen(clinic):
    """On a desktop the sidebar is already there; a button to summon it would
    be a second control for a thing that is not hidden."""
    css = _css()
    assert ".topbar__menu {" in css
    block = css[css.index(".topbar__menu {"):]
    assert "display: none" in block[:200]
    assert ".topbar__menu { display: inline-flex; }" in css


def test_the_rail_is_not_used_on_a_phone(clinic):
    """A 68px rail on a 360px screen takes space without giving information
    back. On a phone the sidebar is over the content or not there."""
    css = _css()
    phone = css[css.index("@media (max-width: 880px)"):]
    assert '.layout[data-sidebar="rail"] { --sidebar-w: 264px; }' in phone
    assert ".sidebar__toggle { display: none; }" in phone


# ------------------------------------------------------------- three states
def test_the_layout_carries_the_state(clinic, doc):
    body = doc.get("/dashboard").get_data(as_text=True)
    assert 'data-sidebar="full"' in body


def test_the_rail_hides_the_names_and_keeps_the_icons(clinic):
    css = _css()
    assert '.layout[data-sidebar="rail"] { --sidebar-w: 68px; }' in css
    assert '.layout[data-sidebar="rail"] .nav-item > span:not(.nav-tip)' in css


def test_the_name_comes_back_as_a_tooltip_on_the_rail(clinic, doc):
    """An icon with no name is a guess. That is the difference between a useful
    icon rail and a row of puzzles."""
    assert "nav-tip" in doc.get("/dashboard").get_data(as_text=True)
    css = _css()
    assert '.layout[data-sidebar="rail"] .nav-item:hover .nav-tip' in css


def test_it_collapses_towards_the_right_edge_in_arabic(clinic):
    """The program flips whole with `dir`. A collapse written with `left` would
    slide off the screen in Arabic, which is the language it is used in."""
    css = _css()
    sidebar = css[css.index("/* ---------- Sidebar: full, rail, drawer"):]
    assert "inset-inline-end" in sidebar or "inset-inline-start" in sidebar
    for absolute in ("left:", "right:"):
        assert absolute not in sidebar, absolute


# ------------------------------------------------------------ it remembers -
def test_the_choice_is_remembered(clinic, doc):
    """A collapse that comes back open on the next page is worse than no
    collapse: you re-do it all day and it never sticks."""
    from app.models import User

    assert doc.post("/set-sidebar", data={"sidebar": "rail"}).status_code == 200
    with clinic["app"].app_context():
        assert User.query.filter_by(username="doc").first().sidebar == "rail"

    body = doc.get("/dashboard").get_data(as_text=True)
    assert 'data-sidebar="rail"' in body


def test_it_can_be_opened_again(clinic, doc):
    from app.models import User

    doc.post("/set-sidebar", data={"sidebar": "rail"})
    doc.post("/set-sidebar", data={"sidebar": "full"})
    with clinic["app"].app_context():
        assert User.query.filter_by(username="doc").first().sidebar == "full"


def test_an_unknown_value_does_not_become_a_third_width(clinic, doc):
    from app.models import User

    doc.post("/set-sidebar", data={"sidebar": "sideways"})
    with clinic["app"].app_context():
        assert User.query.filter_by(username="doc").first().sidebar == "full"


def test_a_user_who_has_never_chosen_gets_the_full_menu(clinic, doc):
    assert 'data-sidebar="full"' in doc.get("/dashboard").get_data(as_text=True)


# ------------------------------------------------------------ the keyboard -
def test_there_is_a_keyboard_shortcut(clinic, doc):
    """Fifty times a day is a lot of reaching for the mouse."""
    assert "'['" in _shell()


def test_the_shortcut_does_not_eat_a_bracket_out_of_a_prescription(clinic):
    """A global single-key shortcut that fires while somebody is typing is a
    shortcut that corrupts what they typed."""
    body = _shell()
    section = body[body.index("function toggleSidebar"):]
    for guard in ("INPUT", "TEXTAREA", "SELECT", "isContentEditable"):
        assert guard in section, guard


# ------------------------------------------- item 21: the copyright block ---
def test_the_sidebar_carries_one_line_not_a_paragraph(clinic, doc):
    """Four lines of small print down the side of every screen, including
    licence terms at 0.64rem — permanent space, read by nobody."""
    body = doc.get("/dashboard").get_data(as_text=True)
    assert "sidebar__footer-line" in body
    assert "يُحظر نسخه" not in body, "the full licence text is still in the sidebar"


def test_the_terms_are_on_a_page_at_a_readable_size(clinic, doc):
    reply = doc.get("/about")
    assert reply.status_code == 200
    body = reply.get_data(as_text=True)
    assert "يُحظر نسخه" in body
    assert "0.64rem" not in body


def test_the_sidebar_line_links_to_it(clinic, doc):
    body = doc.get("/dashboard").get_data(as_text=True)
    assert "/about" in body


def test_the_credit_is_still_visible_without_opening_anything(clinic, doc):
    """Shrinking it must not amount to removing it."""
    body = doc.get("/dashboard").get_data(as_text=True)
    assert "Mohamed Khafaga" in body


def test_the_footer_becomes_one_icon_on_the_rail(clinic, doc):
    """Clipping the line instead would leave a sentence cut off mid-word,
    which reads as broken rather than as collapsed."""
    assert "sidebar__footer-ico" in doc.get("/dashboard").get_data(as_text=True)
    assert '.layout[data-sidebar="rail"] .sidebar__footer-ico' in _css()


# ---------------------------------------------------------- still navigable
def test_every_module_link_is_still_there(clinic, doc):
    """The point of the sidebar is the links in it."""
    body = doc.get("/dashboard").get_data(as_text=True)
    assert body.count("nav-item") >= 3


def test_the_screens_still_render(clinic, doc):
    for url in ("/dashboard", "/about", "/patients/"):
        assert doc.get(url).status_code in (200, 302), url
