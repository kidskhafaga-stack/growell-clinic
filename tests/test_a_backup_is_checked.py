"""A backup is checked: opened, read through, and found whole — or not.

Asked: *«محتاج اعمل خطوة verifying على النسخ بتاعت الباك اب»*. Until now an
uploaded copy was looked at before it was kept, and nothing else was: the
copies the program took itself — every night, before every restore and
every update — were written and never opened again, and a restore copied a
damaged database over the clinic's own without asking whether it was whole.
A copy cut short on a full disk was found out on the day it was needed.

Now every copy is opened as it is made (`backups.verify_backup`): every
entry's checksum, photos included; the passphrase; the files it says it
holds; SQLite's full integrity check; and that it is this program's database.
What it found is kept beside the copy, shown on the backup screen, rung on
the bell when the newest one fails, and a restore refuses a copy that fails.
"""
import json
import os
import sqlite3
import sys
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic(tmp_path):
    """A real on-disk database (backups need a file) with an uploads folder."""
    import config as app_config
    from app import create_app
    from app.extensions import db

    db_file = tmp_path / "clinic.db"
    original = app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(db_file)
    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    static = tmp_path / "static"
    (static / "uploads" / "users").mkdir(parents=True)
    app.static_folder = str(static)
    app.instance_path = str(tmp_path / "instance")
    os.makedirs(app.instance_path, exist_ok=True)

    with app.app_context():
        db.create_all()
        from app.models import Patient, User

        boss = User(username="boss", full_name="المدير", role="admin", is_active=True)
        boss.set_password("secret")
        doc = User(username="doc", full_name="د. أ", role="doctor", photo="avatar.png",
                   is_active=True)
        doc.set_password("x")
        db.session.add_all([boss, doc])
        from datetime import date
        db.session.add(Patient(patient_number="P1", full_name="طفل", gender="male",
                               date_of_birth=date(2024, 1, 1), is_active=True))
        db.session.commit()
        (static / "uploads" / "users" / "avatar.png").write_bytes(
            b"\x89PNG\r\n\x1a\n-a-real-looking-picture" * 40)
        from app.utils.backups import db_path
        assert db_path() == str(db_file)   # never the developer's own clinic
        yield {"app": app, "db": db, "tmp": tmp_path}
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = original


def _path(name):
    from app.utils.backups import backup_path
    return backup_path(name)


def _rewrite(name, change):
    """Rewrite an archive's entries through ``change(entry, data) -> data``."""
    path = _path(name)
    with zipfile.ZipFile(path) as zf:
        entries = [(i.filename, zf.read(i.filename)) for i in zf.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, data in entries:
            data = change(entry, data)
            if data is not None:
                zf.writestr(entry, data)


# ------------------------------------------------ every copy, as it is made --
def test_every_copy_is_checked_as_it_is_made(clinic):
    from app.utils.backups import create_backup, list_backups, read_check, read_manifest

    with clinic["app"].app_context():
        name = create_backup("manual", kind="full")
        check = read_check(name)
        assert check["ok"] and check["reason"] is None
        assert check["counts"]["patients"] == 1
        assert check["files"] == 1 and read_manifest(name)["files"] == 1
        row = next(b for b in list_backups() if b["name"] == name)
        assert row["check"]["ok"]


def test_a_copy_cut_short_is_found_out(clinic):
    from app.utils.backups import create_backup, verify_backup

    with clinic["app"].app_context():
        name = create_backup("auto", kind="full")
        path = _path(name)
        size = os.path.getsize(path)
        with open(path, "r+b") as fh:
            fh.truncate(size // 2)
        assert verify_backup(name)["reason"] == "broken_zip"


def test_a_damaged_photo_inside_is_found_out(clinic):
    """The archive still opens; one photograph inside it does not read back.
    Only reading every entry finds that — the database alone is fine."""
    from app.utils.backups import create_backup, verify_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="full")
        path = _path(name)
        with zipfile.ZipFile(path) as zf:
            info = zf.getinfo("uploads/users/avatar.png")
        with open(path, "r+b") as fh:
            fh.seek(info.header_offset + 26)
            name_len, extra_len = (int.from_bytes(fh.read(2), "little"),
                                   int.from_bytes(fh.read(2), "little"))
            start = info.header_offset + 30 + name_len + extra_len
            fh.seek(start + info.compress_size // 2)
            byte = fh.read(1)
            fh.seek(start + info.compress_size // 2)
            fh.write(bytes([byte[0] ^ 0xFF]))
        check = verify_backup(name)
        assert not check["ok"] and check["reason"] == "broken_zip"


def test_a_database_that_is_damaged_or_not_ours(clinic):
    from app.utils.backups import create_backup, verify_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="db")
        _rewrite(name, lambda e, d: (b"SQLite format 3\x00" + b"\x07" * 4000)
                 if e == "database.db" else d)
        assert verify_backup(name)["reason"] == "corrupt"

        other = clinic["tmp"] / "other.db"
        with sqlite3.connect(other) as conn:
            conn.execute("CREATE TABLE notes (id INTEGER)")
        name2 = create_backup("manual", kind="db")
        _rewrite(name2, lambda e, d: other.read_bytes() if e == "database.db" else d)
        assert verify_backup(name2)["reason"] == "wrong_app"


def test_a_copy_missing_photos_it_says_it_holds(clinic):
    from app.utils.backups import create_backup, verify_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="full")
        _rewrite(name, lambda e, d: None if e.startswith("uploads/") else d)
        assert verify_backup(name)["reason"] == "files_missing"


def test_a_wrong_passphrase_is_not_called_damage(clinic):
    """A copy from before a passphrase change is not damaged — it needs the
    old words, and the check says that instead of «broken»."""
    from app.utils.backups import create_backup, verify_backup

    with clinic["app"].app_context():
        clinic["app"].config["BACKUP_PASSWORD"] = "the-old-words"
        name = create_backup("manual", kind="full")
        assert verify_backup(name)["ok"]
        clinic["app"].config["BACKUP_PASSWORD"] = "the-new-words"
        assert verify_backup(name)["reason"] == "bad_password"
        assert verify_backup(name, password="the-old-words")["ok"]


# ------------------------------------------------------------- the restore --
def test_a_restore_refuses_a_broken_copy_and_touches_nothing(clinic):
    from app.models import Patient
    from app.utils.backups import backup_dir, create_backup, restore_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="full")
        db = clinic["db"]
        from datetime import date
        db.session.add(Patient(patient_number="P2", full_name="طفل تاني", gender="female",
                               date_of_birth=date(2024, 2, 2), is_active=True))
        db.session.commit()
        with open(_path(name), "r+b") as fh:
            fh.truncate(os.path.getsize(_path(name)) // 2)
        before = set(os.listdir(backup_dir()))
        with pytest.raises(ValueError, match="backup_broken"):
            restore_backup(name)
        # Nothing taken, nothing replaced.
        assert not [f for f in set(os.listdir(backup_dir())) - before
                    if "prerestore" in f]
        assert Patient.query.filter_by(patient_number="P2").count() == 1


def test_an_uploaded_copy_is_read_through_too(clinic):
    """The upload already looked at the database; a photo damaged on the way
    is caught now as well, and the copy is not kept."""
    from io import BytesIO

    from werkzeug.datastructures import FileStorage

    from app.utils.backups import backup_dir, create_backup, delete_backup, save_uploaded_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="full")
        path = _path(name)
        with zipfile.ZipFile(path) as zf:
            entries = [(i, zf.read(i.filename)) for i in zf.infolist()]
        # Same archive, one photo's checksum no longer matching its bytes.
        raw = BytesIO()
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_STORED) as zf:
            for info, data in entries:
                zf.writestr(info.filename, data)
        blob = bytearray(raw.getvalue())
        marker = blob.find(b"-a-real-looking-picture")
        blob[marker] ^= 0xFF
        delete_backup(name)
        before = set(os.listdir(backup_dir()))
        with pytest.raises(ValueError):
            save_uploaded_backup(FileStorage(stream=BytesIO(bytes(blob)),
                                             filename="copy.zip"))
        assert set(os.listdir(backup_dir())) == before


# ------------------------------------------------- the screen and the bell --
def _admin(clinic):
    client = clinic["app"].test_client()
    client.post("/login", data={"username": "boss", "password": "secret"})
    return client


def test_the_screen_shows_each_copys_check_and_can_check_again(clinic):
    from app.utils.backups import create_backup, read_check

    with clinic["app"].app_context():
        good = create_backup("manual", kind="full")
    boss = _admin(clinic)
    page = boss.get("/settings/data").get_data(as_text=True)
    assert 'data-backup-check="ok"' in page and "data-backup-verify" in page
    assert f"/settings/data/backup/{good}/verify" in page

    with clinic["app"].app_context():
        os.remove(os.path.join(os.path.dirname(_path(good)), good + ".check.json"))
    page = boss.get("/settings/data").get_data(as_text=True)
    assert 'data-backup-check="none"' in page

    reply = boss.post(f"/settings/data/backup/{good}/verify", follow_redirects=True)
    assert 'data-backup-check="ok"' in reply.get_data(as_text=True)
    with clinic["app"].app_context():
        assert read_check(good)["ok"]
        with open(_path(good), "r+b") as fh:
            fh.truncate(os.path.getsize(_path(good)) // 2)
    reply = boss.post(f"/settings/data/backup/{good}/verify", follow_redirects=True)
    page = reply.get_data(as_text=True)
    assert 'data-backup-check="bad"' in page and "data-backup-why" in page


def test_the_bell_tells_the_admin_when_the_newest_copy_fails(clinic):
    from app.utils import notifications
    from app.utils.backups import create_backup

    with clinic["app"].test_request_context():
        create_backup("auto", kind="db")
        assert "backup_broken" not in [i["key"] for i in notifications._compute()]
        newest = create_backup("auto", kind="full")
        with open(_path(newest), "r+b") as fh:
            fh.truncate(os.path.getsize(_path(newest)) // 2)
        from app.utils.backups import verify_backup
        verify_backup(newest)
        items = [i for i in notifications._compute() if i["key"] == "backup_broken"]
        assert items and items[0]["module"] == "settings"


def test_deleting_a_copy_takes_its_check_with_it(clinic):
    from app.utils.backups import backup_dir, create_backup, delete_backup

    with clinic["app"].app_context():
        name = create_backup("manual", kind="db")
        label = os.path.join(backup_dir(), name + ".check.json")
        assert os.path.isfile(label)
        with open(label, encoding="utf-8") as fh:
            assert json.load(fh)["ok"]
        delete_backup(name)
        assert not os.path.exists(label)
