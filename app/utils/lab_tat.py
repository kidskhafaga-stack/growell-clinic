"""How long the laboratory took — GAHAR DAS.21 and DAS.22.

*"Turnaround Time (TAT) … from the moment a specimen is collected from a
patient until the results … are reported"* (DAS.21). Four pieces of
evidence, and each is here:

1. **each test's turnaround and how it is measured** — the figure is the
   laboratory's own (routine and STAT, on the tests list); it is measured
   from the sample's collection to the result, nothing invented;
2. **unacceptable turnarounds investigated** — every late result is listed
   with the reason the laboratory wrote, or says no reason was written;
3. **the data monitored** — per test, per period: how many, the median and
   the slowest tenth, how many within the time, routine and STAT apart;
4. **delays told to the requester** — who was told, when, by whom.

And DAS.22 دليل ٢, **the STAT list**: the tests the laboratory gave a STAT
time, with that time.

A result is only ever judged against a figure the laboratory wrote. A test
with no time on it is counted and measured, and never called late.
"""
from datetime import datetime, time

from app.extensions import db


class DelayError(ValueError):
    """A refusal with a key the screen can name (``lab_tat.err_<key>``)."""


#: The kinds whose turnaround is measured here — the laboratory (DAS.21/22)
#: and radiology (DAS.07, *"findings are reported within approved
#: timeframe"*).
KINDS = ("lab", "imaging")


def _start(order):
    """The laboratory's clock runs from the sample; radiology's from the
    scan being done — before it there is nothing to report."""
    return order.performed_at if order.kind == "imaging" else order.collected_at


def minutes(order):
    """Collection (or, for a scan, the study) to result, in whole minutes,
    or ``None``."""
    start = _start(order)
    if start is None or order.resulted_at is None:
        return None
    return max(0, int((order.resulted_at - start).total_seconds() // 60))


def waiting_late(order, now=None):
    """Done but not yet reported past its time — ``None`` when no time was
    written or the clock has not started."""
    from app.utils.lab_results import limit_minutes

    limit = limit_minutes(order)
    start = _start(order)
    if not limit or start is None or order.status == "resulted" or order.done_outside:
        return None
    return ((now or datetime.utcnow()) - start).total_seconds() / 60 > limit


def was_late(order):
    """Reported past the laboratory's time — ``None`` when it gave none or
    the order has no collection and result to measure."""
    from app.utils.lab_results import limit_minutes

    took = minutes(order)
    limit = limit_minutes(order)
    if took is None or not limit:
        return None
    return took > limit


def tell_delay(order, told_to, reason=None, user=None, at=None):
    """The requester was told this result is late — and why, when known."""
    told_to = (told_to or "").strip()[:120]
    if order is None or order.kind not in KINDS:
        raise DelayError("not_lab")
    if not told_to:
        raise DelayError("need_who")
    order.delay_told_to = told_to
    order.delay_told_at = at or datetime.utcnow()
    order.delay_told_by = getattr(user, "id", None)
    reason = (reason or "").strip()[:200]
    if reason:
        order.delay_reason = reason
    db.session.flush()
    return order


def explain(order, reason):
    """Why a result was late — the investigation DAS.21 دليل ٢ asks for."""
    reason = (reason or "").strip()[:200]
    if order is None or order.kind not in KINDS:
        raise DelayError("not_lab")
    if not reason:
        raise DelayError("need_reason")
    order.delay_reason = reason
    db.session.flush()
    return order


def _percentile(sorted_values, share):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, int(round(share * (len(sorted_values) - 1)))))
    return sorted_values[index]


def report(start, end, kind="lab"):
    """``(per_test, late_rows)`` for lab results reported between two clinic
    days. ``per_test`` rows: test, urgent, count, median, p90, limit, within,
    late — routine and urgent apart, slowest first."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation
    from app.utils.clock import to_utc
    from app.utils.lab_results import limit_minutes

    since = to_utc(datetime.combine(start, time.min))
    until = to_utc(datetime.combine(end, time.max))
    rows = (VisitInvestigation.query
            .options(selectinload(VisitInvestigation.patient),
                     selectinload(VisitInvestigation.investigation))
            .filter(VisitInvestigation.kind == kind,
                    VisitInvestigation.status == "resulted",
                    (VisitInvestigation.performed_at if kind == "imaging"
                     else VisitInvestigation.collected_at).isnot(None),
                    VisitInvestigation.resulted_at >= since,
                    VisitInvestigation.resulted_at <= until)
            .order_by(VisitInvestigation.resulted_at).all())
    groups = {}
    late_rows = []
    for row in rows:
        took = minutes(row)
        key = (row.investigation_id or row.name, bool(row.urgent))
        entry = groups.setdefault(key, {"name": row.name, "sample": row, "urgent": bool(row.urgent),
                                        "values": [], "limit": limit_minutes(row),
                                        "within": 0, "late": 0})
        entry["values"].append(took)
        verdict = was_late(row)
        if verdict is True:
            entry["late"] += 1
            late_rows.append(row)
        elif verdict is False:
            entry["within"] += 1
    per_test = []
    for entry in groups.values():
        values = sorted(entry.pop("values"))
        entry["count"] = len(values)
        entry["median"] = _percentile(values, 0.5)
        entry["p90"] = _percentile(values, 0.9)
        per_test.append(entry)
    per_test.sort(key=lambda e: (-(e["late"]), -(e["p90"] or 0), e["name"]))
    return per_test, late_rows


def stat_list(kind="lab"):
    """DAS.22 دليل ٢ — the tests the laboratory gave a STAT time."""
    from app.models import Investigation

    return (Investigation.query
            .filter(Investigation.kind == kind, Investigation.is_active.is_(True),
                    db.or_(Investigation.tat_stat_max.isnot(None),
                           Investigation.tat_stat_min.isnot(None)))
            .order_by(Investigation.name_ar).all())
