"""The whole prescription screen was dead, and every test was green.

Found by opening it in a browser and pressing the button.

    PAGEERROR  Unexpected token '&'
    Alpine Expression Error: rxForm is not defined

One inline ``<script>`` failed to parse, so the component behind the entire
screen never came into being — no drug lines, no pickers, no save. And the
suite had nothing to say about it, because **the tests read the page and the
browser runs it**. Asserting that a handler's name appears in the HTML proves
the handler was printed, not that it can execute.

The cause is a Jinja filter used in the wrong context. ``|tojson|forceescape``
is right inside an HTML attribute — ``x-text="… {{ t('x')|tojson|forceescape }}"``
— where the browser un-escapes the entities before Alpine ever sees them. In a
``<script>`` body nothing un-escapes anything: ``&quot;`` arrives at the
JavaScript parser as four characters, and the file stops being JavaScript.

Two guards, and they catch different things:

**No HTML entity inside a script block.** Precise, needs nothing installed,
runs everywhere, and names the exact mistake.

**And the script actually parses**, where a JavaScript engine is on the
machine — which catches the next syntax error, whatever shape it takes.
"""
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The screens whose behaviour lives in an inline script. Not every template in
# the program — these are the ones where a parse error costs a working screen.
SCREENS = [
    "/prescriptions/new",
    "/appointments/",
    "/appointments/new",
]

NODE = shutil.which("node") or "/opt/node22/bin/node"

# Entities a browser resolves in an attribute and never in a script body.
ENTITY = re.compile(r"&(?:quot|apos|amp|lt|gt|#\d+|#x[0-9a-fA-F]+);")


def _scripts(html):
    """The inline script bodies of a page — the ones with no ``src``."""
    return [body for opening, body in
            re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S)
            if "src=" not in opening]


@pytest.fixture()
def screens(clinic):
    from app.utils.drugbook_seed import seed_drugbook

    with clinic["app"].app_context():
        seed_drugbook()
        clinic["db"].session.commit()
    return clinic


@pytest.mark.parametrize("path", SCREENS)
def test_no_html_entity_lands_inside_a_script(screens, path):
    """The exact mistake, named.

    ``&quot;`` in an attribute is correct and in a script body is four
    characters the JavaScript parser chokes on. Same filter, opposite meaning,
    and the two contexts sit ten lines apart in the same file.
    """
    page = screens["sign_in"]("boss").get(path)
    assert page.status_code == 200, path
    for body in _scripts(page.get_data(as_text=True)):
        found = ENTITY.search(body)
        assert not found, (
            f"{path} has {found.group(0)!r} inside a <script> — an attribute "
            "filter (|forceescape) used in a script body")


@pytest.mark.parametrize("path", SCREENS)
def test_the_script_on_the_page_actually_parses(screens, path):
    """The general form of the same guard.

    Reading the page proves the handler was printed; only a parser proves it
    can run. Skipped where no JavaScript engine is installed rather than
    quietly passing — a guard that cannot run should say so.
    """
    if not os.path.exists(NODE):
        pytest.skip("no JavaScript engine on this machine")
    page = screens["sign_in"]("boss").get(path)
    for index, body in enumerate(_scripts(page.get_data(as_text=True))):
        if not body.strip():
            continue
        checked = subprocess.run([NODE, "--check", "-"], input=body,
                                 capture_output=True, text=True)
        assert checked.returncode == 0, (
            f"{path} script #{index} does not parse:\n"
            + (checked.stderr or "").strip()[:800])
