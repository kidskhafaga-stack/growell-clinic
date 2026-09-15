"""«تعالى بعد أسبوعين» — وهل جه؟

GAHAR `ICD.05` evidence 5: *"The plans of care and **follow-up instructions**
are recorded in the patient's medical records."* The instruction was nowhere in
this program. `Visit.plan` is what the doctor decided; it is not what the family
was told on the way out, and the two are read by different people months apart.

**And the instruction alone is half the fact.** A file that says «ارجع بعد
أسبوعين» and nothing else cannot answer the question that makes the instruction
worth recording — *did they come back?* The child booked three follow-ups and
attended none is the most important patient of that month, and every row needed
to see that was already in the database, in two tables nothing joined.

So the state is **derived, never stored**:

* it is right the moment reception books an appointment, without anybody
  telling the visit anything;
* it cannot drift, because there is no second copy of "they came" to go stale;
* and a clinic upgrading into this version gets `none` for every visit ever
  recorded — which is true, because nobody was ever asked.

**It tells, it never blocks.** Nothing here refuses a visit, a booking or a
discharge, and no message is sent from this module: `utils/no_show` and
`utils/recall` own what the clinic says to a family, and both are pressed by a
person. This only answers the question.
"""
from app.extensions import db

#: Where a follow-up stands.
#:
#: ``none``     nobody was told to come back — the default, and what every
#:              visit recorded before this existed truthfully reads as
#: ``told``     an instruction was given and the date has not come yet
#: ``booked``   an appointment is on the books for it
#: ``came``     they came back
#: ``missed``   they were booked and did not come, and have not rebooked
#: ``overdue``  the date has passed with nothing booked and nobody seen
NONE, TOLD, BOOKED, CAME, MISSED, OVERDUE = (
    "none", "told", "booked", "came", "missed", "overdue")
STATES = (NONE, TOLD, BOOKED, CAME, MISSED, OVERDUE)

#: The two that are somebody's errand. `missed` first: a child booked three
#: times who attended none is a different errand from one nobody ever booked.
OUTSTANDING = (MISSED, OVERDUE)


def told(visit):
    """Whether this visit sent the family away with anything to come back for.

    Either column counts. A doctor who writes «ارجع فوراً لو سخن» and sets no
    date has given a follow-up instruction — the safety net is the instruction
    — and reading only the date would record that visit as having said nothing.
    """
    if visit is None:
        return False
    return (visit.followup_due is not None
            or bool((visit.followup_instructions or "").strip()))


def belongs_to(appointment, visit):
    """Whether this booking is an answer to *that* consultation.

    **One definition, used by both readers.** The rule was written twice —
    once as a SQL filter in :func:`since` and once as a Python test inside
    :func:`by_visit` — and a sweep showed the second copy could be deleted
    with the suite still green, because every test went through the first.
    Two spellings of one rule are two chances to disagree, and the file screen
    reads the copy nothing was covering.
    """
    if appointment is None or visit is None:
        return False
    if visit.patient_id is None or visit.visit_date is None:
        return False
    return (appointment.patient_id == visit.patient_id
            and appointment.appt_date is not None
            and appointment.appt_date >= visit.visit_date)


def since(visit):
    """This child's appointments from the visit's own day onwards.

    From the visit date and not from *now*: the question is what was arranged
    **as a result of** this consultation, and an appointment booked the same
    afternoon is the commonest answer to it.
    """
    from app.models import Appointment

    if visit is None or not visit.patient_id or visit.visit_date is None:
        return []
    rows = (Appointment.query
            .filter(Appointment.patient_id == visit.patient_id,
                    Appointment.appt_date >= visit.visit_date)
            .order_by(Appointment.appt_date, Appointment.id).all())
    # Narrowed in SQL for the page's sake, then decided by the one rule — so
    # the filter above is an **optimisation and never the definition**.
    #
    # A mutation sweep survives on that line by design: deleting it changes no
    # answer, only how many rows come back, because `belongs_to` decides
    # afterwards. That is the point of writing it this way, and it is recorded
    # here rather than covered by a test asserting a row count — a test of how
    # many rows a query fetched would fail on a schema change that kept every
    # answer right.
    return [a for a in rows if belongs_to(a, visit)]


def state(visit, on_date=None, appointments=None):
    """Where this visit's follow-up stands, in one word.

    ``appointments`` is the list :func:`since` would return, passed in by a
    screen that has already read it for a page of visits — one query for a
    file instead of one per row.

    **«جه» beats everything.** A child who attended is not also missed, whatever
    else was booked and broken along the way: the point of the instruction was
    that they come back, and they did.
    """
    from app.utils.clock import local_today

    if not told(visit):
        return NONE
    rows = since(visit) if appointments is None else appointments
    if any(a.status == "completed" for a in rows):
        return CAME
    # Anything still on the books outranks a missed one behind it — the family
    # that missed Tuesday and rebooked for Thursday is booked, not missed,
    # which is the same rule `no_show` follows before it sends anything.
    if any(a.status in ("scheduled", "waiting", "in_progress") for a in rows):
        return BOOKED
    if any(a.status == "no_show" for a in rows):
        return MISSED
    if visit.followup_due is not None and visit.followup_due < (
            on_date or local_today()):
        return OVERDUE
    return TOLD


def missed_count(visit, appointments=None):
    """How many bookings this child did not attend after that visit.

    «اتحجزله ٣ مواعيد وما جاش في ولا واحد» — the number is the errand. One
    missed appointment is a family stuck in traffic; three is a child nobody
    has seen since a doctor said they needed to be seen.
    """
    rows = since(visit) if appointments is None else appointments
    return sum(1 for a in rows if a.status == "no_show")


def by_visit(visits):
    """``{visit_id: {"state", "missed"}}`` for a page of visits, in one query.

    A patient file draws every visit it has, so asking per row is one query
    per consultation on a child with three years of them. There is a
    size-comparison test that fails if this becomes that.
    """
    from app.models import Appointment
    from app.utils.clock import local_today

    rows = [v for v in (visits or []) if v is not None]
    if not rows:
        return {}
    patients = {v.patient_id for v in rows if v.patient_id}
    earliest = min(v.visit_date for v in rows if v.visit_date is not None
                   ) if any(v.visit_date for v in rows) else None
    appts = []
    if patients and earliest is not None:
        appts = (Appointment.query
                 .filter(Appointment.patient_id.in_(patients),
                         Appointment.appt_date >= earliest).all())
    today = local_today()
    out = {}
    for visit in rows:
        mine = [a for a in appts if belongs_to(a, visit)]
        out[visit.id] = {
            "state": state(visit, on_date=today, appointments=mine),
            "missed": missed_count(visit, appointments=mine),
        }
    return out


def outstanding(limit=200):
    """The children a doctor asked back who have not been seen, oldest first.

    **Oldest first**, like the bench's rack and the audit queue, and for the
    same reason: a list that puts this morning's on top is a list where last
    month's is still there at the end of the year.

    Narrowed in SQL to the visits that asked for anything at all, then the
    state is worked out by reading — «جه ولا لأ» is a question about another
    table's rows and there is no join that answers it for a page without
    writing the rule a second time in SQL.
    """
    from app.models import Visit

    candidates = (Visit.query
                  .filter(db.or_(Visit.followup_due.isnot(None),
                                 Visit.followup_instructions.isnot(None)))
                  .order_by(Visit.visit_date, Visit.id)
                  .limit(limit * 4).all())
    states = by_visit(candidates)
    out = [v for v in candidates
           if states.get(v.id, {}).get("state") in OUTSTANDING]
    return out[:limit]


def record(visit, due=None, instructions=None):
    """Write what the family was told. Caller commits.

    Both parts optional and ``None`` means *left alone*, not *cleared*: the
    consultation screen saves the whole visit on every keystroke-free submit,
    and a save that blanked the safety net because the date field was not on
    that form would delete the one sentence that brings a child back early.

    An empty string **does** clear — that is a person emptying the box, which
    is a different act from a form that did not carry it.
    """
    if visit is None:
        return None
    if due is not None:
        visit.followup_due = due or None
    if instructions is not None:
        visit.followup_instructions = instructions.strip() or None
    return visit
