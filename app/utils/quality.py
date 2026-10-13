"""The quality programme — see ``models/quality``."""
from datetime import date, datetime

from app.extensions import db
from app.models.quality import (CLINICAL_AREAS, MANAGERIAL_AREAS, MEASURE_KINDS, RISK_CATEGORIES,
                                ImprovementProject, MeasureValue, PerformanceMeasure, ProactiveAssessment,
                                QualityDecision, QualityMeeting, QualitySelfEvaluation, RiskItem,
                                RiskReport)


class QualityError(ValueError):
    """A refusal with a locale key (``qual.err_<key>``)."""


def _text(raw, limit=None):
    s = (raw or "").strip()
    return (s[:limit] if limit else s) or None


def _float(raw):
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


# ============================================================== measures ==
def save_measure(form):
    kind = form.get("kind")
    if kind not in MEASURE_KINDS:
        raise QualityError("kind")
    area = form.get("area")
    if area not in (CLINICAL_AREAS if kind == "clinical" else MANAGERIAL_AREAS):
        raise QualityError("area")
    fields = {k: _text(form.get(k)) for k in ("name", "definition", "data_source", "frequency", "numerator")}
    if not all(fields.values()):
        raise QualityError("sheet")
    hb = form.get("higher_better")
    row = PerformanceMeasure(kind=kind, area=area, sampling=_text(form.get("sampling"), 255),
                             denominator=_text(form.get("denominator"), 255), per=_int(form.get("per")),
                             method=_text(form.get("method")), target=_float(form.get("target")),
                             higher_better=None if hb not in ("1", "0") else hb == "1",
                             owner=_text(form.get("owner"), 120), **fields)
    db.session.add(row)
    db.session.flush()
    return row


def add_value(measure, form, user):
    period = _text(form.get("period"), 10)
    num = _float(form.get("numerator"))
    if not period or num is None:
        raise QualityError("value")
    den = _float(form.get("denominator"))
    if measure.denominator and not den:
        raise QualityError("denominator")
    row = MeasureValue(measure_id=measure.id, period=period, numerator=num, denominator=den,
                       note=_text(form.get("note"), 255), by_id=getattr(user, "id", None),
                       validated_by=getattr(user, "id", None) if form.get("validated") == "1" else None)
    db.session.add(row)
    db.session.flush()
    return row


def off_target(measure, value):
    """``True``/``False`` against the hospital's target, ``None`` without one."""
    if value is None or measure.target is None or measure.higher_better is None:
        return None
    return value < measure.target if measure.higher_better else value > measure.target


def trend(measure, width=260, height=60):
    """SVG polyline points for the values over time — one scale, the
    target drawn on it when set."""
    vals = [(v.period, v.value) for v in measure.values if v.value is not None]
    if len(vals) < 2:
        return None
    nums = [v for _, v in vals] + ([measure.target] if measure.target is not None else [])
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    step = (width - 20) / (len(vals) - 1)

    def y(v):
        return round(height - 8 - (v - lo) / span * (height - 16), 1)

    pts = " ".join(f"{round(10 + i * step, 1)},{y(v)}" for i, (_, v) in enumerate(vals))
    return {"points": pts, "target_y": y(measure.target) if measure.target is not None else None,
            "w": width, "h": height, "last": vals[-1]}


# ================================================================= risks ==
def save_risk(form):
    title, owner = _text(form.get("title"), 200), _text(form.get("owner"), 120)
    category = form.get("category")
    if not title or not owner or category not in RISK_CATEGORIES:
        raise QualityError("risk")
    high = form.get("high") == "1"
    mitigation = _text(form.get("mitigation"))
    if high and not mitigation:
        raise QualityError("mitigation")
    row = RiskItem(title=title, category=category, description=_text(form.get("description")),
                   rating=_text(form.get("rating"), 60), high=high, owner=owner, mitigation=mitigation,
                   review_on=_day(form.get("review_on")))
    db.session.add(row)
    db.session.flush()
    return row


def close_risk(row):
    row.closed_at = datetime.utcnow()
    db.session.flush()
    return row


def add_proactive(form, user):
    year, process, tool, findings = (_int(form.get("year")), _text(form.get("process"), 200),
                                     _text(form.get("tool"), 60), _text(form.get("findings")))
    if not (year and process and tool and findings):
        raise QualityError("proactive")
    row = ProactiveAssessment(year=year, process=process, tool=tool, findings=findings,
                              actions=_text(form.get("actions")), by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def add_risk_report(form):
    quarter, sent = _text(form.get("quarter"), 7), _text(form.get("sent_to"), 160)
    if not quarter or not sent:
        raise QualityError("report")
    row = RiskReport(quarter=quarter, sent_to=sent, note=_text(form.get("note"), 255))
    db.session.add(row)
    db.session.flush()
    return row


def risk_board(today=None):
    today = today or date.today()
    open_ = (RiskItem.query.filter(RiskItem.closed_at.is_(None))
             .order_by(RiskItem.high.desc(), RiskItem.review_on.is_(None), RiskItem.review_on).all())
    year = today.year
    return {"open": open_, "review_due": [r for r in open_ if r.review_on and r.review_on < today],
            "proactive_this_year": ProactiveAssessment.query.filter_by(year=year).all(),
            "proactive": ProactiveAssessment.query.order_by(ProactiveAssessment.year.desc()).all(),
            "reports": RiskReport.query.order_by(RiskReport.quarter.desc()).all(), "year": year}


# ============================================================== projects ==
def save_project(form):
    title, problem, aim = _text(form.get("title"), 200), _text(form.get("problem")), _text(form.get("aim"))
    if not (title and problem and aim):
        raise QualityError("project")
    row = ImprovementProject(title=title, problem=problem, aim=aim, method=_text(form.get("method"), 80),
                             utilization=form.get("utilization") == "1",
                             measure_id=_int(form.get("measure_id")),
                             started_on=_day(form.get("started_on")) or date.today())
    db.session.add(row)
    db.session.flush()
    return row


def update_project(row, form):
    for k in ("tests", "result"):
        v = _text(form.get(k))
        if v is not None:
            setattr(row, k, v)
    if form.get("implemented") == "1":
        if not row.result:
            raise QualityError("result")
        row.implemented = True
    if form.get("close") == "1":
        if not row.result:
            raise QualityError("result")
        row.closed_on = date.today()
    db.session.flush()
    return row


def projects_board(today=None):
    today = today or date.today()
    rows = ImprovementProject.query.order_by(ImprovementProject.started_on.desc()).all()
    return {"rows": rows, "utilization_this_year": any(
        p.utilization and p.started_on.year == today.year for p in rows), "year": today.year}


# ============================================================= committee ==
def save_meeting(form, user):
    from app.models.quality import COMMITTEES

    committee = form.get("committee") if form.get("committee") in COMMITTEES else "quality"
    held = _day(form.get("held_on"))
    attendees, minutes = _text(form.get("attendees")), _text(form.get("minutes"))
    if held is None or not attendees or not minutes:
        raise QualityError("meeting")
    row = QualityMeeting(held_on=held, attendees=attendees, minutes=minutes, committee=committee,
                         circulated_to=_text(form.get("circulated_to"), 255),
                         written_by=getattr(user, "id", None))
    for i, text in enumerate(form.getlist("decision")):
        text = _text(text)
        if not text:
            continue
        owners, dues = form.getlist("owner"), form.getlist("due_on")
        owner = _text(owners[i] if i < len(owners) else None, 120)
        if not owner:
            raise QualityError("owner")
        row.decisions.append(QualityDecision(text=text, owner=owner,
                                             due_on=_day(dues[i] if i < len(dues) else None)))
    db.session.add(row)
    db.session.flush()
    return row


def close_decision(row, note):
    note = _text(note, 255)
    if not note:
        raise QualityError("note")
    row.done_at, row.done_note = datetime.utcnow(), note
    db.session.flush()
    return row


def save_evaluation(year, text, user):
    text = _text(text)
    if not year or not text:
        raise QualityError("evaluation")
    row = QualitySelfEvaluation.query.filter_by(year=year).first() or QualitySelfEvaluation(year=year)
    row.text, row.by_id, row.at = text, getattr(user, "id", None), datetime.utcnow()
    db.session.add(row)
    db.session.flush()
    return row


#: PCC.01 ev. 2 — *"The committee meets at least quarterly"*: the
#: standard's own interval, in days, for the patient-centred committee.
QUARTER_DAYS = 92


def committee_board(committee="quality", today=None):
    today = today or date.today()
    meetings = (QualityMeeting.query.filter_by(committee=committee)
                .order_by(QualityMeeting.held_on.desc()).all())
    last = meetings[0].held_on if meetings else None
    return {"meetings": meetings, "committee": committee,
            "open": (QualityDecision.query.join(QualityMeeting)
                     .filter(QualityDecision.done_at.is_(None), QualityMeeting.committee == committee)
                     .order_by(QualityDecision.due_on.is_(None), QualityDecision.due_on).all()),
            "evaluations": {e.year: e for e in QualitySelfEvaluation.query.all()},
            "last": last,
            "quarter_late": committee == "patient" and (last is None or (today - last).days > QUARTER_DAYS)}


__all__ = ["QualityError", "add_proactive", "add_risk_report", "add_value", "close_decision",
           "close_risk", "committee_board", "off_target", "projects_board", "risk_board",
           "save_evaluation", "save_measure", "save_meeting", "save_project", "save_risk", "trend",
           "update_project"]
