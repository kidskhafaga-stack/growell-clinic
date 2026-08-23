"""A column added by the list, and then again by the safety net.

Reported from a clinic's own screen, in the middle of `update.bat`:

    [4/5] Upgrading the database...
      + vaccines.scope_max_age_days
      ! vaccines.scope_max_age_days: (sqlite3.OperationalError) duplicate
        column name: scope_max_age_days

Nothing was broken by it. SQLite refused the second `ALTER`, the error was
caught, the count stayed right and the upgrade finished. What was wrong is
what a doctor was shown: a red line naming their patient database, at the one
moment they are least able to judge whether it matters.

**The cause is one word.** `apply_schema` adds the columns on its hand-kept
list, and then a second pass adds anything the list forgot — the net that
exists because `named_discounts.members_only` was once left out of the list
and every clinic that updated opened the discounts screen to "no such column".
Both passes were given the *same* `Inspector`, built before either ran, and an
Inspector caches what it reflected. So the net was reading a snapshot of the
table from before the list altered it, and every column the list had just
added still looked missing.

Which means this fired on every column ever added through the list. It only
became visible now because it is the first time anybody read that output
closely.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# A column that is on the model *and* on the hand-kept list — which is the
# combination that produced the duplicate. Any of them would do; this is the
# one the clinic reported.
TABLE, COLUMN = "vaccines", "scope_max_age_days"


def _drop(app):
    """Put the database back to before this column existed."""
    from sqlalchemy import text

    from app.extensions import db

    with app.app_context():
        db.session.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}"))
        db.session.commit()


def _columns(app):
    from sqlalchemy import text

    from app.extensions import db

    with app.app_context():
        return [row[1] for row in
                db.session.execute(text(f"PRAGMA table_info({TABLE})"))]


def test_the_column_is_on_both_the_list_and_the_model(clinic):
    """The premise. If it ever stops being on both, this file is testing
    nothing and should be pointed at a column that is."""
    from app.extensions import db
    from app.utils.schema import ADDITIONS

    assert any(t == TABLE and c == COLUMN for t, c, _ddl in ADDITIONS), \
        f"{TABLE}.{COLUMN} is no longer on the explicit list"
    assert COLUMN in db.metadata.tables[TABLE].columns, \
        f"{TABLE}.{COLUMN} is no longer on the model"


def test_upgrading_reports_no_error_about_the_clinics_database(clinic):
    """The line the doctor saw, and the whole point of the fix."""
    from app.extensions import db
    from app.utils.schema import apply_schema

    _drop(clinic["app"])
    assert COLUMN not in _columns(clinic["app"]), \
        "the before-state could not be reproduced"

    lines = []
    with clinic["app"].app_context():
        apply_schema(report=lines.append)
        db.session.commit()

    complaints = [line for line in lines if line.lstrip().startswith("!")]
    assert not complaints, \
        f"the upgrade reported an error about the database: {complaints}"


def test_and_it_is_added_exactly_once(clinic):
    """Said separately from the message, because "no error" could also be
    reached by swallowing the report."""
    from app.extensions import db
    from app.utils.schema import apply_schema

    _drop(clinic["app"])

    lines = []
    with clinic["app"].app_context():
        apply_schema(report=lines.append)
        db.session.commit()

    added = [line for line in lines if COLUMN in line and "+" in line]
    assert len(added) == 1, f"the column was announced {len(added)} times: {added}"
    assert _columns(clinic["app"]).count(COLUMN) == 1


def test_the_net_still_catches_what_the_list_forgot(clinic):
    """The pass being fixed is a safety net and has to go on being one.

    A fresh inspector could have been "fixed" by not running the second pass
    at all, which would restore the failure it exists for: a column added to a
    model, left off the list, and missing on every clinic that upgrades.
    """
    from sqlalchemy import text

    from app.extensions import db
    from app.utils import schema

    # A column on the model, deliberately *not* on the list, and safe for
    # SQLite to drop — no key, no index, no constraint. `code` is none of
    # those and the first draft picked it, which failed on the fixture rather
    # than on anything this test is about.
    listed = {(t, c) for t, c, _d in schema.ADDITIONS}
    victim = next(
        (col.name for col in db.metadata.tables[TABLE].columns
         if (TABLE, col.name) not in listed
         and not col.primary_key and not col.index and not col.unique
         and not col.foreign_keys and col.nullable),
        None)
    assert victim, "no model column is missing from the list to test with"

    with clinic["app"].app_context():
        db.session.execute(text(f"ALTER TABLE {TABLE} DROP COLUMN {victim}"))
        db.session.commit()
    assert victim not in _columns(clinic["app"])

    with clinic["app"].app_context():
        schema.apply_schema(report=None)
        db.session.commit()

    assert victim in _columns(clinic["app"]), \
        f"the net stopped catching a column the list does not carry: {victim}"


def test_a_second_upgrade_changes_nothing_and_says_nothing(clinic):
    """Running `update.bat` twice is normal — somebody re-runs it after a
    reboot, or after a failure elsewhere. The second run has to be quiet."""
    from app.extensions import db
    from app.utils.schema import apply_schema

    with clinic["app"].app_context():
        apply_schema(report=None)
        db.session.commit()

    lines = []
    with clinic["app"].app_context():
        applied = apply_schema(report=lines.append)
        db.session.commit()

    assert applied == 0, f"a settled database still reports {applied} change(s)"
    assert not [line for line in lines if line.lstrip().startswith("!")], \
        f"a second run complained: {lines}"
