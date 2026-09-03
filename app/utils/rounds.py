"""Has anybody been round to this child today, and what did they say.

Two questions, and only the first of them is hard. "What did they say" is the
newest ``RoundNote``; "has anybody been round today" is the absence of one,
and an absence leaves no row to find — the same shape as a missed observation,
which is why this file looks like ``utils/observations.py``.

**Today is the clinic's today.** The notes are stored in UTC like everything
else, and the question being asked is a *calendar* one: a ward manager at
eleven in the morning wants to know who has not been seen **this morning**.
For a Cairo clinic on a UTC server, comparing against UTC midnight would call
the first three hours of every day yesterday — the mistake four money reports
were fixed for making. ``live.day_bounds`` already owns the conversion and is
reused rather than rewritten.

**Batched.** A round board draws every child in the department, so the newest
note for all of them is one query and today's answer falls out of it. There is
a size-comparison test that fails if this becomes a query per child.
"""
from datetime import datetime

from app.extensions import db
from app.models.round_note import ROUND_TRENDS, RoundNote
from app.utils.clock import local_today

# The departments where a daily round is a thing. Emergency is not one of
# them: a child is there for hours and the stay ends in a decision, so "was
# there a round today" would flag every trolley in the place from the moment
# it filled. Recovery is the same shape, shorter.
#
# A kind list rather than a column, for the reason `place.py` gives about
# kinds: what differs between these departments is tempo, not substance.
NO_ROUND_KINDS = ("emergency", "recovery")


def kind_has_rounds(kind):
    return kind not in NO_ROUND_KINDS


def latest_by_admission(admission_ids):
    """``{admission_id: newest RoundNote}`` in two queries.

    Newest by ``at`` — when the round happened — and not by when it was
    typed: a note written up at the desk after the round still belongs to the
    hour the doctor stood at the bed.
    """
    from sqlalchemy import and_, func

    ids = [i for i in admission_ids if i]
    if not ids:
        return {}
    newest = (db.session.query(
        RoundNote.admission_id.label("admission_id"),
        func.max(RoundNote.at).label("at"))
        .filter(RoundNote.admission_id.in_(ids))
        .group_by(RoundNote.admission_id).subquery())
    rows = (RoundNote.query
            .join(newest, and_(RoundNote.admission_id == newest.c.admission_id,
                               RoundNote.at == newest.c.at)).all())
    return {row.admission_id: row for row in rows}


def done_today(admission_ids, on_date=None):
    """The ids among these whose round has been written for today.

    A set, because the only thing anybody asks of it is membership. One query
    however many children are in the department.
    """
    from app.utils.live import day_bounds

    ids = [i for i in admission_ids if i]
    if not ids:
        return set()
    start, end = day_bounds(on_date or local_today())
    rows = (db.session.query(RoundNote.admission_id)
            .filter(RoundNote.admission_id.in_(ids),
                    RoundNote.at >= start, RoundNote.at <= end)
            .distinct().all())
    return {row[0] for row in rows}


def state(admission_ids, on_date=None):
    """``{admission_id: {"last", "today", "expected_discharge"}}``.

    Everything a department board prints about the round, gathered together so
    the template asks the database nothing. ``expected_discharge`` comes off
    the newest note — the most recent answer to "when do we think they go
    home" — rather than being stored on the stay, so that changing it leaves
    the earlier answer where it was written.
    """
    ids = [i for i in admission_ids if i]
    latest = latest_by_admission(ids)
    today = done_today(ids, on_date)
    out = {}
    for admission_id in ids:
        note = latest.get(admission_id)
        out[admission_id] = {
            "last": note,
            "today": admission_id in today,
            "expected_discharge": note.expected_discharge if note else None,
        }
    return out


def record(admission, trend, user=None, assessment=None, plan=None,
           expected_discharge=None, at=None):
    """Write one stop on the round, or refuse.

    Returns the note. Raises ``ValueError`` when the trend is not one of
    :data:`ROUND_TRENDS`, which is the whole of the blank-note refusal: a note
    with no trend says nothing, and storing it would clear "not seen today"
    off the board without anybody having gone near the child. Words without a
    trend are refused for the same reason — the board reads the trend, so a
    paragraph alone would be a round the screen cannot show.
    """
    if admission is None:
        raise ValueError("no admission")
    if trend not in ROUND_TRENDS:
        raise ValueError("no trend")
    note = RoundNote(
        admission_id=admission.id,
        patient_id=admission.patient_id,
        at=at or datetime.utcnow(),
        recorded_at=datetime.utcnow(),
        trend=trend,
        assessment=(assessment or "").strip() or None,
        plan=(plan or "").strip() or None,
        expected_discharge=expected_discharge,
        by_id=getattr(user, "id", None))
    db.session.add(note)
    return note


def for_patient(patient_id, limit=40):
    """This child's rounds, newest first — for their file.

    Across every stay they have had, which is the reason the note carries a
    patient of its own: a child readmitted in March should read as one story
    and not as two unrelated ones.
    """
    return (RoundNote.query
            .filter(RoundNote.patient_id == patient_id)
            .order_by(RoundNote.at.desc(), RoundNote.id.desc())
            .limit(limit).all())
