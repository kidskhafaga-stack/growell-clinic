"""The top bar fits the screen it is on.

Drawn for a wide desk, the bar laid the date, three theme buttons, the bell,
both languages, the name and role and a worded "log out" in one row that
does not wrap: 753px of it on a 390px phone, and 924px on a 700px tablet
beside the sidebar. Every page scrolled sideways.

Measured in a browser after the change, at 15 widths from 320 to 1600 and in
both languages, with the "close your shift" chip showing: the page is never
wider than the screen. The suite has no browser, so what is held here is the
shape that makes that true — the controls all stay, and what gives way is
words said elsewhere.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: F401,E402

CSS = open("app/static/css/theme.css", encoding="utf-8").read()
SHELL = open("app/templates/shell.html", encoding="utf-8").read()


def _media(width):
    """The body of ``@media (max-width: <width>px)`` blocks, joined."""
    out = []
    for match in re.finditer(r"@media \(max-width: %dpx\) \{" % width, CSS):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(CSS[i], 0)
            i += 1
        out.append(CSS[match.end():i - 1])
    return "\n".join(out)


def test_the_title_gives_way_instead_of_widening_the_row():
    rule = CSS[CSS.index(".topbar__title { min-width: 0;"):]
    rule = rule[:rule.index("}")]
    for part in ("min-width: 0", "overflow: hidden", "text-overflow: ellipsis",
                 "white-space: nowrap"):
        assert part in rule, part
    assert ".topbar__actions { flex: 0 0 auto; }" in CSS


def test_the_words_that_go_are_still_said():
    """Logging out and closing a shift keep their icon on a narrow screen,
    and their words stay for a screen reader and the tooltip."""
    logout = SHELL[SHELL.index('class="btn btn-outline btn-sm topbar__logout"'):]
    logout = logout[:logout.index("</a>")]
    assert "aria-label=\"{{ t('auth.logout') }}\"" in logout
    assert '<span class="topbar__label">' in logout
    chip = SHELL[SHELL.index("topbar__amber-chip"):]
    chip = chip[:chip.index("</a>")]
    assert '<span class="topbar__label">' in chip
    # Hidden the way a screen reader still reads, not display:none.
    narrow = _media(1439)
    assert ".topbar__label { position: absolute; width: 1px;" in narrow
    assert ".topbar__label { display: none" not in CSS


def test_the_language_has_a_short_name_for_a_phone():
    switch = SHELL[SHELL.index('<div class="lang-switch">'):]
    switch = switch[:switch.index("</div>")]
    assert 'class="lang-full"' in switch and 'class="lang-short"' in switch
    assert 'title="{{ lang_name }}"' in switch
    phone = _media(640)
    assert ".lang-switch .lang-short { display: inline;" in phone
    assert ".lang-switch a.active { display: none; }" in phone


def test_each_step_is_there():
    assert ".topbar-date { display: none; }" in _media(1439)
    assert ".user-chip .meta { display: none; }" in _media(1099)
    assert ".theme-switch { display: none; }" in _media(400)


def test_every_control_is_still_on_the_bar():
    """Nothing the bar does is taken off it — only words."""
    for part in ("topbar__menu", "theme-switch", "notif-wrap", "lang-switch",
                 "user-chip", "auth.logout"):
        assert part in SHELL, part
    for selector in (".notif-wrap", ".user-chip {", ".topbar__logout",
                     ".lang-switch {"):
        for width in (1439, 1099, 640, 400):
            assert selector.rstrip(" {") + " { display: none" not in _media(width)
