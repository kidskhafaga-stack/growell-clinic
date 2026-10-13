"""Antimicrobial stewardship — see ``models/stewardship``."""
from datetime import datetime

from app.extensions import db
from app.models.stewardship import (DECISIONS, KINDS, RestrictedAntimicrobial,
                                    StewardshipReview)

#: The drug classes the hospital counts as antimicrobial — ids, comma-separated.
CLASS_SETTING = "stewardship_class_ids"


class StewardshipError(ValueError):
    """A refusal with a locale key (``asp.err_<key>``)."""


def may_decide(user):
    return bool(user is not None and (user.is_admin or user.can("antimicrobial_stewardship")))


def may_see(user):
    return bool(may_decide(user) or (user is not None and user.can_access("pharmacy")))


def class_ids():
    from app.models import Setting

    raw = Setting.get(CLASS_SETTING) or ""
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def set_classes(ids):
    from app.models import Setting

    Setting.set(CLASS_SETTING, ",".join(str(int(i)) for i in sorted(set(ids))))


def add_restricted(form, user):
    generic_id = _int(form.get("generic_id"))
    rule = (form.get("rule") or "").strip()[:255]
    if not generic_id:
        raise StewardshipError("drug")
    if not rule:
        raise StewardshipError("rule")
    row = RestrictedAntimicrobial(generic_id=generic_id, rule=rule, added_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _generic_id(order):
    drug = getattr(order, "drug", None)
    return getattr(drug, "generic_id", None) if drug is not None else None


def restricted_for(order, known=None):
    if known is None:
        known = {r.generic_id: r for r in RestrictedAntimicrobial.query.filter_by(is_active=True)}
    gid = _generic_id(order)
    if gid and gid in known:
        return known[gid]
    from app.models import GenericDrug

    name = (getattr(order, "drug_name", "") or "").strip().lower()
    for g_id, row in known.items():
        g = db.session.get(GenericDrug, g_id)
        if g is not None and name and name in {(g.name_en or "").strip().lower(), (g.name_ar or "").strip().lower()}:
            return row
    return None


def is_antimicrobial(order, classes=None):
    classes = class_ids() if classes is None else classes
    drug = getattr(order, "drug", None)
    generic = getattr(drug, "generic", None) if drug is not None else None
    return bool(generic is not None and generic.class_id in classes)


def _latest(order_id, kind):
    return (StewardshipReview.query.filter_by(order_id=order_id, kind=kind)
            .order_by(StewardshipReview.at.desc()).first())


def _culture_after(order):
    """The latest culture report on this child after the order started."""
    from app.models import VisitInvestigation
    from app.models.micro import CultureResult

    return (CultureResult.query.join(VisitInvestigation, CultureResult.order_id == VisitInvestigation.id)
            .filter(VisitInvestigation.patient_id == order.patient_id,
                    CultureResult.updated_at >= order.started_at)
            .order_by(CultureResult.updated_at.desc()).first())


def board():
    """``{"awaiting": [(order, rule)], "culture": [(order, culture)], "running": [order]}``
    over running inpatient orders."""
    from app.models import MedicationOrder

    known = {r.generic_id: r for r in RestrictedAntimicrobial.query.filter_by(is_active=True)}
    classes = class_ids()
    awaiting, culture_due, running = [], [], []
    for o in MedicationOrder.query.filter(MedicationOrder.stopped_at.is_(None)).all():
        rule = restricted_for(o, known)
        anti = rule is not None or is_antimicrobial(o, classes)
        if not anti:
            continue
        running.append(o)
        if rule is not None and _latest(o.id, "approval") is None:
            awaiting.append((o, rule))
        c = _culture_after(o)
        if c is not None:
            last = _latest(o.id, "culture")
            if last is None or last.at < c.updated_at:
                culture_due.append((o, c))
    return {"awaiting": awaiting, "culture": culture_due, "running": running}


def decide(order, form, user):
    kind = form.get("kind")
    decision = form.get("decision")
    if kind not in KINDS or decision not in DECISIONS:
        raise StewardshipError("decision")
    note = (form.get("note") or "").strip()[:255] or None
    if decision != "approved" and decision != "continue" and not note:
        raise StewardshipError("note")
    row = StewardshipReview(order_id=order.id, kind=kind, decision=decision, note=note,
                            by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def consumption(start, end):
    """Days of therapy (DOT) per 1000 patient-days in ``[start, end)`` — a
    child × drug × clinic day with at least one dose given."""
    from app.models import MedicationDose, MedicationOrder
    from app.models.medication import GIVEN
    from app.utils import ipc_program
    from app.utils.clock import local_date, to_utc

    classes = class_ids()
    known = {r.generic_id: r for r in RestrictedAntimicrobial.query.filter_by(is_active=True)}
    if not classes and not known:
        return {"set": False}
    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.min.time()))
    doses = (MedicationDose.query.join(MedicationOrder, MedicationDose.order_id == MedicationOrder.id)
             .filter(MedicationDose.outcome == GIVEN, MedicationDose.at >= since,
                     MedicationDose.at < until).all())
    days, by_drug = set(), {}
    for d in doses:
        o = d.order
        if not (is_antimicrobial(o, classes) or restricted_for(o, known) is not None):
            continue
        name = (o.drug.generic.display_name("ar") if o.drug is not None and o.drug.generic is not None
                else (o.drug_name or "").strip())
        key = (o.patient_id, name, local_date(d.at))
        if key not in days:
            days.add(key)
            by_drug[name] = by_drug.get(name, 0) + 1
    pdays = ipc_program.rates(start, end)["patient_days"]
    dot = len(days)
    return {"set": True, "dot": dot, "patient_days": pdays,
            "per_1000": (dot / pdays * 1000) if pdays else None,
            "drugs": sorted(by_drug.items(), key=lambda kv: -kv[1])}


__all__ = ["CLASS_SETTING", "StewardshipError", "add_restricted", "board", "class_ids",
           "consumption", "decide", "is_antimicrobial", "may_decide", "may_see",
           "restricted_for", "set_classes"]
