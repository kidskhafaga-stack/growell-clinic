"""How the hospital is governed — GAHAR OGM.01, 03, 05, 10, 13, 15 and
EFS.02 ev. 5. Models in ``app/models/governance.py``.

**The rules the records keep:**

* every committee OGM.05 names (and the patient-centred, ethics and
  governing-body ones) is listed whether or not it exists yet; a committee
  is late only against the meeting interval its own terms of reference set
  — none written, none called late;
* the governing body hears every quarter (OGM.03 ev. 3, EFS.02 ev. 5); a
  quarter gone by with no report is said out loud, and a report waits for
  its feedback (OGM.03 ev. 4);
* an ethical issue is overdue past the date the hospital set for it;
* a contracted service and a supplier are each evaluated at least once a
  year — the standard's figure (OGM.13 ev. 5, OGM.10 ev. 4).
"""
from datetime import timedelta

from app.extensions import db
from app.models.governance import (CHARTER_KEYS, CONTRACT_DECISIONS, ETHICS_KINDS, REPORT_KINDS,
                                   REQUIRED_COMMITTEES, SERVICE_KINDS, SUPPLIER_DECISIONS,
                                   CommitteeCharter, CommitteeReview, ContractedService,
                                   ContractEvaluation, EthicsIssue, GovernanceReport,
                                   SupplierEvaluation)
from app.utils.facility_safety import FacilityError, _day, _int, _text

#: OGM.10 ev. 4, OGM.13 ev. 5 — "at least annually".
YEAR_DAYS = 365


def _today():
    from app.utils.clock import local_today

    return local_today()


def quarter_of(on):
    return f"{on.year}-Q{(on.month - 1) // 3 + 1}"


# ============================================================== committees ==
def _meetings(key):
    """Every meeting date of a committee, newest first, from wherever it
    keeps its minutes."""
    from app.models import DtcMeeting, IpcMeeting, QualityMeeting

    if key == "ipc":
        q = db.session.query(IpcMeeting.held_on)
        return [d for (d,) in q.order_by(IpcMeeting.held_on.desc()).all()]
    if key == "dtc":
        q = db.session.query(DtcMeeting.held_on)
        return [d for (d,) in q.order_by(DtcMeeting.held_on.desc()).all()]
    q = db.session.query(QualityMeeting.held_on).filter(QualityMeeting.committee == key)
    return [d for (d,) in q.order_by(QualityMeeting.held_on.desc()).all()]


def _reviewed(key, year):
    from app.models import DtcAnnualReview, QualitySelfEvaluation

    if CommitteeReview.query.filter_by(key=key, year=year).first() is not None:
        return True
    if key == "quality":
        return QualitySelfEvaluation.query.filter_by(year=year).first() is not None
    if key == "dtc":
        return DtcAnnualReview.query.filter_by(year=year).first() is not None
    return False


def committees(today=None):
    """Every committee with its terms of reference, its meetings this year,
    its last meeting, whether it is late against its own interval, and
    whether last year's performance review was written."""
    today = today or _today()
    from app.models.governance import TEACHING_COMMITTEES
    from app.utils.facility import module_enabled

    charters = {c.key: c for c in CommitteeCharter.query.all()}
    teaching = module_enabled("teaching")
    out = []
    for key in CHARTER_KEYS:
        if key in TEACHING_COMMITTEES and not teaching:
            continue
        dates = _meetings(key)
        charter = charters.get(key)
        last = dates[0] if dates else None
        every = charter.every_days if charter else None
        late = bool(every and (last is None or (today - last).days > every))
        out.append({"key": key, "required": key in REQUIRED_COMMITTEES, "charter": charter,
                    "last": last, "this_year": sum(1 for d in dates if d.year == today.year),
                    "late": late, "reviewed": _reviewed(key, today.year - 1),
                    "reviewed_now": _reviewed(key, today.year)})
    return out


def save_charter(user, key, form):
    if key not in CHARTER_KEYS:
        raise FacilityError("need_kind")
    membership, duties, reports_to = (_text(form.get("membership")), _text(form.get("duties")),
                                      _text(form.get("reports_to"), 160))
    if not membership or not duties or not reports_to:
        raise FacilityError("need_charter")
    row = CommitteeCharter.query.filter_by(key=key).first() or CommitteeCharter(key=key)
    row.membership, row.duties, row.reports_to = membership, duties, reports_to
    row.every_days = _int(form.get("every_days"), 1, 366)
    row.quorum = _text(form.get("quorum"), 120)
    row.agenda = _text(form.get("agenda"))
    row.approved_on = _day(form.get("approved_on"), need=False)
    row.approved_by = _text(form.get("approved_by"), 160)
    row.updated_by = getattr(user, "id", None)
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def save_review(user, key, year, form):
    if key not in CHARTER_KEYS:
        raise FacilityError("need_kind")
    text = _text(form.get("text"))
    if not text:
        raise FacilityError("need_text")
    row = CommitteeReview.query.filter_by(key=key, year=year).first()
    if row is None:
        row = CommitteeReview(key=key, year=year, text=text, by_id=getattr(user, "id", None))
        db.session.add(row)
    else:
        row.text, row.by_id = text, getattr(user, "id", None)
    db.session.flush()
    return row


# ============================================== reports to the governing body ==
def save_report(user, form, file=None):
    kind = form.get("kind")
    if kind not in REPORT_KINDS:
        raise FacilityError("need_kind")
    quarter = (form.get("quarter") or "").strip()
    if len(quarter) != 7 or not quarter[:4].isdigit() or quarter[4:6] != "-Q" or quarter[6] not in "1234":
        raise FacilityError("need_quarter")
    summary = _text(form.get("summary"))
    if not summary:
        raise FacilityError("need_text")
    row = GovernanceReport(kind=kind, quarter=quarter, sent_on=_day(form.get("sent_on")),
                           summary=summary, file=file, sent_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def feedback(row, form):
    text = _text(form.get("feedback"))
    if not text:
        raise FacilityError("need_text")
    row.feedback, row.feedback_on = text, _day(form.get("feedback_on"))
    db.session.flush()
    return row


def reports_board(today=None):
    """Each kind's reports, the finished quarters of this year with none,
    and the reports still waiting for the governing body's feedback."""
    today = today or _today()
    rows = GovernanceReport.query.order_by(GovernanceReport.quarter.desc(),
                                           GovernanceReport.sent_on.desc()).all()
    done = {(r.kind, r.quarter) for r in rows}
    current = (today.month - 1) // 3 + 1
    finished = [f"{today.year}-Q{q}" for q in range(1, current)]
    if current == 1:
        finished = [f"{today.year - 1}-Q4"]
    return {"rows": rows, "kinds": REPORT_KINDS,
            "missing": [(k, q) for k in REPORT_KINDS for q in finished if (k, q) not in done],
            "awaiting": [r for r in rows if not r.feedback]}


# ================================================================== ethics ==
def raise_issue(user, form):
    kind = form.get("kind")
    if kind not in ETHICS_KINDS:
        raise FacilityError("need_kind")
    summary = _text(form.get("summary"))
    if not summary:
        raise FacilityError("need_text")
    row = EthicsIssue(kind=kind, raised_on=_day(form.get("raised_on")), summary=summary,
                      raised_by=_text(form.get("raised_by"), 160),
                      due_on=_day(form.get("due_on"), need=False, future_ok=True),
                      recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def work_issue(row, form):
    """The committee's discussion and decision, to whom it was told, the day
    it was resolved, and how it was used to teach. Resolving needs the
    decision and who was told — "resolved, communicated" (OGM.15)."""
    for name in ("discussion", "decision", "teaching", "communicated_to"):
        if name in form:
            limit = 255 if name in ("teaching", "communicated_to") else None
            setattr(row, name, _text(form.get(name), limit) if limit else _text(form.get(name)))
    if form.get("resolved_on"):
        if not row.decision or not row.communicated_to:
            raise FacilityError("need_decision")
        row.resolved_on = _day(form.get("resolved_on"))
    db.session.flush()
    return row


def ethics_board(today=None):
    today = today or _today()
    rows = EthicsIssue.query.order_by(EthicsIssue.raised_on.desc()).all()
    open_rows = [r for r in rows if r.resolved_on is None]
    return {"rows": rows, "open": open_rows, "kinds": ETHICS_KINDS,
            "overdue": [r for r in open_rows if r.due_on and r.due_on < today],
            "taught": [r for r in rows if r.teaching]}


# ======================================================== contracted services ==
def save_service(form, row=None):
    name, provider, head = (_text(form.get("name"), 160), _text(form.get("provider"), 160),
                            _text(form.get("head"), 160))
    if not name or not provider or not head:
        raise FacilityError("need_name")
    kind = form.get("kind")
    if kind not in SERVICE_KINDS:
        raise FacilityError("need_kind")
    criteria, measures = _text(form.get("criteria")), _text(form.get("measures"))
    if not criteria or not measures:
        raise FacilityError("need_criteria")
    row = row or ContractedService()
    row.name, row.kind, row.provider, row.head = name, kind, provider, head
    row.criteria, row.measures = criteria, measures
    row.starts_on = _day(form.get("starts_on"), need=False, future_ok=True)
    row.ends_on = _day(form.get("ends_on"), need=False, future_ok=True)
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def evaluate_service(service, user, form):
    results = _text(form.get("results"))
    decision = form.get("decision")
    if not results or decision not in CONTRACT_DECISIONS:
        raise FacilityError("need_evaluation")
    row = ContractEvaluation(service_id=service.id, evaluated_on=_day(form.get("evaluated_on")),
                             results=results, decision=decision, note=_text(form.get("note"), 255),
                             by_id=getattr(user, "id", None))
    db.session.add(row)
    if decision == "terminate":
        service.is_active = False
    db.session.flush()
    return row


def services_board(today=None):
    today = today or _today()
    rows = ContractedService.query.order_by(ContractedService.is_active.desc(), ContractedService.name).all()
    since = today - timedelta(days=YEAR_DAYS)
    out = []
    for s in rows:
        last = s.evaluations[0] if s.evaluations else None
        out.append({"service": s, "last": last,
                    "due": s.is_active and (last is None or last.evaluated_on < since)})
    return {"rows": out, "due": [r for r in out if r["due"]], "kinds": SERVICE_KINDS,
            "decisions": CONTRACT_DECISIONS}


# ================================================================ suppliers ==
def evaluate_supplier(supplier, user, form):
    results = _text(form.get("results"))
    decision = form.get("decision")
    if not results or decision not in SUPPLIER_DECISIONS:
        raise FacilityError("need_evaluation")
    row = SupplierEvaluation(supplier_id=supplier.id, evaluated_on=_day(form.get("evaluated_on")),
                             results=results, decision=decision, by_id=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def suppliers_board(today=None):
    from app.models import Supplier

    today = today or _today()
    since = today - timedelta(days=YEAR_DAYS)
    out = []
    for s in Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all():
        last = (SupplierEvaluation.query.filter_by(supplier_id=s.id)
                .order_by(SupplierEvaluation.evaluated_on.desc()).first())
        out.append({"supplier": s, "last": last, "due": last is None or last.evaluated_on < since})
    return {"rows": out, "due": [r for r in out if r["due"]], "decisions": SUPPLIER_DECISIONS}


__all__ = ["committees", "ethics_board", "evaluate_service", "evaluate_supplier", "feedback",
           "quarter_of", "raise_issue", "reports_board", "save_charter", "save_report",
           "save_review", "save_service", "services_board", "suppliers_board", "work_issue",
           "YEAR_DAYS"]
