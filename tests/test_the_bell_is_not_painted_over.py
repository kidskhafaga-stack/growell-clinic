"""The notification panel is chrome, and content must not be drawn on top of it.

Reported from a screenshot of the dashboard with the bell open: *"فى بج فى
الشاشة دي مع الاشعارات بتروح فى الخلفية"* — the panel hangs down from the
topbar and the first card on the page was painted over its middle, so a long
list of alerts appeared with a card-shaped hole punched through it.

**What actually caused it.** `.card:has(details[open]) { z-index: 50 }` — a
rule written so that a card holding an open popover edit form floats above its
sibling cards. That much it needed; the number was the problem. The siblings it
has to beat sit at layer 0 (`.gc-scale-in` finishes on `transform: scale(1)`,
which is a stacking context carrying no z-index of its own), so `1` clears
them. `50` also cleared the **topbar**, which sits at 20 — and the dashboard's
"clinic today" card contains a `<details>` that is open by default, so on that
screen a content card was permanently parked above the app chrome. Nobody had
to do anything to trigger it but open the bell.

**The rule this file holds.** The chrome is layered deliberately — topbar 20,
scrim 29, sidebar 30, its toggle 32, the rail's tooltip 40 — and content lives
underneath all of it. A z-index *inside* a card is not the danger and is not
tested here: `.gc-picker` names 60 and is harmless, because a card is its own
stacking context and 60 inside it means nothing outside it. The danger is a
z-index on an element that competes in the page's own stacking context, and on
these screens that means `.card` itself.

Checked statically, against the stylesheet rather than a browser. The repository
runs no browser in CI, and a rule of the form "no content selector may name a
number that reaches the chrome" is exactly the shape a stylesheet can be read
for. The fix itself was verified in Chromium: with 50, `elementFromPoint` down
the middle of an open panel returned the dashboard card; with 1 it returns the
panel at every point.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

CSS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "app", "static", "css")

# Selectors allowed to name a number at or above the topbar's: the app chrome
# itself, and full-screen overlays which are meant to cover everything. Adding
# to this list is how you say "this is chrome", deliberately.
CHROME = (".sidebar", ".topbar", ".nav-tip", ".gc-live-note", ".gc-overlay",
          ".gc-modal")

# ...and the ones whose number never reaches the page at all, because they sit
# inside a card and a card is always a stacking context: every card on these
# screens carries `.gc-scale-in`, which finishes on `transform: scale(1)`, and
# any card holding an open `<details>` is given a z-index by the rule this file
# was written about. So `.popform`'s 60 means "above the rest of my card" and
# not "above the topbar". They are listed rather than pattern-matched so that a
# new one has to be thought about.
INSIDE_A_CARD = (".popform", ".gc-picker")


def _rules():
    """``[(file, selector, z)]`` for every rule that names a z-index."""
    out = []
    for name in sorted(os.listdir(CSS_DIR)):
        if not name.endswith(".css"):
            continue
        with open(os.path.join(CSS_DIR, name), encoding="utf-8") as fh:
            source = fh.read()
        # Comments first: a z-index quoted in prose is not a rule, and the
        # comment explaining this very fix mentions several.
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
            found = re.search(r"z-index\s*:\s*(-?\d+)", block.group(2))
            if found:
                out.append((name, " ".join(block.group(1).split()),
                            int(found.group(1))))
    return out


def _topbar_layer():
    for _, selector, z in _rules():
        if selector.strip() == ".topbar":
            return z
    pytest.fail("the topbar names no z-index, so there is no chrome layer")


def test_the_topbar_has_a_layer_of_its_own():
    """Everything below rests on this number being real."""
    assert _topbar_layer() > 0


def test_no_card_is_lifted_into_the_chrome():
    """The bug itself. A `.card` competes in the page's own stacking context,
    so a number on one is measured against the topbar's — unlike a number on
    something *inside* a card, which cannot escape it."""
    floor = _topbar_layer()
    for name, selector, z in _rules():
        subject = selector.split(",")[0].strip()
        if not subject.startswith(".card"):
            continue
        assert z < floor, (
            f"{name}: `{selector}` puts a card at {z}, at or above the "
            f"topbar's {floor} — an open bell would be drawn underneath it")


def test_the_chrome_is_declared_and_not_stumbled_into():
    """Anything else reaching the chrome layer has to be named as chrome.

    Not a style rule for its own sake: the reason the bell was covered is that
    a number crept up to 50 with nobody asking what else lives at 50.
    """
    floor = _topbar_layer()
    for name, selector, z in _rules():
        if z < floor:
            continue
        assert any(part in selector for part in CHROME + INSIDE_A_CARD), (
            f"{name}: `{selector}` sits at {z}, in the chrome's range, and is "
            f"neither declared chrome nor known to be sealed inside a card. "
            f"Either lower it or say which it is.")


def test_the_bell_hangs_from_the_topbar_and_not_from_the_page():
    """Where the panel lives decides which layer it inherits. Moved into the
    content it would be content, whatever number it named."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "app", "templates", "shell.html")
    with open(path, encoding="utf-8") as fh:
        shell = fh.read()

    # The markup, not the stylesheet at the top of the same file — the class
    # name appears in both, and the first occurrence is the CSS rule.
    head = shell.index('class="topbar"')
    panel = shell.index('class="notif-panel"')
    closed = shell.index("</header>", head)
    assert head < panel < closed, \
        "the notification panel is no longer inside the topbar"
