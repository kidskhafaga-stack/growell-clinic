"""Two things that were about to restart the clinic on top of each other.

A clinic installed as a Windows service runs under two scheduled tasks: one
serves, and one — the watchdog — asks every five minutes whether the clinic is
answering and restarts it twice-refused.

An update deliberately closes the clinic and then spends **longer than five
minutes** on it: a full backup, a download, a dependency install, a schema
upgrade, a startup check. Nothing told the watchdog. So on any service install
it was going to relaunch the program into the middle of the file copy — a
Python process reading modules that are being overwritten underneath it, which
is the half-new-half-old failure the whole hand-off design exists to prevent,
arriving by the one route nobody was watching. Not a race that might happen:
five minutes against an operation that cannot finish in five.

And when the update did finish, it ran `start.bat` — the launcher for a
clinic run by hand. On a service install that is a second copy beside the
service, both wanting the same port. *"لو البرنامج بالسيرفر شغال وهو عمل
اب ديت مش لازم يعمل استارت، ممكن يعمل ريستارت للسيرفر."*

The marker expires by itself, and every way the update stops clears it. An
update that died must not leave a clinic unwatched: a clinic restarted
mid-update is a bad afternoon, one with no watchdog at all is a bad month
nobody notices.
"""
import os
import time

import pytest

from app import update_guard


@pytest.fixture
def root(tmp_path):
    return str(tmp_path)


# --------------------------------------------------------------- the marker --
def test_nothing_is_in_progress_to_begin_with(root):
    assert update_guard.in_progress(root) is False


def test_marking_says_an_update_is_running(root):
    update_guard.mark(root)
    assert update_guard.in_progress(root) is True


def test_clearing_hands_the_clinic_back(root):
    update_guard.mark(root)
    update_guard.clear(root)
    assert update_guard.in_progress(root) is False


def test_clearing_what_was_never_marked_is_not_an_error(root):
    """Every exit path calls it, including ones the marker never reached."""
    assert update_guard.clear(root) is False


def test_it_lives_beside_the_database_not_beside_the_code(root):
    """The code directory is the thing being overwritten while this file has
    to keep meaning something."""
    assert os.path.dirname(update_guard.marker_path(root)).endswith("instance")


# ------------------------------------------------------------ going stale ----
def test_an_update_that_died_does_not_silence_the_watchdog_for_ever(root):
    """A power cut between the backup and the copy leaves the marker behind.
    After the window the watchdog goes back to work on its own."""
    update_guard.mark(root)
    later = time.time() + update_guard.STALE_AFTER_MINUTES * 60 + 1
    assert update_guard.in_progress(root, now=later) is False


def test_it_still_holds_inside_the_window(root):
    """The window has to outlast a real update or it protects nothing."""
    update_guard.mark(root)
    soon = time.time() + update_guard.STALE_AFTER_MINUTES * 60 - 60
    assert update_guard.in_progress(root, now=soon) is True


def test_the_window_outlasts_the_watchdogs_own_cycle(root):
    """Five minutes is what it is being protected from."""
    assert update_guard.STALE_AFTER_MINUTES * 60 > 5 * 60


def test_a_marker_nobody_can_read_is_not_trusted(root):
    """A half-written file, or one from a version that wrote something else.
    Unreadable means "no update", never "an update for ever"."""
    path = update_guard.marker_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("not a time")
    assert update_guard.in_progress(root) is False


def test_a_marker_from_the_future_is_not_trusted(root):
    """Somebody moved the clock. Trusting it would disable the watchdog until
    that time arrives."""
    path = update_guard.marker_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(int(time.time()) + 86400))
    assert update_guard.in_progress(root) is False


# ------------------------------------------------- what the batch files do ---
def _script(name):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root, name), encoding="utf-8") as fh:
        return fh.read()


def test_the_watchdog_asks_before_it_restarts_anything():
    """And asks *first* — after the health check it would already have
    decided the clinic was dead."""
    text = _script("watchdog.bat")
    assert "app.update_guard" in text
    assert text.index("app.update_guard") < text.index("app.health_check")


def test_the_watchdog_still_restarts_a_clinic_that_is_merely_down():
    """The guard must not turn the watchdog off."""
    text = _script("watchdog.bat")
    assert 'schtasks /Run /TN "GrowellClinic"' in text


def test_the_update_raises_the_marker_before_the_backup():
    """The backup alone can outlast the watchdog's cycle, so the marker has
    to be up before it starts, not before the copy."""
    text = _script("update.bat")
    assert "app.update_guard start" in text
    assert text.index("app.update_guard start") < text.index("backup-now")


def test_every_way_the_update_stops_hands_the_watchdog_back():
    """One way out. A `exit /b 1` that skipped the marker would leave the
    clinic unwatched until the window expired."""
    text = _script("update.bat")
    assert ":die" in text
    # The only bare failure exit is the one inside :die itself.
    assert text.count("exit /b 1") == 1


def test_the_update_restarts_the_service_rather_than_starting_a_second_copy():
    """It ran start.bat regardless — a hand-run copy beside the service, both
    wanting the same port."""
    text = _script("update.bat")
    tail = text.split("app.update_guard done")[1]
    assert 'schtasks /Query /TN "GrowellClinic"' in tail
    assert 'schtasks /Run /TN "GrowellClinic"' in tail


def test_a_machine_without_the_service_still_gets_start_bat():
    """Most clinics run it by hand, and they must keep coming back up."""
    text = _script("update.bat")
    tail = text.split("app.update_guard done")[1]
    assert "start.bat" in tail


# ------------------------------------------- the download that looked hung --
def _update_bat():
    import io
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    with io.open(os.path.join(here, "..", "update.bat"),
                 encoding="utf-8", newline="") as handle:
        return handle.read()


def test_the_progress_bar_is_off():
    """Windows PowerShell 5.1 redraws Invoke-WebRequest's progress bar on
    every chunk, and the redraw costs more than the download.

    Reported from a clinic as an update that stopped: the screen showed
    "Writing request stream... (Number of bytes written: 35105)" and sat
    there. It was not stopped. It was drawing.
    """
    assert "$ProgressPreference='SilentlyContinue'" in _update_bat()


def test_the_archive_is_not_unpacked_a_file_at_a_time():
    """`Expand-Archive` is slow per *file*, not per byte, and this project is
    763 of them — its worst case, in silence. The .NET call does the same job
    in seconds."""
    body = _update_bat()
    assert "ExtractToDirectory" in body
    live = [line for line in body.split("\r\n")
            if not line.strip().startswith("REM")]
    assert not any("Expand-Archive" in line for line in live), \
        "Expand-Archive is back in a line that runs"


def test_it_says_it_is_working():
    """Two lines, because the two slow parts are at opposite ends and a
    clinic staring at a still screen presses Ctrl-C."""
    body = _update_bat()
    assert "Downloading" in body
    assert "Unpacking" in body


def test_the_download_block_has_no_stray_bracket():
    """The bug this file has been bitten by twice: a `)` inside a
    parenthesised block closes it where it stands, and the rest of the block
    runs unconditionally."""
    live = [line for line in _update_bat().split("\r\n")
            if not line.strip().startswith("REM")]
    assert not any(") else (" in line for line in live)
