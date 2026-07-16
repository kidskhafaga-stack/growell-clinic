"""Database backups (Phase 0 of the master plan — the safety net).

Snapshots are taken with SQLite's online backup API, so they are consistent
even while the app is running (WAL included). Files live under
``instance/backups`` next to the database itself.
"""
import os
import re
import sqlite3
from datetime import datetime

from flask import current_app

_NAME_RE = re.compile(r"^backup-\d{8}-\d{6}(-[a-z_]+)?\.db$")


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


def create_backup(reason="manual"):
    """Take a consistent snapshot; returns the created filename."""
    src = db_path()
    if not src or not os.path.isfile(src):
        raise RuntimeError("database file not found")
    reason = re.sub(r"[^a-z_]", "", (reason or "manual").lower()) or "manual"
    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}-{reason}.db"
    dest = os.path.join(backup_dir(), name)
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return name


def list_backups():
    """Existing backups, newest first: [{name, size, created}]."""
    out = []
    for fn in os.listdir(backup_dir()):
        if not _NAME_RE.match(fn):
            continue
        path = os.path.join(backup_dir(), fn)
        st = os.stat(path)
        out.append({"name": fn, "size": st.st_size,
                    "created": datetime.fromtimestamp(st.st_mtime)})
    out.sort(key=lambda b: b["name"], reverse=True)
    return out


def backup_path(name):
    """Absolute path for a known backup name (validated), else None."""
    if not _NAME_RE.match(name or ""):
        return None
    path = os.path.join(backup_dir(), name)
    return path if os.path.isfile(path) else None


def save_uploaded_backup(file_storage, max_bytes=500 * 1024 * 1024):
    """Store a backup file uploaded from the admin's device.

    The file must be a real SQLite database (header + quick_check) and must
    look like one of ours (a ``users`` table exists) so a stray/wrong file
    can't be restored over the clinic's data. Returns the stored filename.
    """
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if header != b"SQLite format 3\x00":
        raise ValueError("not_sqlite")

    name = f"backup-{datetime.now():%Y%m%d-%H%M%S}-uploaded.db"
    dest = os.path.join(backup_dir(), name)
    file_storage.save(dest)
    try:
        if os.path.getsize(dest) > max_bytes:
            raise ValueError("too_big")
        with sqlite3.connect(dest) as conn:
            ok = conn.execute("PRAGMA quick_check").fetchone()
            if not ok or ok[0] != "ok":
                raise ValueError("corrupt")
            has_users = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            if not has_users:
                raise ValueError("wrong_app")
    except Exception:
        os.remove(dest)
        raise
    return name


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
             if not b["name"].endswith(("-manual.db", "-uploaded.db"))]
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
                     if b["name"].endswith("-auto.db")), None)
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


def restore_backup(name):
    """Replace the live database with a backup's content.

    A fresh snapshot of the current state is taken first (reason
    ``prerestore``) so a mistaken restore is itself reversible. SQLAlchemy's
    pool is disposed before copying so no pooled connection serves stale
    pages; the copy runs through SQLite's backup API (backup file → live DB),
    which is safe against readers and needs no app restart.
    Returns the pre-restore snapshot's filename.
    """
    src = backup_path(name)
    if not src:
        raise RuntimeError("backup not found")
    live = db_path()
    if not live or not os.path.isfile(live):
        raise RuntimeError("database file not found")

    pre = create_backup("prerestore")

    from app.extensions import db as _db
    _db.session.remove()
    _db.engine.dispose()

    with sqlite3.connect(src) as source, sqlite3.connect(live) as target:
        source.backup(target)
    return pre
