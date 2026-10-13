"""The safety program beyond fire and utilities — GAHAR EFS.02, EFS.05–08,
EFS.09's rounds and OGM.14's leaders' rounds. Models in
``app/models/safety_program.py``.

**The rules the records keep:**

* a round is who walked, where, and every finding with its risk, its action,
  who owns it and by when — the action is written with the finding, not
  later; a finding is closed with a word on what was done;
* EFS.02 ev. 4 — the environment round is read a quarter at a time: a
  quarter gone by with none is said out loud;
* a hazardous material is not on the inventory without its hazard, its
  place and who is responsible; one without a safety data sheet, or not
  labelled, is listed;
* a pre-construction assessment weighs every item (a)–(h) and gives each a
  measure; the work is not "underway" without its permit;
* a construction check that found the contractor non-compliant needs the
  action taken.
"""
from datetime import date, datetime

from app.extensions import db
from app.models.safety_program import (HAZARD_TYPES, PCRA_ITEMS, PROJECT_STATES, RISK_LEVELS,
                                       ROUND_FOCUS, WASTE_CATEGORIES, ConstructionCheck,
                                       ConstructionProject, HazardousMaterial, PestControlVisit,
                                       RoundFinding, SafetyRound, WasteHandover)
from app.utils.facility_safety import FacilityError, _day, _list, _text


def _today():
    from app.utils.clock import local_today

    return local_today()


def quarter_of(on):
    return f"{on.year}-Q{(on.month - 1) // 3 + 1}"


# ================================================================== rounds ==
def save_round(user, form):
    """A round and its findings. Findings come as parallel lists
    (``f_area``, ``f_finding``, ``f_risk``, ``f_action``, ``f_owner``,
    ``f_due``); a row with no finding is skipped, a finding without its
    risk, action or owner is refused."""
    from app.models import User

    focus = form.get("focus")
    if focus not in ROUND_FOCUS:
        raise FacilityError("need_focus")
    held = _day(form.get("held_on"))
    areas = _text(form.get("areas"), 400)
    if not areas:
        raise FacilityError("need_areas")
    ids = {int(v) for v in _list(form, "team") if str(v).isdigit()}
    team = User.query.filter(User.id.in_(ids)).all() if ids else []
    others = _text(form.get("others"), 255)
    if not team and not others:
        raise FacilityError("need_people")
    row = SafetyRound(focus=focus, held_on=held, areas=areas, others=others,
                      summary=_text(form.get("summary")), sent_to=_text(form.get("sent_to"), 255),
                      recorded_by=getattr(user, "id", None))
    row.team = team
    columns = [_list(form, k) for k in ("f_area", "f_finding", "f_risk", "f_action", "f_owner", "f_due")]
    width = max((len(c) for c in columns), default=0)
    for i in range(width):
        area, finding, risk, action, owner, due = (c[i] if i < len(c) else "" for c in columns)
        finding = _text(finding)
        if not finding:
            continue
        if risk not in RISK_LEVELS or not _text(action) or not _text(owner, 160):
            raise FacilityError("need_finding_action")
        row.findings.append(RoundFinding(area=_text(area, 160), finding=finding, risk=risk,
                                         action=_text(action), owner=_text(owner, 160),
                                         due_on=_day(due, need=False, future_ok=True)))
    db.session.add(row)
    db.session.flush()
    return row


def close_finding(finding, user, form):
    if finding.closed_at is not None:
        raise FacilityError("already_closed")
    note = _text(form.get("note"), 255)
    if not note:
        raise FacilityError("need_note")
    finding.closed_at, finding.closed_note = datetime.utcnow(), note
    finding.closed_by = getattr(user, "id", None)
    db.session.flush()
    return finding


def rounds_board(year=None, today=None):
    """The year's rounds by focus, each quarter's environment rounds against
    EFS.02 ev. 4, and every open finding — high risk and overdue first."""
    today = today or _today()
    year = year or today.year
    rows = (SafetyRound.query.filter(SafetyRound.held_on >= date(year, 1, 1),
                                     SafetyRound.held_on <= date(year, 12, 31))
            .order_by(SafetyRound.held_on.desc()).all())
    quarters = {q: 0 for q in (1, 2, 3, 4)}
    for r in rows:
        if r.focus == "environment":
            quarters[(r.held_on.month - 1) // 3 + 1] += 1
    current = (today.month - 1) // 3 + 1 if year == today.year else 4
    open_rows = (RoundFinding.query.filter(RoundFinding.closed_at.is_(None))
                 .join(SafetyRound).order_by(SafetyRound.held_on).all())
    rank = {r: i for i, r in enumerate(RISK_LEVELS)}
    open_rows.sort(key=lambda f: (rank.get(f.risk, 9), not (f.due_on and f.due_on < today),
                                  f.due_on or date.max))
    return {"year": year, "rounds": rows, "quarters": quarters,
            "missing_quarters": [q for q in quarters if q <= current and not quarters[q]],
            "open": open_rows,
            "overdue": [f for f in open_rows if f.due_on and f.due_on < today],
            "leadership": sum(1 for r in rows if r.focus == "leadership")}


def quarter_summary(quarter):
    """EFS.02 ev. 5 — what the governing body is told about a quarter: the
    rounds walked, the high-risk findings, and what was done or is still
    to be done about them."""
    year, q = int(quarter[:4]), int(quarter[-1])
    start = date(year, 3 * q - 2, 1)
    end = date(year + (q == 4), (3 * q) % 12 + 1, 1)
    rounds = (SafetyRound.query.filter(SafetyRound.held_on >= start, SafetyRound.held_on < end)
              .order_by(SafetyRound.held_on).all())
    findings = [f for r in rounds for f in r.findings]
    return {"quarter": quarter, "rounds": rounds,
            "high": [f for f in findings if f.risk == "high"],
            "closed": [f for f in findings if f.closed_at is not None],
            "open": [f for f in findings if f.closed_at is None]}


# ==================================================== hazardous materials ==
def save_material(form, row=None, sds_file=None):
    name = _text(form.get("name"), 160)
    if not name:
        raise FacilityError("need_name")
    hazard = form.get("hazard")
    if hazard not in HAZARD_TYPES:
        raise FacilityError("need_hazard")
    location, responsible = _text(form.get("location"), 160), _text(form.get("responsible"), 160)
    if not location or not responsible:
        raise FacilityError("need_location")
    row = row or HazardousMaterial()
    row.name, row.hazard, row.location, row.responsible = name, hazard, location, responsible
    row.usage = _text(form.get("usage"), 255)
    row.consumption = _text(form.get("consumption"), 80)
    row.labelled = bool(form.get("labelled"))
    if sds_file:
        row.sds_file = sds_file
        row.sds_reviewed_on = _today()
    elif form.get("sds_reviewed_on"):
        row.sds_reviewed_on = _day(form.get("sds_reviewed_on"))
    if row.id is None:
        db.session.add(row)
    db.session.flush()
    return row


def retire_material(row):
    row.is_active = False
    db.session.flush()


def materials_board():
    rows = HazardousMaterial.query.filter_by(is_active=True).order_by(HazardousMaterial.name).all()
    return {"rows": rows,
            "no_sds": [r for r in rows if not r.sds_file],
            "unlabelled": [r for r in rows if not r.labelled]}


def hand_over_waste(user, form):
    category = form.get("category")
    if category not in WASTE_CATEGORIES:
        raise FacilityError("need_category")
    carrier = _text(form.get("carrier"), 160)
    if not carrier:
        raise FacilityError("need_carrier")
    raw = (form.get("weight_kg") or "").strip().replace(",", ".")
    weight = None
    if raw:
        try:
            weight = round(float(raw), 2)
        except ValueError:
            raise FacilityError("bad_number") from None
        if weight <= 0:
            raise FacilityError("bad_number")
    row = WasteHandover(handed_on=_day(form.get("handed_on")), category=category, weight_kg=weight,
                        carrier=carrier, manifest_no=_text(form.get("manifest_no"), 60),
                        note=_text(form.get("note"), 255), recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def waste_by_month(year):
    """Each category's handed-over weight per month of a year."""
    rows = WasteHandover.query.filter(WasteHandover.handed_on >= date(year, 1, 1),
                                      WasteHandover.handed_on <= date(year, 12, 31)).all()
    table = {c: [0.0] * 12 for c in WASTE_CATEGORIES}
    for r in rows:
        table[r.category][r.handed_on.month - 1] += r.weight_kg or 0
    return {c: v for c, v in table.items() if any(v)}


def pest_visit(user, form):
    company, areas = _text(form.get("company"), 160), _text(form.get("areas"), 400)
    if not company or not areas:
        raise FacilityError("need_company")
    findings, action = _text(form.get("findings")), _text(form.get("action"))
    if findings and not action:
        raise FacilityError("need_action")
    row = PestControlVisit(visited_on=_day(form.get("visited_on")), company=company, areas=areas,
                           method=_text(form.get("method"), 255), findings=findings, action=action,
                           next_due=_day(form.get("next_due"), need=False, future_ok=True),
                           recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def pest_board(today=None):
    today = today or _today()
    rows = PestControlVisit.query.order_by(PestControlVisit.visited_on.desc()).limit(20).all()
    last = rows[0] if rows else None
    return {"rows": rows, "last": last,
            "overdue": bool(last and last.next_due and last.next_due < today)}


# ============================================================ construction ==
def save_project(user, form):
    title, area = _text(form.get("title"), 200), _text(form.get("area"), 200)
    if not title or not area:
        raise FacilityError("need_title")
    departments = _text(form.get("departments"), 400)
    if not departments:
        raise FacilityError("need_departments")
    assessment = {}
    for item in PCRA_ITEMS:
        risk, measure = form.get(f"risk_{item}"), _text(form.get(f"measure_{item}"), 400)
        if item == "other" and not risk and not measure:
            continue
        if risk not in RISK_LEVELS + ("none",) or (risk != "none" and not measure):
            raise FacilityError("need_assessment")
        assessment[item] = {"risk": risk, "measure": measure}
    row = ConstructionProject(title=title, area=area, contractor=_text(form.get("contractor"), 160),
                              starts_on=_day(form.get("starts_on"), need=False, future_ok=True),
                              ends_on=_day(form.get("ends_on"), need=False, future_ok=True),
                              departments=departments, assessment=assessment,
                              icra_class=_text(form.get("icra_class"), 20),
                              assessed_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def permit(project, form):
    by = _text(form.get("permit_by"), 160)
    if not by:
        raise FacilityError("need_permit")
    project.permit_by, project.permit_on = by, _day(form.get("permit_on"))
    db.session.flush()
    return project


def set_state(project, state):
    if state not in PROJECT_STATES:
        raise FacilityError("need_state")
    if state == "underway" and not project.permit_on:
        raise FacilityError("need_permit")
    project.state = state
    db.session.flush()
    return project


def check_project(project, user, form):
    compliant = form.get("compliant")
    if compliant not in ("yes", "no"):
        raise FacilityError("need_result")
    note, action = _text(form.get("note")), _text(form.get("action"))
    if not note:
        raise FacilityError("need_note")
    if compliant == "no" and not action:
        raise FacilityError("need_action")
    row = ConstructionCheck(project_id=project.id, checked_on=_day(form.get("checked_on")),
                            compliant=compliant == "yes", note=note, action=action,
                            recorded_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def projects_board():
    rows = ConstructionProject.query.order_by(ConstructionProject.created_at.desc()).all()
    return {"rows": rows,
            "no_permit": [p for p in rows if p.state != "finished" and not p.permit_on],
            "items": PCRA_ITEMS}


__all__ = ["check_project", "close_finding", "hand_over_waste", "materials_board", "permit",
           "pest_board", "pest_visit", "projects_board", "quarter_of", "quarter_summary",
           "retire_material", "rounds_board", "save_material", "save_project", "save_round",
           "set_state", "waste_by_month"]
