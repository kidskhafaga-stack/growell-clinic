"""الوضع الليلي: حاجة بتكتب لون فاتح بإيدها لازم يبقى ليها نسخة ليلية.

الملف بيتقرا الساعة تلاتة الفجر في قسم داخلي، والشاشة ساعتها سودا. أي كلاس
بيكتب خلفية فاتحة **بالقيمة** — مش بـtoken — بيفضل فاتح في الوضع الليلي، فبيطلع
شريط أبيض وسط صفحة كلها غامقة، والنص اللي عليه بيتقرا بلون التيمة التانية.

ودي اتلقت من صورة: كارت الطفل في أول الملف كان `linear-gradient(..., #fff)` —
أبيض حرفي — فكان الحاجة الوحيدة في الصفحة اللي بتتجاهل التيمة، وهو أول حاجة
حد بيفتح ملف بالليل بيبصّ عليها. وجنبه طلعوا تلاتة بنفس البَج: شريط التنبيه،
ودايرة أيقونته، وشارة النوع، وإطار صورة الطفل.

**القاعدة اللي الملف ده بيمسكها:** كلاس فيه خلفية فاتحة مكتوبة بالقيمة لازم
يبقى ليه `:root[data-theme="dark"]` بيعيد تعريفه — أو يستعمل token أصلاً
وساعتها مش محتاج حاجة.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SHEETS = ("app/static/css/theme.css", "app/static/css/app.css",
          "app/static/css/material.css")

#: Any colour literal in a background. Tokens (`var(--…)`) and `color-mix`
#: are fine — they follow whichever palette is loaded.
BACKGROUND = re.compile(r"background(?:-color)?\s*:")
HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")

#: Above this, a colour is light enough that dark text was written for it and
#: a dark page will not carry it. **Lightness, not "the hex starts with f"** —
#: the first version of this rule flagged `#f59e0b`, a saturated amber used as
#: a warning lamp, which is not a light background at all and needs no dark
#: twin. The bug is "this is nearly white", so that is what is measured.
TOO_LIGHT = 0.72


def _lightness_of(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _lightness(hex_colour):
    """Perceived lightness, 0–1, from a 3- or 6-digit hex."""
    digits = hex_colour.lstrip("#")
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    r, g, b = (int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return _lightness_of(r, g, b)


#: `rgba(255, 255, 255, .6)` is a light background written in numbers. A
#: sweep put it back and the first version of this rule did not notice,
#: because it only read hex and the word `white`.
RGB = re.compile(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)"
                 r"(?:[,/\s]+([\d.]+))?\s*\)")

#: Below this an overlay is faint enough to read as a tint on either ground.
BARELY_THERE = 0.25


def _paints_something_light(declaration):
    """Whether this declaration sets a background that is nearly white."""
    if not BACKGROUND.search(declaration):
        return False
    if re.search(r"\bwhite\b", declaration):
        return True
    for match in RGB.finditer(declaration):
        r, g, b = (int(match.group(i)) / 255 for i in (1, 2, 3))
        alpha = float(match.group(4)) if match.group(4) else 1.0
        if alpha > BARELY_THERE and _lightness_of(r, g, b) >= TOO_LIGHT:
            return True
    return any(_lightness(m.group(0)) >= TOO_LIGHT
               for m in HEX.finditer(declaration))


#: `var(--card, #fff)` is a **fallback**, reached only if the token is
#: missing, which it never is. Not a hardcoded background.
FALLBACK = re.compile(r"var\(\s*--[\w-]+\s*,\s*[^)]*\)")


def _rules():
    """``(sheet, line number, selector, declaration)`` for every rule."""
    out = []
    for sheet in SHEETS:
        text = open(sheet, errors="ignore").read()
        # Comments out first. A rule explaining *why* it no longer paints
        # `#fff` would otherwise be reported for saying so — and that comment
        # exists precisely because this rule was broken once.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        line = 1
        for chunk in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
            line = text[:chunk.start()].count("\n") + 1
            selector = " ".join(chunk.group(1).split())
            out.append((sheet, line, selector, chunk.group(2)))
    return out


def _has_dark_twin(selector, everything):
    """Whether a dark rule names this class **and repaints its background**.

    The second half matters and the first version of this rule left it out: a
    dark rule that only corrects the text colour leaves the light background
    exactly where it was, and the class would have passed for having a
    night version it does not have.
    """
    classes = re.findall(r"\.([\w-]+(?:\.[\w-]+)?)", selector)
    if not classes:
        return True                 # an element rule, not a themed component
    last = classes[-1].split(".")[-1]
    return any('[data-theme="dark"]' in other and f".{last}" in other
               and BACKGROUND.search(body)
               for _s, _l, other, body in everything)


def test_a_hardcoded_light_background_has_a_dark_version():
    """Every light background literal is either a token, a fallback, already
    inside a dark rule, or has a dark rule that redefines it."""
    everything = _rules()
    offenders = []
    for sheet, line, selector, body in everything:
        if '[data-theme="dark"]' in selector or "prefers-color-scheme" in selector:
            continue
        for declaration in body.split(";"):
            if not _paints_something_light(declaration):
                continue
            if FALLBACK.search(declaration):
                continue
            if _has_dark_twin(selector, everything):
                continue
            offenders.append(f"{sheet}:{line} {selector.strip()[:60]} "
                             f"→{declaration.strip()[:50]}")
    # A sweep that makes an already-covered class literally white survives
    # this, and that is right: the class has a dark rule that repaints it, so
    # the night screen is correct. A white chip in *daylight* is a different
    # complaint and not this guard's.
    assert not offenders, (
        "these paint a light background with no dark version, so they stay "
        "bright on a dark screen:\n  " + "\n  ".join(offenders))


def test_the_childs_own_header_follows_the_theme():
    """The one the owner pointed at. It ends on `--card`, not on white."""
    css = open("app/static/css/theme.css", errors="ignore").read()
    rule = re.search(r"\.profile-header\s*\{(.*?)\}", css, re.S)
    assert rule, "the .profile-header rule is gone"
    background = re.search(r"background\s*:([^;]*);", rule.group(1))
    assert background, ".profile-header paints no background"
    said = background.group(1)
    assert "#fff" not in said and "white" not in said, (
        f".profile-header paints a literal white: {said.strip()} — it is the "
        f"first thing on a child's file and it ignored the dark theme once "
        f"already")
    assert "var(--" in said


@pytest.mark.parametrize("name", [
    "alert-banner__item.ab-danger", "alert-banner__item.ab-warn",
    "alert-banner__item.ab-growth", "gender-male", "gender-female",
    "patient-avatar.lg",
])
def test_the_rest_of_the_files_top_strip_has_a_night_version(name):
    """The four that sat beside the header with the same bug. They are one
    strip on the screen — the banner, its icon, the gender chip, the ring
    round the photo — and a file opened at night showed the lot as a bright
    band."""
    css = open("app/static/css/theme.css", errors="ignore").read()
    last = name.split(".")[-1]
    assert re.search(r'\[data-theme="dark"\][^{]*\.' + re.escape(last) + r'\b',
                     css), f".{name} has no dark version"
