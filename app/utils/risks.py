"""What the ward has looked for, what it found, and what is now overdue.

The reading half of ``models/risk_assessment.py`` — ICD.10 falls, ICD.11
pressure ulcers, ICD.12 venous thromboembolism. Read that file first for why
there is one table and why this program computes no score.

Three things are decided here, and each of them is a line the standards draw
between *the hospital's policy* and *the record*:

**Which risks this place looks for.** All three are on, because all three are
required of any hospital GAHAR surveys — but a paediatric ward whose policy
does not cover VTE prophylaxis turns that one off, and then it is absent
rather than permanently unanswered. A switch is a decision somebody made; a
row that says «لم يُقيَّم» for eleven months is a decision nobody made.

**When a reassessment is late.** Every one of the three asks for a
*"timeframe to complete"* and a *"frequency of reassessment"* — **and asks the
hospital for them**, not the program. So the interval starts empty, and while
it is empty nothing is ever late. That is also what keeps upgrade morning
quiet in a ward that has been running for two years: the screen gains the
record, and gains no red.

**What «done» means.** Not "a row exists". All three standards end on the same
element — *"General measures and **tailored care plans** are recorded in the
patient's medical record"* — so a child found at risk with no plan written is
its own state, and it is the one this screen is for. An assessment that
concluded *not* at risk needs no plan and is finished.

---

**It tells, it never blocks.** Nothing here stands between a doctor and an
admission, a move, or a discharge. A stay with no assessment at all is
admitted, shown, and says so.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.risk_assessment import RISK_KINDS, RiskAssessment

#: Settings live under one prefix so they are one query — see
#: ``Setting.GROUPED_PREFIXES``, which this name is registered in.
PREFIX = "risk"

#: What a stay's record shows for one risk.
#:
#: ``none``    nobody has assessed it
#: ``unsaid``  assessed, and whether the child is at risk was left blank
#: ``clear``   assessed, not at risk — finished, and needs no plan
#: ``bare``    **at risk, and no tailored plan is written** — the state all
#:             three standards' last element is about
#: ``planned`` at risk, and the plan is there
NONE, UNSAID, CLEAR, BARE, PLANNED = ("none", "unsaid", "clear", "bare",
                                      "planned")
STATES = (NONE, UNSAID, CLEAR, BARE, PLANNED)

#: Where a reassessment stands. ``quiet`` is a clinic that has not stated a
#: frequency, and it is the default — see the module docstring.
QUIET, OK, DUE = ("quiet", "ok", "due")


def _settings():
    from app.models import Setting

    try:
        return Setting.group(PREFIX)
    except Exception:                   # noqa: BLE001 — table not ready yet
        return {}


def enabled_kinds(rows=None):
    """The risks this place looks for, in the standards' order.

    Reads ``off`` and nothing else as off: a key that was never written, an
    empty one, or one holding anything unexpected all mean on, because the
    failure of a misread setting should be a ward that assesses a risk it did
    not have to and not one that silently stops looking.
    """
    rows = _settings() if rows is None else rows
    return tuple(k for k in RISK_KINDS
                 if (rows.get(f"{PREFIX}:kind:{k}") or "").strip() != "off")


def is_enabled(kind, rows=None):
    return kind in enabled_kinds(rows)


def interval_hours(kind, rows=None):
    """How often this hospital's policy says to reassess, or ``None``.

    ``None`` for anything that is not a positive whole number of hours,
    including the empty default. Zero is not an interval — it would make every
    assessment overdue the moment it was written.
    """
    rows = _settings() if rows is None else rows
    try:
        hours = int((rows.get(f"{PREFIX}:hours:{kind}") or "").strip())
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def tool_name(kind, rows=None):
    """The tool this hospital's policy names, remembered so nobody retypes it.

    A default for the form and never a value the program stores by itself: what
    lands in the record is what the person doing the assessment left in the
    box.
    """
    rows = _settings() if rows is None else rows
    return (rows.get(f"{PREFIX}:tool:{kind}") or "").strip()


def state(assessment):
    """Where one risk stands, in one word. ``none`` for no assessment at all."""
    if assessment is None:
        return NONE
    if assessment.at_risk is None:
        return UNSAID
    if not assessment.at_risk:
        return CLEAR
    return PLANNED if assessment.has_plan else BARE


def due(assessment, kind, now=None, rows=None):
    """Whether this risk is waiting to be looked at again.

    ``quiet`` whenever the hospital has not stated a frequency **and** for a
    risk nobody has assessed yet — an absent assessment is already the loudest
    thing on the screen, and calling it overdue as well would put two marks on
    one gap.
    """
    hours = interval_hours(kind, rows)
    if hours is None or assessment is None:
        return QUIET
    at = assessment.at or (now or datetime.utcnow())
    return DUE if (now or datetime.utcnow()) - at >= timedelta(hours=hours) else OK


def latest(admission_id):
    """``{kind: newest RiskAssessment}`` for one stay.

    **A stay reads its own assessments and not the child's.** That is the whole
    point of asking again on admission — ICD.10 (أ) / ICD.11 (أ) / ICD.12 (أ) —
    and a fall assessment from a different stay eight months ago showing here
    would be a green tick for work nobody on this stay has done.

    It takes a stay and not a patient **because nothing reads it by patient**.
    A second parameter for a caller that does not exist is a branch no test
    covers, and a mutation sweep found exactly that: its filter could be
    deleted with the suite still green.
    """
    query = RiskAssessment.query.filter(
        RiskAssessment.admission_id == admission_id)
    out = {}
    for row in query.order_by(RiskAssessment.at.asc(),
                              RiskAssessment.id.asc()).all():
        out[row.kind] = row          # ascending, so the last write wins
    return out


def panel(admission, now=None):
    """Everything the stay screen prints about risk, in one list.

    One row per enabled kind, in the standards' order, present whether or not
    anybody has assessed it — an absence has no row of its own to find, so the
    list is built from the kinds and the assessments are hung on it.
    """
    if admission is None:
        return []
    rows = _settings()
    found = latest(admission.id)
    when = now or datetime.utcnow()
    out = []
    for kind in enabled_kinds(rows):
        row = found.get(kind)
        out.append({
            "kind": kind,
            "assessment": row,
            "state": state(row),
            "due": due(row, kind, now=when, rows=rows),
            "tool": tool_name(kind, rows),
            "hours": interval_hours(kind, rows),
        })
    return out


def unassessed(panel_rows):
    """The enabled risks this stay has no assessment for at all.

    Takes the panel rather than the stay, so a screen showing both the list
    and its headline counts them off **one** read of the table — and so the
    two numbers can never disagree with the rows printed underneath them.
    """
    return tuple(item["kind"] for item in panel_rows
                 if item["state"] == NONE)


def without_plan(panel_rows):
    """The risks this child was found at risk of and has no tailored plan for.

    The sentence a surveyor's sample is looking for, and the one thing on this
    screen that is a finding rather than a gap: somebody looked, somebody said
    yes, and the element all three standards end on is blank.
    """
    return tuple(item["kind"] for item in panel_rows
                 if item["state"] == BARE)


def record(patient, kind, user=None, admission=None, tool=None, level=None,
           at_risk=None, general_measures=None, plan=None, family_told=None,
           at=None):
    """Write one assessment, or refuse. Caller commits.

    Raises ``ValueError`` for a risk that is not one of the three, for no
    child, and for a kind this hospital has switched off — writing into a
    switched-off risk would put a row in a medical record that no screen in
    the program ever shows again.

    **A blank assessment is not refused**, unlike the round note, and the
    difference is what the two rows mean. A round with no trend clears «nobody
    has seen this child today» off a board without anybody having gone near
    them. An assessment with nothing but a stamp says *somebody looked and did
    not commit to an answer* — which ``unsaid`` is the word for, which the
    screen shows, and which is a truer record of a half-done assessment than
    refusing to keep it.
    """
    if patient is None:
        raise ValueError("no patient")
    # **Two guards, and they are not the same rule.** "Not one of the three"
    # is a programming error; "this hospital does not look for it" is a policy.
    # They refuse alike, so each said the same word — and a mutation sweep
    # showed the first could be deleted outright with the suite still green,
    # because an unknown kind is never in the enabled set either. A guard from
    # one side is half a rule: both stay, and each says which one it is.
    if kind not in RISK_KINDS:
        raise ValueError("unknown risk")
    if not is_enabled(kind):
        raise ValueError("risk switched off")
    row = RiskAssessment(
        patient_id=patient.id,
        admission_id=getattr(admission, "id", None),
        kind=kind,
        at=at or datetime.utcnow(),
        recorded_at=datetime.utcnow(),
        by_id=getattr(user, "id", None),
        tool=(tool or "").strip()[:120] or None,
        level=(level or "").strip()[:60] or None,
        at_risk=at_risk,
        general_measures=(general_measures or "").strip() or None,
        plan=(plan or "").strip() or None,
        family_told=family_told)
    db.session.add(row)
    return row


def save_policy(kind, on=True, hours=None, tool=None):
    """Write one risk's policy. Caller commits.

    ``hours`` of ``None`` or anything unreadable clears the frequency back to
    empty, which is the quiet default and not an error — a hospital taking a
    timeframe back out is stating that its policy no longer names one.
    """
    from app.models import Setting

    if kind not in RISK_KINDS:
        raise ValueError("unknown risk")
    Setting.set(f"{PREFIX}:kind:{kind}", "on" if on else "off")
    try:
        whole = int(str(hours).strip())
    except (TypeError, ValueError):
        whole = 0
    # Cleared rather than stored as ``0``. `interval_hours` refuses a zero on
    # the way out too, which is why a sweep found this line deletable — but a
    # settings row holding "0" is a policy that reads as "reassess every zero
    # hours" to anybody looking at the table, and the two guards are testing
    # different things: what is written, and what is read back.
    Setting.set(f"{PREFIX}:hours:{kind}", str(whole) if whole > 0 else "")
    Setting.set(f"{PREFIX}:tool:{kind}", (tool or "").strip()[:120])
    return True
