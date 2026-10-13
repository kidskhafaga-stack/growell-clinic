"""Telemedicine — see ``models/telemedicine``."""
from datetime import date, datetime, timedelta
from statistics import median

from app.extensions import db
from app.models.telemedicine import CHANNEL, MODALITIES, OUTCOMES, TeleEncounter, TeleReview

#: (i) the hospital's eligibility criteria, (b) its platforms (one per line),
#: and the medical staff member who oversees the service (ev. 3).
CRITERIA_SETTING = "tele_criteria"
PLATFORMS_SETTING = "tele_platforms"
DIRECTOR_SETTING = "tele_director"


class TeleError(ValueError):
    """A refusal with a locale key (``tele.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _when(raw):
    from app.utils.clock import to_utc

    try:
        return to_utc(datetime.fromisoformat(str(raw or "").strip()))
    except ValueError:
        return None


def program():
    from app.models import Setting

    platforms = [p.strip() for p in (Setting.get(PLATFORMS_SETTING) or "").splitlines() if p.strip()]
    return {"criteria": (Setting.get(CRITERIA_SETTING) or "").strip(), "platforms": platforms,
            "director": (Setting.get(DIRECTOR_SETTING) or "").strip()}


def save_program(form):
    from app.models import Setting

    Setting.set(CRITERIA_SETTING, (form.get("criteria") or "").strip()[:2000])
    Setting.set(PLATFORMS_SETTING, (form.get("platforms") or "").strip()[:1000])
    Setting.set(DIRECTOR_SETTING, (form.get("director") or "").strip()[:160])


def request(form, user):
    from app.models import Patient, User

    patient = db.session.get(Patient, form.get("patient_id", type=int) or 0)
    if patient is None:
        raise TeleError("patient")
    reason = _text(form.get("reason"), 255)
    if not reason:
        raise TeleError("reason")
    modality = form.get("modality") if form.get("modality") in MODALITIES else None
    if modality is None:
        raise TeleError("modality")
    eligible = form.get("eligible")
    if eligible not in ("yes", "no"):
        raise TeleError("eligible")
    row = TeleEncounter(patient_id=patient.id, reason=reason, modality=modality,
                        eligible=eligible == "yes", by_id=getattr(user, "id", None),
                        scheduled_for=_when(form.get("scheduled_for")))
    if not row.eligible:
        row.not_eligible_note = _text(form.get("not_eligible_note"), 255)
        if not row.not_eligible_note:
            raise TeleError("not_eligible_note")
    doctor = db.session.get(User, form.get("doctor_id", type=int) or 0)
    if doctor is not None:
        row.doctor_id = doctor.id
    db.session.add(row)
    db.session.flush()
    return row


def start(row, form, user):
    """(g) refused until the identity check and both locations are written.
    Opens the visit the doctor writes on."""
    from app.models import Visit
    from app.utils.clock import local_today

    if row.state != "waiting":
        raise TeleError("not_waiting")
    identity = _text(form.get("identity_how"), 160)
    here, there = _text(form.get("doctor_location"), 160), _text(form.get("patient_location"), 160)
    if not identity:
        raise TeleError("identity")
    if not there:
        raise TeleError("patient_location")
    if not here:
        raise TeleError("doctor_location")
    doctor_id = row.doctor_id or getattr(user, "id", None)
    row.identity_how, row.patient_location, row.doctor_location = identity, there, here
    row.platform = _text(form.get("platform"), 80)
    row.doctor_id = doctor_id
    row.started_at = datetime.utcnow()
    visit = Visit(patient_id=row.patient_id, doctor_id=doctor_id, visit_date=local_today(),
                  channel=CHANNEL, chief_complaint=row.reason)
    db.session.add(visit)
    db.session.flush()
    row.visit_id = visit.id
    db.session.flush()
    return row


def end(row, form):
    if row.state != "running":
        raise TeleError("not_running")
    outcome = form.get("outcome") if form.get("outcome") in OUTCOMES else None
    if outcome is None:
        raise TeleError("outcome")
    row.outcome, row.note, row.ended_at = outcome, _text(form.get("note")), datetime.utcnow()
    db.session.flush()
    return row


def cancel(row, form):
    if row.state not in ("waiting",):
        raise TeleError("not_waiting")
    row.cancelled_at = datetime.utcnow()
    row.note = _text(form.get("note")) or row.note
    db.session.flush()
    return row


def board():
    rows = (TeleEncounter.query.filter(TeleEncounter.cancelled_at.is_(None), TeleEncounter.ended_at.is_(None),
                                       TeleEncounter.eligible.is_(True))
            .order_by(TeleEncounter.scheduled_for.is_(None), TeleEncounter.scheduled_for,
                      TeleEncounter.requested_at).all())
    recent = (TeleEncounter.query.filter(db.or_(TeleEncounter.ended_at.isnot(None),
                                                TeleEncounter.eligible.is_(False),
                                                TeleEncounter.cancelled_at.isnot(None)))
              .order_by(TeleEncounter.requested_at.desc()).limit(30).all())
    return {"open": rows, "recent": recent}


def evaluation(start, end):
    """(l) the period's indicators — access (how many asked, how many were
    eligible), effectiveness (how many needed the child in person after
    all), and the length of an encounter."""
    rows = (TeleEncounter.query.filter(
        TeleEncounter.requested_at >= datetime.combine(start, datetime.min.time()),
        TeleEncounter.requested_at < datetime.combine(end + timedelta(days=1), datetime.min.time())).all())
    done = [r for r in rows if r.ended_at]
    lengths = [r.minutes for r in done if r.minutes is not None]
    return {"requested": len(rows), "not_eligible": sum(1 for r in rows if not r.eligible),
            "done": len(done), "cancelled": sum(1 for r in rows if r.cancelled_at),
            "by_modality": {m: sum(1 for r in done if r.modality == m) for m in MODALITIES},
            "by_outcome": {o: sum(1 for r in done if r.outcome == o) for o in OUTCOMES},
            "came_in": sum(1 for r in done if r.outcome in ("in_person", "emergency")),
            "median_minutes": median(lengths) if lengths else None}


def add_review(form, user):
    try:
        start, end = date.fromisoformat(form.get("period_from") or ""), date.fromisoformat(form.get("period_to") or "")
    except ValueError:
        raise TeleError("period") from None
    if end < start:
        raise TeleError("period")
    text = _text(form.get("text"))
    if not text:
        raise TeleError("review_text")
    row = TeleReview(period_from=start, period_to=end, text=text, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def reviews():
    return TeleReview.query.order_by(TeleReview.period_to.desc()).limit(20).all()


__all__ = ["CRITERIA_SETTING", "DIRECTOR_SETTING", "PLATFORMS_SETTING", "TeleError", "add_review", "board",
           "cancel", "end", "evaluation", "program", "request", "reviews", "save_program", "start"]
