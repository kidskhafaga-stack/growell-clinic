"""The update finishes by opening the program, and only when it worked.

Asked directly: *"يعني دلوقتي أقدر أعمل update من البرنامج زي بتاع الراوتر؟
وهو يقفل البرنامج ويعمل ريستارت ويبدأ البرنامج؟"* — the closing and the
updating were already there; the last step was not. `update.bat` ended at
``pause`` and a clinic had to go and run ``start.bat`` themselves.

**The condition is the whole feature.** Step [5/5] loads the app and asks it
for a page, so "it starts" is measured rather than assumed. Reopening is
allowed to happen only past that gate: an update that broke something must
leave a window with the error on it, not a program that reopens on top of the
message nobody read.

This is a Windows batch file and cannot be executed here, so these read it.
That is a real limit and worth stating: they prove the relaunch sits behind
the gate and that no failure path lost its ``pause``. They cannot prove
``start.bat`` comes up on a clinic's PC.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPDATE = (ROOT / "update.bat").read_text(encoding="utf-8")
HANDOFF = (ROOT / "update_now.bat").read_text(encoding="utf-8")

RELAUNCH = 'start "" "%~dp0start.bat"'


def test_the_update_opens_the_program_when_it_is_done():
    assert UPDATE.count(RELAUNCH) == 1, \
        "the update does not open the program again, or does it more than once"


def test_it_only_opens_it_after_the_check_that_it_starts():
    """The gate. Before [5/5] the program has not been asked whether it runs,
    and reopening a copy that does not is worse than not reopening at all."""
    check = UPDATE.index("[5/5] Checking the program starts")

    assert UPDATE.index(RELAUNCH) > check, \
        "the program is reopened before anything checked that it starts"


def test_every_failure_still_stops_with_something_to_read():
    """`pause` on the error paths is what makes the success path safe to close
    by itself. If a failure exited silently, a clinic would see a window flash
    and have no idea an update had failed.

    Two shapes, because the script has two. An error raised in the main flow
    pauses where it is raised; an error raised inside a subroutine exits with
    a code and is read at the call site — the first version of this test only
    knew the first shape and reported the second as a bug."""
    main = UPDATE[:UPDATE.index(RELAUNCH)]

    for block in main.split("[ERROR]")[1:]:
        upto = block.split("exit /b 1")[0]
        assert "pause" in upto, \
            f"a failure in the main flow exits unread: {upto[:120]!r}"

    for call in re.finditer(r"call :(\w+)\s*\r?\n\s*if errorlevel 1 \((.*?)\)",
                            UPDATE, re.S):
        assert "pause" in call.group(2), \
            f"the failure of :{call.group(1)} is never stopped on"


def test_the_success_path_does_not_wait_for_a_keypress():
    """It was there to say "now go and run start.bat", and there is nothing
    left to say. A window waiting for a keypress it does not need is a window
    a clinic learns to click past."""
    tail = UPDATE[UPDATE.index(RELAUNCH):]

    assert "pause" not in tail, \
        "the update opens the program and then still waits for a keypress"


def test_it_starts_a_window_rather_than_becoming_one():
    """`start.bat` runs the server in the foreground of whatever window calls
    it. Calling it directly would leave the updater and the clinic sharing one
    window and one Ctrl-C."""
    assert "call \"%~dp0start.bat\"" not in UPDATE
    assert RELAUNCH in UPDATE


def test_the_hand_off_still_waits_for_the_program_to_die_first():
    """Unchanged by any of this, and the reason the whole flow is safe: the
    updater watches for the process to be gone before it writes a file, and
    gives up rather than updating underneath a program that will not close."""
    assert "tasklist /FI" in HANDOFF
    assert "NOTHING has been changed" in HANDOFF


def test_the_screen_no_longer_tells_people_to_start_it_themselves(clinic):
    """The instructions and the script have to agree. A screen still saying
    "now run start.bat" after the script does it is how a clinic ends up with
    two copies of the program open on one port.

    Read from the settings panel, which is where all of this lives now — there
    was a second screen for the steps and the button, and it was folded in."""
    import json

    from app.extensions import db
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("update_pending", json.dumps(
            {"installed": "a" * 40, "latest": "b" * 40, "notes": []}))
        db.session.commit()

    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "update.bat" in page, "the manual route is no longer explained"
    assert "لوحده" in page or "by itself" in page, \
        "the screen does not say the program comes back on its own"
