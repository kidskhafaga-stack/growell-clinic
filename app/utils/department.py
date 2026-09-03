"""What a department looks like right now — one question, four tempos.

Emergency and the incubators are the first two departments to get a screen of
their own, and they are **not** two systems. ``HOSPITAL_PLAN.md`` ٤-ب settled
that: the four departments are four *observation densities* over one base —
the place (``models/place.py``), the stay (``models/admission.py``) and the
repeated readings (``models/observation.py``). All three were built before
this file, and this adds no table.

What a department screen answers that the bed board does not: **who is the
one to look at first.** The bed board draws the place and says who is in it.
A department is read the other way round — worst first, and "worst" is a
sentence with four clauses:

1. a child nobody has measured at all since they arrived;
2. a child whose rounds are overdue;
3. a child whose last reading the program reads as urgent;
4. everybody else, longest wait first.

None of those judgements is made here. The flag comes from ``red_flags``, the
lateness from ``observations``, the occupancy from ``beds`` — this file joins
them and sorts. A department that judged a temperature by its own rule would
be a second copy of the clinic's thresholds, free to disagree with the visit
screen about the same child.

**Batched, because a full department is the normal case.** A fixed handful of
queries for any number of children: the open stays, the last observation for
each, the running observation order for each, the last ward-round note and
who has been seen today, and — for the incubators — the last bilirubin and
the last weight. A ward of sixty costs what a ward of four costs, and a
size-comparison test fails if any of them turns into a query per child.
"""
from datetime import datetime

from app.extensions import db
# Aliased, because two different things are called a round in a hospital and
# both are in this file: `observations` is the repeated-reading round (every
# fifteen minutes), and this one is the ward round the doctor walks each
# morning. `_standing` binds the first of those to the name `rounds` locally,
# so the second gets a name that cannot collide with it.
from app.utils import rounds as ward_round

# Where a child sits in the reading order. Not a triage category — the clinic
# already has one of those in `red_flags`, and inventing a second scale here
# is exactly the duplication this file's docstring refuses.
UNSEEN, LATE, URGENT, WATCH, STEADY = (
    "unseen", "late", "urgent", "watch", "steady")

_RANK = {UNSEEN: 0, LATE: 1, URGENT: 2, WATCH: 3, STEADY: 4}


def _open_admissions(kind):
    """Every open stay in a unit of this kind, with child, bed and place."""
    from sqlalchemy.orm import selectinload

    from app.models.admission import Admission, BedStay
    from app.models.place import Bed, Space, Unit

    return (Admission.query
            .join(BedStay, db.and_(BedStay.admission_id == Admission.id,
                                   BedStay.until.is_(None)))
            .join(Bed, BedStay.bed_id == Bed.id)
            .join(Space, Bed.space_id == Space.id)
            .join(Unit, db.and_(Space.unit_id == Unit.id,
                                Unit.kind == kind,
                                Unit.is_active.is_(True)))
            .options(selectinload(Admission.patient),
                     # The bed comes with the stay, and its space and unit
                     # with it: the screen prints "unit · bed" on every row,
                     # and `admission.bed` walks stay → bed → space → unit.
                     # Left lazy this was one query per child — caught by the
                     # comparison test rather than by a guessed ceiling.
                     selectinload(Admission.stays)
                     .selectinload(BedStay.bed)
                     .selectinload(Bed.space)
                     .selectinload(Space.unit))
            .filter(Admission.discharged_at.is_(None))
            .order_by(Admission.admitted_at).all())


def _latest_observations(patient_ids):
    """``{patient_id: Observation}`` — the newest reading for each child.

    One query for the department. The same shape as
    ``observations.latest_for``, which answers per *order*; this one answers
    per child, because a department screen shows children and a child may have
    readings taken before the current order was written.
    """
    from sqlalchemy import and_, func

    from app.models.observation import Observation

    ids = [i for i in patient_ids if i]
    if not ids:
        return {}
    newest = (db.session.query(
        Observation.patient_id.label("patient_id"),
        func.max(Observation.taken_at).label("at"))
        .filter(Observation.patient_id.in_(ids))
        .group_by(Observation.patient_id).subquery())
    rows = (Observation.query
            .join(newest, and_(Observation.patient_id == newest.c.patient_id,
                               Observation.taken_at == newest.c.at)).all())
    return {row.patient_id: row for row in rows}


def _running_orders(patient_ids):
    """``{patient_id: ObservationOrder}`` for the rounds still running."""
    from app.models.observation import ObservationOrder

    ids = [i for i in patient_ids if i]
    if not ids:
        return {}
    rows = (ObservationOrder.query
            .filter(ObservationOrder.patient_id.in_(ids),
                    ObservationOrder.stopped_at.is_(None))
            .order_by(ObservationOrder.started_at).all())
    return {row.patient_id: row for row in rows}


def _standing(admission, last, order, now):
    """Where this child sits in the reading order, and why.

    Returns ``(level, rounds_state, flag)``. The reasons travel with the level
    because a colour nobody can account for gets ignored by the second day —
    the same rule the observation board follows.
    """
    from app.utils import observations as rounds
    from app.utils.red_flags import assess

    state = rounds.state(order, last.taken_at if last else None, now)
    flag = assess(admission.patient, last, admission.reason or "")

    if last is None:
        return UNSEEN, state, flag
    if state["level"] == rounds.LATE:
        return LATE, state, flag
    if flag["level"] == "urgent":
        return URGENT, state, flag
    if flag["level"] == "watch":
        return WATCH, state, flag
    return STEADY, state, flag


def live(kind, now=None):
    """Every child in this kind of department, the one to see first at the top.

    ``kind`` is a ``UNIT_KINDS`` value — "emergency", "nicu" and, when their
    screens arrive, the other four. The rows carry everything the screen
    prints so the template asks the database nothing.
    """
    now = now or datetime.utcnow()
    admissions = _open_admissions(kind)
    if not admissions:
        return []

    patient_ids = [a.patient_id for a in admissions]
    latest = _latest_observations(patient_ids)
    orders = _running_orders(patient_ids)
    newborn = _newborn_extras(admissions) if kind == "nicu" else {}
    # The daily round, where the department has one. Emergency does not: a
    # child is there for hours, and "not seen today" would flag every trolley
    # in the place the moment it filled. See `rounds.NO_ROUND_KINDS`.
    round_state = (ward_round.state([a.id for a in admissions])
                   if ward_round.kind_has_rounds(kind) else {})

    rows = []
    for admission in admissions:
        last = latest.get(admission.patient_id)
        order = orders.get(admission.patient_id)
        level, state, flag = _standing(admission, last, order, now)
        rows.append({
            "admission": admission,
            "patient": admission.patient,
            "bed": admission.bed,
            "since": admission.admitted_at,
            "minutes": int((now - admission.admitted_at).total_seconds() // 60),
            "last": last,
            "order": order,
            "rounds": state,
            "flag": flag,
            "level": level,
            "newborn": newborn.get(admission.patient_id),
            "round": round_state.get(admission.id),
        })
    # Worst first; then, at the same level, whoever nobody has been round to
    # yet; then the one who has been here longest.
    #
    # The round is a tie-breaker and never a level of its own. A child seen
    # this morning and deteriorating outranks one who is stable and unseen,
    # and putting "no round yet" into `_RANK` would have said the opposite —
    # an administrative gap jumping the queue in front of a clinical one.
    rows.sort(key=lambda r: (_RANK[r["level"]],
                             1 if (r["round"] or {}).get("today") else 0,
                             -r["minutes"]))
    return rows


# ------------------------------------------------------ the incubators -----
def _latest_bilirubin(patient_ids):
    """``{patient_id: VisitInvestigation}`` — the newest bilirubin result.

    The jaundice calculator has existed since Phase 4 of
    ``EMERGENCY_NEWBORN_PLAN.md`` and the results have existed longer, and
    nothing joined them: a nurse read the number off the lab screen and did
    the comparison in their head. One query, and the screen does it.
    """
    from sqlalchemy import and_, func

    from app.models import Investigation, VisitInvestigation

    ids = [i for i in patient_ids if i]
    if not ids:
        return {}
    coded = (db.session.query(Investigation.id)
             .filter(Investigation.code == "bilirubin").subquery())
    base = (VisitInvestigation.query
            .filter(VisitInvestigation.patient_id.in_(ids),
                    VisitInvestigation.investigation_id.in_(coded),
                    VisitInvestigation.result_value.isnot(None)))
    newest = (db.session.query(
        VisitInvestigation.patient_id.label("patient_id"),
        func.max(VisitInvestigation.resulted_at).label("at"))
        .filter(VisitInvestigation.patient_id.in_(ids),
                VisitInvestigation.investigation_id.in_(coded),
                VisitInvestigation.result_value.isnot(None))
        .group_by(VisitInvestigation.patient_id).subquery())
    rows = (base.join(newest,
                      and_(VisitInvestigation.patient_id == newest.c.patient_id,
                           VisitInvestigation.resulted_at == newest.c.at)).all())
    return {row.patient_id: row for row in rows}


def _latest_weight(patient_ids):
    """``{patient_id: GrowthRecord}`` — the newest weight on file.

    From the growth records and not from an observation. A daily weight in an
    incubator *is* growth: it belongs on the child's curve, and a second copy
    of it living on a rounds row would be a number free to disagree with the
    chart in the same file. `Observation` deliberately carries no weight for
    that reason.
    """
    from sqlalchemy import and_, func

    from app.models import GrowthRecord

    ids = [i for i in patient_ids if i]
    if not ids:
        return {}
    newest = (db.session.query(
        GrowthRecord.patient_id.label("patient_id"),
        func.max(GrowthRecord.record_date).label("on"))
        .filter(GrowthRecord.patient_id.in_(ids),
                GrowthRecord.weight_kg.isnot(None))
        .group_by(GrowthRecord.patient_id).subquery())
    rows = (GrowthRecord.query
            .filter(GrowthRecord.weight_kg.isnot(None))
            .join(newest, and_(GrowthRecord.patient_id == newest.c.patient_id,
                               GrowthRecord.record_date == newest.c.on)).all())
    return {row.patient_id: row for row in rows}


def _newborn_extras(admissions):
    """What the incubators need that no other department does.

    Hours of life, gestation, weight against birth weight, and where the last
    bilirubin sits against this baby's own threshold. Every one of those is
    read from something that already existed — ``patient.age_hours``,
    ``gestation_weeks``, ``birth_weight_kg``, and ``jaundice.assess`` — and
    none of them is recomputed here.
    """
    from app.utils import jaundice

    ids = [a.patient_id for a in admissions]
    bilirubin = _latest_bilirubin(ids)
    weights = _latest_weight(ids)

    out = {}
    for admission in admissions:
        baby = admission.patient
        result = bilirubin.get(admission.patient_id)
        weighed = weights.get(admission.patient_id)
        verdict = None
        if result is not None:
            # The reading belongs to the moment blood was drawn, not to now:
            # in the first days these curves move fast enough that a few hours
            # crosses them. `assess` takes the hours for exactly this reason.
            hours = getattr(baby, "age_hours", None)
            if hours is not None and result.resulted_at:
                drawn = (datetime.utcnow() - result.resulted_at).total_seconds()
                hours = max(0, hours - drawn / 3600.0)
            verdict = jaundice.assess(baby, result.result_value, hours=hours)
        out[admission.patient_id] = {
            "hours": getattr(baby, "age_hours", None),
            "weeks": getattr(baby, "gestation_weeks", None),
            "birth_weight": getattr(baby, "birth_weight_kg", None),
            "weight": weighed.weight_kg if weighed else None,
            "weighed_on": weighed.record_date if weighed else None,
            "bilirubin": result,
            "jaundice": verdict,
        }
    return out
