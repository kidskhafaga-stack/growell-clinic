"""The patient file, moved onto the clinic's visual language.

Third screen in the roll-out, after the booking form and the till. What
changes here is the treatment, not the shape: the file is still ten tabs and
they still hold what they held.

**It gets no step numbers, and that is a decision rather than an omission.**
The booking form and the till are tasks with an order — a slot cannot be
picked before a doctor and a date, a total cannot be read before the charges
are chosen — so numbering their sections says something true about the work.
A patient file is *read*. Somebody opens it at the tab they need: the mother
asks about the vaccination card, the doctor wants last visit's notes, the desk
wants the balance. Numbering the tabs would put a sequence on a screen that
has none, and a number describing nothing is a number that misleads. The CSS
that draws those circles says the same thing about itself.

**One panel is one surface.** The ten tabs used to live inside a single card
wrapped around the bar and all of them, which made the whole file read as one
object and left nowhere to put a surface without stacking a background on a
background. The bar sits on the page now and each panel is the surface under
it, which is also how Material draws tabs.
"""
import re
from html.parser import HTMLParser

import pytest


@pytest.fixture
def file_page(clinic):
    return clinic["sign_in"]("boss").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)


def _classes(page):
    return [value.split() for value in re.findall(r'class="([^"]*)"', page)]


# ------------------------------------------------------------- it is wired --
def test_the_stylesheet_actually_arrives(file_page):
    """The failure this roll-out already had once: the grammar written in, the
    stylesheet never loaded, and every class inert on a screen that looked
    exactly as it had before."""
    assert "css/material.css" in file_page


def test_the_scope_is_open(file_page):
    """`--md-surface-1` and every other token are declared **on** `.md`. With
    the link but no scope, the panels resolve to no background and no
    elevation — which reads as a styling bug rather than a missing class."""
    assert any("md" in classes for classes in _classes(file_page))


# ------------------------------------------------------------- the surfaces -
def test_each_tab_is_its_own_surface(file_page):
    """One panel, one thing to look at. Counted, because "some panel got the
    class" is satisfied by one of ten."""
    panels = sum(1 for classes in _classes(file_page)
                 if "gc-tab-panel" in classes)
    surfaced = sum(1 for classes in _classes(file_page)
                   if "gc-tab-panel" in classes and "md-section" in classes)
    assert panels >= 8, f"only {panels} tab panels rendered"
    assert surfaced == panels, \
        f"{panels - surfaced} panels are not surfaces"


def test_no_panel_sits_inside_a_card(file_page):
    """A tinted surface inside a card is two backgrounds stacked — the same
    doubling taken off the till screen's sections.

    Answered by walking the document and asking what each panel's ancestors
    are. The first version of this searched the text before the tab bar for a
    card opening, and could never have matched: the slice ended in the middle
    of the bar's own tag. Mutation testing put the card back and nothing
    failed.
    """
    offenders = _panels_inside_a_card(file_page)
    assert offenders == [], \
        f"{len(offenders)} tab panel(s) are drawn inside a card"


class _Ancestry(HTMLParser):
    """Which panels have a card somewhere above them."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.offenders = []

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        classes = dict(attrs).get("class", "").split()
        if "gc-tab-panel" in classes and any("card" in a for a in self.stack):
            self.offenders.append(classes)
        # Void-ish tolerance: the file is well-formed enough for divs, which
        # is all this walks.
        self.stack.append(classes)

    def handle_endtag(self, tag):
        if tag == "div" and self.stack:
            self.stack.pop()


def _panels_inside_a_card(page):
    parser = _Ancestry()
    parser.feed(page)
    return parser.offenders


def test_the_headings_use_the_shared_grammar(file_page):
    """Not a look that resembles it. The booking screen owns this pattern and
    its CSS; a second implementation drifts from it the first time either is
    touched.

    Asserted as "none left behind", not "at least one converted". `any()` is
    satisfied by thirteen out of fourteen, and the one left behind is the
    heading that looks wrong on somebody's screen.
    """
    heads = sum(1 for classes in _classes(file_page)
                if "md-section-head" in classes)
    assert heads >= 10, f"only {heads} headings use the shared grammar"
    # `section-title` survives on two fold *labels* inside `<summary>`, which
    # are labels and not section heads. What must not survive is a heading
    # tag still wearing it.
    stragglers = re.findall(r'<h[1-6][^>]*class="[^"]*\bsection-title\b', file_page)
    assert stragglers == [], f"{len(stragglers)} heading(s) were not converted"


# --------------------------------------------------- and what it is not ----
def test_the_file_is_not_numbered(file_page):
    """The line this screen must not cross.

    Steps are for work that has an order. A file is opened at whichever tab
    the person came for, and a "1" beside the overview would be claiming the
    family tab comes second in something.
    """
    assert "md-step" not in file_page


def test_every_tab_still_exists(file_page):
    """A restyle that quietly loses a tab is a restyle that lost a screen.
    Named one by one, because a count passes while the wrong nine are there.
    """
    for tab in ("overview", "family", "visits", "studies", "growth",
                "vaccinations", "documents", "prescriptions", "finance"):
        assert f"tab==='{tab}'" in file_page, f"the {tab} tab is gone"


def test_the_fields_are_reachable(file_page):
    """`.md` restyles every `.input` and `.select` on the page it scopes.
    Worth one assertion that the page still has forms in it at all — a
    stylesheet cannot break a form, but a botched wrapper can swallow one."""
    assert 'name="csrf_token"' in file_page
    assert "<form" in file_page
