"""The bell says there is a newer version. Nothing installs it.

Asked for exactly that way: *the notice comes through the bell only.* The
console notice `start.bat` prints scrolls past in a window nobody is looking
at, and by the time somebody could act on it the screen is gone.

Three things are held here.

**The bell does not go to the internet.** The launch check asks once and
writes down what it found; the bell reads what was written. Computing the
notice on the bell's own schedule would have turned one request per launch
into one every ninety seconds — on the one feature whose whole promise is that
it says nothing about the clinic to anybody — and would have put a
three-second timeout in front of every page a receptionist opens.

**The notice goes stale by itself.** What is stored names the revision that
was newest at the last launch. Once this copy *is* that revision there is
nothing to say. Which is also why nothing ever stores an empty value: a launch
with no internet reports "no news" exactly as a launch that is up to date
does, and clearing on that would delete a notice that is still true.

**The program does not update itself.** The page the bell points at ends at a
sentence: close the program, run `update.bat`. `start.bat` used to run `git
pull` on every launch — no snapshot in front of it, no schema upgrade behind
it, landing in the middle of a working day — and it cost a clinic a morning.
Replacing the files of a running process is that same failure with a button
on it.
"""
import ast
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

FOUND = {"installed": "a" * 40, "latest": "b" * 40,
         "notes": ["a fix for the reminder list", "a new vaccine brand"]}


def _store(clinic, value):
    from app.extensions import db
    from app.models import Setting
    from app.utils.updates import STORED

    with clinic["app"].app_context():
        Setting.set(STORED, value)
        db.session.commit()


# ------------------------------------------------------ what is remembered

def test_what_the_launch_found_is_what_the_bell_reads(clinic):
    from app.utils.updates import remembered

    _store(clinic, json.dumps(FOUND))
    with clinic["app"].app_context():
        assert remembered() == FOUND


def test_a_notice_about_the_version_this_copy_now_is_has_nothing_to_say(clinic):
    """The clinic ran update.bat. The stored line is still there and is now
    about the copy it is stored in."""
    from app.utils.updates import remembered

    _store(clinic, json.dumps(dict(FOUND, latest=FOUND["installed"])))
    with clinic["app"].app_context(), _installed_as(FOUND["installed"]):
        assert remembered() is None


def test_a_quiet_launch_never_erases_a_notice_that_still_stands(clinic):
    """Offline and up-to-date are the same answer — `None` — and one of them
    must not delete the other's notice."""
    from app.extensions import db
    from app.models import Setting
    from app.utils.updates import STORED, remember

    _store(clinic, json.dumps(FOUND))
    with clinic["app"].app_context():
        assert remember(None) is None
        db.session.commit()
        assert Setting.get(STORED), "a launch with no answer wiped the notice"


@pytest.mark.parametrize("stored", ["", "not json at all", "[]", "{}",
                                    '{"installed": "x"}'])
def test_a_stored_line_it_cannot_read_is_not_a_notice(clinic, stored):
    from app.utils.updates import remembered

    _store(clinic, stored)
    with clinic["app"].app_context():
        assert remembered() is None


class _installed_as:
    """Pretend this copy is a given revision, for the staleness test."""

    def __init__(self, revision):
        self.revision = revision

    def __enter__(self):
        from app.utils import updates

        self.original = updates.installed_revision
        updates.installed_revision = lambda: self.revision
        return self

    def __exit__(self, *exc):
        from app.utils import updates

        updates.installed_revision = self.original


# ------------------------------------------------------------- and the bell

def test_the_bell_carries_it(clinic):
    from app.utils import notifications

    _store(clinic, json.dumps(FOUND))
    with clinic["app"].app_context():
        notifications.invalidate()
        keys = {item["key"] for item in notifications._all()}

    assert "update_available" in keys, "the bell says nothing about an update"


def test_the_bell_is_silent_when_there_is_nothing_to_say(clinic):
    from app.utils import notifications

    _store(clinic, "")
    with clinic["app"].app_context():
        notifications.invalidate()
        keys = {item["key"] for item in notifications._all()}

    assert "update_available" not in keys


def test_only_somebody_who_could_act_on_it_is_told(clinic):
    """It sits under `settings`, which is admin-only. Updating the program is
    not a receptionist's decision, and a notice they cannot act on is noise."""
    from app.utils import notifications

    _store(clinic, json.dumps(FOUND))
    with clinic["app"].app_context():
        notifications.invalidate()
        item = next(i for i in notifications._all()
                    if i["key"] == "update_available")

    assert item["module"] == "settings"


def test_the_bell_never_reaches_the_network(clinic):
    """`_compute` is run with every outbound call in `updates` booby-trapped.

    This is the measurement, not a reading of the code: the bell runs on every
    page, and one network call in it is one per page per user.
    """
    from app.utils import notifications, updates

    def _forbidden(*_a, **_kw):
        raise AssertionError("the bell went to the internet")

    _store(clinic, json.dumps(FOUND))
    original = updates._get, updates.latest_revision, updates.pending
    updates._get = _forbidden
    updates.latest_revision = _forbidden
    updates.pending = _forbidden
    try:
        with clinic["app"].app_context():
            notifications.invalidate()
            keys = {item["key"] for item in notifications._all()}
    finally:
        updates._get, updates.latest_revision, updates.pending = original

    assert "update_available" in keys


# ------------------------------------------------------- and what it points at

def test_the_page_says_what_changed_and_how_to_install_it(clinic):
    _store(clinic, json.dumps(FOUND))
    page = clinic["sign_in"]("boss").get("/update").get_data(as_text=True)

    for note in FOUND["notes"]:
        assert note in page, "the page does not say what changed"
    assert "update.bat" in page, "the page does not say how to install it"


def test_it_is_not_a_page_anybody_can_open(clinic):
    _store(clinic, json.dumps(FOUND))
    desk = clinic["sign_in"]("desk")
    # Signed in for real first — a name nobody has just bounces off the login
    # page, and this would pass while proving nothing.
    assert desk.get("/dashboard").status_code == 200

    res = desk.get("/update", follow_redirects=False)
    assert res.status_code in (302, 403), \
        "somebody who cannot act on it can open the update page"


def test_nothing_on_the_page_can_start_an_update(clinic):
    """The one thing this feature must never grow: a button that replaces the
    files a running program is executing."""
    _store(clinic, json.dumps(FOUND))
    page = clinic["sign_in"]("boss").get("/update").get_data(as_text=True)

    # The page really rendered — otherwise "there is no form on it" is true
    # of an error page too.
    assert "update.bat" in page

    lowered = page.lower()
    for danger in ("<form", "git pull", "method=\"post\"", "subprocess"):
        assert danger not in lowered, \
            f"the update page has grown a way to run something: {danger}"


def test_the_program_still_never_updates_itself(clinic):
    """Read from the parsed module, not from its text — the text explains at
    length why `git pull` was removed, and a search for it matches that."""
    path = os.path.join(HERE, "..", "app", "utils", "updates.py")
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        for doc_owner in (ast.Module, ast.FunctionDef, ast.ClassDef):
            if isinstance(node, doc_owner) and ast.get_docstring(node):
                node.body = node.body[1:]
    stripped = ast.unparse(tree)

    for danger in ("pull", "fetch", "reset", "checkout", "merge"):
        assert danger not in stripped, \
            f"the update module can now change the copy it is running from " \
            f"({danger})"
