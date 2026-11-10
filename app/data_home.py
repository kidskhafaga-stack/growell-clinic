"""Where this clinic's own files live — the ``data`` folder beside the program
(UPGRADE_PLAN.md ٥ and ٦).

::

    <program folder>/
      app/  run.py  start.bat …   ← the program: what an update replaces
      data/                       ← the clinic's: what no update ever touches
        growell.db                  the records
        uploads/                    photographs, scans, signatures, logos
        backups/                    the copies
        clinic.env                  this computer's port, key and passphrase
        licence, version stamp, imports in progress …

**One rule an update can keep:** replace the program, never ``data``. Before
this, the clinic's things were spread over three places inside the program
folder — the database and the backups in ``instance/``, every uploaded file
in ``app/static/uploads/``, the settings file at the top — and keeping them
safe meant an update knowing every one of those exceptions by heart.

**The move happens once, by itself, and only when it is safe** (:func:`settle`,
run before the program opens its database):

* ``instance/`` becomes ``data/`` in one rename — the database, its backups
  and the licence move together or not at all. If anything else has the
  database open (the clinic running as a service while somebody opens the
  tools), it is **not** moved: the old place keeps working and the move is
  tried again on the next start.
* ``clinic.env`` moves into the data folder.
* each upload folder moves into ``data/uploads/`` in one rename; a folder that
  cannot move yet is still read where it is.

Nothing is copied and nothing is deleted: a rename on the same disk is
instant and cannot leave half a file behind. Until a part has moved, the old
place is the one used — so a clinic is never pointed at an empty folder.
"""
import os

DATA = "data"
LEGACY = "instance"
DB_NAME = "growell.db"
ENV_NAME = "clinic.env"
UPLOADS = "uploads"


def default_root():
    """The program folder — where ``run.py`` and ``start.bat`` sit."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _legacy(root):
    return os.path.join(root, LEGACY)


def _new(root):
    return os.path.join(root, DATA)


def data_dir(root=None):
    """The folder holding this clinic's records.

    ``data/`` — unless the old ``instance/`` folder is still there and the
    database has not moved out of it yet: then that is still the clinic's
    folder, exactly as before, until :func:`settle` can move it.
    """
    root = root or default_root()
    legacy, new = _legacy(root), _new(root)
    if os.path.isdir(legacy) and not os.path.isfile(os.path.join(new, DB_NAME)):
        return legacy
    return new


def database_path(root=None):
    return os.path.join(data_dir(root), DB_NAME)


def env_path(root=None):
    """``clinic.env`` — inside the data folder, or where an older copy left
    it until it is moved."""
    root = root or default_root()
    inside = os.path.join(data_dir(root), ENV_NAME)
    if os.path.isfile(inside):
        return inside
    beside = os.path.join(root, ENV_NAME)
    if os.path.isfile(beside):
        return beside
    return inside


# --- uploads ------------------------------------------------------------------
def _app():
    try:
        from flask import current_app, has_app_context
    except ImportError:          # pragma: no cover - flask is always installed
        return None
    return current_app._get_current_object() if has_app_context() else None


def legacy_uploads_root(root=None):
    """Where uploads lived inside the program: ``app/static/uploads``."""
    return os.path.join(root or default_root(), "app", "static", UPLOADS)


def uploads_root(root=None):
    """``data/uploads`` — or the folder the running app was told to use
    (``UPLOAD_FOLDER``; the tests keep their files in a temporary one)."""
    app = _app() if root is None else None
    configured = app.config.get("UPLOAD_FOLDER") if app is not None else None
    return configured or os.path.join(data_dir(root), UPLOADS)


def _holds_files(folder):
    """Anything in it but a ``.gitkeep``."""
    try:
        with os.scandir(folder) as it:
            return any(e.name != ".gitkeep" for e in it)
    except OSError:
        return False


def upload_dir(sub, root=None):
    """The folder for one kind of upload (``patient_docs``, ``clinic`` …).

    The old folder inside the program while it still holds files that have
    not moved; the data folder otherwise — so a file is always looked for
    where it really is.
    """
    app = _app() if root is None else None
    if app is None or not app.config.get("UPLOAD_FOLDER"):
        legacy = os.path.join(legacy_uploads_root(root), sub)
        if _holds_files(legacy):
            return legacy
    return os.path.join(uploads_root(root), sub)


def stored_path(address):
    """The file on disk behind a stored ``static/uploads/<kind>/<name>``
    address (what messages and templates keep), or None."""
    rel = (address or "").replace("\\", "/")
    rel = rel.split("static/", 1)[1] if "static/" in rel else rel.lstrip("/")
    if not rel.startswith(UPLOADS + "/"):
        return None
    kind, _, name = rel[len(UPLOADS) + 1:].partition("/")
    if not kind or not name or ".." in name.split("/") or kind.startswith("."):
        return None
    return os.path.join(upload_dir(kind), *name.split("/"))


# --- the one-time move ----------------------------------------------------------
def _database_url(root):
    """``DATABASE_URL`` from the environment or the settings file, if any."""
    value = (os.environ.get("DATABASE_URL") or "").strip()
    if value:
        return value
    try:
        from app.settings_file import parse
        with open(env_path(root), encoding="utf-8-sig") as fh:
            return (parse(fh.read()).get("DATABASE_URL") or "").strip()
    except OSError:
        return ""


def database_in_use(path):
    """Whether another program has this SQLite file open.

    Leaving write-ahead mode needs the database to itself, so asking for it
    with no patience at all is a yes-or-no question: refused means somebody
    else is in it. Asked only of a file about to be moved.
    """
    import sqlite3

    if not os.path.isfile(path):
        return False
    try:
        conn = sqlite3.connect(path, timeout=0)
    except sqlite3.Error:
        return True
    try:
        mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
        return not mode or str(mode[0]).lower() != "delete"
    except sqlite3.Error:
        return True
    finally:
        conn.close()


def _adopt(src, dest):
    """Move the folder ``src`` to ``dest`` in one rename.

    When ``dest`` already exists (something was written there first), it is
    set aside, ``src`` takes its place, and what was set aside is folded in
    wherever it does not collide. Returns True when ``src`` moved.
    """
    if not os.path.isdir(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        os.rename(src, dest)
        return True
    aside = dest + ".before-move"
    n = 1
    while os.path.exists(aside):
        n += 1
        aside = f"{dest}.before-move-{n}"
    os.rename(dest, aside)
    try:
        os.rename(src, dest)
    except OSError:
        os.rename(aside, dest)
        raise
    _fold_in(aside, dest)
    return True


def _fold_in(src, dest):
    """Put each entry of ``src`` into ``dest`` where nothing has its name;
    remove ``src`` once it is empty. A collision is left where it is."""
    for name in os.listdir(src):
        a, b = os.path.join(src, name), os.path.join(dest, name)
        if not os.path.exists(b):
            os.rename(a, b)
        elif os.path.isdir(a) and os.path.isdir(b):
            _fold_in(a, b)
    try:
        os.rmdir(src)
    except OSError:
        pass


def settle(root=None):
    """Move what an older copy kept inside the program into ``data/``.

    Safe to call on every start: once moved, it finds nothing to do. Returns
    ``{"moved": [...], "waiting": [...]}`` — what moved now, and what could
    not move yet and why (it is still used where it is).
    """
    root = root or default_root()
    moved, waiting = [], []
    legacy, new = _legacy(root), _new(root)

    # 1) instance/ → data/, the database with it.
    if os.path.isdir(legacy) and not os.path.isfile(os.path.join(new, DB_NAME)):
        url = _database_url(root)
        if url and LEGACY in url.replace("\\", "/").split("/"):
            # The clinic pointed DATABASE_URL into instance/ by hand; moving
            # the folder would leave that line pointing at nothing.
            waiting.append(("instance", "database_url"))
        elif database_in_use(os.path.join(legacy, DB_NAME)):
            waiting.append(("instance", "in_use"))
        else:
            try:
                _adopt(legacy, new)
                moved.append("instance")
            except OSError as exc:
                waiting.append(("instance", f"os:{exc.__class__.__name__}"))

    # 2) clinic.env → the data folder (wherever that is right now).
    beside = os.path.join(root, ENV_NAME)
    inside = os.path.join(data_dir(root), ENV_NAME)
    if os.path.isfile(beside) and not os.path.isfile(inside):
        try:
            os.makedirs(os.path.dirname(inside), exist_ok=True)
            os.replace(beside, inside)
            moved.append(ENV_NAME)
        except OSError as exc:
            waiting.append((ENV_NAME, f"os:{exc.__class__.__name__}"))

    # 3) each upload folder → data/uploads/<kind>.
    old_uploads = legacy_uploads_root(root)
    if os.path.isdir(old_uploads):
        for name in sorted(os.listdir(old_uploads)):
            src = os.path.join(old_uploads, name)
            if not os.path.isdir(src) or not _holds_files(src):
                continue
            try:
                _adopt(src, os.path.join(data_dir(root), UPLOADS, name))
                moved.append(f"uploads/{name}")
            except OSError as exc:
                waiting.append((f"uploads/{name}", f"os:{exc.__class__.__name__}"))
    os.makedirs(data_dir(root), exist_ok=True)
    return {"moved": moved, "waiting": waiting}


def has_database(root=None):
    """Whether this clinic already has its records — for ``start.bat``,
    which seeds a brand-new clinic only."""
    url = _database_url(root or default_root())
    if url and not url.startswith("sqlite"):
        return True
    return os.path.isfile(database_path(root))


def main(argv=None):
    import sys

    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "where"
    if command == "settle":
        result = settle()
        for what in result["moved"]:
            print(f"      moved into the data folder: {what}")
        for what, why in result["waiting"]:
            print(f"      not moved yet ({why}): {what} - it is still used where it is")
        return 0
    if command == "has-db":
        return 0 if has_database() else 1
    print(data_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
