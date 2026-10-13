"""The staff health program — GAHAR OGM.17. Models in
``app/models/staff_health.py``.

**The rules the records keep:**

* the occupational risk assessment is by area and job, with the hazard,
  the controls and the level — nothing is assessed without its controls;
* a positive result is not written without the action taken and the day the
  employee was told (ev. 6); an exposure is not written without what was
  done about it — the prophylaxis, the follow-up (ev. 5);
* a restriction carries the day it ends, and the board lists who is
  restricted today;
* the program schedules no examination and no vaccine of its own: what is
  due is the hospital's program, written on paper (ev. 1).

Who may open it: the administrators and infection control (OGM.17 i) — a
staff member's health record is nobody else's business.
"""
from app.extensions import db
from app.models.staff_health import (ENTRY_KINDS, HAZARDS, RESULTS, RISK_LEVELS, OccupationalRisk,
                                     StaffHealthEntry)
from app.utils.facility_safety import FacilityError, _day, _text


def _today():
    from app.utils.clock import local_today

    return local_today()


def may_open(user):
    from app.utils import ipc

    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_admin or ipc.may_review(user)))


def save_risk(user, form):
    area = _text(form.get("area"), 160)
    hazard, level = form.get("hazard"), form.get("level")
    description, controls = _text(form.get("description")), _text(form.get("controls"))
    if not area or hazard not in HAZARDS or level not in RISK_LEVELS:
        raise FacilityError("need_risk")
    if not description or not controls:
        raise FacilityError("need_controls")
    row = OccupationalRisk(area=area, job=_text(form.get("job"), 160), hazard=hazard,
                           description=description, controls=controls, level=level,
                           assessed_on=_day(form.get("assessed_on")),
                           ipc_involved=bool(form.get("ipc_involved")),
                           assessed_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def risks():
    rank = {r: i for i, r in enumerate(RISK_LEVELS)}
    rows = OccupationalRisk.query.filter_by(is_active=True).all()
    rows.sort(key=lambda r: (rank.get(r.level, 9), r.area))
    return rows


def record(user, staff, form):
    if staff is None:
        raise FacilityError("no_person")
    kind = form.get("kind")
    if kind not in ENTRY_KINDS:
        raise FacilityError("need_kind")
    detail = _text(form.get("detail"), 255)
    if not detail:
        raise FacilityError("need_detail")
    result = form.get("result") or "na"
    if result not in RESULTS:
        raise FacilityError("need_result")
    action = _text(form.get("action"))
    informed = _day(form.get("informed_on"), need=False)
    if result == "positive" and (not action or informed is None):
        raise FacilityError("need_positive_action")
    if kind == "exposure" and not action:
        raise FacilityError("need_action")
    until = _day(form.get("restricted_until"), need=False, future_ok=True)
    if kind == "restriction" and until is None:
        raise FacilityError("need_until")
    row = StaffHealthEntry(user_id=staff.id, kind=kind, on=_day(form.get("on")), detail=detail,
                           result=result, action=action, informed_on=informed,
                           restricted_until=until, recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def file_of(staff):
    return (StaffHealthEntry.query.filter_by(user_id=staff.id)
            .order_by(StaffHealthEntry.on.desc(), StaffHealthEntry.id.desc()).all())


def board(today=None):
    """Who is restricted today, the active staff with no pre-employment
    examination on file, and the latest entries."""
    from app.models import User

    today = today or _today()
    restricted = (StaffHealthEntry.query
                  .filter(StaffHealthEntry.restricted_until.isnot(None),
                          StaffHealthEntry.restricted_until >= today)
                  .order_by(StaffHealthEntry.restricted_until).all())
    examined = {uid for (uid,) in db.session.query(StaffHealthEntry.user_id)
                .filter(StaffHealthEntry.kind == "pre_employment")}
    staff = User.query.filter(User.is_active.is_(True)).order_by(User.full_name).all()
    return {"restricted": restricted, "staff": staff,
            "no_pre_employment": [u for u in staff if u.id not in examined],
            "latest": (StaffHealthEntry.query.order_by(StaffHealthEntry.recorded_at.desc())
                       .limit(15).all())}


__all__ = ["board", "file_of", "may_open", "record", "risks", "save_risk"]
