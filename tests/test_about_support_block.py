"""The block a clinic copies into a message when something is wrong.

The About page's best idea was already there: **counted, never typed** — every
figure read at render time, so the page cannot drift from what the
installation holds. It was spent on figures that flatter (patients, drug
products, ICD codes) rather than on the ones that do work.

The first three questions of every support conversation are the same — which
version, what is enabled, how much data — and nobody in a clinic can answer
the last two. So they are gathered on the screen a person is already looking
at when something has gone wrong, in a block they copy into one message.

**The schema fingerprint is the reason this exists.** `version.py` was written
because of a real report — *"I restored a backup and got a load of problems"* —
where the restore was fine and the schema behind it was a version old. That
number is computed, goes into every archive, and until now appeared on **no
screen a person opens when something is wrong**. Implemented, never read: the
same shape as everything else found this week.

**Safe to paste.** No filesystem paths, no passphrase, no patient. A block
meant for WhatsApp has to be safe for WhatsApp, and that is asserted rather
than intended.

**It cannot break the page.** Every fact is wrapped, because a support panel
that raises is a support panel that is missing exactly when it is needed.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def page(clinic):
    return clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()


# ------------------------------------------------------ what it has to carry

def test_it_answers_the_first_three_questions(clinic):
    from app.utils import project

    with clinic["app"].app_context():
        text = "\n".join(project.support_lines())

    from app.utils.version import APP_VERSION, schema_version

    assert APP_VERSION in text, "which version"
    assert schema_version() in text, \
        "the schema fingerprint — the whole reason this block exists"
    assert "modules" in text, "what is enabled"
    assert "patients" in text, "how much data"
    assert "backup" in text


def test_the_schema_number_reaches_a_human_screen(page):
    """It was computed, written into every archive, and shown nowhere.

    Asserted against the rendered page rather than the helper, because the
    defect was never in the arithmetic — it was that nothing displayed it.
    """
    from app.utils.version import schema_version

    assert schema_version() in page


def test_the_block_and_the_page_cannot_disagree(clinic):
    """Built once and rendered twice. Two lists would drift, and the copy is
    the half nobody checks."""
    from app.utils import project

    with clinic["app"].app_context():
        lines = project.support_lines()

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    for line in lines:
        assert line in page, f"the page does not show what the copy holds: {line}"


# ---------------------------------------------------------- safe to paste

def test_it_carries_no_secret_and_no_patient(clinic):
    """A block meant to be pasted into WhatsApp has to be safe to paste into
    WhatsApp. Asserted, not intended."""
    from app.extensions import db
    from app.models import Patient
    from app.utils import project

    with clinic["app"].app_context():
        kid = Patient(patient_number="SEC1", full_name="اسم لا يظهر",
                      gender="male", date_of_birth=date(2020, 5, 1),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()

        text = "\n".join(project.support_lines())

        assert "اسم لا يظهر" not in text, "a patient's name is in the block"
        assert "SEC1" not in text

        # No filesystem paths: they name the machine and help nobody. Asserted
        # against the real paths rather than by hunting for "/" — the block
        # legitimately contains "14/14" and "schema x / gen n", and a test
        # that bans the character bans the content.
        from flask import current_app

        for path in (current_app.instance_path, current_app.root_path):
            assert path not in text, f"a filesystem path leaked: {path}"
        import re

        assert not re.search(r"/[A-Za-z._-]", text), \
            f"something path-shaped is in the block: {text}"


def test_no_password_key_is_anywhere_near_it(clinic):
    """The backup passphrase lives one function away from the backup date.

    Parsed rather than grepped, and deliberately: the first version of this
    searched the source as text and failed on the sentence in `support`'s own
    docstring promising there is no passphrase in it. A test that cannot tell
    a promise from a breach is a test that will be deleted rather than read.
    """
    import ast
    import inspect

    from app.utils import project

    names = set()
    for fn in (project.support, project.support_lines):
        tree = ast.parse(inspect.getsource(fn))
        # Every docstring dropped, at every level — the outer function's and
        # each nested helper's. They are prose about the code, not the code,
        # and this test exists to read the code.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)) and node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    node.body = node.body[1:]
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update(a.name for a in node.names)
                if isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)

    for word in ("password", "passphrase", "secret", "SECRET_KEY",
                 "backup_password", "instance_path"):
        assert not [n for n in names if word.lower() in n.lower()], \
            f"{word} is reachable from the support block"


# ------------------------------------------------- it cannot break the page

def test_a_fact_that_raises_does_not_take_the_page_with_it(clinic, monkeypatch):
    """The panel people open when something is already wrong is the last one
    that may fail. Measured by breaking one on purpose."""
    import app.utils.version as version

    def explode():
        raise RuntimeError("the disk is gone")

    monkeypatch.setattr(version, "schema_version", explode)

    answer = clinic["sign_in"]("boss").get("/about", follow_redirects=True)

    assert answer.status_code == 200


def test_it_survives_a_database_with_no_file_behind_it(clinic):
    """The tests run on an in-memory database, so `db_path()` is None and the
    size cannot be read. That is a real configuration, not a test artefact —
    and it must read as "—", not as a crash."""
    from app.utils import project

    with clinic["app"].app_context():
        data = project.support()

    assert "db_mb" in data
    assert "db —" in "\n".join(project.support_lines(data)) or \
        data["db_mb"] is not None


# --------------------------------------------------- the warning underneath

def test_a_clinic_with_no_backup_is_told_so(clinic, monkeypatch):
    """The one line on this page that is not a fact but a consequence.

    "The clinic's data stays at the clinic" is a promise the About page makes
    two cards further up. Whether it is still true is a date, and the date was
    on a different screen.
    """
    import app.utils.backups as backups

    monkeypatch.setattr(backups, "last_backup_at", lambda: None)

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    from app.i18n import t

    with clinic["app"].test_request_context("/"):
        assert t("about.backup_never") in page


def test_a_backup_from_this_morning_raises_no_alarm(clinic, monkeypatch):
    """The other half — otherwise the warning is wallpaper."""
    from datetime import datetime

    import app.utils.backups as backups

    monkeypatch.setattr(backups, "last_backup_at", lambda: datetime.now())

    page = clinic["sign_in"]("boss").get(
        "/about", follow_redirects=True).data.decode()

    from app.i18n import t

    with clinic["app"].test_request_context("/"):
        assert t("about.backup_never") not in page
        assert t("about.backup_stale") not in page


# ------------------------------------------------------------- the copying

def test_copying_works_without_a_secure_context(page):
    """`navigator.clipboard` is absent on plain http, which is how nearly
    every one of these installations is reached — the clinic's own machine on
    its own network. A copy button that only works on https is a copy button
    that never works here."""
    assert "navigator.clipboard" in page
    assert "execCommand" in page, \
        "there is no fallback for the http installations, which is all of them"


def test_the_wording_exists_in_both_languages(clinic):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    keys = ["support", "support_hint", "copy", "copied",
            "backup_stale", "backup_never"]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["about"]
        for key in keys:
            assert key in block, f"{lang} is missing about.{key}"
