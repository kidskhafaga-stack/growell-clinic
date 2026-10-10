"""Incident reports — GAHAR QPI.10, QPI.11, DAS.23 / GSR.13. The model and
the reasons are in ``app/models/incident.py``.

**The rules the records keep:**

* anybody signed in reports; ``anonymous`` leaves the reporter empty — the
  program then knows nothing about who wrote it;
* only ``incident_manage`` classifies, investigates and closes;
* closing needs the findings and the action; an adverse event that touched a
  patient needs the family told (QPI.10 evidence 5); a sentinel event needs
  the root cause analysis and the external report too (QPI.11 e, c);
* a report marked serious, or classified sentinel, is told to management at
  once (QPI.10 d) — through the bell, to whoever reviews.
"""
from datetime import date, datetime

from app.extensions import db
from app.models.incident import (AFFECTED, CATEGORIES, CLASSES, CLOSED, HARM,
                                 INVESTIGATING, NEW, NO_HARM, SENTINEL,
                                 Incident)

CAPABILITY = "incident_manage"


class IncidentError(ValueError):
    """A refusal with a key the screen can name (``incident.err_<key>``)."""


def _text(value, limit=4000):
    return (str(value or "")).strip()[:limit] or None


def may_review(user):
    return bool(user is not None and user.is_authenticated and user.can(CAPABILITY))


def next_number(now=None):
    """``INC-<year>-<n>``, counted per year."""
    year = (now or datetime.utcnow()).year
    prefix = f"INC-{year}-"
    top = 0
    for (num,) in (Incident.query.filter(Incident.number.like(prefix + "%"))
                   .with_entities(Incident.number).all()):
        tail = num[len(prefix):]
        if tail.isdigit():
            top = max(top, int(tail))
    return f"{prefix}{top + 1:04d}"


# ================================================================ report ==
def report(user, form):
    """A new report. The caller commits."""
    from app.models import Patient
    from app.models.place import Unit
    from app.utils.clock import to_utc

    raw = (form.get("occurred_at") or "").strip()
    try:
        local = datetime.fromisoformat(raw)
    except ValueError:
        raise IncidentError("need_when") from None
    when = to_utc(local)
    if when > datetime.utcnow():
        raise IncidentError("future")
    category = form.get("category")
    if category not in CATEGORIES:
        raise IncidentError("need_category")
    affected = form.get("affected")
    if affected not in AFFECTED:
        raise IncidentError("need_affected")
    what = _text(form.get("what_happened"))
    if not what:
        raise IncidentError("need_what")
    unit_raw = str(form.get("unit_id") or "").strip()
    unit = db.session.get(Unit, int(unit_raw)) if unit_raw.isdigit() else None
    area = None if unit else _text(form.get("area"), 120)
    if unit is None and not area:
        raise IncidentError("need_area")
    number = _text(form.get("patient_number"), 40)
    patient = Patient.query.filter_by(patient_number=number).first() if number else None
    if number and patient is None:
        raise IncidentError("no_patient")
    row = Incident(number=next_number(), occurred_at=when,
                   reported_by=None if form.get("anonymous") else getattr(user, "id", None),
                   unit_id=getattr(unit, "id", None), area=area, category=category,
                   affected=affected,
                   patient_id=patient.id if (patient and affected == "patient") else None,
                   what_happened=what, immediate_action=_text(form.get("immediate_action")),
                   serious=bool(form.get("serious")), status=NEW)
    db.session.add(row)
    db.session.flush()
    return row


# ================================================================ review ==
def review(row, user, form):
    """Classify, investigate, act — and close when the record is whole.

    Returns what closing still waits for (empty when it closed or was not
    asked to): what the reviewer wrote is kept either way, rather than lost
    to a refusal."""
    if row is None:
        raise IncidentError("no_incident")
    if row.status == CLOSED:
        raise IncidentError("closed")
    cls = form.get("classification")
    if cls not in CLASSES:
        raise IncidentError("need_class")
    row.classification = cls
    for field, limit in (("findings", 4000), ("root_cause", 4000), ("action", 4000),
                         ("action_owner", 160), ("family_told", 2000),
                         ("external_report", 2000)):
        value = _text(form.get(field), limit)
        if value is not None or field in form:
            setattr(row, field, value)
    raw_due = (form.get("action_due") or "").strip()
    if raw_due:
        try:
            row.action_due = date.fromisoformat(raw_due)
        except ValueError:
            raise IncidentError("bad_date") from None
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    if form.get("close"):
        missing = still_missing(row)
        if not missing:
            row.status = CLOSED
            row.closed_at = datetime.utcnow()
            return []
        row.status = INVESTIGATING
        return missing
    row.status = INVESTIGATING
    return []


def still_missing(row):
    """What closing waits for, in order."""
    out = []
    if not row.classification:
        out.append("class")
    if not (row.findings or "").strip():
        out.append("findings")
    if not (row.action or "").strip():
        out.append("action")
    if (row.affected == "patient" and row.classification in (HARM, SENTINEL)
            and not (row.family_told or "").strip()):
        out.append("family")
    if row.classification == SENTINEL:
        if not (row.root_cause or "").strip():
            out.append("rca")
        if not (row.external_report or "").strip():
            out.append("external")
    return out


def urgent(row):
    return bool(row.serious or row.classification == SENTINEL)


def open_counts():
    """For the bell: reports nobody has picked up, and the serious ones."""
    new = Incident.query.filter(Incident.status == NEW).count()
    serious = (Incident.query.filter(Incident.status != CLOSED,
                                     db.or_(Incident.serious.is_(True),
                                            Incident.classification == SENTINEL))
               .count())
    return {"new": new, "serious": serious, "attention": new + serious}


# ================================================================= board ==
def board(start, end, status=None, category=None, lang="ar"):
    """The period's reports, and beside them the medication errors and the
    equipment incidents recorded on their own screens — one list, written
    once. Each row: ``{kind, at, title, where, class, open, url_args}``."""
    from app.models import EquipmentEvent, MedicationError
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.max.time()))
    query = Incident.query.filter(Incident.occurred_at >= since, Incident.occurred_at <= until)
    if status in (NEW, INVESTIGATING, CLOSED):
        query = query.filter(Incident.status == status)
    if category in CATEGORIES:
        query = query.filter(Incident.category == category)
    incidents = query.order_by(Incident.occurred_at.desc()).all()
    rows = [{"kind": "incident", "row": r, "at": r.occurred_at} for r in incidents]
    if not status and not category:
        for e in (MedicationError.query
                  .filter(MedicationError.happened_at >= since,
                          MedicationError.happened_at <= until)
                  .order_by(MedicationError.happened_at.desc()).all()):
            rows.append({"kind": "medication", "row": e, "at": e.happened_at})
        for e in (EquipmentEvent.query
                  .filter(EquipmentEvent.kind == "incident",
                          EquipmentEvent.at >= since, EquipmentEvent.at <= until)
                  .order_by(EquipmentEvent.at.desc()).all()):
            rows.append({"kind": "equipment", "row": e, "at": e.at})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


def analysis(start, end):
    """QPI.10 (e) — the period counted by category and by classification,
    with how many are still open."""
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.max.time()))
    rows = Incident.query.filter(Incident.occurred_at >= since,
                                 Incident.occurred_at <= until).all()
    by_cat = {c: 0 for c in CATEGORIES}
    by_class = {c: 0 for c in CLASSES}
    unclassified = 0
    for r in rows:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
        if r.classification:
            by_class[r.classification] += 1
        else:
            unclassified += 1
    return {"total": len(rows), "open": sum(1 for r in rows if r.status != CLOSED),
            "by_category": [(k, v) for k, v in by_cat.items() if v],
            "by_class": list(by_class.items()), "unclassified": unclassified}


__all__ = ["CAPABILITY", "IncidentError", "analysis", "board", "next_number",
           "open_counts", "report", "review", "still_missing", "urgent",
           "may_review", "NO_HARM"]
