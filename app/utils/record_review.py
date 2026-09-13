"""Sampling records and reading them back — GAHAR IMT.09.

**The one rule this module is built on: it invents no completeness standard.**

Every check below is a fact the program *already* derives for one of its own
screens, against a standard already implemented in this repository — a stay
with no discharge summary is ACT.15's finding and the ward screen has been
showing it since the day that work landed; an operation whose sign-out was
never signed is what the theatre list has always drawn as a gap. The review
does not decide anything new. It **samples**, and it **writes down what those
existing answers said on the day**.

That matters twice over:

* A program that invented its own definition of a complete record would be
  auditing the clinic against a rule nobody agreed to — the same line that
  keeps invented vaccine thresholds and invented surgery times out of the
  code.
* And the standard itself puts people in the room for the judging: (d) asks
  for *"involvement of representatives of all disciplines who make entries"*.
  So findings here are **observations**, never verdicts. The committee reads
  them; the program counts them.

The sample is **reproducible after the fact** — every file drawn is written
down as a row — because a review whose sample cannot be shown is not evidence
of anything.
"""
import random
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.record_review import (RecordReview, RecordReviewFinding,
                                      RecordReviewItem, RecordReviewMember)

#: What (a) asks for: *"approximately 5% of patient's medical records"*.
SAMPLE_PERCENT = 5

#: (f) — *"Review occurs **at least quarterly**"*. The floor the standard
#: states, and the program states no other: a clinic that reviews monthly is
#: doing more than is asked, and nothing here tells it to stop.
QUARTER_DAYS = 92


def _period(start, end):
    """Both ends, with today's quarter as the default nobody has to type."""
    from app.utils.clock import local_today

    end = end or local_today()
    return (start or (end - timedelta(days=QUARTER_DAYS)), end)


# --------------------------------------------------- what is looked at ----
def entries_for(patient_id, start, end):
    """Every entry in one file over a period — visits, stays, operations.

    An *entry* is a thing somebody wrote in the record. It is the unit (e)
    talks about (*"completeness and legibility of **entries**"*), and it is
    the unit the checks below run over.
    """
    from app.models.admission import Admission
    from app.models.visit import Visit
    from app.utils.facility import module_enabled

    out = []
    out += [("visit", v) for v in Visit.query.filter(
        Visit.patient_id == patient_id,
        Visit.visit_date >= start, Visit.visit_date <= end).all()]
    if module_enabled("beds"):
        out += [("admission", a) for a in Admission.query.filter(
            Admission.patient_id == patient_id,
            db.func.date(Admission.admitted_at) >= start,
            db.func.date(Admission.admitted_at) <= end).all()]
    if module_enabled("theatres"):
        from app.models.theatre import Operation

        out += [("operation", o) for o in Operation.query.filter(
            Operation.patient_id == patient_id,
            Operation.on_date >= start, Operation.on_date <= end).all()]
    return out


def population(start, end):
    """The files this review may draw from: the ones written in, in the period.

    **An interpretation, and it is written here rather than hidden.** The
    standard says *"5% of patient's medical records"* and does not say of
    what pool. Taken as every file the clinic has ever opened, a paediatric
    practice of twenty thousand files would owe a thousand reviews a quarter,
    most of them of records nobody has touched in years — and reviewing the
    same untouched file every quarter tells nobody anything.

    So the pool is **the files with entries in the period**, which is what (f)
    implies by making the review periodic at all. The number is stored on the
    review and shown on the screen beside the sample, so the share a surveyor
    is being told about is one they can check rather than take.
    """
    from app.models.admission import Admission
    from app.models.visit import Visit
    from app.utils.facility import module_enabled

    ids = set()
    ids.update(pid for (pid,) in db.session.query(Visit.patient_id).filter(
        Visit.visit_date >= start, Visit.visit_date <= end).distinct())
    if module_enabled("beds"):
        ids.update(pid for (pid,) in db.session.query(
            Admission.patient_id).filter(
                db.func.date(Admission.admitted_at) >= start,
                db.func.date(Admission.admitted_at) <= end).distinct())
    if module_enabled("theatres"):
        from app.models.theatre import Operation

        ids.update(pid for (pid,) in db.session.query(
            Operation.patient_id).filter(
                Operation.on_date >= start, Operation.on_date <= end).distinct())
    return sorted(ids)


# ------------------------------------------------------- the checks -------
def _stay_summary(kind, entry):
    """ACT.15 evidence 2 — a stay that ended with no summary written."""
    from app.utils import discharge_summary as summary

    if kind != "admission" or entry.is_open:
        return None
    return "stay_no_summary" if summary.state(entry) == "none" else None


def _stay_summary_short(kind, entry):
    """ACT.15 evidence 2 — written, with named elements still blank."""
    from app.utils import discharge_summary as summary

    if kind != "admission" or entry.is_open:
        return None
    return "summary_short" if summary.state(entry) == "short" else None


def _operation_signed_out(kind, entry):
    """GSR.16 / SAS.06 — a case recorded as done whose sign-out was never
    signed. The theatre screen has been saying this out loud all along."""
    from app.utils import theatres as theatre

    if kind != "operation" or entry.status != "done":
        return None
    return None if theatre.safety(entry)["closed"] else "operation_no_signout"


def _operation_checklist_short(kind, entry):
    """A stop signed with items unticked. ``safety()['missed']`` is the same
    answer the case screen draws, and it is not a completed checklist."""
    from app.utils import theatres as theatre

    if kind != "operation" or entry.status not in ("done", "in_theatre"):
        return None
    return "checklist_short" if theatre.safety(entry)["missed"] else None


def _operation_consent(kind, entry):
    """PCC.08 — no signed, standing consent linked to a case that went ahead.

    ``consent_state`` is the program's existing answer, with its five named
    states, and anything but ``linked`` is the observation.
    """
    from app.utils import theatres as theatre

    if kind != "operation" or entry.status != "done":
        return None
    return None if theatre.consent_state(entry) == "linked" else "operation_no_consent"


def _visit_diagnosis(kind, entry):
    """ICD.06 (j) — an initial assessment includes a provisional diagnosis.

    **An observation, and a soft one.** A vaccination-only visit legitimately
    carries none, and the program does not pretend to know which is which —
    that is what the review committee is for. It reports the fact.
    """
    if kind != "visit":
        return None
    return None if (entry.diagnoses or []) else "visit_no_diagnosis"


#: Every check, with the standard it comes from quoted in its own docstring.
#: ``standard`` is carried here so a finding on a screen can name where the
#: expectation came from — never this program.
CHECKS = (
    ("stay_no_summary", "ACT.15", _stay_summary),
    ("summary_short", "ACT.15", _stay_summary_short),
    ("operation_no_signout", "GSR.16", _operation_signed_out),
    ("checklist_short", "SAS.06", _operation_checklist_short),
    ("operation_no_consent", "PCC.08", _operation_consent),
    ("visit_no_diagnosis", "ICD.06", _visit_diagnosis),
)

#: ``{key: standard}``, for the screens.
STANDARD_OF = {key: standard for key, standard, _fn in CHECKS}


def look(kind, entry):
    """Every check that has something to say about one entry, in order."""
    return [key for key, _standard, check in CHECKS if check(kind, entry) == key]


def _entry_date(kind, entry):
    if kind == "visit":
        return entry.visit_date
    if kind == "operation":
        return entry.on_date
    at = getattr(entry, "admitted_at", None)
    return at.date() if at else None


# ------------------------------------------------------- the sample -------
def draw(start, end, percent=SAMPLE_PERCENT, rng=None, services=True):
    """The files to review, as a list of patient ids.

    (a) asks for *"random sampling and selecting approximately 5%"*, and (b)
    and (c) ask that the sample be **representative of all services and all
    disciplines/staff**. A plain 5% can miss a service the clinic ran twice
    all quarter, and a sample that omits a service is not representative of
    all services — so the draw is stratified:

    1. one file for each kind of entry the period actually has — a visit, a
       stay, an operation — and one for each doctor who made entries, so no
       service and no member of staff is invisible to the review;
    2. then filled at random from the rest, up to the 5%.

    ``rng`` is injectable so a test can pin the draw. Nothing else passes it:
    a review whose sample is not random is not a random sample.
    """
    pool = population(start, end)
    if not pool:
        return []
    rng = rng or random.Random()
    want = max(1, round(len(pool) * percent / 100.0))

    picked = []
    if services:
        for patient_id in _representatives(pool, start, end, rng):
            if patient_id not in picked:
                picked.append(patient_id)
    rest = [p for p in pool if p not in picked]
    rng.shuffle(rest)
    picked += rest[:max(0, want - len(picked))]
    # Stratification can overshoot the 5% on a small period — five doctors in
    # a pool of forty is twelve and a half per cent. **It overshoots rather
    # than dropping somebody**: "approximately 5%" is a floor to aim at, and
    # (b) and (c) are not satisfied by a sample that hit the number by
    # leaving a discipline out.
    return picked


def _representatives(pool, start, end, rng):
    """One file per kind of entry and per person making entries.

    Walks the pool in a shuffled order so *which* file represents a service is
    itself random — otherwise the same child would stand for the ward in every
    review the clinic ever runs.
    """
    order = list(pool)
    rng.shuffle(order)
    seen_kinds, seen_staff, picked = set(), set(), []
    for patient_id in order:
        for kind, entry in entries_for(patient_id, start, end):
            who = (getattr(entry, "doctor_id", None)
                   or getattr(entry, "surgeon_id", None))
            new_kind = kind not in seen_kinds
            new_staff = who is not None and who not in seen_staff
            if new_kind or new_staff:
                seen_kinds.add(kind)
                if who is not None:
                    seen_staff.add(who)
                if patient_id not in picked:
                    picked.append(patient_id)
    return picked


# ------------------------------------------------------- running it -------
def run(start=None, end=None, user=None, percent=SAMPLE_PERCENT, rng=None):
    """Draw a sample, read it, and write down what was found.

    Returns the ``RecordReview``. Every sampled file becomes a row **whether
    or not anything was found**, so a clean quarter is a quarter that was
    reviewed and not one that looks unreviewed.
    """
    start, end = _period(start, end)
    pool = population(start, end)
    review = RecordReview(period_from=start, period_to=end,
                          population=len(pool), sampled=0,
                          run_by=getattr(user, "id", None))
    db.session.add(review)
    db.session.flush()

    for patient_id in draw(start, end, percent=percent, rng=rng):
        entries = entries_for(patient_id, start, end)
        item = RecordReviewItem(review_id=review.id, patient_id=patient_id,
                                entries=len(entries))
        db.session.add(item)
        db.session.flush()
        for kind, entry in entries:
            for key in look(kind, entry):
                db.session.add(RecordReviewFinding(
                    item_id=item.id, check=key, entry_kind=kind,
                    entry_id=entry.id, entry_on=_entry_date(kind, entry)))
        review.sampled += 1
    return review


def add_member(review, user, discipline=None):
    """Record somebody as having taken part — (d). Returns the row, or ``None``.

    **Once per person.** A second press is the same person, and a review that
    counted them twice would read as two disciplines where there is one.
    """
    if review is None or user is None:
        return None
    if any(m.user_id == user.id for m in review.members):
        return None
    # **Through the relationship, not the foreign key** — the same trap the
    # discharge summary fell into one standard earlier. The line above has
    # just read ``review.members`` and SQLAlchemy has cached that answer on
    # the instance; adding a row by ``review_id`` alone leaves the cached list
    # empty, so the *next* call reads it as empty too and the duplicate guard
    # never fires. Assigning the relationship appends to the collection there
    # and then.
    row = RecordReviewMember(review=review, user_id=user.id,
                             discipline=(discipline or "").strip()[:80] or None)
    db.session.add(row)
    return row


def report_to_leaders(review, user=None, at=None):
    """Evidence 3. Stamped once — when they were told is the evidence."""
    if review is None or review.reported_at:
        return None
    review.reported_at = at or datetime.utcnow()
    review.reported_by = getattr(user, "id", None)
    return review


def record_action(review, text, user=None, at=None):
    """Evidence 4 — *"Corrective interventions are taken when needed."*

    Refused empty, which is the whole point: a blank action box and "we looked
    and nothing needed doing" are different answers, and one of them is a
    decision somebody made. The clinic writes the second one down.
    """
    if review is None:
        return None
    text = (text or "").strip()
    if not text:
        return None
    review.action = text
    review.action_at = at or datetime.utcnow()
    review.action_by = getattr(user, "id", None)
    return review


# ------------------------------------------------------- reading it ------
def summarise(review):
    """``{check: count}`` over a review's findings, commonest first.

    What evidence 3 hands to the leaders: not six hundred rows, but *which
    gaps, how many*.
    """
    if review is None:
        return []
    counts = {}
    for item in review.items:
        for finding in item.findings:
            counts[finding.check] = counts.get(finding.check, 0) + 1
    return sorted(({"check": key, "standard": STANDARD_OF.get(key, ""),
                    "count": n} for key, n in counts.items()),
                  key=lambda row: (-row["count"], row["check"]))


def clean_files(review):
    """How many sampled files had nothing found in them."""
    return sum(1 for item in review.items if item.clean) if review else 0


def rounds(limit=None):
    """Every review, most recent first."""
    query = RecordReview.query.order_by(RecordReview.period_to.desc(),
                                        RecordReview.id.desc())
    return query.limit(limit).all() if limit else query.all()


def last_round():
    return rounds(limit=1)[0] if rounds(limit=1) else None


def next_due():
    """The day the next review is owed by, or ``None`` if none has ever run.

    (f) says *"at least quarterly"*, so this is the last review's period end
    plus a quarter — **the standard's own floor and nothing stricter**. A
    clinic that reviews monthly is doing more than is asked and this never
    tells it otherwise.

    ``None`` for a clinic that has never run one: that is not "overdue since
    the beginning of time", it is a clinic that has not started, and the
    screen says so in those words instead.
    """
    last = last_round()
    if last is None:
        return None
    return last.period_to + timedelta(days=QUARTER_DAYS)


def overdue(today=None):
    """Whether the next review is past due. ``False`` where none has run."""
    from app.utils.clock import local_today

    due = next_due()
    return bool(due and (today or local_today()) > due)
