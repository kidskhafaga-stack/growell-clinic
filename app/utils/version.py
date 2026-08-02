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

APP_VERSION = "0.1"


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
