"""Zero is only an answer when it is zero out of something.

A clinic ran the updater and got this:

    [2/5] Fetching the new version...
          This copy is not a git clone, so the files are downloaded instead.

    [4/5] Upgrading the database...
    Database upgraded (0 column(s) added).

and asked what it meant. It is not a silly question — it is genuinely two
different events wearing the same words:

* the database already had every column the new code wants, which is the
  ordinary outcome of an update that landed correctly; or
* the new code never arrived, so its models asked for nothing new.

Nothing on the screen told them apart. **Step 2 printed one sentence and then
nothing at all** — `robocopy` was run with every listing switch on, including
the job summary — and step 4 printed a bare zero. Answering the question took
opening folders and pasting commands to find out whether an update had
happened at all.

Neither step needed to *do* more. Both needed to say what they did.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _update_bat():
    path = os.path.join(os.path.dirname(__file__), "..", "update.bat")
    with open(os.path.abspath(path), encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------- step 2 ---

def test_the_copy_step_prints_its_summary(clinic):
    """`/NJS` suppresses robocopy's job summary — the four lines that say how
    many files were copied. With it on, the only evidence a clinic had that
    anything was copied was that no error appeared."""
    body = _update_bat()
    call = body[body.index('robocopy "%PP_SRC%"'):][:400]

    assert "/NJS" not in call, "the copy still hides how many files it moved"


def test_the_per_file_list_stays_off(clinic):
    """`/NFL` and `/NDL` are not the same decision. A first-time copy lists
    thousands of files and would push every other line off the screen, which
    is its own way of telling somebody nothing."""
    body = _update_bat()
    call = body[body.index('robocopy "%PP_SRC%"'):][:400]

    assert "/NFL" in call and "/NDL" in call


def test_the_file_is_still_readable_by_windows(clinic):
    """The scar this repo already carries: every `.bat` was stored with Unix
    line endings, a GitHub ZIP took the bytes verbatim, and `update.bat`
    opened and closed instantly on a clinic PC. Editing one of these files is
    exactly when that comes back."""
    path = os.path.join(os.path.dirname(__file__), "..", "update.bat")
    with open(os.path.abspath(path), "rb") as fh:
        raw = fh.read()

    lines = raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")
    bare = [i for i, ln in enumerate(lines, 1) if not ln.endswith(b"\r")]
    assert not bare, f"lines with no carriage return: {bare[:5]}"


# ------------------------------------------------------------- step 4 ---

def test_nothing_missing_says_how_much_was_checked(clinic):
    """The heart of it. "0 column(s) added" is silence; "every one of 1,300
    columns is already there" is an answer."""
    from app.utils.schema import apply_schema

    said = []
    with clinic["app"].app_context():
        applied = apply_schema(report=said.append)

    assert applied == 0, "the fixture's database was not already current"
    line = " ".join(said)
    assert "column(s)" in line and "table(s) checked" in line, \
        f"the schema step said nothing about what it looked at: {said}"


def test_the_count_moves_when_the_models_do(clinic):
    """A figure written by hand is true the day it is written. So this checks
    the count *responds* rather than matching today's total — a literal that
    happens to be right today passes the second kind of test and fails nobody
    until the next column is added, which is the failure mode being guarded
    against. Found by mutation testing, which is how it turned into this.
    """
    from sqlalchemy import Column, Integer, Table

    from app.extensions import db
    from app.utils.schema import _columns_the_models_expect

    with clinic["app"].app_context():
        before = _columns_the_models_expect()
        extra = Table("zz_probe", db.metadata,
                      Column("id", Integer, primary_key=True),
                      Column("a", Integer), Column("b", Integer))
        try:
            after = _columns_the_models_expect()
        finally:
            db.metadata.remove(extra)

    assert before > 100, "the count is implausibly small to be the real one"
    assert after == before + 3, \
        f"three columns were added to the models and the count went {before}->{after}"


def test_it_stays_quiet_when_it_actually_changed_something(clinic):
    """The line is for the ambiguous case. On an upgrade that added columns
    the count is not the news, and printing it under a list of what changed
    would bury the list."""
    from app.extensions import db
    from app.utils.schema import apply_schema

    with clinic["app"].app_context():
        db.session.execute(db.text("ALTER TABLE patients DROP COLUMN blood_type"))
        db.session.commit()

        said = []
        applied = apply_schema(report=said.append)

    assert applied >= 1
    assert not any("checked" in line for line in said), \
        "the summary line printed on an upgrade that had real news to report"


def test_the_report_is_optional_as_it_always_was(clinic):
    """`apply_schema` runs on the restore path with nobody watching a
    terminal. A new `report(...)` call that assumed a callable would raise
    there — during a restore, which is the worst possible moment."""
    from app.utils.schema import apply_schema

    with clinic["app"].app_context():
        assert apply_schema() == 0
