"""A new column on an old table has to be in ADDITIONS, or upgrades break.

This exists because it happened. `named_discounts.members_only` was added to
the model and not to :data:`app.utils.schema.ADDITIONS`, so every existing
clinic that pulled the update got:

    sqlite3.OperationalError: no such column: named_discounts.members_only

…on the discounts screen. Not a crash on some edge case — the screen simply
stopped opening, on a database with real money in it, and nothing in the test
suite noticed because the suite builds its database from the models and
therefore always has every column.

That is the trap in one sentence: **`db.create_all()` gives the tests a
perfect database, so tests can never feel a missing migration.** A new *table*
is fine — `create_all` creates it on the clinic's machine too. A new *column
on a table that already exists* is not: SQLite has to be told, and ADDITIONS
is where it is told.

So the check compares the models against a baseline of the schema as it stood
at the last release, and demands that anything added since be either a new
table or an entry in ADDITIONS. Regenerating the baseline is deliberate work,
which is the point — it is the moment somebody decides which of the two this
is.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

BASELINE = os.path.join(os.path.dirname(__file__), "schema_baseline.json")


def _model_schema(clinic):
    with clinic["app"].app_context():
        return {t.name: {c.name for c in t.columns}
                for t in clinic["db"].metadata.tables.values()}


def test_every_new_column_on_an_old_table_is_in_additions(clinic):
    """The one that would have caught it.

    A column on a table the clinic already has does not appear by itself.
    Either list it in ADDITIONS, or — if the whole table is new — regenerate
    the baseline, which says out loud that it is a new table.
    """
    from app.utils.schema import ADDITIONS

    with open(BASELINE, encoding="utf-8") as fh:
        base = json.load(fh)
    covered = {(table, column) for table, column, _ddl in ADDITIONS}

    missing = []
    for table, columns in sorted(_model_schema(clinic).items()):
        if table not in base:
            continue                    # a brand-new table; create_all makes it
        for column in sorted(columns):
            if column in base[table] or (table, column) in covered:
                continue
            missing.append(f"{table}.{column}")

    assert not missing, (
        "these columns were added to tables that already exist on a clinic's "
        "database, and nothing will create them there — add each to "
        "app/utils/schema.py::ADDITIONS: " + ", ".join(missing))


def test_the_column_that_broke_a_clinic_is_listed(clinic):
    """Pinned by name. It is cheap, and the next person to remove it from
    ADDITIONS should have to argue with a test rather than with a clinic."""
    from app.utils.schema import ADDITIONS

    assert ("named_discounts", "members_only") in {(t, c) for t, c, _ in ADDITIONS}


def test_additions_only_names_columns_the_models_really_have(clinic):
    """A stale entry is harmless at runtime and misleading forever: it says a
    column exists that nothing reads, and the next person to touch this list
    has to work out which entries are real."""
    from app.utils.schema import ADDITIONS

    schema = _model_schema(clinic)
    stale = [f"{t}.{c}" for t, c, _ in ADDITIONS
             if t in schema and c not in schema[t]]
    assert not stale, "ADDITIONS names columns no model has: " + ", ".join(stale)


def test_the_additions_actually_apply_to_a_database_missing_them(clinic):
    """End to end, in the direction a clinic experiences it.

    Every column ADDITIONS knows about is dropped from a real database — which
    is what an older clinic's file looks like — and then the upgrade is run.
    Every one has to come back, with DDL SQLite accepts.
    """
    from sqlalchemy import text

    from app.utils.schema import ADDITIONS, apply_schema

    db = clinic["db"]
    with clinic["app"].app_context():
        tables = set(db.metadata.tables)
        dropped = []
        for table, column, _ddl in ADDITIONS:
            if table not in tables:
                continue
            try:
                db.session.execute(
                    text(f"ALTER TABLE {table} DROP COLUMN {column}"))
                dropped.append((table, column))
            except Exception:           # noqa: BLE001 - a column SQLite won't drop
                db.session.rollback()    # (part of a key or an index) — skip it
        db.session.commit()
        assert dropped, "nothing was dropped, so this proved nothing"

        apply_schema()

        from sqlalchemy import inspect

        inspector = inspect(db.engine)
        still_missing = [
            f"{table}.{column}" for table, column in dropped
            if column not in {c["name"] for c in inspector.get_columns(table)}]
    assert not still_missing, (
        "the upgrade did not restore: " + ", ".join(still_missing))


def test_the_baseline_is_a_real_snapshot_not_an_empty_file(clinic):
    """Guarding the guard: an emptied baseline would make the first test pass
    for every column in the program."""
    with open(BASELINE, encoding="utf-8") as fh:
        base = json.load(fh)
    assert len(base) > 50
    assert sum(len(v) for v in base.values()) > 500
    # And it has to describe *this* program, not some other snapshot.
    assert "named_discounts" in base and "patients" in base


# ============================ and the part that does not need to be remembered ==
def test_a_column_left_out_of_additions_is_added_anyway(clinic):
    """The actual fix for this class of bug.

    ADDITIONS is hand-maintained, and a hand-maintained migration list gets
    forgotten exactly once per person who touches the models. So the upgrade
    also compares the models against the database directly: SQLAlchemy holds
    every column the code expects, the database holds every column it has, and
    the difference is precisely what has to be added.

    Simulated the way it really happened — a column dropped from the database
    and absent from ADDITIONS — because that is indistinguishable from one
    that was never listed.
    """
    from sqlalchemy import inspect, text

    from app.utils.schema import ADDITIONS, apply_schema

    db = clinic["db"]
    listed = {(t, c) for t, c, _ in ADDITIONS}
    with clinic["app"].app_context():
        # A real column on a real table that nobody put in ADDITIONS.
        victim = next((c.name for c in db.metadata.tables["patients"].columns
                       if ("patients", c.name) not in listed
                       and not c.primary_key and c.nullable
                       and not c.index and not c.unique
                       and not c.foreign_keys), None)
        assert victim, "no unlisted plain column to test with"

        db.session.execute(text(f"ALTER TABLE patients DROP COLUMN {victim}"))
        db.session.commit()
        assert victim not in {c["name"] for c in
                              inspect(db.engine).get_columns("patients")}

        apply_schema()

        assert victim in {c["name"] for c in
                          inspect(db.engine).get_columns("patients")}


def test_the_recovered_column_is_usable_not_just_present(clinic):
    """A column of the wrong type is a different failure with the same shape."""
    from sqlalchemy import text

    from app.models import Patient
    from app.utils.schema import apply_schema

    db = clinic["db"]
    with clinic["app"].app_context():
        db.session.execute(text("ALTER TABLE patients DROP COLUMN own_phone"))
        db.session.commit()
        apply_schema()

        row = Patient.query.first()
        row.own_phone = "01001234567"
        db.session.commit()
        assert Patient.query.filter_by(own_phone="01001234567").count() == 1


def test_a_boolean_default_survives_the_recovery(clinic):
    """`members_only` defaults to false, and the whole safety of that feature
    rests on old rows reading false rather than NULL."""
    from app.utils.schema import _literal_default

    from app.models import NamedDiscount

    column = NamedDiscount.__table__.columns["members_only"]
    assert _literal_default(column) == "0"


def test_a_callable_default_is_not_frozen_into_the_column(clinic):
    """`created_at` is `datetime.utcnow`. Baking the moment of the upgrade
    into every old row would be worse than leaving them NULL — it would look
    like data."""
    from app.utils.schema import _literal_default

    from app.models import NamedDiscount

    assert _literal_default(NamedDiscount.__table__.columns["created_at"]) is None
