"""Whether an update is running right now. Exit 0 if one is.

Run by ``watchdog.bat`` as ``python -m app.update_guard``, before it decides
the clinic is dead.

**The watchdog and the updater were about to fight over the same files.** The
watchdog asks the clinic every five minutes whether it is answering and
restarts it twice-refused; an update deliberately closes the clinic and then
spends longer than five minutes taking a backup, downloading, installing
dependencies and upgrading the database. So on any service install the
watchdog was going to relaunch the program *into the middle of the file copy*
— a Python process reading modules that are being replaced underneath it,
which is the half-new-half-old failure the whole hand-off design exists to
prevent, arriving by the one route nobody was watching.

The marker is a file rather than a lock or a port, because it has to survive
the updater's own restarts of the shell and be readable by a batch file that
cannot do arithmetic on a timestamp.

**And it goes stale on purpose.** An update that dies — a power cut between
the backup and the copy — must not leave a clinic with no watchdog for ever.
After :data:`STALE_AFTER_MINUTES` the marker is ignored and the watchdog goes
back to work: a clinic briefly restarted mid-update is a bad afternoon, and a
clinic with no watchdog at all is a bad month nobody notices.
"""
import os
import sys
import time

MARKER = "updating.flag"

# Longer than any update should take, short enough that a marker left behind
# by a failed one does not disable the watchdog through a weekend. `update.bat`
# takes a full backup, downloads, installs and upgrades; forty minutes is the
# far end of that on a slow clinic PC with a large database.
STALE_AFTER_MINUTES = 40


def _root():
    return os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def marker_path(root=None):
    """Beside the database, not beside the code.

    The whole point of an update is that the code directory is being
    overwritten while this file has to keep meaning something.
    """
    return os.path.join(root or _root(), "instance", MARKER)


def mark(root=None):
    """Say an update has started. Returns the path written."""
    path = marker_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(int(time.time())))
    return path


def clear(root=None):
    """Say it has finished — however it finished.

    Called on the failure paths too. An update that gave up is over, and the
    clinic should be watched again from that moment rather than from whenever
    the marker happens to go stale.
    """
    try:
        os.remove(marker_path(root))
        return True
    except OSError:
        return False


def in_progress(root=None, now=None):
    """Whether an update is running, as far as anybody can tell from disk."""
    path = marker_path(root)
    try:
        with open(path, encoding="utf-8") as fh:
            started = int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return False
    now = time.time() if now is None else now
    # A marker with no readable time, or one from the future because somebody
    # moved the clock, is treated as stale rather than trusted for ever.
    if started <= 0 or started > now + 60:
        return False
    return (now - started) < STALE_AFTER_MINUTES * 60


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "start":
        print(mark())
        return 0
    if argv and argv[0] == "done":
        clear()
        return 0
    # Default: report. 0 means "an update is running, leave the clinic alone".
    return 0 if in_progress() else 1


if __name__ == "__main__":
    raise SystemExit(main())
