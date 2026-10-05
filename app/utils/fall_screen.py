"""Screening a child for falls in the clinic — GAHAR ICD.10 / GSR.05,
evidence 4: *"Outpatients with certain conditions, situations, or locations
will be screened for risk of falls"*, and (د) of the intent: *"the screening
criteria for outpatient and ambulatory locations, situations, and conditions
that may increase the risk of falls"*.

**Off until the hospital switches it on**, and then it asks only the
hospital's own criteria — one per line, in its words, on the risks settings.
The program has no list of its own: which conditions put a child at risk
in this hospital's clinics is its policy. With the switch off, or with no
criteria written, the visit screen is exactly what it was.

**Ticking is the screening.** A criterion that applies makes the child
screened positive — that is what the hospital's list means — and then the
family has to have been told (evidence 5) before it is saved, with the
hospital's general measures copied onto the record (evidence 6). No
criterion ticked is a screening too, and a negative one: the record says it
was looked at.

Kept in ``RiskAssessment`` (kind ``fall``), the table the inpatient
assessment already uses, with the visit and the criteria that applied — so
"has anybody looked at this child's fall risk" stays one question.
"""
from datetime import datetime, time

from app.extensions import db
from app.models.risk_assessment import FALL, RiskAssessment

ON_SETTING = "risks:fall_outpatient"
CRITERIA_SETTING = "risks:fall_outpatient_criteria"
MEASURES_SETTING = "risks:fall_outpatient_measures"
TOOL = "outpatient_screen"


class ScreenError(ValueError):
    """A refusal with a key the screen can name (``fall_screen.err_<key>``)."""


def _get(key):
    from app.models import Setting

    try:
        return (Setting.get(key) or "").strip()
    except Exception:                   # noqa: BLE001 — settings not ready
        return ""


def criteria():
    """The hospital's criteria, one per line, as it wrote them."""
    seen, out = set(), []
    for line in _get(CRITERIA_SETTING).splitlines():
        line = " ".join(line.split())[:200]
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def measures():
    return _get(MEASURES_SETTING)


def on():
    """Switched on, and with something to ask."""
    from app.utils import risks

    return _get(ON_SETTING) == "1" and bool(criteria()) and risks.is_enabled(FALL)


def save_policy(enabled, criteria_text, measures_text):
    from app.models import Setting

    Setting.set(ON_SETTING, "1" if enabled else "0")
    Setting.set(CRITERIA_SETTING, (criteria_text or "").strip()[:2000])
    Setting.set(MEASURES_SETTING, (measures_text or "").strip()[:1000])


def for_visit(visit_id):
    return (RiskAssessment.query.filter_by(visit_id=visit_id, kind=FALL)
            .order_by(RiskAssessment.at.desc(), RiskAssessment.id.desc()).first())


def screen(visit, user, ticked, family_told=False, note=None):
    """Record the screening for one visit. The caller commits."""
    from app.utils import risks

    if visit is None:
        raise ScreenError("no_visit")
    if not on():
        raise ScreenError("off")
    known = criteria()
    chosen = [c for c in known if c in set(ticked or ())]
    at_risk = bool(chosen)
    if at_risk and not family_told:
        raise ScreenError("need_family")
    row = risks.record(
        visit.patient, FALL, user=user, tool=TOOL,
        level="positive" if at_risk else "negative", at_risk=at_risk,
        general_measures=measures() or None if at_risk else None,
        plan=(note or "").strip()[:1000] or None,
        family_told=True if at_risk else None)
    row.visit_id = visit.id
    row.criteria = "\n".join(chosen) or None
    db.session.flush()
    return row


def report(start, end):
    """Evidence 4–5 over a period: the visits, how many were screened, how
    many screened positive, and of those how many families were told — and
    which criteria applied, most often first."""
    from app.models import Visit
    from app.utils.clock import to_utc

    visits = Visit.query.filter(Visit.visit_date >= start,
                                Visit.visit_date <= end).count()
    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (RiskAssessment.query
            .filter(RiskAssessment.kind == FALL,
                    RiskAssessment.visit_id.isnot(None),
                    RiskAssessment.at >= since, RiskAssessment.at <= until)
            .all())
    latest = {}
    for row in sorted(rows, key=lambda r: (r.at, r.id)):
        latest[row.visit_id] = row
    screened = list(latest.values())
    positive = [r for r in screened if r.at_risk]
    counts = {}
    for row in positive:
        for line in (row.criteria or "").splitlines():
            counts[line] = counts.get(line, 0) + 1
    return {"visits": visits, "screened": len(screened),
            "positive": len(positive),
            "told": sum(1 for r in positive if r.family_told),
            "criteria": sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}
