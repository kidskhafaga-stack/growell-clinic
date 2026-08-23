"""Two kinds of backup, each on its own schedule and its own shelf.

The database and the uploaded files have different natures. The database is
megabytes and changes every minute — every patient, every payment, every dose.
The uploads are gigabytes and are effectively append-only: a photo taken today
is never edited again. One archive for both means copying gigabytes nightly to
capture megabytes of change, which does not merely cost time — it makes the
nightly backup expensive, so it gets taken less often, and the nightly one is
the one that saves you.

So there are two, and the admin sets **both numbers for each**: how often it is
taken, and how many are kept.

Two failures this file exists to keep shut:

* **A shared shelf.** With one retention count, the nightly database snapshots
  — far more numerous — steadily push the weekly full archives off the end. The
  clinic ends up with a fortnight of databases and not one copy of the
  photographs, which is exactly what splitting the backup was meant to prevent.
  Each kind counts its own.
* **A quiet half.** A clinic taking only the quick snapshot can believe it is
  covered for months and find out on the day the disk dies that every
  photograph, signature and scanned document is gone. Records restored beside
  missing pictures is the *original* failure the backup module was written to
  fix, arriving by a new road — so the screen says how old the full copy is,
  and shouts when it has stopped happening.
"""
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_db(tmp_path, monkeypatch):
    """A real on-disk clinic database, a backup folder, and an uploads folder."""
    from app import create_app
    from app.extensions import db

    live = tmp_path / "growell.db"
    backups = tmp_path / "backups"
    uploads = tmp_path / "uploads"
    backups.mkdir()
    (uploads / "patients").mkdir(parents=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    monkeypatch.setenv("BACKUP_PASSWORD", "")
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{live}"
    app.config["BACKUP_PASSWORD"] = ""
    app.instance_path = str(tmp_path)
    with app.app_context():
        db.create_all()

    monkeypatch.setattr("app.utils.backups.db_path", lambda: str(live))
    monkeypatch.setattr("app.utils.backups.backup_dir", lambda: str(backups))
    monkeypatch.setattr("app.utils.backups.uploads_root", lambda: str(uploads))
    return {"app": app, "db": db, "live": live, "backups": backups,
            "uploads": uploads}


def _photo(clinic_db, name="face.jpg", body=b"a picture"):
    path = clinic_db["uploads"] / "patients" / name
    path.write_bytes(body)
    return path


def _entries(clinic_db, name):
    with zipfile.ZipFile(os.path.join(str(clinic_db["backups"]), name)) as zf:
        return zf.namelist()


def _fake(clinic_db, stamp, reason="auto", kind="db", files=0, age_days=0):
    """An archive on disk with a chosen name, kind and age.

    Built by hand rather than by taking real backups: ``create_backup`` names
    archives to the second, so a loop of twenty would collide and overwrite
    each other, and the retention tests need twenty distinct ones.
    """
    from app.utils.backups import DB_ENTRY, FILES_PREFIX, MANIFEST_ENTRY

    name = f"backup-{stamp}-{reason}.zip"
    path = os.path.join(str(clinic_db["backups"]), name)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(DB_ENTRY, b"SQLite format 3\x00")
        if kind is not None:
            zf.writestr(MANIFEST_ENTRY, json.dumps({"kind": kind}))
        for i in range(files):
            zf.writestr(f"{FILES_PREFIX}patients/p{i}.jpg", b"x")
    when = (datetime.now() - timedelta(days=age_days)).timestamp()
    os.utime(path, (when, when))
    return name


# ============================================ what each kind actually holds ==
def test_the_quick_copy_carries_no_pictures(clinic_db):
    """The whole reason it is quick."""
    from app.utils.backups import FILES_PREFIX, create_backup

    _photo(clinic_db)
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("test", kind="db")

    assert not [n for n in _entries(clinic_db, name) if n.startswith(FILES_PREFIX)]


def test_the_full_copy_carries_them(clinic_db):
    from app.utils.backups import FILES_PREFIX, create_backup

    _photo(clinic_db)
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("test", kind="full")

    assert [n for n in _entries(clinic_db, name) if n.startswith(FILES_PREFIX)]


def test_both_kinds_still_carry_the_database(clinic_db):
    """A "database only" backup that forgot the database would be a joke that
    only lands on the day it is needed."""
    from app.utils.backups import DB_ENTRY, create_backup

    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        for kind in ("db", "full"):
            assert DB_ENTRY in _entries(clinic_db, create_backup(kind, kind=kind))


def test_an_unqualified_backup_keeps_behaving_as_it_always_did(clinic_db):
    """Existing callers — the pre-restore and pre-upgrade snapshots — pass no
    kind, and must keep following the clinic's setting rather than silently
    dropping to database-only."""
    from app.utils.backups import FILES_PREFIX, create_backup

    _photo(clinic_db)
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("prerestore")

    assert [n for n in _entries(clinic_db, name) if n.startswith(FILES_PREFIX)]


# ================================================= and what it says it holds =
def test_the_archive_records_its_own_kind(clinic_db):
    from app.utils.backups import create_backup, read_manifest

    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        quick = create_backup("aa", kind="db")
        full = create_backup("bb", kind="full")
        assert read_manifest(quick).get("kind") == "db"
        assert read_manifest(full).get("kind") == "full"


def test_an_older_archive_is_labelled_from_what_is_inside_it(clinic_db):
    """Most of the backups a clinic already owns were written before manifests
    existed. Refusing to label them would make this feature cost people the
    very archives it is meant to organise."""
    from app.utils.backups import backup_kind

    bare_db = _fake(clinic_db, "20260101-010000", kind=None, files=0)
    bare_full = _fake(clinic_db, "20260101-020000", kind=None, files=3)
    with clinic_db["app"].app_context():
        assert backup_kind(bare_db) == "db"
        assert backup_kind(bare_full) == "full"


def test_the_manifest_wins_over_a_guess(clinic_db):
    """A full archive of a clinic that has not uploaded anything yet contains
    no files — and is still a full archive. Counting entries alone would call
    it a database snapshot and start the "you have no picture backup" alarm on
    a clinic that is doing everything right."""
    from app.utils.backups import backup_kind

    empty_full = _fake(clinic_db, "20260101-030000", kind="full", files=0)
    with clinic_db["app"].app_context():
        assert backup_kind(empty_full) == "full"


def test_the_listing_already_knows_the_kind(clinic_db):
    """Read once while the archive is open, not re-opened per row: the settings
    screen lists every backup a clinic has."""
    from app.utils.backups import list_backups

    _fake(clinic_db, "20260101-040000", kind="full", files=2)
    _fake(clinic_db, "20260101-050000", kind="db")
    with clinic_db["app"].app_context():
        kinds = {b["name"]: b["kind"] for b in list_backups()}
    assert set(kinds.values()) == {"full", "db"}


def test_a_listing_row_is_not_reopened_to_ask_again(clinic_db):
    from app.utils.backups import backup_kind

    with clinic_db["app"].app_context():
        assert backup_kind({"name": "gone.zip", "kind": "full"}) == "full"


# =========================================== a shelf each, not a shared one ==
def test_the_daily_snapshots_cannot_push_the_full_ones_off_the_end(clinic_db):
    """The failure this split would otherwise introduce. Nightly database
    snapshots outnumber weekly full archives ten to one, so one shared count
    leaves a clinic with a fortnight of databases and no photographs at all —
    the exact loss the full archive exists to prevent."""
    from app.utils.backups import apply_retention, list_backups

    _fake(clinic_db, "20260101-000000", kind="full", files=2)
    for i in range(10):
        _fake(clinic_db, f"2026020{i}-000000", kind="db")

    with clinic_db["app"].app_context():
        apply_retention(3, 3)
        left = list_backups()

    assert [b for b in left if b["kind"] == "full"], "the pictures were evicted"
    assert len([b for b in left if b["kind"] == "db"]) == 3


def test_each_kind_is_trimmed_to_its_own_number(clinic_db):
    from app.utils.backups import apply_retention, list_backups

    for i in range(8):
        _fake(clinic_db, f"2026030{i}-000000", kind="db")
    for i in range(5):
        _fake(clinic_db, f"2026040{i}-000000", kind="full", files=1)

    with clinic_db["app"].app_context():
        apply_retention(5, 2)
        left = list_backups()

    assert len([b for b in left if b["kind"] == "db"]) == 5
    assert len([b for b in left if b["kind"] == "full"]) == 2


def test_the_newest_are_the_ones_kept(clinic_db):
    from app.utils.backups import apply_retention, list_backups

    old = _fake(clinic_db, "20260101-000000", kind="db")
    new = _fake(clinic_db, "20260601-000000", kind="db")

    with clinic_db["app"].app_context():
        apply_retention(1, 1)
        names = [b["name"] for b in list_backups()]

    assert names == [new] and old not in names


def test_one_number_still_means_one_number(clinic_db):
    """Older callers pass a single count. They must keep meaning what they
    meant, not silently gain an unlimited second shelf."""
    from app.utils.backups import apply_retention, list_backups

    for i in range(4):
        _fake(clinic_db, f"2026050{i}-000000", kind="full", files=1)

    with clinic_db["app"].app_context():
        apply_retention(2)
        assert len(list_backups()) == 2


def test_manual_backups_are_never_trimmed_whichever_kind(clinic_db):
    """They are the admin's. Somebody who took a copy before a risky change
    must find it there afterwards."""
    from app.utils.backups import apply_retention, list_backups

    for i in range(4):
        _fake(clinic_db, f"2026060{i}-000000", reason="manual", kind="db")

    with clinic_db["app"].app_context():
        apply_retention(1, 1)
        assert len(list_backups()) == 4


def test_a_junk_number_does_not_delete_everything(clinic_db):
    from app.utils.backups import apply_retention, list_backups

    for i in range(3):
        _fake(clinic_db, f"2026070{i}-000000", kind="db")

    with clinic_db["app"].app_context():
        apply_retention("", None)
        assert len(list_backups()) == 3


# ============================================== two schedules, independently =
def _due(clinic_db, **settings):
    """Run the scheduler with the clock at midday and given settings.

    The clock is now actually held there. This said "with the clock at
    midday" and did nothing of the kind — it read the wall clock — so
    `test_nothing_is_taken_before_the_chosen_hour`, which picks hour 23
    precisely because 23 is later than midday, was true for twenty-three hours
    a day and false for the twenty-fourth. It went red on CI at 23:34.

    Only the hour is pinned, and the date is left alone. Every other test here
    measures the *age* of a backup in days against today, and freezing the
    date would quietly rewrite what those ages mean.
    """
    from unittest import mock

    from app.models import Setting
    from app.utils import backups as _backups
    from app.utils.backups import _AUTO, auto_backup_if_due

    real = _backups.datetime

    class _AtMidday(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz).replace(hour=12, minute=0, second=0,
                                        microsecond=0)

    with clinic_db["app"].app_context():
        for key, value in settings.items():
            Setting.set(key, str(value))
        clinic_db["db"].session.commit()
        clinic_db["db"].engine.dispose()
        _AUTO["checked_at"] = 0.0
        with mock.patch.object(_backups, "datetime", _AtMidday):
            return auto_backup_if_due()


def test_the_full_copy_runs_on_its_own_rhythm(clinic_db):
    """A database snapshot taken this morning must not count as the weekly
    archive — the pictures were never in it."""
    from app.utils.backups import _days_since_auto

    _fake(clinic_db, "20260401-000000", kind="db", age_days=0)
    with clinic_db["app"].app_context():
        assert _days_since_auto("db") == 0
        assert _days_since_auto("full") > 365, "a database copy passed as full"


def test_a_full_copy_is_taken_when_its_own_interval_is_up(clinic_db):
    from app.utils.backups import backup_kind

    _fake(clinic_db, "20260401-010000", kind="db", age_days=0)
    _fake(clinic_db, "20260401-020000", kind="full", files=1, age_days=9)

    name = _due(clinic_db, backup_hour=0, backup_every_days=1,
                backup_full_every_days=7)
    assert name
    with clinic_db["app"].app_context():
        assert backup_kind(name) == "full"


def test_the_quick_copy_is_taken_when_the_full_one_is_not_due(clinic_db):
    from app.utils.backups import backup_kind

    _fake(clinic_db, "20260401-030000", kind="full", files=1, age_days=1)
    _fake(clinic_db, "20260401-040000", kind="db", age_days=2)

    name = _due(clinic_db, backup_hour=0, backup_every_days=1,
                backup_full_every_days=7)
    assert name
    with clinic_db["app"].app_context():
        assert backup_kind(name) == "db"


def test_when_both_fall_due_only_one_archive_is_written(clinic_db):
    """The full one covers the quick one. Writing both would put the same
    database on disk twice for no reason."""
    from app.utils.backups import backup_kind, list_backups

    name = _due(clinic_db, backup_hour=0, backup_every_days=1,
                backup_full_every_days=7)
    assert name
    with clinic_db["app"].app_context():
        assert backup_kind(name) == "full"
        assert len(list_backups()) == 1


def test_nothing_is_taken_before_the_chosen_hour(clinic_db):
    assert _due(clinic_db, backup_hour=23, backup_every_days=1,
                backup_full_every_days=7) is None


def test_turning_the_schedule_off_turns_both_off(clinic_db):
    assert _due(clinic_db, backup_auto_enabled=0, backup_hour=0,
                backup_every_days=1, backup_full_every_days=7) is None


def test_the_scheduler_trims_both_shelves(clinic_db):
    """Retention has to run from the scheduled backup — it is the only thing
    that runs on its own."""
    import inspect

    from app.utils import backups

    source = inspect.getsource(backups.auto_backup_if_due)
    assert source.count("_retain()") == 2, "one of the two paths never trims"
    retain = inspect.getsource(backups._retain)
    assert "backup_keep" in retain and "backup_full_keep" in retain


# ================================================= the alarm on the quiet half
def test_never_having_taken_a_full_copy_reads_as_no_age(clinic_db):
    from app.utils.backups import full_backup_age_days

    _fake(clinic_db, "20260401-050000", kind="db")
    with clinic_db["app"].app_context():
        assert full_backup_age_days() is None


def test_the_age_is_measured_from_the_full_copy_not_the_last_backup(clinic_db):
    from app.utils.backups import full_backup_age_days

    _fake(clinic_db, "20260401-060000", kind="full", files=1, age_days=20)
    _fake(clinic_db, "20260401-070000", kind="db", age_days=0)
    with clinic_db["app"].app_context():
        assert full_backup_age_days() == 20


def test_never_taken_is_overdue(clinic_db):
    """The state a clinic can sit in for a year without noticing, and the one
    with the most to lose."""
    from app.utils.backups import full_backup_overdue

    with clinic_db["app"].app_context():
        assert full_backup_overdue() is True


def test_a_copy_a_couple_of_days_late_is_not_shouted_about(clinic_db):
    """A weekly archive is normally a day or two late. A banner that lights up
    every Monday is furniture nobody reads by the second week."""
    from app.utils.backups import full_backup_overdue

    with clinic_db["app"].app_context():
        assert full_backup_overdue(8, 7) is False


def test_a_schedule_that_has_actually_stopped_is_shouted_about(clinic_db):
    from app.utils.backups import full_backup_overdue

    with clinic_db["app"].app_context():
        assert full_backup_overdue(30, 7) is True


def test_the_threshold_follows_the_clinics_own_interval(clinic_db):
    """A clinic that chose a monthly archive is not overdue at 30 days."""
    from app.utils.backups import full_backup_overdue

    with clinic_db["app"].app_context():
        assert full_backup_overdue(30, 30) is False
        assert full_backup_overdue(30, 1) is True


# ============================================================ restoring one ==
def test_restoring_a_database_only_copy_leaves_the_pictures_alone(clinic_db):
    """It never held them, so it has nothing to say about them. Wiping the
    uploads folder to match would turn a routine restore into the picture loss
    the whole module exists to prevent."""
    from app.utils.backups import create_backup, restore_backup

    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("test", kind="db")

    kept = _photo(clinic_db, "taken-after.jpg", b"still here")
    with clinic_db["app"].app_context():
        restore_backup(name)

    assert kept.exists() and kept.read_bytes() == b"still here"


def test_restoring_a_full_copy_puts_the_pictures_back(clinic_db):
    from app.utils.backups import create_backup, restore_backup

    photo = _photo(clinic_db, "face.jpg", b"original")
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("test", kind="full")

    photo.unlink()
    with clinic_db["app"].app_context():
        restore_backup(name)

    assert photo.exists() and photo.read_bytes() == b"original"


# ================================================================ the screen =
def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_both_buttons_are_on_the_screen(clinic):
    body = clinic["sign_in"]("boss").get("/settings/data").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("backups.create_db_btn") in body
        assert t("backups.create_full_btn") in body


def test_each_button_says_which_kind_it_takes():
    page = _read("app", "templates", "settings", "data.html")
    assert 'name="kind" value="db"' in page
    assert 'name="kind" value="full"' in page


def test_each_kind_has_its_own_two_settings(clinic):
    """The request, plainly: how often, and how many to keep — for each."""
    body = clinic["sign_in"]("boss").get("/settings/data").get_data(as_text=True)
    for field in ("backup_every_days", "backup_keep",
                  "backup_full_every_days", "backup_full_keep"):
        assert f'name="{field}"' in body, field


def test_the_settings_are_stored(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    boss.post("/settings/data/backup-settings", data={
        "backup_auto_enabled": "1", "backup_hour": "3",
        "backup_every_days": "2", "backup_keep": "9",
        "backup_full_every_days": "14", "backup_full_keep": "3",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        assert Setting.get("backup_every_days") == "2"
        assert Setting.get("backup_keep") == "9"
        assert Setting.get("backup_full_every_days") == "14"
        assert Setting.get("backup_full_keep") == "3"


def test_a_nonsense_count_is_refused_rather_than_stored(clinic):
    """Zero kept copies means the next scheduled backup deletes itself."""
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    boss.post("/settings/data/backup-settings", data={
        "backup_hour": "3", "backup_every_days": "1", "backup_keep": "0",
        "backup_full_every_days": "7", "backup_full_keep": "0",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        assert int(Setting.get("backup_keep")) >= 1
        assert int(Setting.get("backup_full_keep")) >= 1


def test_an_unknown_interval_falls_back_instead_of_being_stored(clinic):
    from app.models import Setting

    boss = clinic["sign_in"]("boss")
    boss.post("/settings/data/backup-settings", data={
        "backup_hour": "3", "backup_every_days": "1",
        "backup_full_every_days": "999", "backup_full_keep": "4",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        assert Setting.get("backup_full_every_days") == "7"


def test_the_screen_says_how_old_the_full_copy_is(clinic):
    body = clinic["sign_in"]("boss").get("/settings/data").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert (t("backups.full_never") in body
                or t("backups.full_age")[:12] in body)


def test_the_row_says_what_is_in_each_archive():
    page = _read("app", "templates", "settings", "data.html")
    assert "b.kind == 'full'" in page
    assert "backups.kind_full" in page and "backups.kind_db" in page


def test_both_languages_carry_the_new_words():
    keys = ["create_db_btn", "create_full_btn", "kind_db", "kind_full",
            "kind_db_hint", "kind_full_hint", "every_2weeks", "every_month",
            "full_never", "full_age", "full_stale_hint"]
    for lang in ("ar", "en"):
        data = json.loads(_read("app", "i18n", "locales", f"{lang}.json"))
        for key in keys:
            assert data["backups"].get(key), f"{lang}.{key}"


def test_the_age_line_has_somewhere_to_put_the_number():
    """A parameterised string whose placeholder was renamed prints the brace
    at the admin instead of the days."""
    for lang in ("ar", "en"):
        data = json.loads(_read("app", "i18n", "locales", f"{lang}.json"))
        assert "{days}" in data["backups"]["full_age"]
    assert "{days}" in _read("app", "templates", "settings", "data.html")
