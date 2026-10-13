"""Special care programmes — see ``models/care_program``."""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.care_program import (MARKERS, PROGRAMS, RESULTS, ProgramEnrollment, ProgramSession,
                                     ViralMarker)

#: The hospital's interval between dialysis viral-marker panels, in days.
MARKER_DAYS_SETTING = "dialysis_marker_days"


class ProgramError(ValueError):
    """A refusal with a locale key (``prog.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def enroll(form, user):
    from app.models import Patient

    program = form.get("program")
    if program not in PROGRAMS:
        raise ProgramError("program")
    patient = db.session.get(Patient, _int(form.get("patient_id")) or 0)
    if patient is None:
        raise ProgramError("patient")
    plan = _text(form.get("plan"))
    if not plan:
        raise ProgramError("plan")
    if ProgramEnrollment.query.filter_by(patient_id=patient.id, program=program, ended_on=None).first():
        raise ProgramError("already")
    row = ProgramEnrollment(patient_id=patient.id, program=program,
                            started_on=_day(form.get("started_on")) or date.today(), plan=plan,
                            cycles=_int(form.get("cycles")) if program == "chemo" else None,
                            by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def record_session(enr, form, user):
    if not enr.is_active:
        raise ProgramError("ended")
    pre = _text(form.get("pre_check"))
    if not pre:
        raise ProgramError("pre_check")
    cleared = form.get("cleared")
    if cleared not in ("yes", "no"):
        raise ProgramError("cleared")
    complications = _text(form.get("complications"), 255)
    action = _text(form.get("action"), 255)
    if (complications or cleared == "no") and not action:
        raise ProgramError("action")
    row = ProgramSession(enrollment_id=enr.id, pre_check=pre, cleared=cleared == "yes",
                         cycle_no=_int(form.get("cycle_no")) if enr.program == "chemo" else None,
                         during=_text(form.get("during")), complications=complications, action=action,
                         progress=_text(form.get("progress"), 255), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def educate(enr, form):
    whom = _text(form.get("educated_whom"), 120)
    if not whom:
        raise ProgramError("whom")
    enr.educated_at, enr.educated_whom = datetime.utcnow(), whom
    db.session.flush()
    return enr


def end(enr, form):
    if enr.program == "rehab" and not _text(form.get("discharge_plan")):
        raise ProgramError("discharge_plan")
    enr.discharge_plan = _text(form.get("discharge_plan"))
    enr.ended_on = date.today()
    db.session.flush()
    return enr


def marker_days():
    from app.models import Setting

    return _int((Setting.get(MARKER_DAYS_SETTING) or "").strip())


def add_markers(patient_id, form, user):
    values = {m: form.get(m) if form.get(m) in RESULTS else None for m in MARKERS}
    if not any(values.values()):
        raise ProgramError("markers")
    row = ViralMarker(patient_id=patient_id, taken_on=_day(form.get("on")) or date.today(),
                      note=_text(form.get("note"), 255), by_id=getattr(user, "id", None), **values)
    db.session.add(row)
    db.session.flush()
    return row


def markers_for(patient_id):
    return ViralMarker.query.filter_by(patient_id=patient_id).order_by(ViralMarker.taken_on).all()


def seroconverted(rows):
    """The markers that went from negative to positive — ``[marker]``."""
    seen_neg, out = set(), []
    for r in rows:
        for m in MARKERS:
            v = getattr(r, m)
            if v == "negative":
                seen_neg.add(m)
            elif v == "positive" and m in seen_neg and m not in out:
                out.append(m)
    return out


def markers_due(patient_id, today=None):
    """``True`` past the hospital's interval, ``None`` while it is unset."""
    days = marker_days()
    if not days:
        return None
    rows = markers_for(patient_id)
    last = rows[-1].taken_on if rows else None
    today = today or date.today()
    return last is None or last + timedelta(days=days) < today


def board(program):
    rows = (ProgramEnrollment.query.filter_by(program=program, ended_on=None)
            .order_by(ProgramEnrollment.started_on.desc()).all())
    out = []
    for e in rows:
        item = {"enr": e, "last": e.sessions.first()}
        if program == "dialysis":
            ms = markers_for(e.patient_id)
            item.update(due=markers_due(e.patient_id), sero=seroconverted(ms))
        out.append(item)
    return out


__all__ = ["MARKER_DAYS_SETTING", "ProgramError", "add_markers", "board", "educate", "end", "enroll",
           "marker_days", "markers_due", "markers_for", "record_session", "seroconverted"]
