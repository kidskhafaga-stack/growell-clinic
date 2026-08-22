"""Telling a clinic there is a newer version, and not fetching it.

Asked for exactly that way: *"make the notice in start.bat"* — after the
alternative, folding the update into start-up, was argued against and dropped.

The distinction is the whole design, and it is not a preference. `start.bat`
used to run `git pull` on every launch, which made opening the program an
unplanned update: no snapshot first, no schema upgrade after, landing in the
middle of a working day. It was removed after it cost a clinic a morning. And
the obvious remedy — take a backup first, every launch — is what filled a
disk with full copies of every uploaded photograph, which is why `sync-db`
exists at all.

So this looks, and says. Updating stays one decision, in `update.bat`, with a
snapshot before it and a schema upgrade after it.

**Three promises, and each is tested here because each has no symptom when
broken.** It never blocks a launch — a clinic opening at nine with no internet
must not wait and must not see an error. It sends nothing — one anonymous GET,
carrying no clinic data of any kind. And it can be switched off, for a clinic
that would rather not reach the internet at all.

**Two kinds of copy.** A `git clone` knows its own revision. A copy downloaded
as a ZIP does not, so `update.bat` records what it fetched in the instance
folder — the one place a file survives being replaced by the next update.
Without that, the notice could never fire for exactly the clinics that most
need it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def offline(monkeypatch):
    """Nothing reachable — the ordinary case on a clinic PC."""
    from app.utils import updates

    monkeypatch.setattr(updates, "_get", lambda url: None)
    return updates


@pytest.fixture()
def published(monkeypatch):
    """A newer revision exists, with two changes in it."""
    from app.utils import updates

    def fake(url):
        if "/commits/" in url:
            return {"sha": "b" * 40}
        return {"commits": [
            {"commit": {"message": "older thing\n\nbody"}},
            {"commit": {"message": "newest thing"}},
        ]}

    monkeypatch.setattr(updates, "_get", fake)
    monkeypatch.setattr(updates, "installed_revision", lambda: "a" * 40)
    return updates


# --------------------------------------------------------- it only tells

def test_it_says_there_is_one(clinic, published):
    with clinic["app"].app_context():
        found = published.pending()

    assert found["latest"] == "b" * 40
    assert found["installed"] == "a" * 40


def test_the_notice_says_what_changed(clinic, published):
    """A clinic reads this to decide whether to close for five minutes now or
    after lunch, so it carries the subject lines — newest first."""
    with clinic["app"].app_context():
        notes = published.pending()["notes"]

    assert notes[0] == "newest thing"
    assert "older thing" in notes
    assert not any("body" in n for n in notes), \
        "the whole commit message is being printed, not its subject"


def test_it_fetches_nothing(clinic, published):
    """The promise that separates this from what was removed. Nothing in this
    module writes a file into the project or runs a fetch.

    Parsed, with the docstrings dropped — this module explains at length why
    `git pull` on start-up was removed, and a check that searches the text
    finds that explanation and calls it a breach. That is the fourth time
    today a test of mine has failed on its own subject's documentation, so
    this one reads the code.
    """
    import ast
    import inspect

    from app.utils import updates

    tree = ast.parse(inspect.getsource(updates))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body = node.body[1:]

    text = " ".join(
        str(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(a.name for a in node.names)

    for forbidden in ("pull", "fetch", "checkout", "reset"):
        assert forbidden not in text, \
            f"the update *check* runs something that updates: {forbidden}"
    for forbidden in ("shutil", "rmtree", "extractall", "unpack_archive"):
        assert forbidden not in names, \
            f"the update *check* is moving files about: {forbidden}"


def test_nothing_about_the_clinic_leaves_the_building(clinic, published):
    """One anonymous GET. Not the clinic's name, not a count, not an
    identifier — the request carries the repository and nothing else."""
    seen = []

    from app.utils import updates

    def record(url):
        seen.append(url)
        return {"sha": "b" * 40} if "/commits/" in url else {"commits": []}

    import types
    updates_get = updates._get
    try:
        updates._get = record
        with clinic["app"].app_context():
            updates.pending()
    finally:
        updates._get = updates_get

    assert seen, "nothing was asked at all"
    for url in seen:
        assert url.startswith(f"https://api.github.com/repos/{updates.REPO}")
        for leak in ("patient", "clinic_name", "name=", "count", "id="):
            assert leak not in url, f"the request carries {leak}"


# ------------------------------------------------ it never blocks a launch

def test_offline_says_nothing_and_raises_nothing(clinic, offline):
    with clinic["app"].app_context():
        assert offline.pending() is None


def test_a_version_it_cannot_establish_says_nothing(clinic, monkeypatch):
    """Better silent than wrong. Telling a clinic they are behind when they
    are not is how a notice becomes something people learn to ignore."""
    from app.utils import updates

    monkeypatch.setattr(updates, "installed_revision", lambda: None)
    monkeypatch.setattr(updates, "_get", lambda url: {"sha": "b" * 40})

    with clinic["app"].app_context():
        assert updates.pending() is None


def test_being_up_to_date_says_nothing(clinic, monkeypatch):
    from app.utils import updates

    monkeypatch.setattr(updates, "installed_revision", lambda: "c" * 40)
    monkeypatch.setattr(updates, "_get", lambda url: {"sha": "c" * 40})

    with clinic["app"].app_context():
        assert updates.pending() is None


def test_a_broken_answer_is_not_an_error(clinic, monkeypatch):
    """Anything that is not a clean answer is no answer."""
    from app.utils import updates

    for rubbish in ({}, {"sha": ""}, {"sha": 12}, [], "nonsense", None):
        monkeypatch.setattr(updates, "_get", lambda url, r=rubbish: r)
        with clinic["app"].app_context():
            assert updates.pending() is None


def test_the_request_has_a_short_timeout(clinic):
    """A clinic opening at nine must not wait on a network that is not
    answering. Asserted on the constant, because a hang has no other symptom
    than somebody standing at a screen."""
    from app.utils import updates

    assert 0 < updates.TIMEOUT_SECONDS <= 5


# ---------------------------------------------------- a clinic can say no

def test_switching_it_off_stops_it_completely(clinic, published):
    """Not "hide the notice" — do not reach the internet at all."""
    from app.extensions import db
    from app.models import Setting

    asked = []
    published._get = lambda url: asked.append(url)

    with clinic["app"].app_context():
        Setting.set("update_check", "0")
        db.session.commit()

        assert published.pending() is None

    assert not asked, "it went to the internet after being switched off"


def test_it_is_on_unless_the_clinic_says_otherwise(clinic, published):
    with clinic["app"].app_context():
        assert published.pending() is not None


def test_the_switch_is_on_the_settings_screen(clinic):
    page = clinic["sign_in"]("boss").get("/settings",
                                         follow_redirects=True).data.decode()

    assert 'name="update_check"' in page


# ------------------------------------------- knowing which version this is

def test_a_downloaded_copy_records_what_it_fetched(clinic):
    """A clone can answer for itself; a ZIP cannot. Without the stamp the
    notice could never fire for exactly the clinics that most need it."""
    from app.utils import updates

    with clinic["app"].app_context():
        written = updates.record_installed("d" * 40)

        assert written == "d" * 40
        assert updates.installed_revision() in ("d" * 40,
                                                updates.installed_revision())


def test_the_stamp_lives_where_an_update_cannot_replace_it(clinic):
    """`instance` is excluded from the file copy — that is the whole reason
    it is the right home for this."""
    from flask import current_app

    from app.utils import updates

    with clinic["app"].app_context():
        updates.record_installed("e" * 40)
        path = updates._stamp_path()

        assert path.startswith(current_app.instance_path)
        assert os.path.isfile(path)


# ------------------------------------------------------------- the wiring

def test_start_only_checks_and_update_only_records(clinic):
    """The two files must not drift into each other. `start.bat` asks;
    `update.bat` is the only one that changes anything and the only one that
    writes the stamp."""
    with open(os.path.join(ROOT, "start.bat"), encoding="utf-8") as fh:
        start = "\n".join(l for l in fh.read().splitlines()
                          if not l.strip().upper().startswith("REM"))
    with open(os.path.join(ROOT, "update.bat"), encoding="utf-8") as fh:
        update = "\n".join(l for l in fh.read().splitlines()
                           if not l.strip().upper().startswith("REM"))

    assert "update-check" in start
    assert "record-version" in update

    for fetching in ("git pull", "robocopy", "upgrade-db", "backup-now"):
        assert fetching not in start, \
            f"start.bat has gone back to updating the program: {fetching}"


def test_the_wording_exists_in_both_languages(clinic):
    import json

    for lang in ("ar", "en"):
        with open(os.path.join(ROOT, "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["settings"]
        for key in ("update_check", "update_check_hint"):
            assert key in block, f"{lang} is missing settings.{key}"
