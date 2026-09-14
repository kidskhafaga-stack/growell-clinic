"""An Alpine attribute that a quote cut in half.

The AI settings card carried a JS comment containing a double quote:

    // "type one manually", which is exactly what it was meant to spare

inside a double-quoted ``x-data="…"``. The browser ends an attribute at the
first matching quote, so the block was truncated at 2013 characters,
mid-sentence, and everything after it was dropped — the model list, the
watcher, ``init()``. Measured in Chromium: ``Unexpected end of input`` and
``provider is not defined``, on a screen that otherwise looked completely
normal. The tab rendered, the provider box worked, and the model box simply
never appeared.

That last part is what makes it worth a test rather than a fix. Nothing looked
broken. This is the **third** time this exact shape has bitten this codebase:
once from ``tojson`` without ``forceescape`` on the settings tabs, once on the
patient profile, and now from an ordinary English sentence in a comment.

So this does not check that one line. It parses every Alpine attribute the way
a browser would — up to the quote that actually ends it, not the one that was
meant to — and asks whether what is left is still whole.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The attributes whose value is JavaScript. A stray quote in any of them is
# the same failure; `x-data` is simply where it shows up worst.
ALPINE = re.compile(
    r'\s(x-data|x-init|x-show|x-if|x-text|x-html|x-model(?:\.\w+)*|'
    r'x-on:[\w.\-]+|x-bind:[\w.\-]+|@[\w.\-]+|:[\w\-]+)="')


def _templates():
    return sorted(glob.glob(os.path.join(ROOT, "app/templates/**/*.html"),
                            recursive=True))


def _attributes():
    """(file, attribute, value) for every Alpine attribute, as a browser reads it."""
    for path in _templates():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        for m in ALPINE.finditer(src):
            end = src.find('"', m.end())
            if end == -1:
                continue
            yield os.path.relpath(path, ROOT), m.group(1), src[m.end():end]


def _balanced(text):
    """Whether brackets balance, ignoring what is inside strings and comments.

    Crude on purpose: it is looking for a value that was *cut off*, and a
    truncated block is unbalanced long before it is unparseable.
    """
    depth = {"{": 0, "(": 0, "[": 0}
    pairs = {"}": "{", ")": "(", "]": "["}
    i, n = 0, len(text)
    string = None
    while i < n:
        ch = text[i]
        if string:
            if ch == "\\":
                i += 2
                continue
            if ch == string:
                string = None
        elif ch in "'`":
            string = ch
        elif ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        elif ch in depth:
            depth[ch] += 1
        elif ch in pairs:
            depth[pairs[ch]] -= 1
        i += 1
    return string is None and all(v == 0 for v in depth.values())


def test_no_alpine_attribute_is_cut_off_by_a_quote():
    """The whole point: read them the way the browser does, then check.

    A double quote anywhere inside one of these — in a string, in a comment,
    in an ordinary English sentence — ends the attribute early and silently.
    """
    broken = []
    for path, attr, value in _attributes():
        if not value.strip():
            continue
        if not _balanced(value):
            broken.append((path, attr, value.strip()[-70:]))

    assert not broken, (
        "these Alpine attributes end before their code does — a double quote "
        "inside a double-quoted attribute closes it: "
        + "; ".join(f"{p} {a} …{tail}" for p, a, tail in broken))


# The quote that is not in the template ------------------------------------
#
# `test_no_alpine_attribute_is_cut_off_by_a_quote` above reads the template
# **source**, and that is what let the fourth instance of this bug ship. In the
# source `{{ notes | tojson }}` is ordinary Jinja text with no double quote in
# it at all, so the attribute reads as whole and balanced. The quote appears
# only after rendering, and only when the value is not empty: `[]` carries
# none, `["a subject line"]` carries two.
#
# So the update card passed every guard on a clinic with nothing to install
# and broke on every clinic that had something — the state badge blank, the
# arrow pointing at nothing, and no error anywhere a person would look.
#
# This is the rule the source *can* be checked against: inside a
# double-quoted attribute, `tojson` without `forceescape` is a quote waiting
# for data.

#: One whole ``{{ … }}``, newlines and all — these attributes span lines.
INTERPOLATION = re.compile(r"\{\{.*?\}\}", re.S)


def _unescaped_tojson(value):
    """Every `tojson` in this attribute that is not paired with `forceescape`.

    Whole interpolations, not the filter alone: the escape is somewhere else
    in the same ``{{ … }}``, so a pattern that stops at the filter can never
    see it — which is what the first draft of this did, and it called every
    correctly written attribute a fault.
    """
    out = []
    for m in INTERPOLATION.finditer(value):
        text = m.group(0)
        if "tojson" in text and "forceescape" not in text:
            out.append(" ".join(text.split()))
    return out


def test_no_double_quoted_attribute_renders_tojson_unescaped():
    """The fourth instance, and the first the source can be read for.

    `tojson` writes `"` around every string. A double-quoted attribute ends at
    the first one. The two are only ever safe together when something turns
    that quote into `&quot;` — which is what `forceescape` is for, and what
    every other attribute in this program already does.
    """
    guilty = []
    for path, attr, value in _attributes():
        for bad in _unescaped_tojson(value):
            guilty.append((path, attr, bad))

    assert not guilty, (
        "`tojson` inside a double-quoted attribute needs `|forceescape`, or "
        "the first quote it writes ends the attribute — and it only does that "
        "once the value is non-empty, so the screen works until it matters: "
        + "; ".join(f"{p} {a} {bad}" for p, a, bad in guilty))


def test_that_checker_would_notice_too():
    """A detector nobody exercised is a detector nobody can trust."""
    assert _unescaped_tojson("{ notes: {{ rows | tojson }} }"), \
        "an unescaped tojson in an attribute went unnoticed"
    assert not _unescaped_tojson("{ notes: {{ rows | tojson | forceescape }} }"), \
        "a correctly escaped tojson was reported as a fault"
    assert not _unescaped_tojson("{ tab: 'clinic' }"), \
        "an attribute with no tojson at all was reported as a fault"


def test_the_ai_settings_block_survives_to_its_own_end():
    """The one that was actually broken, named so the failure says which.

    `init()` is the last thing in that block, so its presence is the proof
    that nothing after the comment was dropped.
    """
    with open(os.path.join(ROOT, "app/templates/settings/index.html"),
              encoding="utf-8") as fh:
        src = fh.read()

    at = src.index('x-show="tab===\'ai\'"')
    start = src.index('x-data="', at) + len('x-data="')
    value = src[start:src.index('"', start)]

    assert "init()" in value, \
        "the AI card's x-data ends before its own code: …" + value[-80:]
    assert "loadModels" in value
    assert _balanced(value), "the AI card's x-data does not close its braces"


def test_the_checker_would_notice(self_check=None):
    """A test that cannot fail is not a test.

    The detector is the thing being trusted here, so it is exercised on the
    exact string that caused the outage and on a healthy one.
    """
    truncated = "{ provider: 'claude', // \"type one manually"
    assert not _balanced(truncated), \
        "the checker does not notice a block cut off mid-comment"

    healthy = "{ provider: 'claude', model: '', init() { this.go(); } }"
    assert _balanced(healthy), "the checker rejects a perfectly good block"

    # A quote inside a *single*-quoted JS string is fine and must not be flagged.
    quoted = "{ label: 'he said \\'hi\\'', n: (1 + 2) }"
    assert _balanced(quoted)


def test_every_template_was_actually_looked_at():
    """A scanner that silently matched nothing would pass forever."""
    seen = {path for path, _a, _v in _attributes()}

    assert len(_templates()) > 50, "the template glob stopped finding files"
    assert len(seen) > 10, \
        f"only {len(seen)} templates had an Alpine attribute — the regex broke"
