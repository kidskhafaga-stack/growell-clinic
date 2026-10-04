"""Critical results: saying one, and telling a doctor — GAHAR ICD.19 / GSR.03.

Written first for the laboratory, and now for the three rooms that answer an
order: the lab, radiology and the device studies. A film can carry a
critical finding as surely as a potassium can, and the policy (أ) asks for
*"lists of critical results and values"*, not lab values alone.

ICD.19 (ج) names what each notification records, and each is a column:
(١) date and time — ``critical_called_at``; (٢) who notified —
``critical_called_by``; (٣) who was notified — ``critical_called_to``;
(٤) how it was conveyed — ``critical_call_method`` and the read-back; (٥)
the result conveyed — the order itself; (٦) **any difficulties** —
``critical_difficulty``. And (ب) the reporting **timeframe** is the
hospital's (``critical_call_minutes``): until it writes one, nothing is late.

Asked as *«القيم الحرجة مش المفروض المعمل يقدر يكتبها»*. The critical limits
are the laboratory's (set on each test's ranges), and a number past them is
flagged by itself; the doctor then says they read it. What the lab could not
do was its own two acts:

* **mark a result critical by hand** — a positive blood culture, a smear
  with blasts: no number crosses a limit, and the technician is the one who
  knows. The reason is written, and no later number takes the mark away;
* **record telling a doctor** — whom, how (telephone, in person, a message),
  when, by whom, and whether the doctor read the value back. The doctor's
  own «I read it» stays the doctor's (`lab_results.mark_read`).
"""
from datetime import datetime

from app.extensions import db

CALL_METHODS = ("phone", "in_person", "message")
#: The rooms whose results can be critical.
KINDS = ("lab", "imaging", "diagnostic")
TIMEFRAME_SETTING = "critical_call_minutes"


class CriticalError(ValueError):
    """A refusal with a key the screen can name (``lab_critical.err_<key>``)."""


def mark(order, reason, user=None, at=None):
    """The technician says this result is critical."""
    from app.utils.lab_results import invalidate

    reason = (reason or "").strip()[:200]
    if order is None or order.kind not in KINDS:
        raise CriticalError("not_lab")
    if not reason:
        raise CriticalError("need_reason")
    if not order.has_result:
        raise CriticalError("no_result")
    order.critical_manual = reason
    if order.critical_at is None:
        order.critical_at = at or datetime.utcnow()
        order.critical_seen_at = order.critical_seen_by = None
    invalidate()
    db.session.flush()
    return order


def call(order, called_to, method, read_back, user=None, at=None,
         difficulty=None):
    """The lab told a doctor — and what made it hard, when something did."""
    called_to = (called_to or "").strip()[:120]
    if order is None or order.critical_at is None:
        raise CriticalError("not_critical")
    if not called_to:
        raise CriticalError("need_who")
    if method not in CALL_METHODS:
        raise CriticalError("bad_method")
    order.critical_called_to = called_to
    order.critical_call_method = method
    order.critical_read_back = bool(read_back)
    order.critical_called_at = at or datetime.utcnow()
    order.critical_called_by = getattr(user, "id", None)
    order.critical_difficulty = (difficulty or "").strip()[:200] or None
    db.session.flush()
    return order


# -------------------------------------------------------------- the door --
#: The modules whose being on opens the critical screens. Not the visits
#: module: every clinic has it, and a clinic with neither a lab nor a
#: radiology module sees nothing of critical results — exactly as before.
#: A device study's critical finding is told wherever one of these is on.
ROOMS = ("labs", "imaging")


def rooms_on():
    from app.utils.facility import module_enabled

    return [m for m in ROOMS if module_enabled(m)]


# ------------------------------------------------------------- the clock --
def timeframe():
    """The hospital's minutes from a critical result to the call, or
    ``None`` until it writes one (ICD.19 ب)."""
    from app.models import Setting

    try:
        value = int(Setting.get(TIMEFRAME_SETTING) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def minutes_to_call(order):
    if order.critical_at is None or order.critical_called_at is None:
        return None
    return max(0, int((order.critical_called_at - order.critical_at).total_seconds() // 60))


def late_call(order, now=None):
    """Past the hospital's timeframe — called late, or not yet called and
    already past it. ``None`` when the hospital has written no timeframe."""
    limit = timeframe()
    if not limit or order.critical_at is None:
        return None
    if order.critical_called_at is not None:
        return minutes_to_call(order) > limit
    return ((now or datetime.utcnow()) - order.critical_at).total_seconds() / 60 > limit


def report(start, end):
    """Every critical result between two clinic days, and the figures the
    hospital monitors (ICD.19 دليل ٤): how many, told, told in time, read
    back, with a difficulty, and read by a doctor."""
    from datetime import time

    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation
    from app.utils.clock import to_utc

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient))
            .filter(VisitInvestigation.critical_at >= since,
                    VisitInvestigation.critical_at <= until)
            .order_by(VisitInvestigation.critical_at.desc()).all())
    sums = {"total": len(rows),
            "called": sum(1 for r in rows if r.critical_called_at),
            "late": sum(1 for r in rows if late_call(r)),
            "no_read_back": sum(1 for r in rows if r.critical_called_at and not r.critical_read_back),
            "difficulty": sum(1 for r in rows if r.critical_difficulty),
            "read": sum(1 for r in rows if r.critical_seen_at),
            "by_kind": {k: sum(1 for r in rows if r.kind == k) for k in KINDS}}
    return rows, sums


def doctor_names():
    """Who a critical result is telephoned to — the box's suggestions."""
    from app.models import User

    rows = (User.query.filter(User.is_active.is_(True),
                              db.or_(User.role == "doctor", User.is_practitioner.is_(True)))
            .order_by(User.full_name).all())
    return [u.full_name for u in rows if u.full_name]

