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


def delete_backup(name):
    path = backup_path(name)
    if path:
        os.remove(path)
        return True
    return False
