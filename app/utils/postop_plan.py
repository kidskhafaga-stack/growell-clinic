"""The post-operative plan — GAHAR SAS.12, and when it was written.

Four evidence items, and what answers each:

1. *"There is a postoperative care plan for all patients … developed by the
   performing physician"* — :func:`state` for the plan, :func:`by_surgeon`
   for who wrote it, and :func:`unplanned` for the cases with none.
2. *"developed based on identified postoperative needs"* — the eight elements
   by name (:attr:`PostOpPlan.ELEMENTS`), so a plan that forgot the diet says
   so instead of reading as complete.
3. *"documented … before leaving the procedure room"* — :func:`late`,
   against the moment the program already stamps when the child leaves
   theatre (``Operation.recovery_at``). No interval is invented: the standard
   names the event.
4. *"implemented and updated based on changes"* — every save is a version
   (:func:`history`), so the plan in force at any hour can still be read.

**The surgeon types less the second time.** A plan for a circumcision is
mostly the same plan every time, so the form starts from this surgeon's own
last plan for the same procedure (:func:`starting_point`). Theirs, not the
program's — and not another surgeon's, whose habits are not this one's.
"""
from datetime import datetime

from app.extensions import db
from app.models.postop_plan import LEVELS, PostOpPlan

#: What :func:`state` can answer.
STATES = ("none", "short", "complete")


def history(operation):
    """Every version, oldest first."""
    if operation is None:
        return []
    return (PostOpPlan.query.filter_by(operation_id=operation.id)
            .order_by(PostOpPlan.at, PostOpPlan.id).all())


def current(operation):
    """The plan in force — the latest version — or ``None``."""
    if operation is None:
        return None
    return (PostOpPlan.query.filter_by(operation_id=operation.id)
            .order_by(PostOpPlan.at.desc(), PostOpPlan.id.desc()).first())


def state(operation):
    """``none`` · ``short`` · ``complete``."""
    plan = current(operation)
    if plan is None:
        return "none"
    return "short" if plan.missing else "complete"


def missing(operation):
    """Which of the eight the plan in force leaves blank."""
    plan = current(operation)
    return list(PostOpPlan.ELEMENTS) if plan is None else plan.missing


def late(operation):
    """Was the first plan written after the child left theatre? — EOC 3.

    ``None`` while either end is missing: a case still in the room and a case
    with no plan are both unanswerable here, and :func:`state` is where the
    second shows. **The first version** is what counts — an update written on
    the ward at midnight is EOC 4 doing its job, not a late plan.
    """
    left = getattr(operation, "recovery_at", None) if operation else None
    versions = history(operation)
    if left is None or not versions:
        return None
    return versions[0].at > left


def by_surgeon(operation):
    """Did the performing physician write the plan in force? — EOC 1.

    ``None`` when there is no plan or no surgeon on the booking. ``False`` is
    shown, not refused: a registrar writing it at the surgeon's word is how a
    theatre runs, and the screen says whose words these are.
    """
    plan = current(operation)
    surgeon = getattr(operation, "surgeon_id", None)
    if plan is None or surgeon is None:
        return None
    return plan.by_id == surgeon


def _clean(value):
    return (value or "").strip() or None


def write(operation, user=None, at=None, **fields):
    """Save a version. Returns the plan in force. The caller commits.

    **An unchanged save is not a version.** Pressing save twice would
    otherwise fill the history with copies, and the history is how EOC 4 is
    shown — a list of identical plans reads as a plan nobody revisited.
    """
    if operation is None or operation.status == "cancelled":
        raise ValueError("no case")
    level = _clean(fields.get("level"))
    if level is not None and level not in LEVELS:
        raise ValueError("unknown level")
    values = {"level": level}
    for name in PostOpPlan.ELEMENTS:
        if name != "level":
            values[name] = _clean(fields.get(name))
    now = current(operation)
    if now is not None and all(getattr(now, k) == v for k, v in values.items()):
        return now
    plan = PostOpPlan(operation_id=operation.id,
                      by_id=getattr(user, "id", None),
                      at=at or datetime.utcnow(), **values)
    db.session.add(plan)
    return plan


def starting_point(operation):
    """What the form opens with: this plan, else this surgeon's last plan
    for the same procedure, else nothing.

    Returns ``(values, source)`` where ``source`` is ``"current"``,
    ``"previous"`` or ``None`` — the screen says which, because a form that
    arrives filled in has to say where the words came from.
    """
    plan = current(operation)
    if plan is not None:
        return ({k: getattr(plan, k) for k in PostOpPlan.ELEMENTS},
                "current")
    from app.models import Operation

    surgeon = getattr(operation, "surgeon_id", None)
    service = getattr(operation, "service_id", None)
    if operation is None or surgeon is None or service is None:
        return ({}, None)
    previous = (PostOpPlan.query.join(Operation,
                                      PostOpPlan.operation_id == Operation.id)
                .filter(Operation.surgeon_id == surgeon,
                        Operation.service_id == service,
                        Operation.id != operation.id,
                        PostOpPlan.by_id == surgeon)
                .order_by(PostOpPlan.at.desc(), PostOpPlan.id.desc())
                .first())
    if previous is None:
        return ({}, None)
    return ({k: getattr(previous, k) for k in PostOpPlan.ELEMENTS},
            "previous")


def unplanned(on_date=None):
    """Finished cases with no plan at all — the queue for EOC 1.

    One query: the cases, less those that have any version.
    """
    from app.models import Operation

    has = db.session.query(PostOpPlan.operation_id).distinct()
    query = (Operation.query
             .filter(Operation.status == "done",
                     Operation.id.notin_(has))
             .order_by(Operation.on_date.desc(), Operation.id))
    if on_date is not None:
        query = query.filter(Operation.on_date == on_date)
    return query.all()


def planned_ids(operation_ids):
    """``{operation_id: state}`` for a list — one query, for boards."""
    ids = [i for i in operation_ids if i]
    if not ids:
        return {}
    rows = (PostOpPlan.query.filter(PostOpPlan.operation_id.in_(ids))
            .order_by(PostOpPlan.operation_id, PostOpPlan.at, PostOpPlan.id)
            .all())
    latest = {}
    for row in rows:
        latest[row.operation_id] = row
    return {op_id: ("short" if plan.missing else "complete")
            for op_id, plan in latest.items()}
