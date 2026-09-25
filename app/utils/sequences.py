"""The highest number already issued in a series — asked of the database.

File numbers and invoice numbers are both "the last one, plus one", and both
used to work out "the last one" by reading **every number ever issued** into
Python and taking the largest. On a clinic two years old that is eight
thousand patients or thirty thousand invoices read on every registration and
every checkout, and the load test (``tools/loadtest``) found it: a quarter of
a second each, on the two busiest writes in the building, and a quarter of a
second in which a second cashier can arrive at the same "last one".

The rule is unchanged — **only a tail made entirely of digits counts**, so a
number imported in some other shape neither breaks the series nor is taken
for part of it. The database answers it with one row instead of all of them.
"""
from sqlalchemy import BigInteger, cast, func

from app.extensions import db


def _digits_only(tail):
    """A condition true when ``tail`` is one or more digits and nothing
    else, in this database's own words — or ``None`` where there is none."""
    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        return (tail != "") & ~tail.op("GLOB")("*[^0-9]*")
    if dialect == "postgresql":
        return tail.op("~")("^[0-9]+$")
    return None


def highest(column, base):
    """The largest all-digit tail after ``base`` among ``column``'s values,
    or 0 when there is none."""
    tail = func.substr(column, len(base) + 1)
    digits = _digits_only(tail)
    starts = column.like(base + "%")
    if digits is None:
        # Some other database: the old way, which is correct and only slow.
        top = 0
        for (value,) in db.session.query(column).filter(starts):
            rest = (value or "")[len(base):]
            if rest.isdigit():
                top = max(top, int(rest))
        return top
    value = (db.session.query(func.max(cast(tail, BigInteger)))
             .filter(starts, digits).scalar())
    return int(value or 0)


def claim(obj, attribute, generate):
    """Add ``obj`` and give it its number **while holding the write lock**.

    "The last one, plus one" goes wrong in the gap between reading the last
    one and writing the next: a second save that commits in that gap takes
    the same number. The load test found the gap is not small — under load
    a save waits seconds for SQLite's write lock, and whoever commits while
    it waits takes its number; retrying only starts the same wait again.

    So the order is turned round. The row is written first under a
    placeholder nobody else can see, which is what takes the lock; the
    number is read **after** that, when no other save can commit until this
    one does. On SQLite that closes the gap. On a database that locks by row
    it narrows it, and :func:`retry_on_number_clash` is the backstop.

    The placeholder never outlives the request: it is replaced before the
    commit, and a rollback takes it with everything else.
    """
    import uuid

    setattr(obj, attribute, "~pending-" + uuid.uuid4().hex[:12])
    db.session.add(obj)
    db.session.flush()
    setattr(obj, attribute, generate())
    db.session.flush()
    return obj


#: The two numbers issued as "the last one, plus one".
NUMBERED = ("invoice_number", "patient_number")


def retry_on_number_clash(view, attempts=3):
    """Redo a save whose new number another save took first.

    "The last one, plus one" is read, then written; two cashiers pressing
    collect in the same instant read the same last one, and the second write
    is refused by the database's unique rule. The load test found it at
    thirty-two people — **the refused cashier got a server error page**,
    though nothing was half-written: the whole save was rolled back.

    So the save is simply done again, from the start, with a fresh number —
    the first one's is now the last one. Only for a clash on one of the two
    numbered columns, and only a few times; anything else is raised as it
    always was.

    **Only for a view that commits once, at the end, and reads no uploaded
    file** — rolling back has to leave nothing behind, and doing it again
    has to read the same request again.
    """
    from functools import wraps

    from sqlalchemy.exc import IntegrityError

    @wraps(view)
    def wrapped(*args, **kwargs):
        for attempt in range(attempts):
            try:
                return view(*args, **kwargs)
            except IntegrityError as exc:
                db.session.rollback()
                clash = any(name in str(getattr(exc, "orig", exc))
                            for name in NUMBERED)
                if not clash or attempt == attempts - 1:
                    raise
        return None  # pragma: no cover - the loop returns or raises

    return wrapped
