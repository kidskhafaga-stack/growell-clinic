"""A restore that leaves the database a version behind is not a restore.

Reported: *"when I took a backup and restored it I got a load of problems,
because I had developed parts in between."*

`restore_backup` put the older database and its files back and stopped. Newer
code then went looking for a column that database has never had. The symptoms
scatter — one screen fine, the next raising ``no such column`` — so it reads as
a corrupt backup rather than a schema one version behind, and the reasonable
response to a corrupt backup is to abandon it and re-enter the settings by hand.

That is a restore which *appeared to work* and cost somebody their afternoon,
and it is the worst shape a bug can take: the failure is far from the cause, and
the obvious diagnosis is the wrong one.

The first test here reproduces it properly — an old database really missing a
column the code needs — because a test that only checks "the upgrade was called"
would still pass if the upgrade stopped doing anything.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic_db(tmp_path, monkeypatch):
    """A real on-disk clinic database, plus a backup folder."""
    from app import create_app
    from app.extensions import db

    live = tmp_path / "growell.db"
    backups = tmp_path / "backups"
    backups.mkdir()

    # The env var has to be set *before* create_app: the engine is built when
    # the extension initialises, so assigning the URI afterwards would leave
    # every table in the in-memory database and the file empty.
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
    return {"app": app, "db": db, "live": live, "backups": backups}


def _columns(path, table):
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _drop_column(path, table, column):
    """Make a database look like one taken before ``column`` existed.

    SQLite cannot drop a column on older versions, so the table is rebuilt
    without it — which is exactly the shape an older backup really has.
    """
    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")
                if r[1] != column]
        joined = ", ".join(cols)
        conn.execute(f"CREATE TABLE _old AS SELECT {joined} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE _old RENAME TO {table}")


# --------------------------------------------------------- the reported bug -
def test_restoring_an_older_backup_brings_its_schema_forward(clinic_db):
    """The reported failure, reproduced: a backup genuinely missing a column
    the running code reads."""
    from app.utils.backups import create_backup, restore_backup

    live = str(clinic_db["live"])
    # Age the database *before* backing it up, so the archive genuinely is one
    # taken before the column existed. (The archive is a zip, so it cannot be
    # edited in place — and faking it there would test the test, not the code.)
    _drop_column(live, "cash_accounts", "settle_after_days")
    assert "settle_after_days" not in _columns(live, "cash_accounts")
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        name = create_backup("test")
    assert name

    with clinic_db["app"].app_context():
        restore_backup(name)
        assert "settle_after_days" in _columns(
            str(clinic_db["live"]), "cash_accounts"), (
            "the restored database is still a version behind — this is the "
            "bug: the next screen to read that column raises no such column")


def test_the_restored_data_is_still_the_backups(clinic_db):
    """Upgrading the schema must not have quietly re-seeded or reset anything.
    The point of a restore is the data in the backup, not a fresh install."""
    from app.models import Patient
    from app.utils.backups import create_backup, restore_backup

    with clinic_db["app"].app_context():
        clinic_db["db"].session.add(Patient(
            patient_number="P-BACKUP", full_name="طفل النسخة", gender="male",
            date_of_birth=__import__("datetime").date(2025, 1, 1),
            is_active=True))
        clinic_db["db"].session.commit()
        name = create_backup("test")

        clinic_db["db"].session.query(Patient).delete()
        clinic_db["db"].session.commit()
        assert Patient.query.count() == 0

        restore_backup(name)
        clinic_db["db"].session.expire_all()
        assert Patient.query.filter_by(patient_number="P-BACKUP").count() == 1


def test_restoring_a_current_backup_changes_nothing(clinic_db):
    """Idempotent, or every restore of an up-to-date backup would be a
    schema migration nobody asked for."""
    from app.utils.backups import create_backup, restore_backup

    with clinic_db["app"].app_context():
        before = _columns(str(clinic_db["live"]), "cash_accounts")
        name = create_backup("test")
        restore_backup(name)
        assert _columns(str(clinic_db["live"]), "cash_accounts") == before


def test_the_pre_restore_snapshot_is_still_taken(clinic_db):
    """A mistaken restore has to stay reversible — the upgrade running
    afterwards must not have displaced the snapshot taken before."""
    from app.utils.backups import create_backup, restore_backup

    with clinic_db["app"].app_context():
        name = create_backup("test")
        pre = restore_backup(name)
    assert pre and "prerestore" in pre


# ------------------------------------------------------- the schema itself --
def test_applying_the_schema_twice_does_nothing_the_second_time(clinic_db):
    from app.utils.schema import apply_schema

    with clinic_db["app"].app_context():
        apply_schema()
        assert apply_schema() == 0


def test_it_adds_a_missing_column_and_reports_it(clinic_db):
    from app.utils.schema import apply_schema

    _drop_column(str(clinic_db["live"]), "cash_accounts", "fee_percent")
    said = []
    with clinic_db["app"].app_context():
        clinic_db["db"].engine.dispose()
        assert apply_schema(report=said.append) >= 1
    assert any("cash_accounts.fee_percent" in line for line in said)
    assert "fee_percent" in _columns(str(clinic_db["live"]), "cash_accounts")


def test_it_never_removes_anything(clinic_db):
    """Additive only. A migration that can drop a column is a migration that
    can lose data on a path nobody is watching — and the restore path is
    exactly that."""
    import inspect

    from app.utils import schema

    source = inspect.getsource(schema.apply_schema).lower()
    for danger in ("drop table", "drop column", "delete from", "truncate"):
        assert danger not in source, danger


def test_the_cli_and_the_restore_run_the_same_code():
    """They drifted apart once already — the command had the schema and the
    restore had nothing. One function, two callers."""
    import inspect

    from app import cli
    from app.utils import backups

    assert "apply_schema" in inspect.getsource(cli.register_commands)
    assert "apply_schema" in inspect.getsource(backups)


# ----------------------------------------------------- the launcher scripts -
def _read(name):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, name), encoding="utf-8", errors="replace") as fh:
        return fh.read()


def test_starting_the_program_is_not_an_update():
    """`start.bat` ran `git pull` on every launch: no backup first, no schema
    upgrade after, in the middle of a working day. Starting the program and
    changing the program are different decisions."""
    body = _read("start.bat")
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("REM"):
            continue                       # the note explaining the removal
        assert "git pull" not in stripped, stripped


def test_there_is_a_deliberate_way_to_update():
    """Removing the automatic pull without leaving a way to update would just
    move the problem to whoever needs the new version."""
    assert os.path.isfile(os.path.join(
        os.path.dirname(__file__), "..", "update.bat"))


def test_the_update_backs_up_before_it_changes_anything():
    """Order is the whole design: the backup is what makes every later step
    reversible, so it cannot come after them."""
    body = _read("update.bat")
    live = [ln for ln in body.splitlines()
            if not ln.strip().upper().startswith("REM")]
    joined = "\n".join(live)
    assert joined.index("backup-now") < joined.index("git pull")
    assert joined.index("git pull") < joined.index("upgrade-db")


def test_the_update_stops_if_the_backup_fails():
    """Continuing without one is precisely the situation this file exists to
    prevent."""
    body = _read("update.bat")
    after = body[body.index("backup-now"):]
    assert "exit /b 1" in after[:after.index("git pull")]


def test_the_update_checks_the_program_still_starts():
    """"Finished without an error" is not "works", and the difference only
    shows if somebody looks."""
    body = _read("update.bat")
    assert "create_app" in body and body.index("upgrade-db") < body.index("create_app")


# ------------------------------------------- what every launch should cost --
def test_starting_the_program_matches_the_schema_without_backing_up(clinic_db):
    """Reported as a question: *"why isn't upgrade-db in start.bat so it runs
    automatically?"* It was — and that was the problem.

    ``upgrade-db`` takes a **pre-upgrade backup first**, and that archive holds
    the database *and every uploaded file*. Running it on every launch meant a
    clinic with a few gigabytes of photos wrote a few gigabytes every time
    somebody opened the program, and nothing trimmed those copies until the
    next scheduled backup happened to come round. Five launches in a morning,
    five full copies of the clinic. Disks fill quietly, and a full disk is what
    stops a clinic.

    What a launch actually needs is for the database's *shape* to match the
    code about to read it. That is additive, idempotent and free.
    """
    body = _read("start.bat")
    live = [ln for ln in body.splitlines()
            if not ln.strip().upper().startswith("REM")]
    joined = "\n".join(live)
    assert "sync-db" in joined
    assert "upgrade-db" not in joined, "every start still costs a full backup"


def test_the_deliberate_update_still_does_the_full_job(clinic_db):
    """Splitting them must not have left `update.bat` doing only the shape:
    the seeding and backfills are what a new version brings with it."""
    body = _read("update.bat")
    live = [ln for ln in body.splitlines()
            if not ln.strip().upper().startswith("REM")]
    assert "upgrade-db" in "\n".join(live)


def test_the_shape_command_takes_no_backup(clinic_db):
    """A snapshot per launch is the cost this split exists to remove."""
    import inspect

    from app import cli

    source = inspect.getsource(cli.register_commands)
    start = source.index('@app.cli.command("sync-db")')
    end = source.index('@app.cli.command("upgrade-db")')
    assert "create_backup" not in source[start:end]


def test_the_automatic_snapshots_are_trimmed_like_every_other(clinic_db):
    """Retention only ever ran from the *scheduled* backup, so pre-upgrade
    archives piled up until that came round — and each carries every uploaded
    file in the clinic."""
    import inspect

    from app import cli

    source = inspect.getsource(cli.register_commands)
    # Anchored on the call, not on the words: the first draft of this test
    # matched the phrase inside the docstring that *explains* the problem and
    # passed without looking at any code.
    block = source[source.index('create_backup("preupgrade")'):]
    assert "apply_retention" in block[:400]


def test_the_shape_command_is_idempotent(clinic_db):
    """It runs on every launch, so doing nothing on an up-to-date database is
    not an optimisation — it is the requirement."""
    from app.utils.schema import apply_schema

    with clinic_db["app"].app_context():
        apply_schema()
        assert apply_schema() == 0


# ------------------------------------- every backup says where it came from -
def test_a_new_backup_carries_a_manifest(clinic_db):
    """UPGRADE_PLAN steps 3 and 4, which are really one thing. A backup that
    does not say where it came from is a backup you restore by guessing — and
    that guessing is the gap behind the reported "I restored a backup and got
    a load of problems": the restore was fine, the schema behind it was a
    version old, and nothing on the archive said so."""
    from app.utils.backups import create_backup, read_manifest

    with clinic_db["app"].app_context():
        name = create_backup("test")
        info = read_manifest(name)
    assert info.get("app_version")
    assert isinstance(info.get("schema_generation"), int)
    assert info.get("schema_version")


def test_the_schema_version_is_derived_not_typed(clinic_db):
    """A number somebody has to remember to bump is a number that will be
    wrong exactly when it matters — the release where a column was added and
    the version was not."""
    import inspect

    from app.utils import version

    source = inspect.getsource(version.schema_version)
    assert "ADDITIONS" in source
    assert "return \"" not in source, "the version is hard-coded"


def test_adding_a_column_changes_the_fingerprint(clinic_db):
    from app.utils import schema
    from app.utils.version import schema_generation, schema_version

    before, count = schema_version(), schema_generation()
    schema.ADDITIONS.append(("patients", "made_up_column", "INTEGER"))
    try:
        assert schema_version() != before
        assert schema_generation() == count + 1
    finally:
        schema.ADDITIONS.pop()


# ------------------------------------------------ the two directions --------
def test_an_older_backup_restores_and_is_brought_forward(clinic_db):
    """Already true; the manifest only means we can now *say* it is happening,
    and silence is what made the original problem hard to place."""
    from app.utils.backups import create_backup, restore_backup, restore_check

    with clinic_db["app"].app_context():
        name = create_backup("test")
        # Pretend this build has since learned a column.
        from app.utils import schema
        schema.ADDITIONS.append(("patients", "made_up_column", "INTEGER"))
        try:
            ok, reason, info = restore_check(name)
            assert ok and reason == "older"
            assert info.get("app_version")
            restore_backup(name)
        finally:
            schema.ADDITIONS.pop()


def test_a_backup_from_a_newer_build_is_refused(clinic_db):
    """The one with teeth. Older code reading newer data does not crash — it
    **misreads**, which is the damage somebody finds weeks later in a number
    they cannot explain. Moving a backup from an updated computer onto one
    that was never updated is the ordinary way this happens."""
    import pytest as _pytest

    from app.utils.backups import create_backup, restore_backup, restore_check

    with clinic_db["app"].app_context():
        from app.utils import schema
        schema.ADDITIONS.append(("patients", "made_up_column", "INTEGER"))
        try:
            name = create_backup("test")      # written by the "newer" build
        finally:
            schema.ADDITIONS.pop()            # and now we are the older one

        ok, reason, _ = restore_check(name)
        assert not ok and reason == "newer"
        with _pytest.raises(ValueError) as caught:
            restore_backup(name)
        assert str(caught.value) == "backup_newer"


def test_a_refused_restore_touches_nothing(clinic_db):
    """Refusing after overwriting the live database would be the worst of both
    answers."""
    import pytest as _pytest

    from app.models import Patient
    from app.utils.backups import create_backup, restore_backup

    with clinic_db["app"].app_context():
        from app.utils import schema
        schema.ADDITIONS.append(("patients", "made_up_column", "INTEGER"))
        try:
            name = create_backup("test")
        finally:
            schema.ADDITIONS.pop()

        clinic_db["db"].session.add(Patient(
            patient_number="P-LIVE", full_name="طفل حالي", gender="male",
            date_of_birth=__import__("datetime").date(2025, 1, 1),
            is_active=True))
        clinic_db["db"].session.commit()

        with _pytest.raises(ValueError):
            restore_backup(name)
        clinic_db["db"].session.expire_all()
        assert Patient.query.filter_by(patient_number="P-LIVE").count() == 1


def test_a_backup_with_no_manifest_is_still_allowed(clinic_db):
    """Most of the backups a clinic already has have no manifest. Refusing
    them would make this feature cost people the very archives it exists to
    protect."""
    from app.utils.backups import read_manifest, restore_check

    with clinic_db["app"].app_context():
        assert read_manifest("backup-20240101-000000-manual.zip") == {}
        ok, reason, _ = restore_check("backup-20240101-000000-manual.zip")
        assert ok and reason == "unknown"


def test_the_same_version_says_so(clinic_db):
    from app.utils.backups import create_backup, restore_check

    with clinic_db["app"].app_context():
        name = create_backup("test")
        ok, reason, _ = restore_check(name)
        assert ok and reason == "same"


def test_the_version_shows_in_the_list_before_restoring(clinic_db):
    """The only moment it is any use is before somebody clicks."""
    from app.utils.backups import create_backup, list_backups

    with clinic_db["app"].app_context():
        create_backup("test")
        rows = list_backups()
    assert rows and rows[0]["app_version"]


def test_a_backup_never_fails_over_its_own_label(clinic_db):
    """The manifest is a nicety; the database is not. Anything that goes wrong
    labelling the archive must not cost the clinic the snapshot."""
    import inspect

    from app.utils import backups

    source = inspect.getsource(backups._manifest_for)
    assert "except Exception" in source
