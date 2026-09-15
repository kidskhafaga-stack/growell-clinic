"""«بتعمل الشغل وتنسى تحط باب ليه».

That sentence is the owner's, said after five features landed in one week, and
it was **correct**: a sweep of this session's own work found four readers
written, documented and tested — and called by nothing. A screen nobody can
open is the same as a screen nobody built, except that it costs the same to
maintain and reads on a matrix as done.

This file is the rule that outlives the fix.

**What it checks, and what it deliberately does not.** A general "every public
function in `app/utils` must have a caller" rule matches 462 functions today,
most of them internal helpers that are public only by habit — that is a
project of its own and a guard nobody would keep green. So this names the
**clinic-wide readers**: the ones that answer "who in the whole place needs
something", which exist for one purpose only, which is to be drawn on a
screen. Those are exactly the ones this project keeps orphaning, because they
are written while the feature's own screen is fresh and wired up later —
except when later never comes.

Adding one to :data:`READERS` is how a new one gets held to the same rule.
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

#: ``(module, function)`` — a reader that answers a question about the whole
#: clinic, and therefore must be reachable from a screen.
READERS = [
    ("blood", "unwatched"),
    ("blood", "emergencies_waiting"),
    ("blood", "for_patient"),
    ("care_plan", "overdue_everywhere"),
    ("followup", "outstanding"),
    ("risks", "unassessed"),
    ("risks", "without_plan"),
    ("invoice_signoff", "waiting"),
    ("recall", "candidates"),
]

#: Screens whose own door must exist — ``(endpoint, template that links it)``.
#: A route with no link to it is the same failure one level up: the reader is
#: called, and the page calling it is unreachable.
DOORS = [
    ("beds.watch", "app/templates/beds/index.html"),
    ("visits.followups", "app/templates/visits/list.html"),
    ("patients.care_plan_goals", "app/templates/patients/list.html"),
    ("settings.risks", "app/templates/settings/index.html"),
]


def _blueprint_and_template_text():
    """Everything a person can actually reach: routes and the pages they draw."""
    out = []
    for base in ("app/blueprints", "app/templates"):
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith((".py", ".html")):
                    path = os.path.join(dirpath, name)
                    out.append((path, open(path, errors="ignore").read()))
    return out


@pytest.mark.parametrize("module,func", READERS)
def test_a_clinic_wide_reader_is_drawn_on_a_screen(module, func):
    """It is called from a blueprint or a template, not only from its own file.

    A reader used solely inside its own module is a helper; a reader used by
    **nothing** is a feature with no door — and the four this file was written
    for were all in the second group while reading as done on a matrix.
    """
    pattern = re.compile(r"\b(?:%s|\w+)\.%s\s*\(" % (re.escape(module),
                                                     re.escape(func)))
    bare = re.compile(r"\b%s\s*\(" % re.escape(func))
    reached = []
    for path, text in _blueprint_and_template_text():
        if pattern.search(text) or (
                f"import {func}" in text and bare.search(text)):
            reached.append(path)
    assert reached, (
        f"app/utils/{module}.py::{func} answers a question about the whole "
        f"clinic and no blueprint or template calls it — a reader with no "
        f"door. Wire it to a screen, or delete it.")


@pytest.mark.parametrize("endpoint,template", DOORS)
def test_a_screen_has_something_that_links_to_it(endpoint, template):
    """Somewhere a person can click. The same rule one level up.

    Six times in this project something was built and nothing led to it, and
    the sixth was caught by the owner rather than by a test.
    """
    assert os.path.exists(template), template
    text = open(template, errors="ignore").read()
    assert f"url_for('{endpoint}')" in text, (
        f"{endpoint} is a screen with no link to it in {template} — "
        f"reachable only by typing the address.")


def test_every_reader_named_here_actually_exists(clinic):
    """The list cannot rot into a list of names that are gone.

    A guard whose subjects have been renamed is a guard that passes forever.
    """
    for module, func in READERS:
        path = f"app/utils/{module}.py"
        assert os.path.exists(path), path
        names = {n.name for n in ast.parse(open(path).read()).body
                 if isinstance(n, ast.FunctionDef)}
        assert func in names, f"{path} no longer defines {func}"


def test_every_door_endpoint_is_a_real_route(clinic):
    """And the endpoints are real, so a renamed route fails here rather than
    in a browser."""
    with clinic["app"].app_context():
        known = {r.endpoint for r in clinic["app"].url_map.iter_rules()}
    for endpoint, _template in DOORS:
        assert endpoint in known, f"{endpoint} is not a route in this app"
