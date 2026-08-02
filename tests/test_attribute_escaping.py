"""JSON handed to an HTML attribute has to survive being an HTML attribute.

Reported as garbage text on the AI settings screen: a line of JavaScript from
inside an ``x-data`` block rendered on the page for the user to read.

The cause is small and repeats: ``|tojson`` emits a **double-quoted** JSON
string, and these attributes are double-quoted, so the first quote of the value
closes the attribute. The browser then treats the rest of the Alpine component
as stray markup and text — which is exactly what appeared on screen.

``tojson`` looks safe because Flask's version escapes ``<``, ``>``, ``&`` and
``'`` for embedding inside ``<script>`` tags. It does not escape ``"``, because
inside a script tag there is no attribute to close. In an attribute there is.

The visible symptom was on one screen; the same construct was silently breaking
four others, where the failure is quieter and worse — an Alpine component that
never initialises just leaves a form that does nothing when you click it.

So this file does not test one screen. It renders **every** template that hands
JSON to an attribute and checks the attribute survived.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# `tojson` inside a double-quoted attribute, without the escape that makes it
# safe there.
_UNESCAPED = re.compile(r'="[^"\n]*\|\s*tojson\s*\}\}')
_TOJSON_IN_ATTR = re.compile(r'="[^"\n]*\|\s*tojson')


def _templates():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".html"):
                yield os.path.join(folder, name)


def test_no_template_puts_raw_tojson_in_an_attribute():
    """The rule, checked across every template rather than the one that was
    reported. A fifth screen written next month fails here, not in a clinic."""
    offenders = []
    for path in _templates():
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if _UNESCAPED.search(line):
                    offenders.append(f"{os.path.basename(path)}:{number}")
    assert not offenders, (
        "`|tojson` in a double-quoted attribute closes the attribute at its "
        "first quote — add `|forceescape` after it: " + ", ".join(offenders))


def test_every_json_bearing_attribute_is_escaped():
    """The positive half: the places that legitimately pass JSON to an
    attribute all carry the escape."""
    seen = 0
    for path in _templates():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if _TOJSON_IN_ATTR.search(line):
                    seen += 1
                    assert "forceescape" in line, (
                        f"{os.path.basename(path)}: {line.strip()[:90]}")
    assert seen >= 4, "expected several JSON-bearing attributes; found %d" % seen


@pytest.mark.parametrize("value", ['', 'gpt-4o', 'a "quoted" name', "خزنة"])
def test_the_escape_actually_survives_a_round_trip(value):
    """Not a style rule — the escaped form has to still parse as JSON once the
    browser has decoded the attribute."""
    import html
    import json

    from flask import Flask

    app = Flask(__name__)
    with app.app_context():
        rendered = app.jinja_env.from_string(
            '<div x-data="{ model: {{ v|tojson|forceescape }} }"></div>'
        ).render(v=value)

    # The attribute must not have been closed early: exactly one pair of real
    # quotes around the whole value.
    assert rendered.count('"') == 2, rendered
    inner = rendered.split('"')[1]
    assert json.loads(html.unescape(inner).strip().removeprefix(
        "{ model:").removesuffix("}").strip()) == value


def test_the_unescaped_form_is_genuinely_broken():
    """Pins *why* the rule exists. If a future Jinja or Flask starts escaping
    quotes in `tojson` by itself, this test fails and the rule can be retired
    deliberately rather than left as folklore."""
    from flask import Flask

    app = Flask(__name__)
    with app.app_context():
        rendered = app.jinja_env.from_string(
            '<div x-data="{ model: {{ v|tojson }} }"></div>').render(v="x")
    assert rendered.count('"') > 2, (
        "`tojson` now escapes quotes on its own — the `forceescape` rule in "
        "test_no_template_puts_raw_tojson_in_an_attribute can be revisited")
