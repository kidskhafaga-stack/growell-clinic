"""«تحليل الأسباب» — the fishbone and the Pareto (RCA_PLAN.md).

**Nothing on the screen is a new fact.** A problem's causes are either written
by the quality team or the department's head (``RcaCause``), or counted from
what the program already holds: the complaints of the period by the root cause
they were closed with and what they were about, and the incident reports by
the bone their reviewer chose and their kind. The Pareto and the fishbone are
the same list, drawn twice.

**Who sees it.** The quality team (whoever reviews the incident reports) and
the administration see every problem; a department's head (``CostCentre.
head_id``) sees the problems of their own department, and the counted ones
only for it.
"""
import time
from collections import Counter

from app.extensions import db
from app.models.complaint import ROOT_CAUSES
from app.models.rca import SOURCES, SYSTEM_SOURCES, RcaCause, RcaProblem

#: The bones, in the order they are drawn. ``unclear`` is listed in the table
#: but never drawn: a bone called «not clear» is not a cause.
BONES = tuple(c for c in ROOT_CAUSES if c != "unclear")
#: The share of the problem the first causes are read to — the Pareto line.
PARETO_LINE = 80
#: Causes drawn on each bone; the rest are in the table.
PER_BONE = 3


class RcaError(ValueError):
    pass


# ------------------------------------------------------------- who sees ---
_HEADS = {"at": 0.0, "ids": None}
HEADS_TTL = 60


def heads():
    """The ids of every department head — asked by the menu on every page,
    so kept for a minute."""
    if _HEADS["ids"] is not None and time.time() - _HEADS["at"] < HEADS_TTL:
        return _HEADS["ids"]
    from app.models import CostCentre

    ids = {row[0] for row in db.session.query(CostCentre.head_id)
           .filter(CostCentre.head_id.isnot(None)).all()}
    _HEADS["at"], _HEADS["ids"] = time.time(), ids
    return ids


def forget_heads():
    _HEADS["at"], _HEADS["ids"] = 0.0, None


def is_team(user):
    from app.utils import incidents as inc

    return bool(user) and getattr(user, "is_authenticated", True) and (
        user.is_admin or inc.may_review(user))


def headed(user):
    """The departments this person heads."""
    from app.models import CostCentre

    if not user or user.id not in heads():
        return []
    return CostCentre.query.filter_by(head_id=user.id, is_active=True).all()


def may_open(user):
    return is_team(user) or bool(user and user.id in heads())


def may_edit(user, problem):
    if is_team(user):
        return True
    return problem is not None and problem.cost_centre_id in {c.id for c in headed(user)}


def visible(user):
    """The problems this person may see, open first, newest first."""
    q = RcaProblem.query
    if not is_team(user):
        ids = [c.id for c in headed(user)]
        if not ids:
            return []
        q = q.filter(RcaProblem.cost_centre_id.in_(ids))
    return q.order_by(RcaProblem.closed_at.isnot(None), RcaProblem.created_at.desc()).all()


# -------------------------------------------------------- the measure -----
def measure_state(measure, baseline=None):
    """``{now, period, before, change_pct, off, moved, better}`` for a
    measure: its latest value, the one before, and — against the value the
    problem was opened at — whether it moved the right way."""
    from app.utils import quality as q

    vals = [v for v in measure.values if v.value is not None]
    if not vals:
        return None
    now, prev = vals[-1], (vals[-2] if len(vals) > 1 else None)
    change = (round((now.value - prev.value) / prev.value * 100)
              if prev is not None and prev.value else None)
    moved = better = None
    if baseline is not None and measure.higher_better is not None:
        moved = round(now.value - baseline, 2)
        better = None if moved == 0 else (moved > 0) == bool(measure.higher_better)
    return {"now": round(now.value, 2), "period": now.period,
            "before": round(prev.value, 2) if prev is not None else None,
            "change_pct": change, "off": q.off_target(measure, now.value),
            "moved": moved, "better": better}


def off_target_measures():
    """Active measures whose latest value misses the hospital's target and
    that no open problem is studying yet — offered as problems to open."""
    from app.models import PerformanceMeasure

    studied = {p.measure_id for p in RcaProblem.query.filter(
        RcaProblem.closed_at.is_(None), RcaProblem.measure_id.isnot(None)).all()}
    out = []
    for m in PerformanceMeasure.query.filter_by(is_active=True).order_by(PerformanceMeasure.name).all():
        if m.id in studied:
            continue
        state = measure_state(m)
        if state and state["off"]:
            out.append((m, state))
    return out


# ------------------------------------------------------------ the causes --
def _complaint_causes(problem, start, end):
    from app.models import Complaint

    q = Complaint.query.filter(Complaint.kind == "complaint",
                               Complaint.created_at >= start, Complaint.created_at < end)
    if problem.cost_centre_id:
        q = q.filter(Complaint.cost_centre_id == problem.cost_centre_id)
    counts = Counter((c.root_cause or "unclear", c.category or "") for c in q.all())
    return [{"category": bone, "label": ("cmp.cat_" + what) if what else "rca.no_category",
             "weight": n, "source": "system"} for (bone, what), n in counts.items()]


def _incident_causes(problem, start, end):
    from app.models import Incident

    q = Incident.query.filter(Incident.occurred_at >= start, Incident.occurred_at < end)
    if problem.cost_centre_id and problem.cost_centre and problem.cost_centre.unit_id:
        q = q.filter(Incident.unit_id == problem.cost_centre.unit_id)
    elif problem.cost_centre_id:
        return []
    counts = Counter((i.cause_category or "unclear", i.category) for i in q.all())
    return [{"category": bone, "label": "incident.c_" + what, "weight": n, "source": "system"}
            for (bone, what), n in counts.items()]


def system_total(problem, start, end):
    """How many complaints or incidents the counted problem is, in a window."""
    return sum(c["weight"] for c in _counted(problem, start, end))


def _counted(problem, start, end):
    if problem.source == "complaints":
        return _complaint_causes(problem, start, end)
    if problem.source == "incidents":
        return _incident_causes(problem, start, end)
    return []


def causes(problem, start, end, only=None):
    """Every cause of a problem, heaviest first: the ones written down, and —
    for a counted problem — the ones counted in the window. ``only`` is
    ``system`` or ``manual``."""
    rows = []
    if only != "system":
        for c in problem.causes:
            if c.is_active:
                rows.append({"category": c.category, "text": c.text, "weight": c.weight,
                             "source": "manual", "id": c.id, "row": c})
    if only != "manual":
        rows.extend(_counted(problem, start, end))
    rows.sort(key=lambda r: (-r["weight"], r.get("text") or r.get("label") or ""))
    return rows


def pareto(rows, line=PARETO_LINE):
    """The rows with their share and running share, and how many it takes
    to reach the line — «the vital few»."""
    total = sum(r["weight"] for r in rows) or 0
    out, running, vital = [], 0, 0
    for r in rows:
        share = r["weight"] * 100.0 / total if total else 0
        before = running
        running += share
        if total and before < line:
            vital += 1
        out.append({**r, "share": round(share, 1), "running": round(min(running, 100.0), 1),
                    "vital": bool(total) and before < line})
    return {"rows": out, "total": total, "vital": vital}


def by_bone(rows):
    """``[(bone, weight, share)]`` heaviest first — the strip under the
    Pareto."""
    total = sum(r["weight"] for r in rows)
    tally = Counter()
    for r in rows:
        tally[r["category"]] += r["weight"]
    return [(bone, n, round(n * 100.0 / total, 1) if total else 0)
            for bone, n in tally.most_common()]


# ------------------------------------------------------------ the drawing --
def pareto_chart(rows, width=440, height=250, most=10):
    """The bars and the running line on one scale. The bars are drawn in
    descending order from the right (the screen reads right to left)."""
    rows = rows[:most]
    if not rows:
        return None
    left, right, top, bottom = 34, 12, 14, 28
    inner_w, inner_h = width - left - right, height - top - bottom
    biggest = max(r["weight"] for r in rows) or 1
    step = inner_w / len(rows)
    bars, points = [], []
    for i, r in enumerate(rows):
        # First (heaviest) on the right.
        x = left + inner_w - (i + 1) * step + step * 0.15
        h = r["weight"] / biggest * inner_h
        bars.append({"x": round(x, 1), "y": round(top + inner_h - h, 1),
                     "w": round(step * 0.7, 1), "h": round(h, 1), "n": i + 1,
                     "vital": r["vital"], "weight": r["weight"],
                     "cx": round(x + step * 0.35, 1)})
        points.append((round(x + step * 0.35, 1), round(top + inner_h - r["running"] / 100 * inner_h, 1)))
    return {"w": width, "h": height, "bars": bars,
            "line": " ".join(f"{x},{y}" for x, y in points), "dots": points,
            "y80": round(top + inner_h - PARETO_LINE / 100 * inner_h, 1),
            "y100": top, "y50": round(top + inner_h / 2, 1), "y0": top + inner_h,
            "left": left, "right": width - right, "base": top + inner_h}


def fishbone(rows, width=1000, height=440, title=""):
    """Bones, their causes and where to write them. Up to :data:`PER_BONE`
    causes on each bone, heaviest first; a bone with nothing on it is not
    drawn, so the picture is only what is known.

    Each cause is a twig reaching from its bone towards the head, its words
    above the twig — in the space between two bones, so neighbours do not
    write over each other."""
    groups = {}
    for r in rows:
        if r["category"] in BONES:
            groups.setdefault(r["category"], []).append(r)
    order = [b for b in BONES if b in groups]
    total = sum(r["weight"] for r in rows) or 0
    spine_y = height / 2
    head_w, tail_x = 190, width - 50
    top, bottom = order[0::2], order[1::2]
    slots = max(len(top), len(bottom), 1)
    first = head_w + 40
    gap = (tail_x - 90 - first) / slots
    reach = gap * 0.62
    bones = []
    for side, group in (("top", top), ("bottom", bottom)):
        sign = -1 if side == "top" else 1
        for i, bone in enumerate(group):
            # The heaviest bones nearest the head.
            x0 = first + gap * i + gap * 0.62
            x1, y1 = x0 + 70, spine_y + sign * (spine_y - 52)
            twigs = []
            for k, r in enumerate(groups[bone][:PER_BONE]):
                f = 0.3 + 0.27 * k
                px, py = x0 + (x1 - x0) * f, spine_y + (y1 - spine_y) * f
                twigs.append({"x": round(px, 1), "y": round(py, 1), "row": r,
                              "end": round(px - reach, 1),
                              "tx": round(px - 8, 1), "nx": round(px - reach + 2, 1)})
            weight = sum(r["weight"] for r in groups[bone])
            bones.append({"bone": bone, "side": side, "x0": round(x0, 1), "y0": spine_y,
                          "x1": round(x1, 1), "y1": round(y1, 1), "twigs": twigs,
                          "share": round(weight * 100.0 / total) if total else 0,
                          "lx": round(x1, 1), "ly": round(y1 + sign * 20, 1)})
    words, lines = (title or "").split(), [""]
    for w in words:
        if len(lines[-1]) + len(w) + 1 > 16 and lines[-1]:
            if len(lines) == 2:
                lines[-1] = lines[-1].rstrip() + "…"
                break
            lines.append("")
        lines[-1] = (lines[-1] + " " + w).strip()
    return {"w": width, "h": height, "spine_y": spine_y, "head_w": head_w,
            "tail_x": tail_x, "bones": bones, "total": total, "title": lines,
            "reach": reach, "pill_w": round(min(176, gap - 12), 1),
            # Characters the pill holds at 12.5px, beside « · 30%».
            "pill_chars": max(6, int((min(176, gap - 12) - 52) / 7.2))}


# ---------------------------------------------------------------- writes --
def _text(raw, limit):
    raw = (raw or "").strip()
    return raw[:limit] if raw else None


def open_problem(form, user):
    """A problem: a measure, the complaints, the incidents, or written in.
    A department head opens problems only for a department they head."""
    from app.models import CostCentre, PerformanceMeasure

    source = form.get("source") if form.get("source") in SOURCES else "manual"
    centre = db.session.get(CostCentre, int(form.get("cost_centre_id") or 0) or 0)
    if not is_team(user):
        mine = {c.id for c in headed(user)}
        if centre is None or centre.id not in mine:
            raise RcaError("centre")
    measure = None
    title = _text(form.get("title"), 200)
    if source == "measure":
        measure = db.session.get(PerformanceMeasure, int(form.get("measure_id") or 0) or 0)
        if measure is None:
            raise RcaError("measure")
        title = title or measure.name
    if source in SYSTEM_SOURCES and not title:
        from app.i18n import t

        title = t("rca.src_" + source)
    if not title:
        raise RcaError("title")
    row = RcaProblem(title=title, source=source, measure_id=getattr(measure, "id", None),
                     cost_centre_id=getattr(centre, "id", None),
                     note=_text(form.get("note"), 4000), by_id=user.id)
    if measure is not None:
        state = measure_state(measure)
        if state:
            row.baseline, row.baseline_period = state["now"], state["period"]
    db.session.add(row)
    db.session.flush()
    return row


def add_cause(problem, form, user):
    if problem is None or not problem.is_open:
        raise RcaError("closed")
    bone = form.get("category")
    text = _text(form.get("text"), 200)
    if bone not in ROOT_CAUSES:
        raise RcaError("bone")
    if not text:
        raise RcaError("text")
    try:
        weight = max(1, min(100000, int(form.get("weight") or 1)))
    except (TypeError, ValueError):
        raise RcaError("weight") from None
    row = RcaCause(problem_id=problem.id, category=bone, text=text, weight=weight,
                   note=_text(form.get("note"), 255), by_id=user.id)
    db.session.add(row)
    db.session.flush()
    return row


def edit_cause(cause, form):
    if form.get("remove") == "1":
        cause.is_active = False
        return cause
    if form.get("category") in ROOT_CAUSES:
        cause.category = form.get("category")
    text = _text(form.get("text"), 200)
    if text:
        cause.text = text
    if form.get("weight"):
        try:
            cause.weight = max(1, min(100000, int(form.get("weight"))))
        except (TypeError, ValueError):
            raise RcaError("weight") from None
    return cause


def to_project(cause, form):
    """«ابدأ مشروع تحسين» from a cause — the project knows the problem, the
    cause and the measure; its aim is the person's to write."""
    from datetime import date

    from app.models import ImprovementProject

    if cause.project_id:
        return cause.project
    aim = _text(form.get("aim"), 4000)
    if not aim:
        raise RcaError("aim")
    problem = cause.problem
    row = ImprovementProject(title=cause.text[:200], problem=f"{problem.title} — {cause.text}",
                             aim=aim, method="PDCA", measure_id=problem.measure_id,
                             started_on=date.today())
    db.session.add(row)
    db.session.flush()
    cause.project_id = row.id
    return row


def close(problem):
    from datetime import datetime

    problem.closed_at = None if problem.closed_at else datetime.utcnow()
    return problem
