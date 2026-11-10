"""Alembic's entry point, run inside the program.

The connection is the program's own, handed in by ``app/utils/migrations``:
nothing here reads a URL or a config file, so a migration always runs on the
database the program has open — the clinic's, never a guess.
"""
from alembic import context

connection = context.config.attributes["connection"]
# Batch mode lets a migration change a column on SQLite, which cannot ALTER
# one in place: the table is rebuilt with the change and the data copied.
context.configure(connection=connection, target_metadata=None,
                  render_as_batch=True, compare_type=False)

with context.begin_transaction():
    context.run_migrations()
