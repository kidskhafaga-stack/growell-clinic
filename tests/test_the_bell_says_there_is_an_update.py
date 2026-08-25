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

def test_the_page_says_how_to_install_it_and_which_version(clinic):
    """This used to also assert the page listed what changed, and it did.

    So did the settings tab — which left a clinic with the version, the check
    button and the launch toggle on one screen, the steps and the install
    button on another, and the release notes on both. Half the facts on each,
    and you had to know which half was where.

    There is one screen now — asked for after living with the split, because
    finding your way was worth more than whatever the separation bought. So
    everything about the version is on it: what is installed, what is waiting,
    what is in it, and how to put it on."""
    _store(clinic, json.dumps(FOUND))
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "update.bat" in page, "the screen does not say how to install it"
    assert FOUND["latest"][:12] in page, \
        "the screen does not say which version it is installing"
    for note in FOUND["notes"]:
        assert note in page, \
            "the one screen does not say what is in the release"


def test_it_is_not_a_page_anybody_can_open(clinic):
    _store(clinic, json.dumps(FOUND))
    desk = clinic["sign_in"]("desk")
    # Signed in for real first — a name nobody has just bounces off the login
    # page, and this would pass while proving nothing.
    assert desk.get("/dashboard").status_code == 200

    res = desk.get("/update/install", follow_redirects=False)
    assert res.status_code in (302, 403), \
        "somebody who cannot act on it can open the update page"
    # And the screen it now redirects to is admin-only in its own right, so
    # the redirect is not a way round the door.
    assert desk.get("/settings/", follow_redirects=False).status_code in (302, 403)


def test_the_page_never_updates_the_program_it_is_running_in(clinic,
                                                              monkeypatch):
    """The one line this feature must never cross.

    The page *does* have a button now — deliberately, and it does not update
    anything. It starts a separate program, hands it this process's id, and
    closes the clinic; that program sits watching until this one is gone
    before it writes a single file.

    Replacing the files a running Python process is executing leaves half the
    modules on disk new and half of what is in memory old, and nobody finds
    out until a request lands on the seam. So the order is the contract: hand
    off, then close, then write. This test holds the first two — nothing is
    started without the hand-off going first, and the program only closes
    once it has.
    """
    from app.utils import updates

    order = []
    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    monkeypatch.setattr(updates, "hand_off",
                        lambda: order.append("hand_off") or True)
    monkeypatch.setattr(updates, "close_after",
                        lambda *a, **k: order.append("close"))

    _store(clinic, json.dumps(FOUND))
    res = clinic["sign_in"]("boss").post(
        "/update/start", data={"csrf_token": "x"}, follow_redirects=True)

    assert res.status_code == 200
    assert order == ["hand_off", "close"], \
        f"the program closed without handing the job over first: {order}"


def test_a_hand_off_that_did_not_start_leaves_the_clinic_running(clinic,
                                                                  monkeypatch):
    """No updater, no shutdown. A program that closed itself and started
    nothing is a clinic staring at a dead browser tab in the middle of a
    working day, with no update and no way back except the power button."""
    from app.utils import updates

    closed = []
    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    monkeypatch.setattr(updates, "hand_off", lambda: False)
    monkeypatch.setattr(updates, "close_after",
                        lambda *a, **k: closed.append(True))

    _store(clinic, json.dumps(FOUND))
    res = clinic["sign_in"]("boss").post(
        "/update/start", data={"csrf_token": "x"}, follow_redirects=True)

    assert res.status_code == 200
    assert not closed, "the program shut itself down with no updater waiting"


def test_it_will_not_close_the_clinic_for_an_update_that_is_not_there(
        clinic, monkeypatch):
    from app.utils import updates

    closed = []
    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    monkeypatch.setattr(updates, "hand_off", lambda: closed.append("started"))
    monkeypatch.setattr(updates, "close_after",
                        lambda *a, **k: closed.append("closed"))

    _store(clinic, "")          # nothing pending
    clinic["sign_in"]("boss").post("/update/start", data={"csrf_token": "x"},
                                   follow_redirects=True)

    assert not closed, f"the clinic was closed for nothing: {closed}"


def test_only_an_admin_can_close_the_clinic(clinic, monkeypatch):
    from app.utils import updates

    closed = []
    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    monkeypatch.setattr(updates, "hand_off", lambda: closed.append("started"))
    monkeypatch.setattr(updates, "close_after",
                        lambda *a, **k: closed.append("closed"))

    _store(clinic, json.dumps(FOUND))
    desk = clinic["sign_in"]("desk")
    assert desk.get("/dashboard").status_code == 200
    desk.post("/update/start", data={"csrf_token": "x"}, follow_redirects=True)

    assert not closed, "a receptionist closed the clinic"


def test_the_button_is_only_offered_where_it_can_work(clinic, monkeypatch):
    """A copy without the hand-off script, or one not on Windows, gets the
    instructions and no button — rather than a button that quietly does
    nothing, which is the worse of the two by a distance."""
    from app.utils import updates

    _store(clinic, json.dumps(FOUND))
    boss = clinic["sign_in"]("boss")

    monkeypatch.setattr(updates, "can_hand_off", lambda: False)
    page = boss.get("/settings/").get_data(as_text=True)
    assert "update.bat" in page, "the steps did not render at all"
    assert "/update/start" not in page, \
        "a button was offered on a copy that cannot use it"

    monkeypatch.setattr(updates, "can_hand_off", lambda: True)
    assert "/update/start" in boss.get("/settings/").get_data(as_text=True)


def test_the_hand_off_script_waits_before_it_writes(clinic):
    """Read out of the script itself. Its whole job is the waiting; a version
    of it that called `update.bat` first would look almost identical and would
    be the bug this feature exists to avoid."""
    path = os.path.join(HERE, "..", "update_now.bat")
    with open(path, encoding="utf-8") as fh:
        # `REM` lines explain at length why the waiting matters, and a search
        # over them would match the explanation rather than the script.
        lines = [ln for ln in fh.read().splitlines()
                 if not ln.strip().lower().startswith("rem")]

    body = "\n".join(lines).lower()
    wait_at = body.index("tasklist")
    call_at = body.index("call ")
    assert wait_at < call_at, \
        "the updater calls update.bat before it has waited for anything"
    assert "%~1" in body, "it does not take the process id to wait for"
    # It gives up rather than updating a program that would not close.
    assert "exit /b 1" in body


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


# ------------------------------------- and the copy that was downloaded

@pytest.fixture()
def downloaded(clinic, tmp_path, monkeypatch):
    """A copy that was downloaded rather than cloned: no `.git` to ask.

    Its stamp lives under the same temporary folder, so each test starts with
    a copy that has never been stamped — otherwise one test's version is still
    on disk for the next, and "it wrote nothing down" and "it wrote down what
    was already there" look identical.
    """
    from app.utils import updates

    monkeypatch.setattr(updates, "_root", lambda: str(tmp_path))
    monkeypatch.setattr(updates, "_stamp_path",
                        lambda: str(tmp_path / "instance" / updates.STAMP))
    return clinic


def test_a_downloaded_copy_stops_being_told_to_update(downloaded, monkeypatch):
    """The case that made this worth chasing.

    A `git clone` answers "which revision am I" from git, so an update moves it
    on its own. A copy that was downloaded as a ZIP cannot, and reads the stamp
    `update.bat` wrote instead — which means asking it what it is *after* an
    update returns what it was *before* one.

    `record-version` runs at the end of every update with no argument, so it
    asked exactly that question and wrote the old answer straight back. The
    stamp never moved. A clinic that updates by downloading was told there was
    a newer version for ever, at every launch, with a badge on the bell that
    never cleared — which is how a notice becomes something people learn to
    ignore, and the one thing this feature cannot afford.
    """
    from app.utils import updates

    old, new = "1" * 40, "2" * 40

    with downloaded["app"].app_context():
        updates.record_installed(old)
        assert updates.installed_revision() == old

        # The update ran: the files on disk are `new` now. Nothing about a
        # downloaded copy says so, which is the whole problem.
        monkeypatch.setattr(updates, "latest_revision", lambda: new)
        updates.record_installed()

        assert updates.installed_revision() == new, \
            "a downloaded copy still calls itself the version it replaced"

    _store(downloaded, json.dumps({"installed": old, "latest": new,
                                   "notes": []}))
    with downloaded["app"].app_context():
        assert updates.remembered() is None, \
            "the bell goes on telling a clinic to install what it just installed"


def test_the_revision_it_was_handed_wins(downloaded):
    """`update.bat` knows exactly which commit it downloaded, because it asks
    for that commit by name. Nothing should second-guess it."""
    from app.utils import updates

    with downloaded["app"].app_context():
        assert updates.record_installed("3" * 40) == "3" * 40
        assert updates.installed_revision() == "3" * 40


def test_it_never_invents_a_version_it_could_not_establish(downloaded,
                                                           monkeypatch):
    """Offline at the end of an update, with no revision given.

    Writing anything down here would be a guess, and a wrong stamp is worse
    than none: it tells a clinic they are current when they are not.
    """
    from app.utils import updates

    with downloaded["app"].app_context():
        monkeypatch.setattr(updates, "latest_revision", lambda: None)
        assert updates.record_installed() is None
        assert updates.installed_revision() is None


def test_a_clinic_that_switched_the_check_off_is_not_shown_a_stale_one(clinic,
                                                                      monkeypatch):
    """Off means off. A notice stored by an earlier launch must not go on
    sitting on the bell after somebody turns the check off."""
    from app.utils import updates

    _store(clinic, json.dumps(FOUND))
    with clinic["app"].app_context():
        assert updates.remembered() is not None
        monkeypatch.setattr(updates, "_enabled", lambda: False)
        assert updates.remembered() is None


def test_something_that_is_not_a_commit_is_not_written_down(downloaded,
                                                            monkeypatch):
    """The revision reaches Python from a PowerShell command inside a batch
    file. A warning line, or a proxy's error page, arrives down the same pipe.

    A stamp that says something other than a commit can never match anything,
    so the clinic would be told to update for ever — the same failure this
    whole change exists to fix, arriving by a different door.
    """
    from app.utils import updates

    with downloaded["app"].app_context():
        monkeypatch.setattr(updates, "latest_revision", lambda: None)
        for rubbish in ("WARNING: TLS is deprecated", "<html>404</html>",
                        "not-a-sha", "", "   "):
            assert updates.record_installed(rubbish) is None, rubbish
            assert updates.installed_revision() is None


def test_a_short_revision_is_still_a_revision(downloaded):
    """git can be asked for an abbreviated one, and a clinic may have stamped
    a copy by hand. Both are commits."""
    from app.utils import updates

    with downloaded["app"].app_context():
        assert updates.record_installed("a1b2c3d") == "a1b2c3d"
