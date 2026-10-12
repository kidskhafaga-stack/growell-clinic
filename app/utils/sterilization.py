"""The sterilization logbook — see ``models/sterilization``.

A cycle is judged only against what the hospital set for that sterilizer:
an unset limit judges nothing. The two cadences the board speaks of are the
standard's own words: Bowie-Dick/Helix *"every day before starting to use
the autoclave"* (IPC.15 a v) and the biological indicator *"at least
weekly"* (a iv).
"""
from datetime import datetime

from app.extensions import db
from app.models.sterilization import (BI_RESULTS, CYCLE_KINDS, RESULTS, HldTest,
                                      SterilizationReview, Sterilizer, SterilizerCycle)

#: IPC.15 a iv — «at least weekly».
BI_EVERY_DAYS = 7


class SterilizationError(ValueError):
    """A refusal with a locale key (``steril.err_<key>``)."""


def _float(raw):
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _text(raw, limit):
    s = (raw or "").strip()
    return s[:limit] or None


def may_record(user):
    """Whoever runs the sterilizer: theatres, the ward, or infection control."""
    from app.utils import ipc

    return bool(ipc.may_review(user) or (user is not None and (
        user.can_access("theatres") or user.can_access("beds"))))


def save_sterilizer(form, row=None):
    name = _text(form.get("name"), 120)
    if not name:
        raise SterilizationError("name")
    row = row or Sterilizer()
    row.name = name
    row.serial = _text(form.get("serial"), 80)
    row.location = _text(form.get("location"), 120)
    row.temp_min, row.temp_max = _float(form.get("temp_min")), _float(form.get("temp_max"))
    row.minutes_min = _int(form.get("minutes_min"))
    row.pressure_min, row.pressure_max = _float(form.get("pressure_min")), _float(form.get("pressure_max"))
    db.session.add(row)
    db.session.flush()
    return row


def outside(sterilizer, cycle):
    """The physical values outside the hospital's limits — ``[name]``."""
    out = []
    t, m, p = cycle.temperature, cycle.minutes, cycle.pressure
    if t is not None and ((sterilizer.temp_min is not None and t < sterilizer.temp_min)
                          or (sterilizer.temp_max is not None and t > sterilizer.temp_max)):
        out.append("temperature")
    if m is not None and sterilizer.minutes_min is not None and m < sterilizer.minutes_min:
        out.append("minutes")
    if p is not None and ((sterilizer.pressure_min is not None and p < sterilizer.pressure_min)
                          or (sterilizer.pressure_max is not None and p > sterilizer.pressure_max)):
        out.append("pressure")
    return out


def record_cycle(sterilizer, form, user):
    kind = form.get("kind")
    if kind not in CYCLE_KINDS:
        raise SterilizationError("kind")
    chemical = form.get("chemical")
    if chemical not in RESULTS:
        raise SterilizationError("chemical")
    bi = form.get("bi") or None
    if bi is not None and bi not in BI_RESULTS:
        raise SterilizationError("bi")
    row = SterilizerCycle(sterilizer_id=sterilizer.id, kind=kind,
                          cycle_no=_text(form.get("cycle_no"), 30),
                          temperature=_float(form.get("temperature")),
                          minutes=_int(form.get("minutes")),
                          pressure=_float(form.get("pressure")),
                          chemical=chemical, bi=bi if kind == "load" else None,
                          action=_text(form.get("action"), 255),
                          run_by=getattr(user, "id", None))
    row.failed = bool(chemical == "fail" or bi == "fail" or outside(sterilizer, row))
    if row.failed and not row.action:
        raise SterilizationError("action")
    db.session.add(row)
    db.session.flush()
    return row


def read_bi(cycle, form, user):
    result = form.get("bi")
    if cycle.bi != "pending" or result not in RESULTS:
        raise SterilizationError("bi")
    cycle.bi = result
    cycle.bi_read_at = datetime.utcnow()
    if result == "fail":
        action = _text(form.get("action"), 255)
        if not action:
            raise SterilizationError("action")
        cycle.failed = True
        cycle.action = action
    db.session.flush()
    return cycle


def record_hld(form, user):
    solution = _text(form.get("solution"), 120)
    if not solution:
        raise SterilizationError("solution")
    result = form.get("result")
    if result not in RESULTS:
        raise SterilizationError("result")
    action = _text(form.get("action"), 255)
    if result == "fail" and not action:
        raise SterilizationError("action")
    row = HldTest(solution=solution, result=result, action=action,
                  tested_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def review(month, note, user):
    try:
        datetime.strptime(month or "", "%Y-%m")
    except ValueError:
        raise SterilizationError("month") from None
    row = SterilizationReview(month=month, note=_text(note, 255), reviewed_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def board(today):
    """Per sterilizer: today's air-removal test done?, the last biological
    indicator and whether it is past a week, pending BIs, today's cycles."""
    from app.utils.clock import to_local, to_utc

    start = to_utc(datetime.combine(today, datetime.min.time()))
    out = []
    for s in Sterilizer.query.filter_by(is_active=True).order_by(Sterilizer.name).all():
        todays = s.cycles.filter(SterilizerCycle.run_at >= start).all()
        test_today = any(c.kind in ("bowie_dick", "helix") for c in todays)
        last_bi = (s.cycles.filter(SterilizerCycle.bi.isnot(None))
                   .order_by(SterilizerCycle.run_at.desc()).first())
        bi_days = ((today - to_local(last_bi.run_at).date()).days if last_bi else None)
        pending = s.cycles.filter(SterilizerCycle.bi == "pending").all()
        out.append({"sterilizer": s, "today": todays, "test_today": test_today,
                    "bi_days": bi_days,
                    "bi_late": bi_days is None or bi_days > BI_EVERY_DAYS,
                    "pending": pending})
    return out


def months():
    """``[(month, cycles, failed, review)]`` newest first."""
    counts = {}
    for c in SterilizerCycle.query.all():
        k = c.run_at.strftime("%Y-%m")
        e = counts.setdefault(k, [0, 0])
        e[0] += 1
        e[1] += 1 if c.failed else 0
    reviews = {r.month: r for r in SterilizationReview.query.order_by(SterilizationReview.id)}
    return [(m, n, f, reviews.get(m)) for m, (n, f) in sorted(counts.items(), reverse=True)]


__all__ = ["BI_EVERY_DAYS", "SterilizationError", "board", "may_record", "months",
           "outside", "read_bi", "record_cycle", "record_hld", "review", "save_sterilizer"]
