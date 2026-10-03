"""What each child in emergency is waiting on, and for how long.

Asked as *«مش التحاليل المتأخره بس — هو قاعد وملهوش علاج، وخلص جلسة النفس،
او مستنى اشعة، او مستنى الطبيب يكتب روشتة فى الخروج من الطوارئ، مستنى
اجراء»*. A screen that says a child has been here ninety minutes says
nothing about whose move it is; this says whose.

**Nothing here is stored and nothing is typed.** Every item is read off what
the department already writes — the arrival and triage, the treatments and
who approved them, the tests and where they are, the time a session ends:

* ``triage``    arrived, nobody has triaged;
* ``doctor``    triaged, and nothing at all written for the child yet —
                «قاعد وملهوش علاج»;
* ``approval``  an outside prescription waiting for one of our doctors;
* ``treatment`` written and not given yet — the nurse's move;
* ``reassess``  a timed treatment (a nebuliser session) has run its course
                and nothing has been written since — somebody should look;
* ``sample``    a test ordered and not drawn;
* ``result``    drawn and not answered;
* ``imaging``   a scan or study ordered and not done;
* ``decision``  everything done and the child still here — the doctor's
                decision, or the discharge prescription.

**Times are the department's, not the program's.** How long a session runs
is the service's own ``duration_minutes``; how long a child should be here at
all is the unit's ``max_stay_minutes``. Unset, nothing is inferred and
nothing is flagged — the program does not decide that forty minutes is too
long for a CBC.

Batched: a fixed handful of queries for any number of children.
"""
from datetime import datetime, timedelta

from app.extensions import db

KINDS = ("triage", "approval", "doctor", "treatment", "reassess", "sample",
         "imaging", "result", "decision")
_RANK = {k: i for i, k in enumerate(KINDS)}

#: Bootstrap icons, one per kind, so the screen says it in a shape as well as
#: in words — «عايز الشاشة تبقى فيها اشكال تصف المعنى جنب الكلام».
ICONS = {
    "triage": "clipboard2-pulse",
    "approval": "file-earmark-medical",
    "doctor": "person-badge",
    "treatment": "capsule",
    "reassess": "wind",
    "sample": "droplet",
    "imaging": "radioactive",
    "result": "hourglass-split",
    "decision": "door-open",
}


def _item(kind, since, now, detail=None):
    since = since or now
    return {"kind": kind, "since": since, "detail": detail,
            "icon": ICONS[kind],
            "minutes": max(0, int((now - since).total_seconds() // 60))}


def emergency_limit():
    """The emergency's own «too long» figure, in minutes, or ``None``.

    The strictest of the emergency units that set one: a child with no bed
    belongs to the department, not to one of its rooms.
    """
    from app.models.place import Unit

    values = [u.max_stay_minutes for u in Unit.query.filter(
        Unit.kind == "emergency", Unit.is_active.is_(True),
        Unit.max_stay_minutes.isnot(None)).all() if u.max_stay_minutes]
    return min(values) if values else None


def _tests_by(column, keys):
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation

    keys = [k for k in keys if k]
    if not keys:
        return {}
    out = {}
    for row in (VisitInvestigation.query
                .options(selectinload(VisitInvestigation.investigation))
                .filter(column.in_(keys)).all()):
        out.setdefault(getattr(row, column.key), []).append(row)
    return out


def _test_items(tests, now):
    """Where the child's tests and scans stand — the items they wait on."""
    from app.utils.lab_results import late

    items = []
    for x in tests:
        if x.status == "resulted" or x.done_outside:
            continue
        name = x.display_name() if hasattr(x, "display_name") else x.name
        if x.kind == "lab":
            if x.collected_at is None:
                items.append(_item("sample", x.created_at, now, name))
            else:
                row = _item("result", x.collected_at, now, name)
                row["late"] = bool(late(x, now))
                items.append(row)
        else:
            items.append(_item("imaging", x.created_at, now, name))
    return items


def _latest(*moments):
    moments = [m for m in moments if m is not None]
    return max(moments) if moments else None


def for_attendances(attendances, now=None):
    """``{attendance_id: {"items": [...], "top": item|None, "minutes",
    "limit", "over"}}`` for children in emergency with no bed."""
    from sqlalchemy.orm import selectinload

    from app.models import EmergencyOrder

    now = now or datetime.utcnow()
    attendances = [a for a in attendances if a is not None]
    if not attendances:
        return {}
    ids = [a.id for a in attendances]
    orders = {}
    for o in (EmergencyOrder.query
              .options(selectinload(EmergencyOrder.service))
              .filter(EmergencyOrder.emergency_visit_id.in_(ids)).all()):
        orders.setdefault(o.emergency_visit_id, []).append(o)
    tests = _tests_by(_visit_column(), [a.visit_id for a in attendances])
    limit = emergency_limit()

    out = {}
    for a in attendances:
        mine = [o for o in orders.get(a.id, []) if o.cancelled_at is None]
        mine_tests = tests.get(a.visit_id, []) if a.visit_id else []
        items = []
        if a.is_open:
            items = _attendance_items(a, mine, mine_tests, now)
        items.sort(key=lambda i: (_RANK[i["kind"]], -i["minutes"]))
        minutes = a.minutes
        out[a.id] = {"items": items, "top": items[0] if items else None,
                     "minutes": minutes, "limit": limit,
                     "over": bool(limit and a.is_open and minutes > limit)}
    return out


def _visit_column():
    from app.models import VisitInvestigation

    return VisitInvestigation.visit_id


def _attendance_items(a, orders, tests, now):
    if a.triaged_at is None:
        return [_item("triage", a.arrived_at, now)]
    items = []
    for o in orders:
        if o.state == "waiting_doctor":
            items.append(_item("approval", o.created_at, now, o.name))
        elif o.state == "ready":
            items.append(_item("treatment", o.approved_at or o.created_at,
                               now, o.name))
    items += _test_items(tests, now)

    if not orders and not tests:
        # «قاعد وملهوش علاج» — triaged, and nobody has written a thing.
        return [_item("doctor", a.triaged_at, now)]

    # The last time anybody wrote or did anything for this child.
    last_act = _latest(*([o.created_at for o in orders]
                         + [o.given_at for o in orders]
                         + [x.created_at for x in tests]
                         + [x.resulted_at for x in tests]))
    ended = _session_ended(orders, now)
    if ended is not None:
        # Anything written or done since the session ended answers it — but
        # not the session's own line, which may well have been written up
        # after it was given.
        since = _latest(*([o.created_at for o in orders if o is not ended[2]]
                          + [o.given_at for o in orders if o is not ended[2]]
                          + [x.created_at for x in tests]
                          + [x.resulted_at for x in tests]))
        if since is None or since <= ended[0]:
            items.append(_item("reassess", ended[0], now, ended[1]))
    if not items:
        # Everything written is given and answered, and the child is still
        # here: the doctor's move — a decision, or the discharge paper.
        items.append(_item("decision", last_act or a.triaged_at, now))
    return items


def _session_ended(orders, now):
    """``(when it ended, name, order)`` for the latest given treatment whose service
    says how long it runs and whose time is up — or ``None``."""
    best = None
    for o in orders:
        minutes = getattr(o.service, "duration_minutes", None) if o.service else None
        if o.given_at is None or not minutes:
            continue
        end = o.given_at + timedelta(minutes=int(minutes))
        if end > now:
            continue
        if best is None or end > best[0]:
            best = (end, o.name, o)
    return best


def running_session(orders, now=None):
    """The timed treatment running now, for a countdown: ``{"name",
    "ends", "left", "total"}`` or ``None``."""
    now = now or datetime.utcnow()
    for o in sorted(orders, key=lambda x: x.given_at or now, reverse=True):
        minutes = getattr(o.service, "duration_minutes", None) if o.service else None
        if o.given_at is None or not minutes or o.cancelled_at is not None:
            continue
        end = o.given_at + timedelta(minutes=int(minutes))
        if end > now:
            left = int((end - now).total_seconds() // 60) + 1
            return {"name": o.name, "ends": end, "left": min(left, int(minutes)),
                    "total": int(minutes)}
    return None


def for_stays(rows, now=None):
    """The same question for children in an emergency **bed**: the rows of
    ``department.live``, each given ``waiting`` — drugs due or late, tests,
    and time over the unit's own limit."""
    from app.models import VisitInvestigation

    now = now or datetime.utcnow()
    if not rows:
        return rows
    tests = _tests_by(VisitInvestigation.admission_id,
                      [r["admission"].id for r in rows])
    for r in rows:
        items = []
        drugs = r.get("drugs") or {}
        for entry in drugs.get("orders", []):
            level = entry["state"]["level"]
            if level in ("late", "due"):
                row = _item("treatment", entry["state"].get("due_at") or now,
                            now, entry["order"].name)
                row["late"] = level == "late"
                items.append(row)
        items += _test_items(tests.get(r["admission"].id, []), now)
        items.sort(key=lambda i: (_RANK[i["kind"]], -i["minutes"]))
        bed = r.get("bed")
        unit = bed.unit if bed is not None else None
        limit = getattr(unit, "max_stay_minutes", None)
        r["waiting"] = {"items": items, "top": items[0] if items else None,
                        "limit": limit,
                        "over": bool(limit and r["minutes"] > limit)}
    return rows
