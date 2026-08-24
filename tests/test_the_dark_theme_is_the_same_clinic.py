"""A clinic that recolours the program recolours both of its themes.

Reported after looking at the two screenshots side by side: *"الوضع الليلي ليه
مسبتين الأخضر؟"* — a clinic with a blue accent had a blue sidebar in light mode
and a green one in dark.

The cause is one line of history. Light mode reads `--green-800` / `--green-600`
/ `--green-100`, and `:root[style*="--accent"]` rewrites those from the clinic's
chosen colour, so light mode follows it for free. The dark rules were written
later, by hand, with the greens typed in as literals — so they kept being green
no matter what the clinic chose. Half a theme system.

**And the fix needs a line drawn, not just a find-and-replace.** Not every
colour in dark mode should follow the accent:

* **Brand** — the sidebar, links, the brand badges, the info panels. These say
  "this is your program" and must change when a clinic recolours it.
* **Semantic** — success green, danger red, warning amber. These say "this went
  well" or "this went wrong". They are meanings, and a clinic that picks a red
  accent must not end up reading red as its success colour.

This file holds that line: brand rules must be derived, semantic ones must stay
literal, and both halves are checked so a later edit cannot quietly move a rule
from one side to the other.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# Rules that carry the clinic's identity, and must therefore be derived from
# the accent-following tokens rather than typed in.
BRAND = [".sidebar", "a", ".badge--green", ".badge--role", ".info-note"]

# Rules that carry a meaning rather than a brand. Literal on purpose.
SEMANTIC = [".flash--success", ".flash--danger", ".flash--warning"]

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _theme_css():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "static",
                        "css", "theme.css")
    with open(os.path.abspath(path), encoding="utf-8") as fh:
        return fh.read()


def _dark_block(css, selector):
    """The declarations of the dark rule for one selector.

    Selectors are grouped in this file, so the rule is found by scanning for
    the one whose selector list contains it — matching on the exact text would
    break the first time somebody adds a sibling to the group, and a test that
    breaks on formatting is a test people delete.
    """
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        head, body = match.group(1), match.group(2)
        if 'data-theme="dark"' not in head:
            continue
        parts = [p.strip() for p in head.split(",")]
        if any(p.endswith(f' {selector}') or p.endswith(f']{selector}')
               for p in parts):
            return body
    return None


# ------------------------------------------------------------- brand ----

@pytest.mark.parametrize("selector", BRAND)
def test_the_dark_brand_colour_follows_the_accent(clinic, selector):
    """Derived, not typed. A literal here is a colour that cannot follow a
    clinic that recoloured the program — which is exactly what was reported."""
    body = _dark_block(_theme_css(), selector)

    assert body is not None, f"no dark rule for {selector}"
    assert "--green-" in body, \
        f"{selector} in dark mode uses no brand token: {body.strip()}"


@pytest.mark.parametrize("selector", BRAND)
def test_no_brand_colour_is_typed_in(clinic, selector):
    """A `color-mix` toward a dark neutral is fine — `#06090d` is not a colour,
    it is the dark it is being mixed *into*, and it carries no hue to fight
    the accent. What must not appear is a green: a hex with a green channel
    clearly ahead of the others is the bug this file exists for."""
    body = _dark_block(_theme_css(), selector) or ""

    for hexcode in HEX.findall(body):
        raw = hexcode[1:]
        if len(raw) == 3:
            raw = "".join(c * 2 for c in raw)
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
        assert not (g > r + 20 and g > b + 20), \
            f"{selector} has a green typed into it ({hexcode}); it cannot " \
            "follow a clinic that chose another colour"


def test_the_sidebar_is_dark_in_either_case(clinic):
    """Following the accent must not make it *bright*. It is mixed toward
    near-black rather than dimmed, because a colour reduced in lightness alone
    goes muddy while one mixed into a dark neutral keeps its identity."""
    body = _dark_block(_theme_css(), ".sidebar") or ""

    assert "color-mix" in body and "#0" in body, \
        f"the dark sidebar is not mixed into a dark ground: {body.strip()}"


# ---------------------------------------------------------- semantic ----

@pytest.mark.parametrize("selector", SEMANTIC)
def test_the_meanings_do_not_follow_the_accent(clinic, selector):
    """The other half of the line, and the reason this is not a find-and-
    replace. A clinic that picks a red accent must not end up reading red as
    its success colour."""
    body = _dark_block(_theme_css(), selector)

    assert body is not None, f"no dark rule for {selector}"
    assert "--green-" not in body and "--accent" not in body, \
        f"{selector} was made to follow the accent; it is a meaning, " \
        f"not branding: {body.strip()}"
    assert HEX.search(body), \
        f"{selector} should carry its own literal colour: {body.strip()}"


def test_the_distinction_is_written_down(clinic):
    """A rule somebody can follow beats a rule they have to infer from which
    lines happen to use tokens."""
    css = _theme_css()

    assert "Brand tints follow the accent" in css
    assert "Semantic, and therefore literal on purpose" in css
