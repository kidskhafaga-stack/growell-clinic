"""A backup's whole job is to leave the building.

Onto a flash drive, into a cloud folder, sent to whoever keeps the spare copy.
The archive holds every patient the clinic has ever seen — names, phone
numbers, diagnoses, the photographs — and until it was encrypted, every one of
those journeys handed the lot to whoever picked it up.

Encrypted as AES-256 (WinZip), which 7-Zip opens, because a backup you can
only restore by having this program working is a backup that fails you on the
day the computer doesn't.
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PASSPHRASE = "clinic-backup-2026"


@pytest.fixture()
def clinic_on_disk(tmp_path, monkeypatch):
    """A clinic whose database is a real file — backups copy one.

    The in-memory database every other test uses has nothing to snapshot, so
    this is the one fixture that needs a path on disk.
    """
    from app import create_app
    from app.extensions import db

    dbfile = tmp_path / "growell.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    monkeypatch.setenv("BACKUP_PASSWORD", "")
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{dbfile}"
    app.config["BACKUP_PASSWORD"] = ""
    app.instance_path = str(tmp_path)
    with app.app_context():
        db.create_all()
        from app.models import Patient
        from datetime import date
        db.session.add(Patient(patient_number="B-1", full_name="طفل النسخة",
                               gender="male", date_of_birth=date(2024, 1, 1),
                               is_active=True))
        db.session.commit()
    return {"app": app, "db": db, "tmp": tmp_path}


def _with_passphrase(clinic_on_disk, value=PASSPHRASE):
    clinic_on_disk["app"].config["BACKUP_PASSWORD"] = value
    return clinic_on_disk


def _make(clinic_on_disk, reason="manual"):
    from app.utils.backups import backup_dir, create_backup

    with clinic_on_disk["app"].app_context():
        name = create_backup(reason)
        return name, os.path.join(backup_dir(), name)


# ------------------------------------------------------------ unencrypted --
def test_without_a_passphrase_the_backup_is_a_plain_zip(clinic_on_disk):
    """Not a regression — a clinic that hasn't set one must still get
    backups, and they must still restore."""
    from app.utils.backups import is_encrypted

    _name, path = _make(clinic_on_disk)
    assert zipfile.ZipFile(path).namelist()[0] == "database.db"
    with clinic_on_disk["app"].app_context():
        assert is_encrypted(path) is False


# -------------------------------------------------------------- encrypted --
def test_with_a_passphrase_the_contents_are_locked(clinic_on_disk):
    from app.utils.backups import is_encrypted

    _with_passphrase(clinic_on_disk)
    _name, path = _make(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        assert is_encrypted(path) is True
    # …and the database really is unreadable without it.
    with zipfile.ZipFile(path) as zf:
        with pytest.raises(RuntimeError):
            zf.read("database.db")


def test_the_locked_archive_still_opens_with_the_passphrase(clinic_on_disk):
    """The point of AES-ZIP rather than a container of our own: any archiver
    can do this, so a restore never depends on this program running."""
    import pyzipper

    _with_passphrase(clinic_on_disk)
    _name, path = _make(clinic_on_disk)

    with pyzipper.AESZipFile(path) as zf:
        zf.setpassword(PASSPHRASE.encode())
        assert zf.read("database.db").startswith(b"SQLite format 3\x00")


def test_a_wrong_passphrase_does_not_open_it(clinic_on_disk):
    import pyzipper

    _with_passphrase(clinic_on_disk)
    _name, path = _make(clinic_on_disk)

    with pyzipper.AESZipFile(path) as zf:
        zf.setpassword(b"not-the-one")
        with pytest.raises(Exception):
            zf.read("database.db")


def test_the_file_names_stay_readable_and_that_is_said_out_loud(clinic_on_disk):
    """WinZip AES encrypts contents, not the directory. The paths are random
    ids so it is close to nothing — but it is not nothing, and a test is where
    that stops being a surprise."""
    _with_passphrase(clinic_on_disk)
    _name, path = _make(clinic_on_disk)

    assert "database.db" in zipfile.ZipFile(path).namelist()


# ------------------------------------------------------------ round trip ---
def test_an_encrypted_backup_restores(clinic_on_disk):
    from app.models import Patient
    from app.utils.backups import restore_backup

    _with_passphrase(clinic_on_disk)
    name, _path = _make(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        clinic_on_disk["db"].session.query(Patient).delete()
        clinic_on_disk["db"].session.commit()
        assert Patient.query.count() == 0

        restore_backup(name)
        assert Patient.query.count() == 1


def test_restoring_with_the_wrong_passphrase_says_so(clinic_on_disk):
    from app.utils.backups import restore_backup

    _with_passphrase(clinic_on_disk)
    name, _path = _make(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        with pytest.raises(ValueError) as exc:
            restore_backup(name, password="wrong-one")
        assert str(exc.value) == "bad_password"


def test_a_backup_from_before_a_passphrase_change_still_restores(clinic_on_disk):
    """Changing the passphrase must not orphan every snapshot taken under the
    old one. The clinic types the old words once."""
    from app.models import Patient
    from app.utils.backups import restore_backup

    _with_passphrase(clinic_on_disk, "the-old-words-here")
    name, _path = _make(clinic_on_disk)
    _with_passphrase(clinic_on_disk, "the-new-words-here")

    with clinic_on_disk["app"].app_context():
        clinic_on_disk["db"].session.query(Patient).delete()
        clinic_on_disk["db"].session.commit()

        restore_backup(name, password="the-old-words-here")
        assert Patient.query.count() == 1


def test_a_wrong_passphrase_is_caught_before_anything_is_overwritten(
        clinic_on_disk):
    """Discovering it after the live database had been replaced would be the
    worst possible moment."""
    from app.models import Patient
    from app.utils.backups import list_backups, restore_backup

    _with_passphrase(clinic_on_disk)
    name, _path = _make(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        before = len(list_backups())
        with pytest.raises(ValueError):
            restore_backup(name, password="wrong-one")
        # The live data is untouched, and no pre-restore snapshot was taken
        # for a restore that never happened.
        assert Patient.query.count() == 1
        assert len(list_backups()) == before


def test_a_plain_backup_still_restores_after_a_passphrase_is_set(clinic_on_disk):
    """Snapshots taken before the clinic turned encryption on are not
    suddenly unreadable."""
    from app.models import Patient
    from app.utils.backups import restore_backup

    name, _path = _make(clinic_on_disk)          # no passphrase yet
    _with_passphrase(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        clinic_on_disk["db"].session.query(Patient).delete()
        clinic_on_disk["db"].session.commit()

        restore_backup(name)
        assert Patient.query.count() == 1


# ----------------------------------------------------------- the listing ---
def test_the_list_says_which_snapshots_are_locked(clinic_on_disk):
    """Read from the archive, not from its name: a name can be changed by
    anyone who can rename a file, and a clinic must not be told a snapshot is
    protected when it isn't."""
    from app.utils.backups import list_backups

    _make(clinic_on_disk, "manual")
    _with_passphrase(clinic_on_disk)
    _make(clinic_on_disk, "auto")

    with clinic_on_disk["app"].app_context():
        states = {b["name"].split("-")[-1]: b["encrypted"]
                  for b in list_backups()}
    assert states["auto.zip"] is True
    assert states["manual.zip"] is False


# ---------------------------------------------------- where the key lives --
def test_the_passphrase_is_not_in_the_database(clinic_on_disk):
    """A key stored beside the thing it locks is decoration — whoever took the
    database would have taken the passphrase with it."""
    from app.models import Setting

    _with_passphrase(clinic_on_disk)
    _make(clinic_on_disk)

    with clinic_on_disk["app"].app_context():
        values = " ".join((s.value or "") for s in Setting.query.all())
        assert PASSPHRASE not in values


def test_clinic_env_replaces_the_line_rather_than_stacking_them(tmp_path):
    """Appending a second BACKUP_PASSWORD= would leave the old one above it,
    and `parse` takes the last — the file would say one thing and the program
    mean another."""
    from app import settings_file

    env = {}
    target = tmp_path / "clinic.env"
    target.write_text("PORT=5000\n# a comment the clinic wrote\n",
                      encoding="utf-8")

    settings_file.set_value("BACKUP_PASSWORD", "first-one", root=str(tmp_path),
                            environ=env)
    settings_file.set_value("BACKUP_PASSWORD", "second-one", root=str(tmp_path),
                            environ=env)

    text = target.read_text(encoding="utf-8")
    assert text.count("BACKUP_PASSWORD=") == 1
    assert "second-one" in text
    assert env["BACKUP_PASSWORD"] == "second-one"
    # The clinic's own lines survive.
    assert "PORT=5000" in text
    assert "# a comment the clinic wrote" in text


def test_clearing_it_removes_the_line(tmp_path):
    from app import settings_file

    env = {}
    target = tmp_path / "clinic.env"
    target.write_text("PORT=5000\n", encoding="utf-8")

    settings_file.set_value("BACKUP_PASSWORD", "x" * 12, root=str(tmp_path),
                            environ=env)
    settings_file.set_value("BACKUP_PASSWORD", "", root=str(tmp_path),
                            environ=env)

    assert "BACKUP_PASSWORD" not in target.read_text(encoding="utf-8")
    assert "BACKUP_PASSWORD" not in env


# ------------------------------------------------------------- the screen --
def test_the_screen_warns_a_clinic_with_no_passphrase(clinic):
    body = clinic["sign_in"]("boss").get("/settings/data").get_data(as_text=True)
    assert "تشفير النسخة الاحتياطية" in body


def test_setting_it_needs_the_two_entries_to_match(clinic, tmp_path,
                                                   monkeypatch):
    from app import settings_file

    monkeypatch.setattr(settings_file, "default_root", lambda: str(tmp_path))
    boss = clinic["sign_in"]("boss")

    boss.post("/settings/data/backup-password",
              data={"backup_password": "longenough1",
                    "backup_password_confirm": "different11"})

    assert not (tmp_path / "clinic.env").exists() or \
        "BACKUP_PASSWORD" not in (tmp_path / "clinic.env").read_text()


def test_a_short_passphrase_is_refused(clinic, tmp_path, monkeypatch):
    from app import settings_file

    monkeypatch.setattr(settings_file, "default_root", lambda: str(tmp_path))
    boss = clinic["sign_in"]("boss")

    boss.post("/settings/data/backup-password",
              data={"backup_password": "short", "backup_password_confirm": "short"})

    assert not (tmp_path / "clinic.env").exists() or \
        "BACKUP_PASSWORD" not in (tmp_path / "clinic.env").read_text()


def test_setting_it_writes_clinic_env_and_never_the_audit_log(clinic, tmp_path,
                                                              monkeypatch):
    from app import settings_file
    from app.models import ActivityLog

    monkeypatch.setattr(settings_file, "default_root", lambda: str(tmp_path))
    (tmp_path / "clinic.env").write_text("PORT=5000\n", encoding="utf-8")
    boss = clinic["sign_in"]("boss")

    boss.post("/settings/data/backup-password",
              data={"backup_password": PASSPHRASE,
                    "backup_password_confirm": PASSPHRASE})

    assert PASSPHRASE in (tmp_path / "clinic.env").read_text(encoding="utf-8")
    with clinic["app"].app_context():
        rows = ActivityLog.query.filter_by(action="backup.password").all()
        assert len(rows) == 1
        assert rows[0].detail == "set"
        assert PASSPHRASE not in (rows[0].detail or "")
