"""Backups — the database *and* the files it points at.

Snapshots are taken with SQLite's online backup API, so they are consistent
even while the app is running (WAL included). Files live under
``instance/backups`` next to the database itself.

**Photos used to be lost.** A backup was the ``.db`` file alone, but a photo is
not in the database — the row only stores its filename, and the picture itself
sits in ``static/uploads``. Restoring gave you every record back with a broken
image beside it: patient photos, staff avatars, the clinic logo, doctors'
signatures and stamps, prescriptions' letterheads, attached documents.

So a backup is now a ``.zip`` holding the database and those files together.
Older ``.db`` snapshots still restore exactly as before — they are simply
missing the pictures they never contained.

**And that archive is every patient the clinic has ever seen.** Names, phone
numbers, diagnoses, prescriptions, the photographs. A backup's whole job is to
leave the building — onto a flash drive, into a cloud folder, sent to whoever
keeps the spare copy — and until it was encrypted, any of those journeys
handed the lot to whoever picked it up.

So when a passphrase is set, the archive is written as **AES-256 (WinZip)**,
which 7-Zip and every other archiver can open. That matters more than a
neater format of our own: a backup you can only restore by having this
program working is a backup that fails you on the day the computer doesn't.

Two things this does *not* do, said plainly:

* **The file names inside stay readable.** WinZip AES encrypts contents, not
  the directory. Someone with the archive learns that it holds a database and
  some upload paths — the paths are random ids, so this is close to nothing,
  but it is not nothing.
* **It does not protect the clinic's own computer.** The passphrase lives in
  ``clinic.env`` on that machine, because unattended nightly backups cannot
  stop and ask for it. Anyone with the PC has both. What it protects is the
  copy that left — which is the way this data actually escapes.
"""
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime

import pyzipper
from flask import current_app

_NAME_RE = re.compile(r"^backup-\d{8}-\d{6}(-[a-z_]+)?\.(db|zip)$")

# Where the database's filenames actually resolve to on disk. Everything a row
# can point at lives under one of these.
UPLOAD_DIRS = ["users", "patients", "clinic", "crm", "patient_docs",
               "drug_media"]
# The database's name inside the archive.
DB_ENTRY = "database.db"
FILES_PREFIX = "uploads/"


def db_path():
    """Filesystem path of the SQLite database (None for non-file DBs)."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not uri.startswith("sqlite:///") or uri.endswith(":memory:"):
        return None
    path = uri[len("sqlite:///"):]
    if not os.path.isabs(path):
        path = os.path.join(current_app.instance_path, path)
    return path


def backup_dir():
    d = os.path.join(current_app.instance_path, "backups")
    os.makedirs(d, exist_ok=True)
    return d


def uploads_root():
    """The folder holding every uploaded file."""
    return os.path.join(current_app.static_folder, "uploads")


def backup_password():
    """The passphrase this install writes backups with, or None.

    Kept out of the database on purpose. A key stored beside the thing it
    locks is decoration — anyone who took the database would have taken the
    passphrase with it.
    """
    try:
        configured = (current_app.config.get("BACKUP_PASSWORD") or "").strip()
    except RuntimeError:      # outside an app context
        configured = ""
    return configured or (os.environ.get("BACKUP_PASSWORD") or "").strip() or None


def is_encrypted(path):
    """Whether an archive's contents need a passphrase."""
    if not path or not path.endswith(".zip"):
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            return any(info.flag_bits & 0x1 for info in zf.infolist())
    except Exception:  # noqa: BLE001 - a damaged archive is not "encrypted"
        return False


def _zip_writer(dest, password):
    if not password:
        return zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED)
    zf = pyzipper.AESZipFile(dest, "w", compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES)
    zf.setpassword(password.encode("utf-8"))
    return zf


def _zip_reader(path, password=None):
    """Open an archive, encrypted or not. ``AESZipFile`` reads plain zips too,
    so there is one reader rather than two paths that can drift apart."""
    zf = pyzipper.AESZipFile(path)
    if password:
        zf.setpassword(password.encode("utf-8"))
    return zf


def _snapshot_db(dest):
    """A consistent copy of the live database at ``dest``."""
    src = db_path()
    if not src or not os.path.isfile(src):
        raise RuntimeError("database file not found")
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)


def _include_files():
    """Whether this clinic wants its pictures inside the snapshot."""
    try:
        from app.models import Setting
        return Setting.get("backup_include_files", "1") != "0"
    except Exception:  # noqa: BLE001 - before the settings table exists
        return True


def create_backup(reason="manual"):
    """Take a consistent snapshot; returns the created filename.

    The archive holds the database plus every uploaded file, so a restore puts
    the photos back too — which is the whole point of having taken one.
    """
    reason = re.sub(r"[^a-z_]", "", (reason or "manual").lower()) or "manual"
    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}-{reason}.zip"
    dest = os.path.join(backup_dir(), name)

    tmp_db = os.path.join(tempfile.mkdtemp(prefix="gc-backup-"), DB_ENTRY)
    try:
        _snapshot_db(tmp_db)
        with _zip_writer(dest, backup_password()) as zf:
            zf.write(tmp_db, DB_ENTRY)
            if _include_files():
                for rel, path in _upload_files():
                    zf.write(path, FILES_PREFIX + rel)
    except Exception:
        if os.path.isfile(dest):
            os.remove(dest)
        raise
    finally:
        shutil.rmtree(os.path.dirname(tmp_db), ignore_errors=True)
    return name


def _upload_files():
    """``(relative_path, absolute_path)`` for every uploaded file."""
    root = uploads_root()
    for folder in UPLOAD_DIRS:
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                path = os.path.join(dirpath, fn)
                yield os.path.relpath(path, root).replace(os.sep, "/"), path


def list_backups():
    """Existing backups, newest first.

    ``[{name, size, created, has_files, encrypted}]`` — the lock is read from
    each archive rather than from its name, because a name can be changed by
    anyone who can rename a file and a clinic must not be told a snapshot is
    protected when it isn't.
    """
    out = []
    for fn in os.listdir(backup_dir()):
        if not _NAME_RE.match(fn):
            continue
        path = os.path.join(backup_dir(), fn)
        st = os.stat(path)
        out.append({"name": fn, "size": st.st_size,
                    "created": datetime.fromtimestamp(st.st_mtime),
                    "has_files": _counts_files(path),
                    "encrypted": is_encrypted(path)})
    out.sort(key=lambda b: b["name"], reverse=True)
    return out


def _counts_files(path):
    """How many uploaded files this snapshot carries (0 for a bare ``.db``)."""
    if not path.endswith(".zip"):
        return 0
    try:
        with zipfile.ZipFile(path) as zf:
            return sum(1 for n in zf.namelist() if n.startswith(FILES_PREFIX))
    except Exception:  # noqa: BLE001 - a damaged archive must not break the list
        return 0


def backup_path(name):
    """Absolute path for a known backup name (validated), else None."""
    if not _NAME_RE.match(name or ""):
        return None
    path = os.path.join(backup_dir(), name)
    return path if os.path.isfile(path) else None


def _check_sqlite(path):
    """Raise unless ``path`` is a healthy database of *this* application."""
    with open(path, "rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise ValueError("not_sqlite")
    with sqlite3.connect(path) as conn:
        ok = conn.execute("PRAGMA quick_check").fetchone()
        if not ok or ok[0] != "ok":
            raise ValueError("corrupt")
        if not conn.execute("SELECT 1 FROM sqlite_master "
                            "WHERE type='table' AND name='users'").fetchone():
            raise ValueError("wrong_app")


def save_uploaded_backup(file_storage, max_bytes=500 * 1024 * 1024,
                         password=None):
    """Store a backup file uploaded from the admin's device.

    Accepts either format: an archive from a newer install (database + files)
    or a bare ``.db`` from an older one. Either way it must be a real SQLite
    database of *this* application, so a stray file can't be restored over the
    clinic's data. Returns the stored filename.

    An encrypted archive is proved the same way as any other, which means it
    has to be opened — so a file this install cannot decrypt is refused
    (``bad_password``) rather than stored unverified. Keeping something we
    could not read, next to a restore button, is how a stray file gets written
    over a clinic's records.
    """
    head = file_storage.stream.read(4)
    file_storage.stream.seek(0)
    is_zip = head[:2] == b"PK"
    if not is_zip and head != b"SQLi":
        raise ValueError("not_sqlite")

    suffix = "zip" if is_zip else "db"
    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}-uploaded.{suffix}"
    dest = os.path.join(backup_dir(), name)
    file_storage.save(dest)
    tmp = None
    try:
        if os.path.getsize(dest) > max_bytes:
            raise ValueError("too_big")
        if is_zip:
            tmp = _extract_db(dest, password)
            _check_sqlite(tmp)
        else:
            _check_sqlite(dest)
    except Exception:
        os.remove(dest)
        raise
    finally:
        if tmp:
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    return name


def _extract_db(archive, password=None):
    """Pull the database out of an archive into a temp dir; returns its path.

    ``password`` overrides the configured one, which is what makes an archive
    from before a passphrase change restorable at all: the clinic types the
    old words once instead of losing every snapshot taken under them.
    """
    password = password or backup_password()
    with _zip_reader(archive, password) as zf:
        names = zf.namelist()
        entry = DB_ENTRY if DB_ENTRY in names else next(
            (n for n in names if n.endswith(".db") and "/" not in n), None)
        if entry is None:
            raise ValueError("wrong_app")
        out = tempfile.mkdtemp(prefix="gc-restore-")
        try:
            zf.extract(entry, out)
        except (RuntimeError, ValueError) as exc:
            shutil.rmtree(out, ignore_errors=True)
            raise ValueError("bad_password") from exc
        return os.path.join(out, entry)


def delete_backup(name):
    path = backup_path(name)
    if path:
        os.remove(path)
        return True
    return False


def apply_retention(keep):
    """Trim *automatic* snapshots (auto/prerestore/preupgrade) to the newest
    ``keep``. Manual backups are the admin's — never deleted automatically."""
    try:
        keep = max(int(keep), 1)
    except (TypeError, ValueError):
        keep = 14
    autos = [b for b in list_backups()
             if not re.search(r"-(manual|uploaded)\.(db|zip)$", b["name"])]
    removed = 0
    for b in autos[keep:]:
        if delete_backup(b["name"]):
            removed += 1
    return removed


# Throttle so the due-check costs nothing on normal requests.
_AUTO = {"checked_at": 0.0}
_AUTO_CHECK_EVERY = 300  # seconds


def auto_backup_if_due():
    """Opportunistic scheduled backup (poor-man's cron for a single clinic PC).

    On the first request after the configured hour, once every N days
    (``backup_every_days``: 1 = daily, 2 = every other day, 7 = weekly,
    counted from the last automatic snapshot), take a backup and apply
    retention. Throttled to one cheap check every few minutes; never raises.
    """
    import time as _time

    now = _time.time()
    if now - _AUTO["checked_at"] < _AUTO_CHECK_EVERY:
        return None
    _AUTO["checked_at"] = now
    try:
        from app.models import Setting

        if Setting.get("backup_auto_enabled", "1") == "0":
            return None
        try:
            hour = int(Setting.get("backup_hour", "2"))
        except (TypeError, ValueError):
            hour = 2
        try:
            every = max(int(Setting.get("backup_every_days", "1")), 1)
        except (TypeError, ValueError):
            every = 1
        today = datetime.now()
        if today.hour < hour:
            return None
        # Due when `every` days have passed since the last auto snapshot.
        last = next((b for b in list_backups()
                     if re.search(r"-auto\.(db|zip)$", b["name"])), None)
        if last is not None:
            last_date = datetime.strptime(
                last["name"].split("-")[1], "%Y%m%d").date()
            if (today.date() - last_date).days < every:
                return None
        name = create_backup("auto")
        apply_retention(Setting.get("backup_keep", "14"))
        return name
    except Exception:  # noqa: BLE001 - a failed backup must never break a request
        return None


def restore_backup(name, password=None):
    """Replace the live database — and the uploaded files — with a backup's.

    A fresh snapshot of the current state is taken first (reason
    ``prerestore``) so a mistaken restore is itself reversible. SQLAlchemy's
    pool is disposed before copying so no pooled connection serves stale
    pages; the database copy runs through SQLite's backup API, which is safe
    against readers and needs no app restart.

    Files are written back *over* what is there rather than replacing the
    folder wholesale: a snapshot restored onto a newer install must not delete
    pictures taken since, and a bare ``.db`` from an older install carries no
    files at all, so it must leave the ones on disk alone.

    Returns the pre-restore snapshot's filename.
    """
    src = backup_path(name)
    if not src:
        raise RuntimeError("backup not found")
    live = db_path()
    if not live or not os.path.isfile(live):
        raise RuntimeError("database file not found")

    # Opened before anything is replaced. A wrong passphrase discovered after
    # the live database had been overwritten would be the worst possible
    # moment to find out.
    tmp = _extract_db(src, password) if src.endswith(".zip") else None

    pre = create_backup("prerestore")

    from app.extensions import db as _db
    _db.session.remove()
    _db.engine.dispose()

    if tmp is not None:
        try:
            with sqlite3.connect(tmp) as source, sqlite3.connect(live) as target:
                source.backup(target)
            _restore_files(src, password)
        finally:
            shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    else:
        with sqlite3.connect(src) as source, sqlite3.connect(live) as target:
            source.backup(target)

    _upgrade_restored_schema()
    return pre


def _upgrade_restored_schema():
    """Bring the restored database's shape up to the running code's.

    Without this, restoring last month's backup onto a version that has since
    gained a column leaves the program reading a column that database has never
    had. The symptoms scatter — one screen fine, the next raising ``no such
    column`` — so it reads as a corrupt backup rather than a schema a version
    behind, and the reasonable response to a corrupt backup is to abandon it and
    re-enter everything by hand. That is a restore that appeared to work and
    cost somebody their afternoon.

    Additive and idempotent, so restoring a backup that is already current does
    nothing. It runs **after** the copy and never before: the shape has to be
    brought forward on the database that is now live, not on the one being
    replaced.

    A failure here is reported through the caller rather than swallowed. The
    data is already back; what has not happened is the upgrade, and telling
    somebody "restored, but run upgrade-db" is far better than letting them
    discover it one screen at a time.
    """
    from app.utils.schema import apply_schema

    return apply_schema()


def _restore_files(archive, password=None):
    """Write the archive's uploaded files back under ``static/uploads``."""
    root = uploads_root()
    restored = 0
    with _zip_reader(archive, password or backup_password()) as zf:
        for entry in zf.namelist():
            if not entry.startswith(FILES_PREFIX) or entry.endswith("/"):
                continue
            rel = entry[len(FILES_PREFIX):]
            # Never let an archive write outside the uploads folder.
            dest = os.path.normpath(os.path.join(root, rel))
            if not dest.startswith(os.path.normpath(root) + os.sep):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(entry) as fh, open(dest, "wb") as out:
                shutil.copyfileobj(fh, out)
            restored += 1
    return restored
