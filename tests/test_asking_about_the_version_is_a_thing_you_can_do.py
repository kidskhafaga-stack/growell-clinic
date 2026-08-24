"""The program can be asked about its version, not only told at start-up.

Reported: *"بالنسبة للابديت مبقتش بشوف الإشعار"*.

Nothing was broken. The check ran in exactly one place — the launch hook in
``app/cli.py`` — and `pending()` was called from nowhere else in the program.
So a clinic that leaves the program open all week is told about a release the
following Monday, and one whose connection was down at nine o'clock is not told
at all until the next restart. The machinery was all there: a stored answer, a
bell item, a whole update page, even a hand-off updater. **The missing verb was
"ask".**

**And it still only ever says.** Updating stays one decision somebody makes in
`update.bat`, with a backup in front of it and a schema upgrade after — the
reason the launch check was a notice and not an action in the first place. This
adds a button that asks; it adds no button that updates.

**"Up to date" and "could not reach GitHub" are different facts.** `pending()`
answers ``None`` to both, which is right for a notice at start-up — all the
silent cases look the same to somebody opening the program. It is wrong for a
person who just pressed a button and is waiting, so the route separates them.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HERE = "a" * 40
THERE = "b" * 40


@pytest.fixture()
def admin(clinic):
    return clinic


def _check(clinic):
    return clinic["sign_in"]("boss").post("/settings/update/check").get_json()


def _patch(monkeypatch, *, installed, latest, notes=()):
    from app.utils import updates

    monkeypatch.setattr(updates, "installed_revision", lambda: installed)
    monkeypatch.setattr(updates, "latest_revision", lambda: latest)
    monkeypatch.setattr(updates, "notes_between",
                        lambda a, b, limit=5: list(notes))


# --------------------------------------------------- asking, and answers

def test_a_newer_version_is_reported_with_what_is_in_it(admin, monkeypatch):
    _patch(monkeypatch, installed=HERE, latest=THERE,
           notes=["Eight things a clinic found by using the program"])

    answer = _check(admin)

    assert answer["ok"] is True and answer["behind"] is True
    assert answer["latest"] == THERE
    assert answer["notes"], "it said there was an update and not what was in it"


def test_being_up_to_date_is_an_answer_and_not_a_silence(admin, monkeypatch):
    _patch(monkeypatch, installed=HERE, latest=HERE)

    answer = _check(admin)

    assert answer["ok"] is True and answer["behind"] is False


def test_offline_is_not_reported_as_up_to_date(admin, monkeypatch):
    """The distinction the whole route exists for. `pending()` answers None to
    both, which is right for a notice nobody asked for and wrong for a person
    watching a spinner: one means there is nothing new, the other means nobody
    could find out."""
    _patch(monkeypatch, installed=HERE, latest=None)

    answer = _check(admin)

    assert answer["ok"] is False and answer["reason"] == "unreachable"


def test_a_copy_that_cannot_say_what_it_is_says_that(admin, monkeypatch):
    """Files replaced by hand, never stamped. Answering "up to date" here
    would be a guess, and a wrong one is how a notice becomes something people
    learn to ignore."""
    _patch(monkeypatch, installed=None, latest=THERE)

    answer = _check(admin)

    assert answer["ok"] is False and answer["reason"] == "unknown_version"


def test_what_it_found_is_kept_for_the_bell(admin, monkeypatch):
    """The bell reads what was stored rather than asking again, so a check
    made here has to leave the same trace a launch would."""
    from app.models import Setting

    _patch(monkeypatch, installed=HERE, latest=THERE, notes=["something"])
    _check(admin)

    with admin["app"].app_context():
        assert Setting.get("update_pending"), \
            "the answer was shown once and not kept"


def test_a_check_that_finds_nothing_clears_a_stale_notice(admin, monkeypatch):
    """Somebody who has just updated presses this to confirm. A notice left
    sitting on the bell afterwards is the program contradicting itself."""
    from app.models import Setting

    _patch(monkeypatch, installed=HERE, latest=THERE, notes=["old news"])
    _check(admin)

    _patch(monkeypatch, installed=HERE, latest=HERE)
    _check(admin)

    from app.utils.updates import remembered

    with admin["app"].app_context():
        assert remembered() is None, "the bell still says there is an update"
        assert Setting.get("update_pending") in (None, "", "null")


# ------------------------------------------------- it never updates here

def test_the_route_does_not_update_anything(admin, monkeypatch):
    """The line the launch check was built to hold. Replacing the files a
    running process is executing is not a theoretical problem, and this button
    must not be the place it starts."""
    import inspect

    from app.blueprints.settings.routes import update_check_now

    source = inspect.getsource(update_check_now)

    for verb in ("hand_off", "close_after", "subprocess", "robocopy"):
        assert verb not in source, \
            f"the version check reaches for {verb}; updating is update.bat's job"


def test_it_is_admin_only(admin):
    """Updating is not a receptionist's decision, and a notice they cannot act
    on is noise. The bell item is already filed under `settings` for that
    reason; the button has to agree."""
    answer = admin["sign_in"]("desk").post("/settings/update/check")

    assert answer.status_code in (302, 403), \
        "reception can ask the program to phone GitHub"


# ----------------------------------------------------------- the screen

def test_the_settings_screen_has_somewhere_to_ask(admin):
    page = admin["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "/settings/update/check" in page, "there is no way to ask"
    assert "tab==='update'" in page, "the panel is not on any tab"


def test_the_launch_toggle_is_on_the_same_screen(admin):
    """`update_check` decides whether the program asks at start-up. Keeping it
    anywhere other than beside the version is how a clinic turns off a notice
    and then wonders why it never hears about releases."""
    page = admin["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert 'name="update_check"' in page


def test_the_screen_says_what_it_sends(admin):
    """One anonymous GET carrying no clinic data. A clinic being asked to let
    the program reach the internet is owed the sentence, on the screen where
    they decide."""
    from app.i18n import t  # noqa: F401

    page = admin["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "من غير أي بيانات عن العيادة" in page or "no clinic data" in page


def test_being_offline_never_wipes_a_notice_nobody_acted_on(admin, monkeypatch):
    """The reason `forget()` is its own verb rather than `remember(None)`.

    A clinic is told there is an update and does not act on it that morning.
    The connection blips. If "found nothing" cleared the store, the notice
    would be gone and the clinic would never hear about that release again —
    because the next check compares against the same installed revision and
    finds the same answer it just threw away.
    """
    from app.utils.updates import remembered

    _patch(monkeypatch, installed=HERE, latest=THERE, notes=["real news"])
    _check(admin)

    _patch(monkeypatch, installed=HERE, latest=None)      # the connection drops
    answer = _check(admin)

    assert answer["reason"] == "unreachable"
    with admin["app"].app_context():
        assert remembered(), "a network blip threw away a real notice"


def test_forgetting_is_a_verb_of_its_own(admin, monkeypatch):
    """Pinned at the source, not only through the route: the next person to
    read `remember()` should not be able to 'tidy it up' by making a falsy
    argument clear the store."""
    import inspect

    from app.utils import updates

    remember_src = inspect.getsource(updates.remember)

    assert "forget" not in remember_src
    assert callable(getattr(updates, "forget", None)), \
        "clearing a notice has no verb of its own"
