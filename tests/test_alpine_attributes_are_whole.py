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
