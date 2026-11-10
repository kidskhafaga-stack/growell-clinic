"""The starting point: every database as it stands when migrations arrived.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-10

Nothing to do, on purpose. The clinics already running each stopped at a
different update, so a first migration that tried to *describe* their tables
would be wrong for most of them. Their shape is brought up to the code by the
additive step that has always done it (``app/utils/schema.apply_schema``), and
this revision only says «from here on, changes are numbered».
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    raise NotImplementedError("restore the preupgrade backup instead")
