"""Numbered migrations (Alembic) beside the additive upgrade — UPGRADE_PLAN.md ٧.

**Why two mechanisms, and which one a change uses.**

The additive step (``schema.apply_schema``) has always brought a database up
to the code: new tables, new nullable columns, the indexes the models ask
for — derived from the models themselves, so a column a developer forgets to
list is still added. It is proven on every clinic, and it stays.

What it cannot do is anything that is not an addition: drop or rename a
column, change its type, move data from one shape to another — and it cannot
say **where a database stands**. Those are what the numbered migrations in
``app/migrations/versions/`` are for, and the database records the last one
it ran (Alembic's ``alembic_version`` table).

So, from here on:

* a new table or a new nullable column → the model (and ``ADDITIONS`` if it
  needs a default or a backfill), exactly as before;
* anything else → a new numbered migration.

**Gradually, on purpose.** The first revision (``0001_baseline``) does
nothing: every clinic already running stopped at a different update, and a
migration that tried to describe their tables would be wrong for most of
them. A database that has never been numbered is stamped at the baseline once
its shape has been brought up by the additive step, and the migrations after
it then run in order. A brand-new database is built from the models — already
the newest shape — and is stamped at the newest revision without running any.

**It goes forward only.** A clinic goes back by restoring the backup the
update took first, never by running a migration backwards over its records.
"""
import os

BASELINE = "0001_baseline"


def location():
    """The folder holding ``env.py`` and ``versions/``."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "migrations")


def _config(connection, where=None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", where or location())
    cfg.attributes["connection"] = connection
    return cfg


def _script(where=None):
    from alembic.script import ScriptDirectory

    return ScriptDirectory(where or location())


def head(where=None):
    """The newest revision this program knows."""
    return _script(where).get_current_head()


def known(revision, where=None):
    """Whether this program knows a revision — a backup stamped with one it
    does not know was written by a newer program."""
    if not revision:
        return True
    try:
        return _script(where).get_revision(revision) is not None
    except Exception:  # noqa: BLE001 - alembic has several ways of saying «unknown»
        return False


def current(connection):
    """The revision this database last ran, or None if it was never numbered."""
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(connection).get_current_revision()


def bring_forward(fresh=False, report=None, where=None):
    """Stamp a database that was never numbered, then run what it has not run.

    ``fresh``: the database was just built from the models (the newest shape),
    so it is stamped at the newest revision and nothing runs. Returns the list
    of revisions run. The caller has already committed the additive step.
    """
    from alembic import command

    from app.extensions import db

    newest = head(where)
    ran = []
    with db.engine.begin() as connection:
        mine = current(connection)
        cfg = _config(connection, where)
        if mine is None:
            command.stamp(cfg, newest if fresh else BASELINE)
            if report:
                report(f"  ~ numbered migrations: stamped at "
                       f"{newest if fresh else BASELINE}")
            if fresh:
                return ran
            mine = BASELINE
        if mine != newest:
            script = _script(where)
            ran = [rev.revision for rev in
                   reversed(list(script.iterate_revisions(newest, mine)))]
            command.upgrade(cfg, "head")
            if report:
                for rev in ran:
                    report(f"  + migration {rev}")
    return ran
