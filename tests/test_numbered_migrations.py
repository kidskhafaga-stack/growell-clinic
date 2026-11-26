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

revision = "0003_test"
down_revision = "0002_severity_per_score"
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
    (where / "versions" / "0003_test.py").write_text(SECOND, encoding="utf-8")
    return str(where)


def _revision(db):
    with db.engine.connect() as conn:
        return migrations.current(conn)


def test_the_program_knows_its_baseline():
    assert migrations.head() == "0002_severity_per_score"
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

    assert ran == ["0002_severity_per_score", "0003_test"]
    assert _revision(db) == "0003_test"
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
    assert _revision(db) == "0003_test"
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


def test_a_stay_may_keep_two_severity_scores_after_the_upgrade(clinic):
    """0002 — the incubators keep SNAPPE-II and CRIB-II for one child, each
    on its own (HOSPITAL_PLAN ت-٦ب, 26 Nov). A database from before had one
    result per stay and unit; it is moved, and its rows keep their score."""
    from datetime import datetime

    from sqlalchemy import text

    from app.models import Admission, Patient, SeverityRecord, SeverityScore

    db = clinic["db"]
    db.create_all()
    from datetime import date

    child = Patient(patient_number="M-1", full_name="طفل", date_of_birth=date(2026, 10, 1), gender="male")
    db.session.add(child)
    db.session.flush()
    stay = Admission(patient_id=child.id, admitted_at=datetime.utcnow())
    a = SeverityScore(key="snappe2", name_ar="أ", kind="points", inputs=[], examples=[])
    b = SeverityScore(key="crib2", name_ar="ب", kind="points", inputs=[], examples=[])
    db.session.add_all([stay, a, b])
    db.session.commit()
    ids = (stay.id, child.id, a.id, b.id)
    with db.engine.begin() as conn:      # the table as it was before
        conn.execute(text("DROP TABLE severity_records"))
        conn.execute(text(
            "CREATE TABLE severity_records (id INTEGER PRIMARY KEY, admission_id INTEGER NOT NULL, "
            "patient_id INTEGER NOT NULL, unit_kind VARCHAR(12) NOT NULL, score_id INTEGER NOT NULL, "
            "entered_at DATETIME NOT NULL, measured_at DATETIME NOT NULL, \"values\" JSON NOT NULL, "
            "missing JSON NOT NULL, points FLOAT, probability FLOAT, recorded_by INTEGER, "
            "recorded_at DATETIME NOT NULL, "
            "CONSTRAINT uq_severity_stay_unit UNIQUE (admission_id, unit_kind))"))
        conn.execute(text(
            "INSERT INTO severity_records (admission_id, patient_id, unit_kind, score_id, entered_at, "
            "measured_at, \"values\", missing, points, recorded_at) VALUES "
            "(:s, :p, 'nicu', :a, '2026-11-01', '2026-11-01', '{}', '[]', 7, '2026-11-01')"),
            {"s": ids[0], "p": ids[1], "a": ids[2]})

    assert migrations.bring_forward() == ["0002_severity_per_score"]

    db.session.expire_all()
    old = SeverityRecord.query.one()
    assert (old.score_key, old.points) == ("snappe2", 7), "the old row keeps its score"
    now = datetime.utcnow()
    db.session.add(SeverityRecord(admission_id=ids[0], patient_id=ids[1], unit_kind="nicu",
                                  score_id=ids[3], score_key="crib2", entered_at=now,
                                  measured_at=now, values={}, missing=[], points=4))
    db.session.commit()
    assert SeverityRecord.query.filter_by(admission_id=ids[0]).count() == 2
    uniques = {u["name"] for u in inspect(db.engine).get_unique_constraints("severity_records")}
    assert "uq_severity_stay_unit" not in uniques and "uq_severity_stay_unit_score" in uniques
