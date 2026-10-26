"""The severity engine (HOSPITAL_PLAN.md ٥‑د ت-٦ب) — locked until a score is
approved.

Asked by the hospital's owner after a long discussion of PIM3, CRIB-II and
SNAPPE-II: *«هو هيقدر يعدل من البرنامج صح؟ ولا محتاجين نكتب كود؟»* — and
answered: the score each unit uses, its numbers and its worked examples are
set from the screen; the **shapes** the engine understands are code.

**The program writes no clinical number.** No score ships with it. The
hospital enters a score's inputs, coefficients or points, its window and its
rule for a value that was not measured — all from the original paper — with
worked examples from the paper or the official calculator. **A score runs
only when it reproduces every example**, carries its source and whose
licence it is used under, and a named person approved it. That is the guard,
not a tick in a box.

Two shapes:

``equation``
    ``logit = intercept + Σ coefficient × f(reading)``, the probability
    ``1 / (1 + e^-logit)``. ``f`` is one of :data:`TRANSFORMS`.
``points``
    each reading falls in a band worth some points; the total, and — when the
    paper gives the line — ``1 / (1 + e^-(intercept + slope × total))``.

A reading is a number, a yes/no, or a ratio of two numbers times a scale.
A score with another shape is code, once.

**What the board says, and what it does not.** Deaths against the deaths the
score expected, over the last twelve months together, with the 95% interval
and the number of children — a unit of fifteen children a month moves on one
death, so a month alone says nothing. The VLAD line (expected minus observed,
child by child) shows the direction early. It is the whole unit over time —
**not a judgement on a doctor, and not a prediction for one child** — and the
score was built in other hospitals, so the unit against itself is the fairer
comparison.
"""
import math
import re
from datetime import datetime, timedelta

from app.extensions import db

#: The units a score is kept for, each behind its own module.
UNITS = ("icu", "nicu")

#: What may be done to a reading before its coefficient — the shapes the
#: original papers use. Named, so a definition says which in words.
TRANSFORMS = {
    "value": lambda x: x,
    "square": lambda x: x * x,
    "abs": abs,
    "div1000": lambda x: x / 1000.0,
    "square_div1000": lambda x: x * x / 1000.0,
    "ln": lambda x: math.log(x),
}
TYPES = ("number", "yesno", "ratio")

#: How many worked examples a score must reproduce before it may run.
MIN_EXAMPLES = 3

#: Fewer children than this in the twelve months and the board says the
#: number is too small to read. A reading rule, not a clinical number.
FEW = 30

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬", "0123456789.,")


def module_on(unit_kind=None):
    from app.utils.facility import module_enabled

    kinds = [unit_kind] if unit_kind else UNITS
    return any(module_enabled(k) for k in kinds)


def units_on():
    from app.utils.facility import module_enabled

    return [k for k in UNITS if module_enabled(k)]


# ------------------------------------------------------------- the text --
def _num(raw):
    raw = (raw or "").strip().translate(_DIGITS)
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(raw)


def parse_inputs(text, kind):
    """The hospital's input lines, one per reading, ``|`` between parts::

        equation: code | الاسم | name | type | unit | transform | coefficient | if not measured
        points:   code | الاسم | name | type | unit | bands | if not measured

    ``type``: ``number``, ``yesno``, or ``ratio:<scale>`` (two numbers, the
    first over the second, times the scale). Bands: ``lo..hi=points`` joined
    by ``;`` (an end may be left open), or ``yes=points`` for a yes/no.
    «If not measured» blank means the reading is required.

    Returns ``(inputs, problems)``; ``problems`` are ``(line number, why)``.
    """
    out, problems, seen = [], [], set()
    for n, line in enumerate((text or "").splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        want = 8 if kind == "equation" else 7
        if len(parts) != want:
            problems.append((n, "parts"))
            continue
        code = parts[0].lower()
        if not re.match(r"^[a-z][a-z0-9_]{0,29}$", code) or code in seen:
            problems.append((n, "code"))
            continue
        seen.add(code)
        row = {"code": code, "ar": parts[1][:120], "en": parts[2][:120], "unit": parts[4][:20]}
        kind_raw = parts[3].lower()
        if kind_raw.startswith("ratio"):
            try:
                row["type"], row["scale"] = "ratio", _num(kind_raw.split(":", 1)[1]) if ":" in kind_raw else 1.0
            except ValueError:
                problems.append((n, "type"))
                continue
        elif kind_raw in ("number", "yesno"):
            row["type"] = kind_raw
        else:
            problems.append((n, "type"))
            continue
        try:
            if kind == "equation":
                if parts[5] not in TRANSFORMS:
                    problems.append((n, "transform"))
                    continue
                row["transform"] = parts[5]
                row["coef"] = _num(parts[6])
                if row["coef"] is None:
                    problems.append((n, "coef"))
                    continue
                row["missing"] = _num(parts[7])
            else:
                row["bands"], row["yes"] = _bands(parts[5], row["type"])
                row["missing"] = _num(parts[6])
        except ValueError:
            problems.append((n, "number"))
            continue
        if row["type"] == "yesno" and row["missing"] not in (None, 0.0, 1.0):
            problems.append((n, "number"))
            continue
        out.append(row)
    return out, problems


def _bands(text, kind):
    if kind == "yesno":
        m = re.match(r"^\s*yes\s*=\s*(.+)$", text or "", re.I)
        if not m:
            raise ValueError(text)
        return [], _num(m.group(1))
    bands = []
    for piece in (text or "").split(";"):
        if not piece.strip():
            continue
        span, _, pts = piece.partition("=")
        lo, _, hi = span.partition("..")
        bands.append([_num(lo), _num(hi), _num(pts)])
    if not bands or any(b[2] is None for b in bands):
        raise ValueError(text)
    return bands, None


def inputs_text(inputs, kind):
    """The lines back, as the hospital wrote them."""
    def n(v):
        return "" if v is None else ("%g" % v)

    lines = []
    for r in inputs or []:
        t = r["type"] if r["type"] != "ratio" else f"ratio:{n(r.get('scale'))}"
        if kind == "equation":
            parts = [r["code"], r["ar"], r["en"], t, r["unit"], r["transform"], n(r["coef"]), n(r.get("missing"))]
        else:
            bands = (f"yes={n(r['yes'])}" if r["type"] == "yesno" else
                     "; ".join(f"{n(lo)}..{n(hi)}={n(p)}" for lo, hi, p in r["bands"]))
            parts = [r["code"], r["ar"], r["en"], t, r["unit"], bands, n(r.get("missing"))]
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def parse_examples(text):
    """``code=value, code=value => p=0.0123`` (or ``=> points=12``), one per
    line; a ratio as ``top/bottom``. Returns ``(examples, problems)``."""
    out, problems = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        left, arrow, right = line.partition("=>")
        m = re.match(r"^\s*(p|points)\s*=\s*(.+)$", right.strip(), re.I)
        if not arrow or not m:
            problems.append((n, "shape"))
            continue
        try:
            values = {}
            for pair in left.split(","):
                if not pair.strip():
                    continue
                k, _, v = pair.partition("=")
                v = v.strip()
                values[k.strip().lower()] = ([_num(x) for x in v.split("/", 1)] if "/" in v else _num(v))
            out.append({"values": values, "what": m.group(1).lower(), "expected": _num(m.group(2))})
        except ValueError:
            problems.append((n, "number"))
    return out, problems


def examples_text(examples):
    def v(x):
        return "/".join("%g" % y for y in x) if isinstance(x, list) else ("%g" % x if x is not None else "")

    return "\n".join(", ".join(f"{k}={v(x)}" for k, x in e["values"].items())
                     + f" => {e['what']}={'%g' % e['expected']}" for e in examples or [])


# ------------------------------------------------------------- the sums --
def _reading(row, raw):
    if raw is None:
        return None
    if row["type"] == "ratio":
        top, bottom = raw if isinstance(raw, (list, tuple)) and len(raw) == 2 else (None, None)
        if top is None or not bottom:
            return None
        return top / bottom * (row.get("scale") or 1.0)
    return float(raw)


def compute(score, values):
    """``{"points", "probability", "missing", "error"}`` for these values.

    A reading not measured takes the paper's own value where the hospital
    entered one, and is listed in ``missing``; with none, the score is not
    computed. Nothing is ever guessed."""
    missing, total, logit = [], 0.0, None
    kind = score.kind if hasattr(score, "kind") else score["kind"]
    inputs = score.inputs if hasattr(score, "inputs") else score["inputs"]
    intercept = score.intercept if hasattr(score, "intercept") else score.get("intercept")
    slope = score.slope if hasattr(score, "slope") else score.get("slope")
    if kind == "equation":
        if intercept is None:
            return {"error": "no_intercept"}
        logit = intercept
    for row in inputs:
        x = _reading(row, values.get(row["code"]))
        if x is None:
            if row.get("missing") is None:
                return {"error": "required", "code": row["code"]}
            x = row["missing"]
            missing.append(row["code"])
        if row["type"] == "yesno" and x not in (0.0, 1.0):
            return {"error": "yesno", "code": row["code"]}
        if kind == "equation":
            try:
                logit += row["coef"] * TRANSFORMS[row["transform"]](x)
            except (ValueError, ZeroDivisionError):
                return {"error": "domain", "code": row["code"]}
        else:
            if row["type"] == "yesno":
                total += row["yes"] if x == 1.0 else 0.0
            else:
                for lo, hi, pts in row["bands"]:
                    if (lo is None or x >= lo) and (hi is None or x <= hi):
                        total += pts
                        break
                else:
                    return {"error": "no_band", "code": row["code"]}
    if kind == "points":
        if intercept is not None and slope is not None:
            logit = intercept + slope * total
    prob = None
    if logit is not None:
        prob = 1.0 / (1.0 + math.exp(-logit)) if logit > -700 else 0.0
    return {"points": total if kind == "points" else None, "probability": prob,
            "missing": missing, "error": None}


def run_examples(score):
    """Every worked example against what the engine makes of it.
    ``(all passed, [{n, expected, got, ok}])``."""
    detail = []
    for n, ex in enumerate(score.examples or [], 1):
        got = compute(score, ex["values"])
        if got.get("error"):
            detail.append({"n": n, "expected": ex["expected"], "got": None,
                           "ok": False, "error": got["error"]})
            continue
        value = got["probability"] if ex["what"] == "p" else got["points"]
        ok = value is not None and abs(value - ex["expected"]) <= (
            score.tolerance if ex["what"] == "p" else 1e-9)
        detail.append({"n": n, "expected": ex["expected"],
                       "got": None if value is None else round(value, 6), "ok": ok})
    return bool(detail) and all(d["ok"] for d in detail), detail


def test(score):
    ok, detail = run_examples(score)
    score.test_ok, score.test_detail, score.test_at = ok, detail, datetime.utcnow()
    return ok


def blockers(score):
    """What still stands between this version and running — ``[]`` when
    nothing does."""
    out = []
    if score.status != "draft":
        out.append("not_draft")
    if not score.inputs:
        out.append("inputs")
    if score.kind == "equation" and score.intercept is None:
        out.append("intercept")
    if score.window_after_h is None:
        out.append("window")
    if not (score.source or "").strip():
        out.append("source")
    if not (score.licence_holder or "").strip() or not (score.licence_ref or "").strip():
        out.append("licence")
    if len(score.examples or []) < MIN_EXAMPLES:
        out.append("examples")
    elif not score.test_ok:
        out.append("test")
    return out


def activate(score, user, note):
    """Approved by a named person, with a word; the version is frozen."""
    from app.models import ActivityLog

    problems = blockers(score)
    if problems:
        return problems
    score.status = "active"
    score.approved_by = user.id
    score.approved_at = datetime.utcnow()
    score.approval_note = (note or "").strip()[:255] or None
    ActivityLog.record("severity.activate", user_id=user.id, entity="severity_score",
                       entity_id=score.id, detail=f"{score.key} v{score.version}")
    return []


def new_version(score, user):
    """A draft copy one version up — the way an active score is changed."""
    from app.models import SeverityScore

    top = (db.session.query(db.func.max(SeverityScore.version))
           .filter(SeverityScore.key == score.key).scalar() or 0)
    copy = SeverityScore(
        key=score.key, version=top + 1, name_ar=score.name_ar, name_en=score.name_en,
        kind=score.kind, source=score.source, licence_holder=score.licence_holder,
        licence_ref=score.licence_ref, window_before_h=score.window_before_h,
        window_after_h=score.window_after_h, intercept=score.intercept, slope=score.slope,
        inputs=list(score.inputs or []), examples=list(score.examples or []),
        tolerance=score.tolerance, created_by=user.id)
    db.session.add(copy)
    return copy


# ------------------------------------------------------- which unit uses --
def choice(unit_kind, on=None):
    """The score this unit uses on that day (``None`` when it uses none)."""
    from app.models import SeverityUnitChoice
    from app.utils.clock import local_today

    on = on or local_today()
    row = (SeverityUnitChoice.query
           .filter(SeverityUnitChoice.unit_kind == unit_kind, SeverityUnitChoice.since <= on)
           .order_by(SeverityUnitChoice.since.desc(), SeverityUnitChoice.id.desc()).first())
    return row.score if row and row.score and row.score.status == "active" else None


def choose(unit_kind, score, since, user, note=None):
    """From ``since`` this unit uses ``score`` (or none). Earlier children
    keep the score they were scored with."""
    from app.models import ActivityLog, SeverityUnitChoice

    if unit_kind not in UNITS:
        return "unit"
    if score is not None and score.status != "active":
        return "not_active"
    db.session.add(SeverityUnitChoice(unit_kind=unit_kind, score_id=score.id if score else None,
                                      since=since, set_by=user.id,
                                      note=(note or "").strip()[:255] or None))
    ActivityLog.record("severity.unit_choice", user_id=user.id, entity="severity_unit",
                       detail=f"{unit_kind}: {score.key + ' v' + str(score.version) if score else '—'} from {since}")
    return None


def history(unit_kind):
    from app.models import SeverityUnitChoice

    return (SeverityUnitChoice.query.filter_by(unit_kind=unit_kind)
            .order_by(SeverityUnitChoice.since.desc(), SeverityUnitChoice.id.desc()).all())


# -------------------------------------------------------------- a child --
def entered(admission, unit_kind):
    """When this stay first entered a bed of that kind of unit, or ``None``."""
    from app.models import BedStay
    from app.models.place import Bed, Space, Unit

    row = (db.session.query(BedStay.since)
           .join(Bed, BedStay.bed_id == Bed.id).join(Space, Bed.space_id == Space.id)
           .join(Unit, Space.unit_id == Unit.id)
           .filter(BedStay.admission_id == admission.id, Unit.kind == unit_kind)
           .order_by(BedStay.since).first())
    return row[0] if row else None


def window(score, moment):
    return (moment - timedelta(hours=score.window_before_h or 0),
            moment + timedelta(hours=score.window_after_h or 0))


def record(admission, unit_kind, measured_at, values, user):
    """Score this child on entering the unit. ``(row, None)`` or
    ``(None, why)``. Refused outside the score's window, and refused when a
    required reading is missing — never filled in."""
    from app.models import SeverityRecord
    from app.utils.clock import local_date

    came = entered(admission, unit_kind)
    if came is None:
        return None, "not_in_unit"
    score = choice(unit_kind, on=local_date(came))
    if score is None:
        return None, "no_score"
    if SeverityRecord.query.filter_by(admission_id=admission.id, unit_kind=unit_kind).first():
        return None, "already"
    start, end = window(score, came)
    if not start <= measured_at <= end:
        return None, "window"
    got = compute(score, values)
    if got.get("error"):
        return None, got["error"]
    row = SeverityRecord(admission_id=admission.id, patient_id=admission.patient_id,
                         unit_kind=unit_kind, score_id=score.id, entered_at=came,
                         measured_at=measured_at, values=values, missing=got["missing"],
                         points=got["points"], probability=got["probability"],
                         recorded_by=user.id)
    db.session.add(row)
    return row, None


# -------------------------------------------------------------- the unit --
Z95 = 1.959964


def interval(observed, expected):
    """The 95% interval of observed ÷ expected — Byar's approximation to the
    Poisson interval of the observed count, divided by the expected."""
    if not expected:
        return None, None
    o = observed
    if o == 0:
        low = 0.0
    else:
        low = o * (1 - 1 / (9 * o) - Z95 / (3 * math.sqrt(o))) ** 3
    o1 = o + 1
    high = o1 * (1 - 1 / (9 * o1) + Z95 / (3 * math.sqrt(o1))) ** 3
    return round(low / expected, 2), round(high / expected, 2)


def board(unit_kind, today=None, months=12):
    """The unit over the last ``months`` months, by the day each child left:
    children, deaths, expected deaths, SMR with its interval, the VLAD line
    and — with enough children — expected against observed in five groups."""
    from app.models import Admission, SeverityRecord
    from app.utils.clock import local_today, to_utc

    today = today or local_today()
    since = today - timedelta(days=round(months * 30.44))
    start = to_utc(datetime.combine(since, datetime.min.time())).replace(tzinfo=None)
    rows = (SeverityRecord.query.join(Admission, SeverityRecord.admission_id == Admission.id)
            .filter(SeverityRecord.unit_kind == unit_kind,
                    Admission.discharged_at.isnot(None), Admission.discharged_at >= start)
            .order_by(Admission.discharged_at, SeverityRecord.id).all())
    scored = [r for r in rows if r.probability is not None]
    n = len(scored)
    observed = sum(1 for r in scored if r.admission.outcome == "died")
    expected = round(sum(r.probability for r in scored), 2)
    smr = round(observed / expected, 2) if expected else None
    low, high = interval(observed, expected)
    vlad, running = [], 0.0
    for r in scored:
        running += r.probability - (1 if r.admission.outcome == "died" else 0)
        vlad.append((r.admission.discharged_at, round(running, 2)))
    groups = []
    if n >= 5 * 10:
        ordered = sorted(scored, key=lambda r: r.probability)
        size = n / 5.0
        for g in range(5):
            part = ordered[round(g * size):round((g + 1) * size)]
            groups.append({"n": len(part),
                           "expected": round(sum(r.probability for r in part), 1),
                           "observed": sum(1 for r in part if r.admission.outcome == "died"),
                           "top": round(max(r.probability for r in part) * 100, 1)})
    versions = sorted({r.score.display_name() for r in scored})
    return {"n": n, "observed": observed, "expected": expected, "smr": smr,
            "low": low, "high": high, "vlad": vlad, "groups": groups,
            "few": n < FEW, "since": since, "to": today, "versions": versions,
            "unscored": len(rows) - n}
