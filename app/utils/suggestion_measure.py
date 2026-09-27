"""How often does the desk change the program's suggested time?

``BOOKING_APPROVAL_PLAN.md`` stage five is not a thing to build — it is a
decision, after two months of use, about whether one kind of request (the
vaccination follow-up, say) can be booked without a person choosing the
time. The plan says it is to be decided **by the numbers, not by opinion**,
and the numbers are these: of the requests booked, how many kept the time
the card suggested, and how many moved it — to another time the same day,
another day, or another doctor.

Recorded from the day this shipped (``booking_requests.booked``); a request
booked before then has no record, and none is made up for it. The counting
is all here; the screen only draws it.
"""
from collections import Counter
from datetime import datetime, timedelta

from app.models import BookingRequest
from app.models.booking_request import SUGGESTION_OUTCOMES

#: The periods the screen offers, in days; ``None`` is everything recorded.
PERIODS = (30, 60, 90, None)

#: What the desk can do with a suggestion. ``none`` is kept apart: when
#: nothing was free there was no suggestion to keep or to change.
CHANGES = tuple(o for o in SUGGESTION_OUTCOMES if o != "none")


def _share(counts):
    """``{outcome: (count, percent)}`` over the ones that had a suggestion,
    and that total. Percentages are whole numbers that add up to 100."""
    total = sum(counts.get(o, 0) for o in CHANGES)
    if not total:
        return {o: (0, 0) for o in CHANGES}, 0
    raw = {o: counts.get(o, 0) * 100 / total for o in CHANGES}
    whole = {o: int(v) for o, v in raw.items()}
    # Hand the rounding leftovers to the largest remainders, so the bar is
    # never 99% or 101% wide.
    for o in sorted(CHANGES, key=lambda o: raw[o] - whole[o],
                    reverse=True)[:100 - sum(whole.values())]:
        whole[o] += 1
    return {o: (counts.get(o, 0), whole[o]) for o in CHANGES}, total


def report(days=None, now=None):
    """The numbers for the last ``days`` days (all of them for ``None``)."""
    now = now or datetime.utcnow()
    query = BookingRequest.query.filter(
        BookingRequest.suggestion_outcome.isnot(None))
    first = (query.with_entities(BookingRequest.decided_at)
             .order_by(BookingRequest.decided_at).first())
    if days:
        query = query.filter(BookingRequest.decided_at >= now - timedelta(days=days))
    rows = query.all()

    counts = Counter(r.suggestion_outcome for r in rows)
    shares, suggested = _share(counts)
    by_type = {}
    for row in rows:
        by_type.setdefault(row.appt_type or "", Counter())[row.suggestion_outcome] += 1
    by_source = {}
    for row in rows:
        by_source.setdefault(row.source or "desk", Counter())[row.suggestion_outcome] += 1

    def lines(groups):
        out = []
        for key, group in groups.items():
            share, total = _share(group)
            if total:
                out.append({"key": key, "total": total, "share": share})
        return sorted(out, key=lambda line: (-line["total"], line["key"]))

    return {
        "days": days,
        "since": first[0].date() if first else None,
        "booked": len(rows),
        "suggested": suggested,
        "nothing_free": counts.get("none", 0),
        "share": shares,
        "by_type": lines(by_type),
        "by_source": lines(by_source),
    }
