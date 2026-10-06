"""The building's safety records — GAHAR EFS.03 / GSR.23, EFS.04 / GSR.24,
EFS.11 / GSR.28. Models in ``app/models/facility_safety.py``.

**The rules the records keep:**

* a drill is written with its date and time, shift, areas, who took part,
  the evaluation **and** the corrective action — evidence 3 and 4 in one
  form, so neither is left for later;
* the year's drills are read against the standard's own figures: one each
  quarter, one of them unannounced, and every member of staff in one;
* a failed fire-system check or utility check needs the action beside it;
* a utility is overdue only against the interval written for it — the
  program invents no maintenance schedule.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.facility_safety import (FIRE_SYSTEMS, RESULTS, SHIFTS,
                                        UTILITY_CHECKS, UTILITY_KINDS,
                                        FireDrill, FireSystemCheck,
                                        FireTraining, UtilityCheck,
                                        UtilitySystem)


class FacilityError(ValueError):
    """A refusal with a key the screen can name (``facility.err_<key>``)."""


def _today():
    from app.utils.clock import local_today

    return local_today()


def _day(value, need=True, future_ok=False):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        if need:
            raise FacilityError("need_date")
        return None
    try:
        on = date.fromisoformat(raw)
    except ValueError:
        raise FacilityError("bad_date") from None
    if not future_ok and on > _today():
        raise FacilityError("future")
    return on


def _text(value, limit=4000):
    return (str(value or "")).strip()[:limit] or None


def _int(value, low=0, high=100000):
    raw = str(value or "").strip()
    if not raw:
        return None
    if not raw.isdigit() or not low <= int(raw) <= high:
        raise FacilityError("bad_number")
    return int(raw)


def _list(form, key):
    if hasattr(form, "getlist"):
        return form.getlist(key)
    value = form.get(key)
    return value if isinstance(value, list) else ([value] if value else [])


def may_manage(user):
    """Whoever looks after the building: the administrators and the store —
    where the maintenance office usually sits in the program."""
    return bool(user is not None and (user.is_admin or user.can_access("inventory")))


# ================================================================== drills ==
def drill(user, form):
    from app.models import User

    raw = (form.get("held_at") or "").strip()
    try:
        held = datetime.fromisoformat(raw)
    except ValueError:
        raise FacilityError("need_when") from None
    if held.date() > _today():
        raise FacilityError("future")
    shift = form.get("shift")
    if shift not in SHIFTS:
        raise FacilityError("need_shift")
    areas = _text(form.get("areas"), 400)
    if not areas:
        raise FacilityError("need_areas")
    evaluation, action = _text(form.get("evaluation")), _text(form.get("corrective_action"))
    if not evaluation or not action:
        raise FacilityError("need_evaluation")
    ids = {int(v) for v in _list(form, "participants") if str(v).isdigit()}
    people = User.query.filter(User.id.in_(ids)).all() if ids else []
    others = _int(form.get("others"))
    if not people and not others:
        raise FacilityError("need_people")
    row = FireDrill(held_at=held, shift=shift, areas=areas,
                    unannounced=bool(form.get("unannounced")),
                    evacuation_minutes=_int(form.get("evacuation_minutes"), 0, 600),
                    others=others, evaluation=evaluation, corrective_action=action,
                    recorded_by=getattr(user, "id", None))
    row.participants = people
    db.session.add(row)
    db.session.flush()
    return row


def year_of_drills(year=None):
    """The year read against EFS.04: each quarter's drills, whether one was
    unannounced, and the active staff not yet in one."""
    from app.models import User

    year = year or _today().year
    drills = (FireDrill.query
              .filter(FireDrill.held_at >= datetime(year, 1, 1),
                      FireDrill.held_at < datetime(year + 1, 1, 1))
              .order_by(FireDrill.held_at.desc()).all())
    quarters = {q: 0 for q in (1, 2, 3, 4)}
    took_part = set()
    for d in drills:
        quarters[(d.held_at.month - 1) // 3 + 1] += 1
        took_part.update(p.id for p in d.participants)
    current_q = (_today().month - 1) // 3 + 1 if year == _today().year else 4
    missing_q = [q for q in quarters if q <= current_q and not quarters[q]]
    not_yet = [u for u in User.query.filter(User.is_active.is_(True))
               .order_by(User.full_name).all() if u.id not in took_part]
    return {"year": year, "drills": drills, "quarters": quarters,
            "missing_quarters": missing_q,
            "unannounced": any(d.unannounced for d in drills),
            "not_yet": not_yet}


# ==================================================== fire systems, training ==
def fire_check(user, form):
    system = form.get("system")
    if system not in FIRE_SYSTEMS:
        raise FacilityError("need_system")
    result = form.get("result")
    if result not in RESULTS:
        raise FacilityError("need_result")
    action = _text(form.get("action"))
    if result == "fail" and not action:
        raise FacilityError("need_action")
    row = FireSystemCheck(system=system, location=_text(form.get("location"), 160),
                          checked_on=_day(form.get("checked_on")),
                          done_by=_text(form.get("done_by"), 160), result=result,
                          details=_text(form.get("details")), action=action,
                          next_due=_day(form.get("next_due"), need=False, future_ok=True),
                          recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def fire_systems_now(today=None):
    """The newest check of each system and place — failed, or past its next
    date, first."""
    today = today or _today()
    newest = {}
    for row in FireSystemCheck.query.order_by(FireSystemCheck.checked_on.desc(),
                                              FireSystemCheck.id.desc()):
        newest.setdefault((row.system, (row.location or "").strip()), row)
    rows = [{"check": r, "overdue": bool(r.next_due and r.next_due < today)}
            for r in newest.values()]
    rows.sort(key=lambda x: (x["check"].result == "pass", not x["overdue"], x["check"].system))
    return rows


def train(user, form):
    from app.models import User

    ids = {int(v) for v in _list(form, "user_ids") if str(v).isdigit()}
    people = User.query.filter(User.id.in_(ids)).all() if ids else []
    if not people:
        raise FacilityError("no_person")
    on = _day(form.get("trained_on"))
    trainer = _text(form.get("trainer"), 160)
    rows = [FireTraining(user_id=p.id, trained_on=on, trainer=trainer,
                         recorded_by=getattr(user, "id", None)) for p in people]
    db.session.add_all(rows)
    db.session.flush()
    return rows


def untrained_this_year(today=None):
    """EFS.03 evidence 2 — active staff with no fire training in the last
    twelve months."""
    from app.models import User

    today = today or _today()
    since = today - timedelta(days=365)
    trained = {uid for (uid,) in db.session.query(FireTraining.user_id)
               .filter(FireTraining.trained_on >= since)}
    return [u for u in User.query.filter(User.is_active.is_(True))
            .order_by(User.full_name).all() if u.id not in trained]


# =============================================================== utilities ==
def save_utility(form, row=None):
    name = _text(form.get("name"), 160)
    if not name:
        raise FacilityError("need_name")
    kind = form.get("kind")
    if kind not in UTILITY_KINDS:
        raise FacilityError("need_kind")
    row = row or UtilitySystem()
    row.name, row.kind = name, kind
    row.location = _text(form.get("location"), 160)
    row.is_critical = bool(form.get("is_critical"))
    row.backup = _text(form.get("backup"), 200)
    row.check_every_days = _int(form.get("check_every_days"), 1, 3650)
    if row.is_critical and not row.backup:
        raise FacilityError("need_backup")
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def utility_check(system, user, form):
    if system is None or not system.is_active:
        raise FacilityError("no_system")
    kind = form.get("kind")
    if kind not in UTILITY_CHECKS:
        raise FacilityError("need_kind")
    result = form.get("result")
    if result not in RESULTS:
        raise FacilityError("need_result")
    action = _text(form.get("action"))
    if result == "fail" and not action:
        raise FacilityError("need_action")
    row = UtilityCheck(system_id=system.id, kind=kind, done_on=_day(form.get("done_on")),
                       done_by=_text(form.get("done_by"), 160), result=result,
                       details=_text(form.get("details")), action=action,
                       fuel=_text(form.get("fuel"), 60),
                       recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def utilities_now(today=None):
    """Every active utility with its newest check and, where an interval is
    written, when the next is due — failed, overdue and critical first."""
    today = today or _today()
    out = []
    for system in (UtilitySystem.query.filter_by(is_active=True)
                   .order_by(UtilitySystem.name).all()):
        last = system.checks[0] if system.checks else None
        due = None
        if system.check_every_days:
            due = (last.done_on if last else system.created_at.date()) + timedelta(
                days=system.check_every_days)
        out.append({"system": system, "last": last, "due": due,
                    "overdue": bool(due and due < today),
                    "failed": bool(last and last.result == "fail")})
    out.sort(key=lambda r: (not r["failed"], not r["overdue"], not r["system"].is_critical,
                            r["system"].name))
    return out
