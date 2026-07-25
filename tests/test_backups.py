"""A backup has to bring the photos back too.

A photo is not in the database — the row stores its filename and the picture
itself sits in ``static/uploads``. A snapshot of the ``.db`` alone restored
every record with a broken image beside it, which is what a clinic discovers
on the worst possible day. These tests hold the round trip: take a backup,
lose both the data and the files, restore, and check the picture is back.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic(tmp_path):
    """A real on-disk database (backups need a file) with an uploads folder."""
    import config as app_config
    from app import create_app
    from app.extensions import db

    # Flask-SQLAlchemy builds its engine inside ``init_app``, so the URI has to
    # be right *before* the app is created — otherwise the test quietly writes
    # into the developer's own clinic database.
    db_file = tmp_path / "clinic.db"
    original = app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(db_file)
    app = create_app("development")
    app.config.update(TESTING=True)
    # Keep every uploaded file inside the temp dir, never the real static tree.
    static = tmp_path / "static"
    (static / "uploads" / "users").mkdir(parents=True)
    app.static_folder = str(static)
    app.instance_path = str(tmp_path / "instance")
    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        db.create_all()
        from app.models import User

        user = User(username="doc", full_name="د. أ", role="doctor",
                    photo="avatar.png")
        user.set_password("x")
        db.session.add(user)
        db.session.commit()
        avatar = static / "uploads" / "users" / "avatar.png"
        avatar.write_bytes(b"\x89PNG\r\n\x1a\n-a-real-looking-picture")
        from app.utils.backups import db_path
        assert db_path() == str(db_file)   # never the developer's own clinic
        yield {"app": app, "db": db, "avatar": avatar, "tmp": tmp_path}
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = original


def test_a_backup_carries_the_photos(clinic):
    from app.utils.backups import create_backup, list_backups

    with clinic["app"].app_context():
        name = create_backup("manual")
        assert name.endswith(".zip")
        entry = next(b for b in list_backups() if b["name"] == name)
        assert entry["has_files"] == 1


def test_restore_brings_back_the_record_and_its_picture(clinic):
    """The whole point: the row and the file it points at, together."""
    from app.models import User
    from app.utils.backups import create_backup, restore_backup

    app, db = clinic["app"], clinic["db"]
    with app.app_context():
        name = create_backup("manual")

        # Now lose both halves, the way a real failure does.
        User.query.filter_by(username="doc").delete()
        db.session.commit()
        os.remove(clinic["avatar"])
        assert not clinic["avatar"].exists()

        restore_backup(name)
        assert User.query.filter_by(username="doc").one().photo == "avatar.png"
        assert clinic["avatar"].exists()
        assert clinic["avatar"].read_bytes().startswith(b"\x89PNG")


def test_a_restore_never_deletes_pictures_taken_since(clinic):
    """Restoring an older snapshot onto a newer install must not wipe files
    the backup simply doesn't know about."""
    from app.utils.backups import create_backup, restore_backup

    with clinic["app"].app_context():
        name = create_backup("manual")
        newer = clinic["avatar"].parent / "taken-later.png"
        newer.write_bytes(b"\x89PNG\r\n\x1a\nlater")
        restore_backup(name)
        assert newer.exists()


def test_an_old_database_only_backup_still_restores(clinic):
    """Snapshots taken before this change are ``.db`` files. They must keep
    working — they are simply missing the pictures they never held."""
    import sqlite3

    from app.models import User
    from app.utils.backups import backup_dir, db_path, restore_backup

    app, db = clinic["app"], clinic["db"]
    with app.app_context():
        legacy = os.path.join(backup_dir(), "backup-20200101-000000-manual.db")
        with sqlite3.connect(db_path()) as src, sqlite3.connect(legacy) as dst:
            src.backup(dst)

        User.query.filter_by(username="doc").delete()
        db.session.commit()
        os.remove(clinic["avatar"])

        restore_backup("backup-20200101-000000-manual.db")
        assert User.query.filter_by(username="doc").count() == 1
        # No pictures in a bare .db, and none invented.
        assert not clinic["avatar"].exists()


def test_an_uploaded_archive_is_checked_before_it_is_kept(clinic):
    """A stray zip must not be restorable over the clinic's data."""
    import zipfile

    from werkzeug.datastructures import FileStorage

    from app.utils.backups import save_uploaded_backup

    with clinic["app"].app_context():
        bogus = os.path.join(tempfile.mkdtemp(), "not-ours.zip")
        with zipfile.ZipFile(bogus, "w") as zf:
            zf.writestr("readme.txt", "hello")
        with open(bogus, "rb") as fh:
            with pytest.raises(ValueError):
                save_uploaded_backup(FileStorage(fh, filename="not-ours.zip"))
        shutil.rmtree(os.path.dirname(bogus), ignore_errors=True)


def test_a_real_archive_uploads_and_restores(clinic):
    from werkzeug.datastructures import FileStorage

    from app.models import User
    from app.utils.backups import (backup_path, create_backup,
                                   restore_backup, save_uploaded_backup)

    app, db = clinic["app"], clinic["db"]
    with app.app_context():
        made = create_backup("manual")
        with open(backup_path(made), "rb") as fh:
            stored = save_uploaded_backup(FileStorage(fh, filename=made))
        assert stored.endswith("-uploaded.zip")

        User.query.filter_by(username="doc").delete()
        db.session.commit()
        os.remove(clinic["avatar"])
        restore_backup(stored)
        assert User.query.filter_by(username="doc").count() == 1
        assert clinic["avatar"].exists()
