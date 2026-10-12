"""Notifiable diseases and outbreaks — see ``models/ipc_outbreak``.

Recording and counting only. Which diseases are notifiable is the Ministry's
list; whether a cluster is an outbreak is the team's call (IPC.18: *"in
excess of normal expectations"* — the hospital's expectation, not the
program's). :func:`clusters` lists, it never declares.
"""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.ipc_outbreak import (STEPS, DiseaseReport, Outbreak, OutbreakCase,
                                     OutbreakStep)


class OutbreakError(ValueError):
    """A refusal with a locale key (``ipco.err_<key>``)."""


def _day(raw, required=False):
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        if required:
            raise OutbreakError("date") from None
        return None


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _patient(number):
    from app.models import Patient

    number = (number or "").strip()
    row = Patient.query.filter(Patient.patient_number == number).first() if number else None
    if row is None:
        raise OutbreakError("patient")
    return row


# --------------------------------------------------------------- reports ---
def add_report(form, user):
    patient = _patient(form.get("patient_number"))
    disease = _text(form.get("disease"), 160)
    if not disease:
        raise OutbreakError("disease")
    row = DiseaseReport(patient_id=patient.id, disease=disease,
                        suspected_on=_day(form.get("suspected_on"), required=True),
                        note=_text(form.get("note")), written_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    from app.utils import notifications
    notifications.invalidate()
    return row


def mark_reported(report, form, user):
    if report.reported_on is not None:
        raise OutbreakError("already_reported")
    to = _text(form.get("reported_to"), 160)
    if not to:
        raise OutbreakError("reported_to")
    report.reported_on = _day(form.get("reported_on"), required=True)
    report.reported_to = to
    report.reference = _text(form.get("reference"), 80)
    report.reported_by = getattr(user, "id", None)
    db.session.flush()
    from app.utils import notifications
    notifications.invalidate()
    return report


def reports(limit=100):
    pending = (DiseaseReport.query.filter(DiseaseReport.reported_on.is_(None))
               .order_by(DiseaseReport.suspected_on).all())
    done = (DiseaseReport.query.filter(DiseaseReport.reported_on.isnot(None))
            .order_by(DiseaseReport.reported_on.desc(), DiseaseReport.id.desc())
            .limit(limit).all())
    return pending, done


# ------------------------------------------------------------- outbreaks ---
def open_outbreak(form, user):
    title, team = _text(form.get("title"), 160), _text(form.get("team"))
    if not title:
        raise OutbreakError("title")
    if not team:
        raise OutbreakError("team")
    row = Outbreak(title=title, agent=_text(form.get("agent"), 160),
                   unit_id=form.get("unit_id", type=int) or None,
                   opened_on=_day(form.get("opened_on"), required=True), team=team,
                   case_definition=_text(form.get("case_definition")),
                   opened_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def record_step(outbreak, form, user):
    step = form.get("step", type=int)
    if step not in STEPS:
        raise OutbreakError("step")
    note = _text(form.get("note"))
    if not note:
        raise OutbreakError("note")
    row = next((s for s in outbreak.steps if s.step == step), None)
    if row is None:
        row = OutbreakStep(step=step)
        outbreak.steps.append(row)
    row.done_on = _day(form.get("done_on"), required=True)
    row.note = note
    row.done_by = getattr(user, "id", None)
    if step == 3 and not outbreak.case_definition:
        outbreak.case_definition = note
    db.session.flush()
    return row


def add_case(outbreak, form, user):
    patient = _patient(form.get("patient_number"))
    if any(c.patient_id == patient.id for c in outbreak.cases):
        raise OutbreakError("already_case")
    outbreak.cases.append(OutbreakCase(patient_id=patient.id,
                                       onset_on=_day(form.get("onset_on")),
                                       note=_text(form.get("note"), 255),
                                       added_by=getattr(user, "id", None)))
    db.session.flush()
    return outbreak


def close_outbreak(outbreak, form, user):
    if not outbreak.is_open:
        raise OutbreakError("closed")
    conclusion, measures = _text(form.get("conclusion")), _text(form.get("measures"))
    if not conclusion or not measures:
        raise OutbreakError("close_needs")
    outbreak.conclusion, outbreak.measures = conclusion, measures
    outbreak.closed_on = _day(form.get("closed_on"), required=True)
    outbreak.closed_by = getattr(user, "id", None)
    db.session.flush()
    return outbreak


def summary(outbreak, today):
    """Ev. 4 — what is monitored: cases, days open, steps done."""
    end = outbreak.closed_on or today
    return {"cases": len(outbreak.cases), "days": (end - outbreak.opened_on).days,
            "steps": len(outbreak.steps)}


# -------------------------------------------------------------- clusters ---
def clusters(today, days=30):
    """Alert organisms and healthcare-associated infections in the last
    ``days`` grouped by unit and organism (or kind), where more than one —
    ``[{unit, label, n, last}]``, most first. A list for the team to look at;
    nothing here is called an outbreak."""
    from app.models import HaiCase, IpcAlert
    from app.utils import beds
    from app.utils.clock import to_utc

    since = today - timedelta(days=days)
    since_utc = to_utc(datetime.combine(since, datetime.min.time()))
    groups = {}
    for a in IpcAlert.query.filter(IpcAlert.raised_at >= since_utc).all():
        stay = beds.open_admission(a.patient_id)
        unit = stay.bed.unit if stay is not None and stay.bed is not None else None
        key = (unit.id if unit else None, "org", a.organism.name)
        g = groups.setdefault(key, {"unit": unit, "label": a.organism.name, "kind": "organism",
                                    "patients": set(), "last": None})
        g["patients"].add(a.patient_id)
        g["last"] = max(filter(None, [g["last"], a.raised_at.date()]))
    for c in HaiCase.query.filter(HaiCase.onset_on >= since,
                                  HaiCase.status != "ruled_out").all():
        key = (c.unit_id, "hai", c.kind)
        g = groups.setdefault(key, {"unit": c.unit, "label": c.kind, "kind": "hai",
                                    "patients": set(), "last": None})
        g["patients"].add(c.patient_id)
        g["last"] = max(filter(None, [g["last"], c.onset_on]))
    out = [dict(g, n=len(g["patients"])) for g in groups.values() if len(g["patients"]) > 1]
    return sorted(out, key=lambda g: (-g["n"], str(g["label"])))


__all__ = ["OutbreakError", "STEPS", "add_case", "add_report", "close_outbreak",
           "clusters", "mark_reported", "open_outbreak", "record_step", "reports", "summary"]
