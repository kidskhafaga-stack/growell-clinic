"""Internal and external quality control — GAHAR DAS.18 and DAS.19.

See `models/lab_quality` for what is kept. Here: the arithmetic and the
decisions.

**The target is the laboratory's.** A control's mean and SD come from the
manufacturer's insert for that lot, or the laboratory's own data, and are
typed by the laboratory. A value is read as how many SDs it sits from that
mean, and nothing else.

**The rules are the laboratory's choice** (DAS.18 هـ, ``lab_qc_rules``),
from the multirule set every laboratory text describes:

* ``1_2s`` one value beyond 2 SD — a warning, never a rejection;
* ``1_3s`` one value beyond 3 SD;
* ``2_2s`` two in a row beyond 2 SD on the same side;
* ``R_4s`` two in a row beyond 2 SD on opposite sides;
* ``4_1s`` four in a row beyond 1 SD on the same side;
* ``10x``  ten in a row on the same side of the mean.

Until it picks any, nothing is judged for it: the person who ran the
control says whether it passed.
"""
from datetime import date, datetime

from app.extensions import db

RULES = ("1_2s", "1_3s", "2_2s", "R_4s", "4_1s", "10x")
WARNING_ONLY = ("1_2s",)
RULES_SETTING = "lab_qc_rules"
EQA_KINDS = ("proficiency", "interlab")
EQA_OUTCOMES = ("pending", "acceptable", "unacceptable")


class QualityError(ValueError):
    """A refusal with a key the screen can name (``lab_quality.err_<key>``)."""


def chosen_rules():
    from app.models import Setting

    raw = Setting.get(RULES_SETTING) or ""
    return [r for r in raw.split(",") if r in RULES]


def set_rules(rules):
    from app.models import Setting

    Setting.set(RULES_SETTING, ",".join(r for r in RULES if r in set(rules)))


def may_review(user):
    from app.utils import lab_release

    return lab_release.may_release(user)


def _float(raw):
    try:
        return float(str(raw or "").strip().replace(",", "."))
    except ValueError:
        return None


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


# --------------------------------------------------------------- materials --
def save_material(form):
    from app.models import LabAnalyte, QcMaterial

    name = (form.get("name") or "").strip()[:160]
    if not name:
        raise QualityError("need_name")
    mean, sd = _float(form.get("target_mean")), _float(form.get("target_sd"))
    if mean is None or sd is None or sd <= 0:
        raise QualityError("need_target")
    analyte = None
    if (form.get("analyte_id") or "").isdigit():
        analyte = db.session.get(LabAnalyte, int(form["analyte_id"]))
    row = QcMaterial(name=name, analyte_id=analyte.id if analyte else None,
                     level=(form.get("level") or "").strip()[:40] or None,
                     lot_number=(form.get("lot_number") or "").strip()[:60] or None,
                     expiry_date=_day(form.get("expiry_date")),
                     target_mean=mean, target_sd=sd,
                     unit=(form.get("unit") or "").strip()[:30]
                     or (analyte.unit if analyte else None))
    db.session.add(row)
    db.session.flush()
    return row


def z(material, value):
    return (value - material.target_mean) / material.target_sd


def broken(material, value, rules=None):
    """The chosen rules this value breaks, given the runs before it."""
    rules = chosen_rules() if rules is None else rules
    zs = [z(material, r.value) for r in material.runs] + [z(material, value)]
    now = zs[-1]
    out = []
    if "1_3s" in rules and abs(now) > 3:
        out.append("1_3s")
    if len(zs) >= 2:
        prev = zs[-2]
        if "2_2s" in rules and ((now > 2 and prev > 2) or (now < -2 and prev < -2)):
            out.append("2_2s")
        if "R_4s" in rules and ((now > 2 and prev < -2) or (now < -2 and prev > 2)):
            out.append("R_4s")
    last4 = zs[-4:]
    if "4_1s" in rules and len(last4) == 4 and (all(v > 1 for v in last4) or all(v < -1 for v in last4)):
        out.append("4_1s")
    last10 = zs[-10:]
    if "10x" in rules and len(last10) == 10 and (all(v > 0 for v in last10) or all(v < 0 for v in last10)):
        out.append("10x")
    if "1_2s" in rules and abs(now) > 2 and not out:
        out.append("1_2s")
    return out


def record_run(material, value, user=None, accepted=None, action=None, at=None):
    """A control value. Rejected when it breaks a rejecting rule the
    laboratory chose; otherwise as the person who ran it says."""
    from app.models import QcRun

    if material is None or not material.is_active:
        raise QualityError("no_material")
    value = _float(value)
    if value is None:
        raise QualityError("need_value")
    rules = chosen_rules()
    hits = broken(material, value, rules)
    rejecting = [h for h in hits if h not in WARNING_ONLY]
    if rules:
        ok = not rejecting
    else:
        ok = accepted is not False
    row = QcRun(material_id=material.id, value=value, run_at=at or datetime.utcnow(),
                run_by=getattr(user, "id", None), rule_broken=",".join(hits) or None,
                accepted=ok, action=(action or "").strip()[:255] or None)
    db.session.add(row)
    db.session.flush()
    db.session.refresh(material)
    return row


def add_action(run, text):
    text = (text or "").strip()[:255]
    if not text:
        raise QualityError("need_action")
    run.action = text
    db.session.flush()
    return run


def chart(material, last=30):
    """Points for a Levey-Jennings chart: ``[(index, z, accepted, value)]``,
    the most recent ``last`` runs."""
    runs = material.runs[-last:]
    return [(i, max(-4.0, min(4.0, z(material, r.value))), r.accepted, r.value)
            for i, r in enumerate(runs)]


def failed_without_action():
    from app.models import QcRun

    return (db.session.query(db.func.count(QcRun.id))
            .filter(QcRun.accepted.is_(False), QcRun.action.is_(None)).scalar() or 0)


# ------------------------------------------------------------------ review --
def months():
    """``[(month, runs, failed, review)]`` newest first."""
    from app.models import QcReview, QcRun

    counts = {}
    for run in QcRun.query.all():
        key = run.run_at.strftime("%Y-%m")
        entry = counts.setdefault(key, [0, 0])
        entry[0] += 1
        entry[1] += 0 if run.accepted else 1
    reviews = {r.month: r for r in QcReview.query.order_by(QcReview.id).all()}
    return [(m, c[0], c[1], reviews.get(m)) for m, c in sorted(counts.items(), reverse=True)]


def review(month, user, note=None):
    from app.models import QcReview

    if not may_review(user):
        raise QualityError("not_allowed")
    month = (month or "").strip()
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise QualityError("bad_month") from None
    row = QcReview(month=month, reviewed_by=user.id,
                   note=(note or "").strip()[:255] or None)
    db.session.add(row)
    db.session.flush()
    return row


# --------------------------------------------------------------------- EQA --
def save_round(form, user=None, row=None):
    from app.models import EqaRound

    provider = (form.get("provider") or "").strip()[:160]
    if not provider:
        raise QualityError("need_provider")
    kind = form.get("kind") or "proficiency"
    if kind not in EQA_KINDS:
        raise QualityError("bad_kind")
    if row is None:
        row = EqaRound(provider=provider, created_by=getattr(user, "id", None))
        db.session.add(row)
    row.kind = kind
    row.provider = provider
    row.round_code = (form.get("round_code") or "").strip()[:60] or None
    row.tests = (form.get("tests") or "").strip()[:255] or None
    row.received_on = _day(form.get("received_on"))
    row.due_on = _day(form.get("due_on"))
    row.submitted_on = _day(form.get("submitted_on"))
    db.session.flush()
    return row


def grade_round(row, outcome, note=None, remedial=None, user=None):
    """The returned grade, reviewed by somebody authorized (DAS.19 أ–ج);
    an unacceptable one needs its remedial action."""
    if outcome not in EQA_OUTCOMES:
        raise QualityError("bad_outcome")
    if not may_review(user):
        raise QualityError("not_allowed")
    remedial = (remedial or "").strip()[:255] or None
    if outcome == "unacceptable" and not remedial:
        raise QualityError("need_action")
    row.outcome = outcome
    row.grade_note = (note or "").strip()[:255] or None
    row.remedial_action = remedial
    row.reviewed_by = user.id
    row.reviewed_at = datetime.utcnow()
    db.session.flush()
    return row


def rounds():
    from app.models import EqaRound

    return EqaRound.query.order_by(EqaRound.created_at.desc()).all()
