"""Surveillance, care bundles and the committee — see ``models/ipc_program``.

Everything here is counting and recording. No definition of an infection, no
bundle element and no acceptable rate is the program's: the hospital's
committee sets the criteria (IPC.03 a), writes the bundles (IPC.11) and
reads the rates.
"""
import json
from datetime import date, datetime, timedelta

from app.extensions import db
from app.models.ipc_program import (ANSWERS, BUNDLE_SCOPES, DEVICE_LINES, HAI_KINDS,
                                    HAI_STATUSES, BundleCheck, BundleElement,
                                    CareBundle, HaiCase, IpcDecision, IpcMeeting)


class ProgramError(ValueError):
    """A refusal with a locale key (``ipcp.err_<key>``)."""


def _day(raw, required=False):
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        if required:
            raise ProgramError("date") from None
        return None


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def may_check(user):
    """A bundle check is the ward's: whoever works the beds, or the team."""
    from app.utils import ipc

    return bool(ipc.may_review(user) or (user is not None and user.can_access("beds")))


# ---------------------------------------------------------- surveillance ---
def report_case(form, user):
    from app.models import Admission, Line, Patient

    number = (form.get("patient_number") or "").strip()
    patient = Patient.query.filter(Patient.patient_number == number).first() if number else None
    if patient is None:
        raise ProgramError("patient")
    kind = form.get("kind")
    if kind not in HAI_KINDS:
        raise ProgramError("kind")
    if kind == "other" and not _text(form.get("kind_note")):
        raise ProgramError("kind_note")
    onset = _day(form.get("onset_on"), required=True)
    # The stay and the line it is counted against are the ones the child was
    # in on the day it began — found, not typed.
    # The onset is the clinic's day; the times are stored in UTC.
    from app.utils.clock import to_utc

    day_start = to_utc(datetime.combine(onset, datetime.min.time()))
    day_end = to_utc(datetime.combine(onset + timedelta(days=1), datetime.min.time()))
    stay = (Admission.query.filter(Admission.patient_id == patient.id,
                                   Admission.admitted_at < day_end,
                                   db.or_(Admission.discharged_at.is_(None),
                                          Admission.discharged_at >= day_start))
            .order_by(Admission.admitted_at.desc()).first())
    line = None
    if kind in DEVICE_LINES:
        line = (Line.query.filter(Line.patient_id == patient.id,
                                  Line.kind.in_(DEVICE_LINES[kind]),
                                  Line.inserted_at < day_end,
                                  db.or_(Line.removed_at.is_(None),
                                         Line.removed_at >= day_start))
                .order_by(Line.inserted_at.desc()).first())
    unit_id = None
    if stay is not None and stay.bed is not None and stay.bed.unit is not None:
        unit_id = stay.bed.unit.id
    row = HaiCase(patient_id=patient.id, admission_id=stay.id if stay else None,
                  line_id=line.id if line else None, unit_id=unit_id, kind=kind,
                  kind_note=_text(form.get("kind_note"), 120), onset_on=onset,
                  organism=_text(form.get("organism"), 160),
                  criteria=_text(form.get("criteria")),
                  reported_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def decide_case(case, form, user):
    status = form.get("status")
    if status not in ("confirmed", "ruled_out"):
        raise ProgramError("status")
    if not _text(form.get("note")):
        raise ProgramError("note")
    case.status = status
    case.decision_note = _text(form.get("note"))
    case.decided_by = getattr(user, "id", None)
    case.decided_at = datetime.utcnow()
    db.session.flush()
    return case


def _overlap_days(start, end, since, until):
    """Days of ``[start, end)`` inside ``[since, until)``, fractional."""
    lo, hi = max(start, since), min(end, until)
    return max(0.0, (hi - lo).total_seconds() / 86400.0)


def quarter_bounds(label):
    """``"2026-Q3"`` → (date(2026,7,1), date(2026,10,1)) or None."""
    try:
        year, q = label.split("-Q")
        year, q = int(year), int(q)
        if q not in (1, 2, 3, 4):
            return None
    except (AttributeError, ValueError):
        return None
    start = date(year, 3 * (q - 1) + 1, 1)
    end = date(year + 1, 1, 1) if q == 4 else date(year, 3 * q + 1, 1)
    return start, end


def quarter_of(day):
    return f"{day.year}-Q{(day.month - 1) // 3 + 1}"


def rates(start, end):
    """``{kinds: [{kind, cases, denominator, unit, rate}], patient_days, open}``
    for confirmed cases with onset in ``[start, end)``.

    Device-associated kinds are counted per 1000 device-days of the lines
    they name (`DEVICE_LINES`); the others per 1000 patient-days. Arithmetic
    only — no benchmark, no verdict.
    """
    from app.models import Admission, Line

    from app.utils.clock import to_utc

    # The quarter is in the clinic's days; the stays and lines are in UTC.
    since = to_utc(datetime.combine(start, datetime.min.time()))
    until = to_utc(datetime.combine(end, datetime.min.time()))
    now = datetime.utcnow()
    stays = (Admission.query.filter(Admission.admitted_at < until,
                                    db.or_(Admission.discharged_at.is_(None),
                                           Admission.discharged_at > since)).all())
    patient_days = sum(_overlap_days(a.admitted_at, a.discharged_at or now, since, until)
                       for a in stays)
    device_days = {}
    for kind, line_kinds in DEVICE_LINES.items():
        lines = (Line.query.filter(Line.kind.in_(line_kinds), Line.inserted_at < until,
                                   db.or_(Line.removed_at.is_(None), Line.removed_at > since))
                 .all())
        device_days[kind] = sum(_overlap_days(ln.inserted_at, ln.removed_at or now, since, until)
                                for ln in lines)
    counts = dict(db.session.query(HaiCase.kind, db.func.count(HaiCase.id))
                  .filter(HaiCase.status == "confirmed", HaiCase.onset_on >= start,
                          HaiCase.onset_on < end)
                  .group_by(HaiCase.kind).all())
    out = []
    for kind in HAI_KINDS:
        n = counts.get(kind, 0)
        if kind in device_days:
            denom, unit = device_days[kind], "device_days"
        else:
            denom, unit = patient_days, "patient_days"
        out.append({"kind": kind, "cases": n, "denominator": round(denom, 1), "unit": unit,
                    "rate": (n / denom * 1000) if denom else None})
    suspected = HaiCase.query.filter(HaiCase.status == "suspected").count()
    return {"kinds": out, "patient_days": round(patient_days, 1), "suspected": suspected}


def cases(start, end):
    return (HaiCase.query.filter(HaiCase.onset_on >= start, HaiCase.onset_on < end)
            .order_by(HaiCase.onset_on.desc(), HaiCase.id.desc()).all())


# --------------------------------------------------------------- bundles ---
def save_bundle(form, bundle=None):
    from app.models.line import KINDS as LINE_KINDS

    name = _text(form.get("name"), 160)
    if not name:
        raise ProgramError("name")
    kind = form.get("kind")
    if kind not in HAI_KINDS:
        raise ProgramError("kind")
    scope = form.get("scope") or "line"
    if scope not in BUNDLE_SCOPES:
        raise ProgramError("scope")
    kinds = [k for k in form.getlist("line_kinds") if k in LINE_KINDS]
    if scope == "line" and not kinds:
        raise ProgramError("line_kinds")
    elements = [ln.strip()[:255] for ln in (form.get("elements") or "").splitlines() if ln.strip()]
    if bundle is None:
        if not elements:
            raise ProgramError("elements")
        bundle = CareBundle()
        db.session.add(bundle)
    bundle.name, bundle.kind, bundle.scope = name, kind, scope
    bundle.line_kinds = ",".join(kinds) if scope == "line" else None
    start = len(bundle.elements)
    for i, text in enumerate(elements):
        bundle.elements.append(BundleElement(text=text, sort_order=start + i))
    db.session.flush()
    return bundle


def active_elements(bundle):
    return [e for e in bundle.elements if e.is_active]


def due_today(today):
    """``[(bundle, target, checked_today)]`` — each active bundle against each
    open line of its kinds (line bundles) or each open stay (stay bundles)."""
    from app.models import Admission, Line

    out = []
    bundles = CareBundle.query.filter_by(is_active=True).order_by(CareBundle.name).all()
    if not bundles:
        return out
    done = {(c.bundle_id, c.line_id, c.admission_id) for c in
            BundleCheck.query.filter(BundleCheck.checked_on == today).all()}
    open_stays = Admission.query.filter(Admission.discharged_at.is_(None)).all()
    for b in bundles:
        if b.scope == "line":
            lines = (Line.query.filter(Line.kind.in_(b.kinds or ["-"]), Line.removed_at.is_(None))
                     .order_by(Line.inserted_at).all())
            for ln in lines:
                out.append((b, {"line": ln, "admission": None, "patient": ln.patient},
                            (b.id, ln.id, None) in done))
        else:
            for a in open_stays:
                out.append((b, {"line": None, "admission": a, "patient": a.patient},
                            (b.id, None, a.id) in done))
    return out


def record_check(bundle, form, user, today):
    from app.models import Admission, Line

    line = db.session.get(Line, form.get("line_id", type=int) or 0)
    stay = db.session.get(Admission, form.get("admission_id", type=int) or 0)
    if bundle.scope == "line":
        if line is None or line.kind not in bundle.kinds:
            raise ProgramError("target")
        patient_id, stay_id = line.patient_id, line.admission_id
    else:
        if stay is None:
            raise ProgramError("target")
        patient_id, stay_id = stay.patient_id, stay.id
    answers = {}
    for e in active_elements(bundle):
        a = form.get(f"e_{e.id}")
        if a not in ANSWERS:
            raise ProgramError("unanswered")
        answers[str(e.id)] = a
    if not answers:
        raise ProgramError("elements")
    row = BundleCheck(bundle_id=bundle.id, patient_id=patient_id, admission_id=stay_id,
                      line_id=line.id if bundle.scope == "line" else None,
                      checked_on=today, answers=json.dumps(answers),
                      all_met=all(a in ("yes", "na") for a in answers.values()),
                      note=_text(form.get("note"), 255), checked_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def compliance(start, end):
    """``[{bundle, checks, met, pct}]`` — all or none."""
    rows = (db.session.query(BundleCheck.bundle_id, db.func.count(BundleCheck.id),
                             db.func.sum(db.case((BundleCheck.all_met.is_(True), 1), else_=0)))
            .filter(BundleCheck.checked_on >= start, BundleCheck.checked_on < end)
            .group_by(BundleCheck.bundle_id).all())
    by = {bid: (n, int(met or 0)) for bid, n, met in rows}
    out = []
    for b in CareBundle.query.order_by(CareBundle.name).all():
        n, met = by.get(b.id, (0, 0))
        out.append({"bundle": b, "checks": n, "met": met,
                    "pct": (met / n * 100) if n else None})
    return out


# -------------------------------------------------------------- committee ---
def save_meeting(form, user):
    held = _day(form.get("held_on"), required=True)
    attendees, minutes = _text(form.get("attendees")), _text(form.get("minutes"))
    if not attendees or not minutes:
        raise ProgramError("minutes")
    quarter = _text(form.get("surveillance_quarter"), 7)
    if quarter and quarter_bounds(quarter) is None:
        raise ProgramError("quarter")
    row = IpcMeeting(held_on=held, attendees=attendees, minutes=minutes,
                     surveillance_quarter=quarter, written_by=getattr(user, "id", None))
    db.session.add(row)
    texts = form.getlist("decision")
    owners = form.getlist("owner")
    dues = form.getlist("due_on")
    for i, text in enumerate(texts):
        text = (text or "").strip()
        if not text:
            continue
        owner = (owners[i] if i < len(owners) else "").strip()
        if not owner:
            raise ProgramError("owner")
        row.decisions.append(IpcDecision(text=text, owner=owner[:120],
                                         due_on=_day(dues[i] if i < len(dues) else None)))
    db.session.flush()
    return row


def close_decision(decision, form, user):
    if decision.done_at is not None:
        raise ProgramError("already_done")
    decision.done_at = datetime.utcnow()
    decision.done_by = getattr(user, "id", None)
    decision.done_note = _text(form.get("note"), 255)
    db.session.flush()
    return decision


def open_decisions():
    return (IpcDecision.query.filter(IpcDecision.done_at.is_(None))
            .order_by(IpcDecision.due_on.is_(None), IpcDecision.due_on, IpcDecision.id).all())


def months_without_meeting(today, back=6):
    """The last ``back`` whole months (and this one, once it is over) with no
    meeting — IPC.03 asks for one at least monthly."""
    held = {(m.held_on.year, m.held_on.month) for m in IpcMeeting.query.all()}
    out = []
    y, mth = today.year, today.month
    for _ in range(back):
        mth -= 1
        if mth == 0:
            y, mth = y - 1, 12
        if (y, mth) not in held:
            out.append(f"{y}-{mth:02d}")
    return out


def unreviewed_quarters(today, back=4):
    """Finished quarters whose surveillance report no meeting has reviewed."""
    reviewed = {m.surveillance_quarter for m in IpcMeeting.query.all() if m.surveillance_quarter}
    out, day = [], today
    for _ in range(back):
        start, _end = quarter_bounds(quarter_of(day))
        day = start - timedelta(days=1)
        q = quarter_of(day)
        if q not in reviewed:
            out.append(q)
    return out


__all__ = ["ProgramError", "cases", "close_decision", "compliance", "decide_case",
           "due_today", "may_check", "months_without_meeting", "open_decisions",
           "quarter_bounds", "quarter_of", "rates", "record_check", "report_case",
           "save_bundle", "save_meeting", "unreviewed_quarters", "HAI_KINDS",
           "HAI_STATUSES"]
