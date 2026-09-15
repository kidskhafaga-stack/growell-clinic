"""What the plan already knows, and what is still nobody's answer — ICD.15.

Read ``models/care_plan.py`` first for the split this file implements. In one
line: **the program assembles element (ب), derives (و), and asks a person for
(ج), (د), (هـ) and (ز).**

Three things are decided here.

**The plan points at the record; it never copies it.** ``stands_on`` returns
the *live* rows the plan is based on — the problem list, the risk assessments,
the readings, the results, the medicines, the allergies. Snapshotting them into
the plan would have made the plan a second copy of facts that keep moving, and
this codebase has argued the same thing about the device studies, the lab
curves and the discharge summary's three read elements: two copies of one
reading are two chances to disagree, and the one on the plan is the one nobody
updates.

**«محتاجة تحديث» is a comparison, not a flag.** Element (و) asks that the plan
be *"updated as appropriate based on the reassessment of the patient"*. Stored
as a column, that is something somebody has to remember to set — and the
morning nobody remembers is the morning it matters. Derived, it is right the
second a nurse writes a reading, because it is one moment against another.

**And it tells, it never blocks.** No visit, admission, prescription or
discharge waits on a plan. A child with no plan has none, the file says so,
and nothing in the program stops.
"""
from datetime import datetime

from app.extensions import db
from app.models.care_plan import (GOAL_PROGRESS, MET, NOT_MET, OPEN,
                                  CarePlan, CarePlanGoal)

#: The written elements, in the standard's own lettering, and what answers
#: each. ``None`` means the record answers it and nobody types it.
#:
#: This is the same shape as ``discharge_summary.ELEMENTS`` and for the same
#: reason: a screen can then show a doctor which boxes are theirs and which
#: are already answered, instead of presenting seven empty fields of which
#: three are a lie.
ELEMENTS = (
    ("أ", "disciplines", "mrp_signed_at"),
    ("ب", "assessments", None),
    ("ج", "family", "family_involved"),
    ("د", "guideline", "guideline"),
    ("هـ", "goals", "goals"),
    ("و", "updated", None),
    ("ز", "progress", "progress"),
)


def current(patient_id, admission_id=None):
    """This child's plan — the newest, or ``None``.

    **One live plan per child, not one per encounter.** ICD.15 asks for *an*
    individualized plan, and a child with four plans from four visits has no
    plan at all: the ward would be reading one while the clinic updated
    another. A stay writes into the same plan and stamps ``admission_id`` on
    it, which is what element (و) — *updated*, not *replaced* — describes.
    """
    query = CarePlan.query.filter(CarePlan.patient_id == patient_id)
    if admission_id is not None:
        query = query.filter(CarePlan.admission_id == admission_id)
    return query.order_by(CarePlan.written_at.desc(),
                          CarePlan.id.desc()).first()


def stands_on(patient_id):
    """Element (ب) — the assessments this plan is based on, **read live**.

    Returns a list of ``{"key", "rows", "at"}``: what the record holds, how
    many, and when the newest of them landed. Nothing here is stored on the
    plan; see the module docstring.
    """
    from app.models import Diagnosis, PatientProblem, Visit
    from app.models.observation import Observation
    from app.models.risk_assessment import RiskAssessment
    from app.models.visit import VisitInvestigation

    problems = (PatientProblem.query
                .filter(PatientProblem.patient_id == patient_id,
                        PatientProblem.status == "active")
                .order_by(PatientProblem.created_at.desc()).all())
    risks = (RiskAssessment.query
             .filter(RiskAssessment.patient_id == patient_id)
             .order_by(RiskAssessment.at.desc()).limit(20).all())
    readings = (Observation.query
                .filter(Observation.patient_id == patient_id)
                .order_by(Observation.taken_at.desc()).limit(5).all())
    # **A diagnosis hangs off a visit and carries no child of its own**, so it
    # is reached through one join rather than by walking the child's visits in
    # Python — a file with three years on it is a hundred encounters.
    dx = (Diagnosis.query.join(Visit, Diagnosis.visit_id == Visit.id)
          .filter(Visit.patient_id == patient_id)
          .order_by(Diagnosis.created_at.desc()).limit(20).all())
    # A result **does** carry one, so it is asked directly. The join would
    # have given the same rows and one more place for the filter to go
    # missing, which is exactly how another child's tests reached a file once
    # already.
    results = (VisitInvestigation.query
               .filter(VisitInvestigation.patient_id == patient_id)
               .order_by(VisitInvestigation.id.desc()).limit(20).all())

    return [
        {"key": "problems", "rows": problems,
         "at": _newest(problems, "created_at")},
        {"key": "diagnoses", "rows": dx, "at": _newest(dx, "created_at")},
        {"key": "risks", "rows": risks, "at": _newest(risks, "at")},
        {"key": "readings", "rows": readings,
         "at": _newest(readings, "taken_at")},
        {"key": "results", "rows": results, "at": None},
    ]


def _newest(rows, field):
    stamps = [getattr(r, field, None) for r in rows]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def last_assessment_at(patient_id):
    """When the record last learned something about this child.

    The other half of element (و). Only the sources that carry a real moment
    count — a row whose only stamp is ``id`` cannot say whether it came before
    or after the plan was written, and guessing would make the plan read as
    stale on the day it was signed.
    """
    stamps = [item["at"] for item in stands_on(patient_id) if item["at"]]
    return max(stamps) if stamps else None


def needs_update(plan):
    """Element (و) — whether the record has moved on since anybody touched it.

    ``False`` for no plan at all: a child with no plan has a gap, and calling
    that gap "out of date" would put two marks on one absence — the same rule
    the risk screen follows about an unassessed risk never also being overdue.
    """
    if plan is None:
        return False
    newest = last_assessment_at(plan.patient_id)
    if newest is None or plan.updated_at is None:
        return False
    return newest > plan.updated_at


def state(plan):
    """Where the plan stands, in one word.

    ``none`` no plan · ``empty`` a cover with no goals on it · ``unsigned``
    goals but no responsible physician against it · ``stale`` signed and the
    record has moved since · ``current`` signed and up to date.

    **``empty`` is its own word** because a plan with no goals is element (هـ)
    missing — the body of the thing — and a screen that called it "written"
    would be the false green tick this codebase keeps taking out.
    """
    if plan is None:
        return "none"
    if not plan.goals:
        return "empty"
    if not plan.is_signed:
        return "unsigned"
    return "stale" if needs_update(plan) else "current"


def missing(plan):
    """The written elements nobody has answered yet, by their letters.

    (ب) and (و) are never in it — the record answers one and time answers the
    other, and listing them would ask a doctor to type something no box
    accepts.
    """
    if plan is None:
        return [letter for letter, _key, column in ELEMENTS if column]
    out = []
    for letter, _key, column in ELEMENTS:
        if column is None:
            continue
        if column == "goals":
            filled = bool(plan.goals)
        elif column == "progress":
            # (ز) is answered when somebody has looked at any goal at all —
            # not when every goal is closed. A plan whose goals are all still
            # open is being monitored the moment one of them is reviewed.
            filled = any(g.progress != OPEN for g in plan.goals)
        elif column == "family_involved":
            filled = plan.family_involved is not None
        else:
            value = getattr(plan, column, None)
            filled = value is not None and (
                not isinstance(value, str) or bool(value.strip()))
        if not filled:
            out.append(letter)
    return out


def assemble(plan, patient_id=None):
    """All seven elements, each saying where its answer comes from.

    ``{"letter", "key", "written", "filled"}`` per element, in ICD.15's order.
    The same shape the discharge summary returns, so one screen pattern draws
    both.
    """
    who = patient_id if patient_id is not None else getattr(plan, "patient_id",
                                                            None)
    gaps = set(missing(plan))
    holds_assessments = any(item["rows"] for item in stands_on(who)) if who \
        else False
    out = []
    for letter, key, column in ELEMENTS:
        if key == "assessments":
            filled = holds_assessments
        elif key == "updated":
            filled = plan is not None and not needs_update(plan)
        else:
            filled = plan is not None and letter not in gaps
        out.append({"letter": letter, "key": key,
                    "written": column is not None, "filled": filled})
    return out


# ------------------------------------------------------- writing it -------
def start(patient, user=None, admission=None):
    """Open a plan for a child who has none. Caller commits.

    Returns the existing plan when there already is one — **pressing «ابدأ
    خطة» twice must not give a child two plans**, which is the failure the
    whole "one live plan" rule above exists to prevent.
    """
    if patient is None:
        raise ValueError("no patient")
    found = current(patient.id)
    if found is not None:
        return found
    plan = CarePlan(patient_id=patient.id,
                    admission_id=getattr(admission, "id", None),
                    written_by=getattr(user, "id", None))
    db.session.add(plan)
    return plan


def add_goal(plan, need, intervention=None, outcome=None, by_when=None):
    """One identified need and what is being done about it. Caller commits.

    **The need is required and nothing else is.** *"identified needs,
    interventions, and desired outcomes with timeframes"* — a goal with no
    need named is not a goal, while a need with no intervention yet is a real
    and common thing to write down at the moment it is identified, and
    refusing it would send it to the margin of a paper chart.
    """
    if plan is None:
        raise ValueError("no plan")
    said = (need or "").strip()
    if not said:
        raise ValueError("no need")
    goal = CarePlanGoal(plan_id=plan.id, need=said[:255],
                        intervention=(intervention or "").strip() or None,
                        outcome=(outcome or "").strip() or None,
                        by_when=by_when)
    db.session.add(goal)
    touch(plan)
    return goal


def record_progress(goal, progress, user=None, note=None, at=None):
    """Element (ز) — how this goal is going. Caller commits.

    Raises ``ValueError`` for a progress that is not one of the four, because
    a word the screen cannot draw is a monitoring entry nobody will ever read.
    """
    if goal is None:
        raise ValueError("no goal")
    if progress not in GOAL_PROGRESS:
        raise ValueError("unknown progress")
    goal.progress = progress
    goal.progress_note = (note or "").strip() or None
    goal.progress_at = at or datetime.utcnow()
    goal.progress_by = getattr(user, "id", None)
    touch(goal.plan)
    return goal


def sign(plan, user=None, at=None):
    """Element (أ) — the most responsible physician puts their name to it.

    Refused for a plan with no goals: a signature under an empty plan is a
    claim that somebody supervised the making of nothing, and it is the one
    state that would read as complete while element (هـ) is missing.
    """
    if plan is None or not plan.goals:
        return None
    plan.mrp_signed_by = getattr(user, "id", None)
    plan.mrp_signed_at = at or datetime.utcnow()
    return plan


def describe(plan, family_involved=None, family_note=None, guideline=None,
             preferences=None):
    """Elements (ج) and (د). Caller commits.

    Every argument is optional and ``None`` means *left alone*, not *cleared*
    — the screen saves one part of the cover at a time, and a save that blanked
    the others would lose the family's answer every time somebody corrected
    the guideline.
    """
    if plan is None:
        return None
    if family_involved is not None:
        plan.family_involved = family_involved
    if family_note is not None:
        plan.family_note = family_note.strip() or None
    if guideline is not None:
        plan.guideline = guideline.strip()[:200] or None
    if preferences is not None:
        plan.preferences = preferences.strip() or None
    touch(plan)
    return plan


def touch(plan, at=None):
    """Mark the plan as looked at now — which is what element (و) reads.

    Set explicitly rather than left to ``onupdate``, because a change to a
    *goal* is a change to the plan and SQLAlchemy's ``onupdate`` fires only on
    the row that changed. Without this, adding a goal would leave the plan
    reading as stale against an assessment it had just been updated for.
    """
    if plan is not None:
        plan.updated_at = at or datetime.utcnow()
    return plan


def overdue_everywhere(limit=100):
    """Every open goal whose timeframe has passed, oldest first.

    For a screen that asks the question across the clinic rather than one
    child at a time — *"desired outcomes **with timeframes**"* is only worth
    recording if something ever looks at them.
    """
    from app.utils.clock import local_today

    return (CarePlanGoal.query
            .filter(CarePlanGoal.by_when.isnot(None),
                    CarePlanGoal.by_when < local_today(),
                    CarePlanGoal.progress.notin_((MET, NOT_MET)))
            .order_by(CarePlanGoal.by_when, CarePlanGoal.id)
            .limit(limit).all())
