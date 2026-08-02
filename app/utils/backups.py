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
import json
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
# What this archive is, written beside the database. A backup that does not
# say where it came from is a backup you restore by guessing — which is the
# gap behind "I restored a backup and got a load of problems".
MANIFEST_ENTRY = "manifest.json"


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


def create_backup(reason="manual", kind=None):
    """Take a consistent snapshot; returns the created filename.

    ``kind`` is ``"full"`` (database + every uploaded file) or ``"db"``
    (database only). Default: whatever ``backup_include_files`` says, so
    existing callers keep behaving exactly as before.

    **Why there are two.** The two halves have different natures. The database
    is megabytes and changes every minute — every patient, every payment, every
    dose. The uploads are gigabytes and are effectively append-only: a photo
    taken today is never edited again. Putting them in one archive means
    copying gigabytes daily to capture megabytes of change, which does not just
    cost time — it makes the daily backup expensive, so people take it less
    often, and the daily backup is the one that saves you.

    **And the trap that comes with splitting them.** A database from Tuesday
    and a files archive from Friday are not a matched pair, and worse, a clinic
    taking only the quick one can believe it is covered for months. That is why
    :func:`last_full_backup` exists and the screen shows its age: a database
    restored beside pictures that were never backed up is the *original*
    failure this module was written to fix, arriving by a new road.
    """
    reason = re.sub(r"[^a-z_]", "", (reason or "manual").lower()) or "manual"
    with_files = _include_files() if kind is None else (kind == "full")
    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}-{reason}.zip"
    dest = os.path.join(backup_dir(), name)

    tmp_db = os.path.join(tempfile.mkdtemp(prefix="gc-backup-"), DB_ENTRY)
    try:
        _snapshot_db(tmp_db)
        with _zip_writer(dest, backup_password()) as zf:
            zf.write(tmp_db, DB_ENTRY)
            zf.writestr(MANIFEST_ENTRY, json.dumps(
                _manifest_for("full" if with_files else "db"), indent=2))
            if with_files:
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

    ``[{name, size, created, has_files, kind, encrypted}]`` — the lock is read
    from each archive rather than from its name, because a name can be changed
    by anyone who can rename a file and a clinic must not be told a snapshot is
    protected when it isn't.
    """
    out = []
    for fn in os.listdir(backup_dir()):
        if not _NAME_RE.match(fn):
            continue
        path = os.path.join(backup_dir(), fn)
        st = os.stat(path)
        # The version is read from inside, not guessed from the filename: it
        # is what tells somebody, before they click restore, that this one is
        # from before the change they are trying to undo.
        info = read_manifest(fn)
        files = _counts_files(path)
        out.append({"name": fn, "size": st.st_size,
                    "created": datetime.fromtimestamp(st.st_mtime),
                    "has_files": files,
                    "kind": _kind_from(info, files),
                    "encrypted": is_encrypted(path),
                    "app_version": info.get("app_version"),
                    "generation": info.get("schema_generation")})
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


def _manifest_for(kind="full"):
    """The manifest written into a new archive (best-effort)."""
    try:
        from app.utils.version import manifest
        info = manifest()
        info["kind"] = kind
        return info
    except Exception:  # noqa: BLE001 - never fail a backup over its label
        return {"kind": kind}


def read_manifest(name, password=None):
    """What an archive says about itself, or ``{}``.

    Empty for a snapshot taken before manifests existed, and for a bare
    ``.db``. Those are not errors — they are most of the backups a clinic
    already has, and refusing them would make this feature cost people the
    archives it is meant to protect.
    """
    path = backup_path(name)
    if not path or not path.endswith(".zip"):
        return {}
    try:
        with _zip_reader(path, password or backup_password()) as zf:
            if MANIFEST_ENTRY not in zf.namelist():
                return {}
            data = json.loads(zf.read(MANIFEST_ENTRY).decode("utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable label is no label
        return {}
    return data if isinstance(data, dict) else {}


def restore_check(name, password=None):
    """Whether this archive may be restored onto this build.

    Returns ``(ok, reason, info)``. Three cases, and the third is the one with
    teeth:

    * **older** — restore it, then bring the schema forward. This already
      happens; the manifest only means we can now *say* it is happening.
    * **same** — nothing to say.
    * **newer** — refused. The archive was written by a build that knows
      columns this one does not, so this code would read that data through an
      older understanding of it: not a crash, a **misreading**, which is the
      kind of damage that gets noticed weeks later in a number nobody can
      explain. Somebody moving a backup from an updated computer onto one that
      was never updated is the ordinary way this happens.

    An archive with no manifest is allowed through — see :func:`read_manifest`.
    """
    from app.utils.version import schema_generation

    info = read_manifest(name, password)
    theirs = info.get("schema_generation")
    if not isinstance(theirs, int):
        return True, "unknown", info
    mine = schema_generation()
    if theirs > mine:
        return False, "newer", info
    return True, ("older" if theirs < mine else "same"), info


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


def _count(value, fallback):
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return fallback


def apply_retention(keep, full_keep=None):
    """Trim *automatic* snapshots (auto/prerestore/preupgrade) to the newest
    ``keep`` **of each kind**. Manual backups are the admin's — never deleted
    automatically.

    Counting the two kinds separately is the whole point. One shared quota
    means the cheap nightly database snapshots, which are taken far more often,
    steadily push the large full archives off the end — so the clinic ends up
    with a fortnight of databases and not one copy of the photographs, which is
    precisely the failure the split exists to avoid. Each kind now keeps its
    own count, so a daily database rhythm cannot evict the weekly full one.

    ``full_keep`` defaults to ``keep`` so the older single-argument callers
    behave as they always did.

    One honest caveat: ``prerestore`` and ``preupgrade`` snapshots are full
    archives and count against the full quota. Several restores in a row can
    therefore age the scheduled full copies out faster than the schedule alone
    would — which is the correct trade, since those snapshots are the ones
    protecting the work being undone right now.
    """
    keep = _count(keep, 14)
    full_keep = keep if full_keep is None else _count(full_keep, keep)
    limits = {"db": keep, "full": full_keep}
    seen = {}
    removed = 0
    for b in list_backups():
        if re.search(r"-(manual|uploaded)\.(db|zip)$", b["name"]):
            continue
        kind = backup_kind(b)
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] > limits.get(kind, max(keep, full_keep)):
            if delete_backup(b["name"]):
                removed += 1
    return removed


def _retain():
    """Apply both configured limits (used by the scheduler)."""
    from app.models import Setting

    return apply_retention(Setting.get("backup_keep", "14"),
                           Setting.get("backup_full_keep", "4"))


# Throttle so the due-check costs nothing on normal requests.
_AUTO = {"checked_at": 0.0}
_AUTO_CHECK_EVERY = 300  # seconds


def _days_since_auto(kind=None):
    """Days since the last automatic snapshot of ``kind`` (any kind if None).

    A very large number when there has never been one, so "never taken" and
    "long overdue" take the same branch — which is what they deserve.
    """
    for entry in list_backups():
        if not re.search(r"-auto\.(db|zip)$", entry["name"]):
            continue
        if kind is not None and backup_kind(entry) != kind:
            continue
        return (datetime.now().date() - entry["created"].date()).days
    return 10 ** 6


def _kind_from(info, has_files):
    """What an archive holds, from its manifest or from what is in it.

    The manifest is believed first; falling back on the contents is what keeps
    every backup a clinic already owns honestly labelled, because those were
    written before manifests existed and there is no going back to stamp them.
    """
    kind = info.get("kind")
    if kind in ("full", "db"):
        return kind
    return "full" if has_files else "db"


def backup_kind(entry):
    """What an archive holds: ``"full"``, ``"db"``, or ``"unknown"``.

    Takes a row from :func:`list_backups` — which already carries the answer,
    so this costs nothing there — or a bare name, which is read from disk.
    """
    if isinstance(entry, dict) and entry.get("kind") in ("full", "db"):
        return entry["kind"]
    name = entry["name"] if isinstance(entry, dict) else entry
    info = read_manifest(name)
    if isinstance(entry, dict) and entry.get("has_files") is not None:
        return _kind_from(info, entry["has_files"])
    path = backup_path(name)
    if not path:
        return "unknown"
    return _kind_from(info, _counts_files(path))


def last_full_backup():
    """The newest archive that actually contains the pictures, or ``None``.

    The number the split makes necessary. A clinic taking the quick database
    snapshot nightly can go months believing it is covered, and find out on the
    day the disk dies that every photograph, signature and scanned document is
    gone. Records restored beside missing pictures is the failure this module
    was written to fix; splitting the backup lets it back in through a
    different door, and this is the door's alarm.
    """
    for entry in list_backups():
        if backup_kind(entry) == "full":
            return entry
    return None


def full_backup_age_days():
    """Days since the last archive containing files, or ``None`` if never."""
    last = last_full_backup()
    if last is None:
        return None
    return (datetime.now() - last["created"]).days


def full_backup_overdue(age=None, every=None):
    """Whether the full copy is old enough that somebody should be told.

    Never taken counts as overdue — that is the state a clinic can sit in for
    a year without noticing, and the one with the most to lose.

    The threshold is **twice** the configured interval rather than one, because
    a weekly archive is normally a day or two late and a banner that lights up
    every Monday is furniture nobody reads by the second week. Twice over means
    a schedule that has actually stopped running, which is worth interrupting
    somebody for.
    """
    if age is None:
        age = full_backup_age_days()
        if age is None:
            return True
    if every is None:
        try:
            from app.models import Setting
            every = Setting.get("backup_full_every_days", "7")
        except Exception:  # noqa: BLE001 - before the settings table exists
            every = 7
    return age > _count(every, 7) * 2


def auto_backup_if_due():
    """Opportunistic scheduled backup (poor-man's cron for a single clinic PC).

    On the first request after the configured hour, take whichever kind is due
    and trim both shelves. Throttled to one cheap check every few minutes;
    never raises — a failed backup must not cost somebody the page they asked
    for.

    Each kind carries its own pair of numbers, set by the admin:

    * ``backup_every_days`` / ``backup_keep`` — the quick database snapshot.
    * ``backup_full_every_days`` / ``backup_full_keep`` — the archive with the
      uploaded files in it.

    The intervals are counted from the last *automatic* snapshot — a manual
    copy does not quietly cancel tonight's. The full one counts only full
    archives, since a database snapshot never held the pictures. The quick one
    counts **either**, because a full archive contains the database too and
    taking a second copy of it hours later would be work for nothing.
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
        try:
            full_every = max(int(Setting.get("backup_full_every_days", "7")), 1)
        except (TypeError, ValueError):
            full_every = 7
        today = datetime.now()
        if today.hour < hour:
            return None

        # Two rhythms, because the halves have different natures: the database
        # changes every minute and is small; the pictures barely change and are
        # large. One schedule for both means copying gigabytes nightly to catch
        # megabytes of change — which makes the nightly backup expensive, so it
        # gets taken less often, and the nightly one is the one that saves you.
        #
        # The full one is checked first. When both fall due on the same day the
        # full archive covers the quick one, and taking two would be writing
        # the database twice for no reason.
        if _days_since_auto("full") >= full_every:
            name = create_backup("auto", kind="full")
            _retain()
            return name
        if _days_since_auto(None) >= every:
            name = create_backup("auto", kind="db")
            _retain()
            return name
        return None
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
    # A backup from a *newer* build is refused before anything is touched.
    # Older code reading newer data does not crash — it misreads, and that is
    # the kind of damage somebody finds weeks later in a number they cannot
    # explain.
    allowed, reason, _info = restore_check(name, password)
    if not allowed:
        raise ValueError("backup_newer")
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
