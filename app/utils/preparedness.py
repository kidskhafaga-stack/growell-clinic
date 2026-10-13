"""Being ready, and keeping the plans current — GAHAR EFS.01, EFS.13 and the
annual review the standards ask of every plan. Models in
``app/models/preparedness.py``.

* the hazards are ranked by probability × impact on the hospital's own
  scale — the program fixes no scale and adds no hazard of its own;
* the call tree is ordered by title, with the outside numbers apart;
* a plan is due for review ``review_months`` after its approval — twelve,
  the standard's "annually", unless the hospital wrote otherwise; a newer
  version replaces it and the old one stays as history;
* an outside authority's observation stays open until it is closed with a
  word on what was done, and is overdue past its deadline.
"""
from datetime import date

from app.extensions import db
from app.models.preparedness import (HAZARD_KINDS, PLAN_KINDS, REVIEW_MONTHS, CallTreeEntry,
                                     EmergencyHazard, ExternalInspection, HospitalPlan)
from app.utils.facility_safety import FacilityError, _day, _int, _text


def _today():
    from app.utils.clock import local_today

    return local_today()


def add_months(on, months):
    month = on.month - 1 + months
    year, month = on.year + month // 12, month % 12 + 1
    from calendar import monthrange

    return date(year, month, min(on.day, monthrange(year, month)[1]))


# ================================================================= hazards ==
def save_hazard(user, form, row=None):
    name = _text(form.get("name"), 160)
    if not name:
        raise FacilityError("need_name")
    kind = form.get("kind")
    if kind not in HAZARD_KINDS:
        raise FacilityError("need_kind")
    probability, impact = _int(form.get("probability"), 1, 100), _int(form.get("impact"), 1, 100)
    if not probability or not impact:
        raise FacilityError("need_score")
    row = row or EmergencyHazard()
    row.name, row.kind, row.probability, row.impact = name, kind, probability, impact
    row.preparedness = _text(form.get("preparedness"))
    row.resources = _text(form.get("resources"))
    row.assessed_on = _day(form.get("assessed_on"))
    row.assessed_by = getattr(user, "id", None)
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def hazards():
    rows = EmergencyHazard.query.filter_by(is_active=True).all()
    rows.sort(key=lambda h: (-h.score, h.name))
    return rows


def save_contact(form):
    title, phone = _text(form.get("title"), 160), _text(form.get("phone"), 40)
    if not title or not phone:
        raise FacilityError("need_contact")
    row = CallTreeEntry(title=title, phone=phone, name=_text(form.get("name"), 160),
                        external=bool(form.get("external")), duty=_text(form.get("duty"), 255),
                        position=_int(form.get("position"), 0, 999) or 0)
    db.session.add(row)
    db.session.flush()
    return row


def call_tree():
    rows = (CallTreeEntry.query.filter_by(is_active=True)
            .order_by(CallTreeEntry.position, CallTreeEntry.id).all())
    return {"inside": [r for r in rows if not r.external], "outside": [r for r in rows if r.external]}


def retire(row):
    row.is_active = False
    db.session.flush()


# =================================================================== plans ==
def save_plan(user, form, file=None, replaces=None):
    kind = form.get("kind")
    if kind not in PLAN_KINDS:
        raise FacilityError("need_kind")
    title, by = _text(form.get("title"), 200), _text(form.get("approved_by"), 160)
    if not title or not by:
        raise FacilityError("need_title")
    months = _int(form.get("review_months"), 1, 60) or REVIEW_MONTHS
    row = HospitalPlan(kind=kind, title=title, approved_on=_day(form.get("approved_on")),
                       approved_by=by, review_months=months, file=file,
                       changes=_text(form.get("changes")), recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    if replaces is not None and replaces.replaced_by is None:
        replaces.replaced_by = row.id
        db.session.flush()
    return row


def due_on(plan):
    return add_months(plan.approved_on, plan.review_months or REVIEW_MONTHS)


def plans_board(today=None):
    """The current version of every plan, when each is due, the overdue ones,
    and the plans the standards name that the hospital has not entered."""
    today = today or _today()
    current = (HospitalPlan.query.filter(HospitalPlan.replaced_by.is_(None))
               .order_by(HospitalPlan.kind, HospitalPlan.title).all())
    rows = [{"plan": p, "due": due_on(p), "overdue": due_on(p) < today} for p in current]
    from app.models.preparedness import TEACHING_PLANS
    from app.utils.facility import module_enabled

    held = {p.kind for p in current}
    teaching = module_enabled("teaching")
    return {"rows": rows, "overdue": [r for r in rows if r["overdue"]],
            "missing": [k for k in PLAN_KINDS if k != "other" and k not in held
                        and (teaching or k not in TEACHING_PLANS)]}


def history(plan):
    """Every earlier version this one replaced, newest first."""
    out, seen = [], {plan.id}
    node = HospitalPlan.query.filter_by(replaced_by=plan.id).first()
    while node is not None and node.id not in seen:
        out.append(node)
        seen.add(node.id)
        node = HospitalPlan.query.filter_by(replaced_by=node.id).first()
    return out


# ============================================================= inspections ==
def save_inspection(user, form, file=None):
    authority = _text(form.get("authority"), 160)
    observations, plan = _text(form.get("observations")), _text(form.get("corrective_plan"))
    if not authority or not observations or not plan:
        raise FacilityError("need_inspection")
    row = ExternalInspection(authority=authority, visited_on=_day(form.get("visited_on")),
                             observations=observations, corrective_plan=plan,
                             due_on=_day(form.get("due_on"), need=False, future_ok=True), file=file,
                             recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def close_inspection(row, form):
    if row.closed_on is not None:
        raise FacilityError("already_closed")
    note = _text(form.get("note"), 255)
    if not note:
        raise FacilityError("need_note")
    row.closed_on, row.closed_note = _day(form.get("closed_on")), note
    db.session.flush()
    return row


def inspections_board(today=None):
    today = today or _today()
    rows = ExternalInspection.query.order_by(ExternalInspection.visited_on.desc()).all()
    open_rows = [r for r in rows if r.closed_on is None]
    return {"rows": rows, "open": open_rows,
            "overdue": [r for r in open_rows if r.due_on and r.due_on < today]}


__all__ = ["add_months", "call_tree", "close_inspection", "due_on", "hazards", "history",
           "inspections_board", "plans_board", "retire", "save_contact", "save_hazard",
           "save_inspection", "save_plan"]
