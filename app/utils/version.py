"""What version this is, and how far the database's shape has come.

A backup that does not say where it came from is a backup you restore by
guessing. That is the gap behind the reported *"I restored a backup and got a
load of problems"*: the restore itself was fine, the schema behind it was a
version old, and nothing on the archive said so.

Two numbers, and they answer different questions:

* ``APP_VERSION`` is the release. It is for people — it goes on the About page
  and into the archive so somebody can say "this is from before the change".
* ``schema_version()`` is what the *code* can actually check. It is derived
  from the additive-column list rather than typed by hand, because a number
  somebody has to remember to bump is a number that will be wrong exactly when
  it matters — the release where a column was added and the version was not.

Deriving it means it cannot drift from the thing it describes.
"""
import hashlib

# **A date, because a date cannot go stale quietly.**
#
# This was ``"0.1"`` and had been since the day it was typed — through every
# release since. Two installs a hundred commits apart both said 0.1, which is
# worse than saying nothing: it answers the question wrongly instead of
# admitting it does not know. The file itself already argued this about the
# schema number: *"a number somebody has to remember to bump is a number that
# will be wrong exactly when it matters"*.
#
# So the release is **the day the build was made**, worked out from the build
# rather than typed into it — sortable, readable by anybody, and obviously
# wrong when it is wrong, which "0.1" never was. Asked for in one line:
# *«عايز رقم النسخة يبقى واضح، بلاش بالأرقام والحروف كده»*.
FALLBACK_VERSION = "0.1"


def _git_date(root):
    """The commit date of a checkout, or ``None``."""
    import subprocess

    try:
        out = subprocess.run(["git", "show", "-s", "--format=%cd",
                              "--date=format:%Y.%m.%d", "HEAD"],
                             cwd=root, capture_output=True, text=True,
                             timeout=5)
    except Exception:  # noqa: BLE001 — no git, or not a usable repo
        return None
    value = (out.stdout or "").strip()
    return value if out.returncode == 0 and value else None


def _file_date(root):
    """When this copy's own files landed here.

    The answer for a machine with no git — a clinic that installed from a
    downloaded copy — and it is a true answer rather than a guess: whatever
    put the files there is what set their date, whether that was an unzip or
    a checkout.
    """
    import os
    from datetime import datetime

    newest = 0
    package = os.path.join(root, "app")
    for folder, _dirs, files in os.walk(package):
        if "__pycache__" in folder:
            continue
        for name in files:
            if name.endswith(".py"):
                try:
                    newest = max(newest, os.path.getmtime(
                        os.path.join(folder, name)))
                except OSError:
                    continue
    if not newest:
        return None
    return datetime.fromtimestamp(newest).strftime("%Y.%m.%d")


_cached_version = None


def app_version():
    """The release, as a date. Computed once and kept.

    Falls back to :data:`FALLBACK_VERSION` only when neither the repository
    nor the files can say — which is a state worth showing as itself rather
    than as a number that looks precise.
    """
    global _cached_version
    if _cached_version is None:
        import os

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        _cached_version = (_git_date(root) or _file_date(root)
                           or FALLBACK_VERSION)
    return _cached_version


#: Kept as a name because a lot of code reads it, and it is now the computed
#: release rather than a constant somebody has to remember.
APP_VERSION = app_version()


def schema_version():
    """A stable fingerprint of the shape this code expects.

    Two builds with the same additive columns give the same answer, and adding
    one changes it. Not an ordering — see :func:`schema_generation` for the
    part that says which is newer.
    """
    from app.utils.schema import ADDITIONS

    joined = ";".join(f"{table}.{column}" for table, column, _ in ADDITIONS)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def schema_generation():
    """How many additive columns this code knows about.

    Crude on purpose, and enough for the only comparison that matters: a
    backup whose generation is **higher** than this build's came from a newer
    version, and restoring it would hand newer data to older code. A count
    only ever grows, because the list is additive — that is the property being
    leaned on, and it is the same property the upgrade itself relies on.
    """
    from app.utils.schema import ADDITIONS

    return len(ADDITIONS)


def manifest():
    """What goes in the archive beside the database."""
    from datetime import datetime

    return {
        "app_version": APP_VERSION,
        "schema_version": schema_version(),
        "schema_generation": schema_generation(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
