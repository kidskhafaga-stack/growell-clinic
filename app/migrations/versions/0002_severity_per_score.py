"""A unit may keep more than one severity score per child.

Revision ID: 0002_severity_per_score
Revises: 0001_baseline
Create Date: 2026-11-26

HOSPITAL_PLAN ت-٦ب, decided by the hospital on 26 Nov: the incubators score
every child with SNAPPE-II **and** CRIB-II, each on its own — never one in
place of the other, never averaged. ``severity_records`` was unique on
(stay, unit), so it could hold one. This moves it to (stay, unit, score):
the column ``score_key`` (the additive step already added it from the
model) is filled from each record's score, and the old unique key is
replaced. SQLite cannot drop a constraint, so the table is rebuilt in batch
mode with its rows; a database already in the new shape is left alone.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_severity_per_score"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

OLD, NEW = "uq_severity_stay_unit", "uq_severity_stay_unit_score"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "severity_records" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("severity_records")}
    uniques = {u["name"] for u in inspector.get_unique_constraints("severity_records")}
    if "score_key" not in columns or OLD in uniques or NEW not in uniques:
        with op.batch_alter_table("severity_records", recreate="always") as table:
            if "score_key" not in columns:
                table.add_column(sa.Column("score_key", sa.String(40)))
            if OLD in uniques:
                table.drop_constraint(OLD, type_="unique")
            if NEW not in uniques:
                table.create_unique_constraint(NEW, ["admission_id", "unit_kind", "score_key"])
    op.execute(
        "UPDATE severity_records SET score_key = "
        "(SELECT severity_scores.key FROM severity_scores "
        " WHERE severity_scores.id = severity_records.score_id) "
        "WHERE score_key IS NULL")


def downgrade():
    raise NotImplementedError("restore the preupgrade backup instead")
