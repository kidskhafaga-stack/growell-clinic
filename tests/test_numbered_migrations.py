"""Numbered migrations beside the additive upgrade (UPGRADE_PLAN.md ٧).

A database that was never numbered is stamped at the baseline once its shape
is brought up, then runs what came after it, once. A new database is built
from the models and stamped at the newest revision without running anything.
A backup stamped with a revision this program does not know came from a newer
program, and is refused.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.utils import migrations  # noqa: E402

SECOND = '''"""A test migration: what the additive step cannot do — move data."""
from alembic import op

revision = "0002_test"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE settings SET value = 'moved' WHERE key = 'migrate_me'")
'''


@pytest.fixture
def clinic(tmp_path, monkeypatch):
    from app import create_app
    from app.extensions import db

    live = tmp_path / "growell.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    app = create_app("testing")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{live}"
    app.instance_path = str(tmp_path)
    ctx = app.app_context()
    ctx.push()
    yield {"app": app, "db": db, "tmp": tmp_path}
    db.session.remove()
    db.engine.dispose()
    ctx.pop()


def _with_second(tmp_path):
    """A copy of the migrations folder with one more revision in it."""
    where = tmp_path / "migrations"
    shutil.copytree(migrations.location(), where,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (where / "versions" / "0002_test.py").write_text(SECOND, encoding="utf-8")
    return str(where)


def _revision(db):
    with db.engine.connect() as conn:
        return migrations.current(conn)


def test_the_program_knows_its_baseline():
    assert migrations.head() == migrations.BASELINE
    assert migrations.known(migrations.BASELINE) and migrations.known(None)
    assert not migrations.known("9999_from_a_newer_program")


def test_a_new_database_is_stamped_at_the_newest_without_running_anything(clinic):
    from app.utils.schema import apply_schema

    apply_schema()
    assert _revision(clinic["db"]) == migrations.head()
    assert "alembic_version" in inspect(clinic["db"].engine).get_table_names()


def test_a_running_clinic_is_stamped_at_the_baseline_then_runs_what_follows_once(clinic):
    from app.models import Setting

    db = clinic["db"]
    db.create_all()                      # a clinic from before migrations
    Setting.set("migrate_me", "old")
    db.session.commit()
    where = _with_second(clinic["tmp"])

    ran = migrations.bring_forward(where=where)

    assert ran == ["0002_test"]
    assert _revision(db) == "0002_test"
    db.session.expire_all()
    assert Setting.get("migrate_me") == "moved"
    # A second upgrade finds nothing left to run.
    Setting.set("migrate_me", "typed again")
    db.session.commit()
    assert migrations.bring_forward(where=where) == []
    assert Setting.get("migrate_me") == "typed again"


def test_a_new_database_does_not_run_a_migration_written_for_older_ones(clinic):
    from app.models import Setting

    db = clinic["db"]
    db.create_all()
    Setting.set("migrate_me", "new clinic")
    db.session.commit()
    where = _with_second(clinic["tmp"])
    assert migrations.bring_forward(fresh=True, where=where) == []
    assert _revision(db) == "0002_test"
    assert Setting.get("migrate_me") == "new clinic"


def test_the_upgrade_says_what_it_did(clinic):
    from app.utils.schema import apply_schema

    clinic["db"].create_all()
    lines = []
    apply_schema(report=lines.append)
    assert any("stamped at 0001_baseline" in line for line in lines)


def test_a_backup_from_a_newer_program_is_refused(clinic, monkeypatch):
    from app.utils import backups

    monkeypatch.setattr(backups, "read_manifest",
                        lambda name, password=None: {"migration": "0009_newer",
                                                     "schema_generation": 1})
    ok, reason, _info = backups.restore_check("backup-20261110-120000.zip")
    assert (ok, reason) == (False, "newer")
    monkeypatch.setattr(backups, "read_manifest",
                        lambda name, password=None: {"migration": migrations.BASELINE,
                                                     "schema_generation": 1})
    assert backups.restore_check("backup-20261110-120000.zip")[0] is True


def test_every_backup_says_where_its_database_stands(clinic):
    from app.utils.schema import apply_schema
    from app.utils.version import manifest

    apply_schema()
    assert manifest()["migration"] == migrations.head()


def test_migrations_only_go_forward():
    folder = os.path.join(migrations.location(), "versions")
    for name in os.listdir(folder):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                assert "restore the preupgrade backup" in fh.read(), name
