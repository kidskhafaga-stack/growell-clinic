"""Is there a newer version, and what is in it.

Asked for as a notice and deliberately not as an action: *"start.bat should
tell you there is an update, without doing it."*

The distinction is the whole design. `start.bat` used to run `git pull` on
every launch, which made opening the program an unplanned update — no snapshot
first, no schema upgrade after, landing in the middle of a working day. That
was removed after it cost a clinic a morning. Bringing it back with a backup
in front of it is worse, not better: taking a full snapshot on every start is
what filled the disk and is exactly why `sync-db` exists.

So this looks, and says. Updating stays one decision somebody makes, in
`update.bat`, with a backup before it and a schema upgrade after it.

**It never blocks the program.** A clinic opening at nine with no internet
must not wait, and must not see an error about something that does not matter.
Every path here has a short timeout and returns None rather than raising.

**It sends nothing.** One HTTP GET to GitHub's public API, carrying no clinic
data of any kind — not the name, not a count, not an identifier. What comes
back is a commit hash and some subject lines. A clinic that would rather not
reach the internet at all turns `update_check` off in settings, and the whole
module returns None.

**Two kinds of copy, two ways of knowing which version this is.** A `git
clone` knows its own revision. A copy that was downloaded as a ZIP does not,
so `update.bat` writes the revision it fetched into the instance folder — the
one place a file survives being replaced by the next update.
"""
import json
import os
import subprocess
import urllib.request

# The project's own repository, the same one `update.bat` fetches from.
REPO = "kidskhafaga-stack/growell-clinic"
BRANCH = "main"

# Short on purpose. This runs while somebody is waiting for the program to
# open, and the answer is never worth a pause anybody would notice.
TIMEOUT_SECONDS = 3

# Where a downloaded copy records what it is. Inside `instance` because that
# is the one folder an update does not replace.
STAMP = "installed_revision.txt"


# Where the answer is kept between the launch that asked and the screens that
# show it.
STORED = "update_pending"


def remember(found):
    """Store what the launch check found, so nothing else has to ask again."""
    from app.extensions import db
    from app.models import Setting

    if not found:
        return None
    Setting.set(STORED, json.dumps(found))
    db.session.commit()
    return found


def remembered():
    """What the last launch check found, or None.

    The bell reads this and never reaches the network itself. Computing the
    notice on the bell's own schedule would have turned one request per launch
    into one every ninety seconds — on a program whose whole promise about this
    feature is that it does not talk to anybody about the clinic — and would
    have put a three-second timeout in front of pages a receptionist opens all
    day.

    It goes stale on its own. The stored answer names the revision that was
    newest when somebody last launched; once this copy *is* that revision there
    is nothing to say, and a clinic that has already updated must not go on
    being told to. Which is also why nothing ever writes an empty value here:
    a launch with no internet returns "no news" exactly like a launch that is
    up to date, and clearing on that would delete a notice that is still true.
    """
    from app.models import Setting

    # Off means off. A notice a launch stored earlier must not go on sitting
    # on the bell after somebody switches the check off — the setting is about
    # whether the clinic wants to be told, not only about whether it asks.
    if not _enabled():
        return None
    try:
        raw = Setting.get(STORED)
    except Exception:  # noqa: BLE001 — the settings table may not be ready
        return None
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(found, dict) or not found.get("latest"):
        return None
    if found.get("latest") == installed_revision():
        return None
    return found


def _enabled():
    """Whether the clinic wants this asked at all."""
    try:
        from app.models import Setting

        return (Setting.get("update_check", "1") or "1").strip() != "0"
    except Exception:      # noqa: BLE001 — no database yet, or none needed
        return True


def _root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _stamp_path():
    from flask import current_app

    return os.path.join(current_app.instance_path, STAMP)


def installed_revision():
    """The revision this copy is running, or None if it cannot be known.

    A clone is asked directly; anything else is read from the stamp. Neither
    is guessed at: a wrong answer here means telling a clinic they are behind
    when they are not, which is how a notice becomes something people learn to
    ignore.
    """
    root = _root()
    if os.path.isdir(os.path.join(root, ".git")):
        try:
            out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                 capture_output=True, text=True,
                                 timeout=TIMEOUT_SECONDS)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:  # noqa: BLE001 — no git, or not a usable repo
            pass
    try:
        with open(_stamp_path(), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except Exception:      # noqa: BLE001 — never stamped, or no app context
        return None


def _revision_now_on_disk():
    """What this copy is once an update has replaced its files.

    A clone knows: `git` has already moved HEAD on, and asking it is exact.

    A downloaded copy has nothing on disk that says so — and asking
    :func:`installed_revision` returns the stamp written before *this* update,
    which is the answer that was wrong. So it is asked of the branch instead,
    which at the end of an update that has just finished downloading it is
    what the files are.

    Only ever the fallback. `update.bat` asks GitHub for the branch head
    first and then downloads *that commit by name*, so the revision it hands
    over is exactly what it fetched with no window for a commit to land in
    between. This is for a clinic still running an older `update.bat`, which
    is most of the reason it exists.

    Nothing here reaches the network when the clinic has turned the check off.
    """
    if os.path.isdir(os.path.join(_root(), ".git")):
        return installed_revision()
    if not _enabled():
        return installed_revision()
    return latest_revision()


def _is_revision(text):
    """Whether this looks like a commit id at all.

    The revision arrives from a PowerShell command inside a batch file, and a
    warning line or a proxy's error page would arrive down the same pipe. A
    stamp that says something other than a commit is worse than no stamp: it
    can never match, so the clinic is told to update for ever.
    """
    text = (text or "").strip()
    return 7 <= len(text) <= 40 and all(c in "0123456789abcdefABCDEF"
                                        for c in text)


def record_installed(revision=None):
    """Write down what this copy now is. Called at the end of an update."""
    revision = (revision or "").strip()
    if revision and not _is_revision(revision):
        revision = ""      # not a commit id — work it out instead
    revision = revision or _revision_now_on_disk()
    if not revision or not _is_revision(revision):
        return None
    path = _stamp_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(revision)
    return revision


def _get(url):
    """One short, anonymous GET. None for anything that is not a clean answer."""
    try:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "PediaPro-update-check"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            if answer.status != 200:
                return None
            return json.loads(answer.read().decode("utf-8"))
    except Exception:      # noqa: BLE001 — offline is the ordinary case
        return None


def latest_revision():
    """The newest revision published, or None when it cannot be reached."""
    data = _get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}")
    if not isinstance(data, dict):
        return None
    sha = data.get("sha")
    return sha if isinstance(sha, str) and sha else None


def notes_between(installed, latest, limit=5):
    """What changed, in the words the changes were committed under.

    The subject lines only, and a handful of them: this is a notice at the top
    of a terminal, not a changelog. A clinic reads it to decide whether to
    close for five minutes now or after lunch.
    """
    data = _get(f"https://api.github.com/repos/{REPO}/compare/{installed}...{latest}")
    if not isinstance(data, dict):
        return []
    out = []
    for row in (data.get("commits") or []):
        message = ((row.get("commit") or {}).get("message") or "").strip()
        if message:
            out.append(message.splitlines()[0])
    # Newest first: the last thing merged is the thing somebody is waiting for.
    return list(reversed(out))[:limit]


def pending():
    """``{"installed", "latest", "notes"}`` when there is a newer version.

    None when there is nothing to say — up to date, offline, switched off, or
    a copy whose revision cannot be established. All four are the same to the
    person opening the program: no notice.
    """
    if not _enabled():
        return None
    installed = installed_revision()
    if not installed:
        return None
    latest = latest_revision()
    if not latest or latest == installed:
        return None
    return {"installed": installed, "latest": latest,
            "notes": notes_between(installed, latest)}
