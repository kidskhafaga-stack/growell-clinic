"""The staff file — see ``models/staff_file``."""
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.staff_file import (CREDENTIAL_KINDS, EVALUATION_KINDS, ORIENTATION_LEVELS,
                                   StaffCredential, StaffEducation, StaffEvaluation, StaffJob,
                                   StaffOrientation)

#: WFM.09 ev. 1 / WFM.13 ev. 1 — *"at least annually"*.
EVALUATION_EVERY_DAYS = 365


class StaffFileError(ValueError):
    """A refusal with a locale key (``sfile.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _float(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def add_credential(user, form):
    kind, title = form.get("kind"), _text(form.get("title"), 160)
    if kind not in CREDENTIAL_KINDS or not title:
        raise StaffFileError("credential")
    row = StaffCredential(user_id=user.id, kind=kind, title=title, number=_text(form.get("number"), 80),
                          issuer=_text(form.get("issuer"), 160), issued_on=_day(form.get("issued_on")),
                          expires_on=_day(form.get("expires_on")))
    db.session.add(row)
    db.session.flush()
    return row


def verify(cred, form, by):
    source = _text(form.get("source"), 255)
    if not source:
        raise StaffFileError("source")
    cred.verified_at, cred.verified_by, cred.verification_source = datetime.utcnow(), getattr(by, "id", None), source
    db.session.flush()
    return cred


def add_job(user, form):
    title, started = _text(form.get("title"), 120), _day(form.get("started_on"))
    if not title or started is None:
        raise StaffFileError("job")
    row = StaffJob(user_id=user.id, title=title, department=_text(form.get("department"), 120),
                   started_on=started, ended_on=_day(form.get("ended_on")),
                   job_description=_text(form.get("job_description")))
    db.session.add(row)
    db.session.flush()
    return row


def jd_signed(job, form):
    if not job.job_description:
        raise StaffFileError("no_jd")
    job.jd_signed_on = _day(form.get("signed_on")) or date.today()
    db.session.flush()
    return job


def add_orientation(user, form):
    level, done = form.get("level"), _day(form.get("completed_on"))
    if level not in ORIENTATION_LEVELS or done is None:
        raise StaffFileError("orientation")
    row = StaffOrientation(user_id=user.id, level=level, completed_on=done, note=_text(form.get("note"), 255))
    db.session.add(row)
    db.session.flush()
    return row


def add_education(user, form):
    title, on = _text(form.get("title"), 200), _day(form.get("on"))
    if not title or on is None:
        raise StaffFileError("education")
    row = StaffEducation(user_id=user.id, title=title, on=on, hours=_float(form.get("hours")),
                         provider=_text(form.get("provider"), 160))
    db.session.add(row)
    db.session.flush()
    return row


def add_evaluation(user, form):
    kind, on = form.get("kind"), _day(form.get("on"))
    evaluator, result = _text(form.get("evaluator"), 120), _text(form.get("result"))
    if kind not in EVALUATION_KINDS or on is None or not evaluator or not result:
        raise StaffFileError("evaluation")
    row = StaffEvaluation(user_id=user.id, kind=kind, on=on, evaluator=evaluator, result=result,
                          feedback=_text(form.get("feedback")), actions=_text(form.get("actions")))
    db.session.add(row)
    db.session.flush()
    return row


def file_for(user):
    q = lambda model, order: model.query.filter_by(user_id=user.id).order_by(order).all()  # noqa: E731
    return {"credentials": q(StaffCredential, StaffCredential.expires_on),
            "jobs": q(StaffJob, StaffJob.started_on.desc()),
            "orientation": {o.level: o for o in q(StaffOrientation, StaffOrientation.completed_on)},
            "education": q(StaffEducation, StaffEducation.on.desc()),
            "evaluations": q(StaffEvaluation, StaffEvaluation.on.desc())}


def gaps(user, today=None, data=None):
    """What this file is missing — ``[key]``, in the standard's order."""
    today = today or date.today()
    data = data or file_for(user)
    out = []
    if not data["credentials"]:
        out.append("no_credentials")
    if any(c.verified_at is None for c in data["credentials"]):
        out.append("unverified")
    if any(c.expires_on and c.expires_on < today for c in data["credentials"]):
        out.append("expired")
    current = [j for j in data["jobs"] if j.ended_on is None]
    if not current or not current[0].job_description:
        out.append("no_jd")
    elif not current[0].jd_signed_on:
        out.append("jd_unsigned")
    if any(level not in data["orientation"] for level in ORIENTATION_LEVELS):
        out.append("orientation")
    annual = [e for e in data["evaluations"] if e.kind in ("annual", "oppe")]
    if not annual or annual[0].on + timedelta(days=EVALUATION_EVERY_DAYS) < today:
        out.append("evaluation_due")
    return out


def board(users, today=None):
    return [(u, gaps(u, today)) for u in users]


__all__ = ["EVALUATION_EVERY_DAYS", "StaffFileError", "add_credential", "add_education",
           "add_evaluation", "add_job", "add_orientation", "board", "file_for", "gaps", "jd_signed",
           "verify"]
