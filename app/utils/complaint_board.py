"""The complaints and suggestions board (COMPLAINTS_PLAN.md ش-٥).

Asked as: *«داش بورد كام مشكل خلال فترة ورضا العملاء مع الربط»*.

For a period the clinic picks, against the period before it:

* how many complaints, suggestions and thank-yous, and the complaints **per
  1,000 visits** — a busy month is not a worse month;
* week by week;
* what they were about (the HCAT categories), where (the part of the clinic,
  with the survey's satisfaction for the same part beside its count), how
  they came, how serious, and what lay behind them;
* the two clocks and the family's own verdict on the answer;
* who was thanked and who was complained of — counts only, never coloured or
  ranked under :data:`MIN_FOR_STAFF`, because two complaints are not a
  verdict on a person (the rule ``cs_board`` keeps for doctors);
* the suggestions: received, decided, refused, done;
* the families who came back with more than one.

**Nothing here is a new fact**: every number is counted from the cases
(``Complaint``), the visits, and the survey (``cs_board``), so the board can be
wrong only where those are.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from app.extensions import db

#: Fewer mentions than this and a person's line is shown plain.
MIN_FOR_STAFF = 3


def _cases(start, end):
    from app.models import Complaint

    return (Complaint.query.filter(Complaint.created_at >= start, Complaint.created_at < end)
            .order_by(Complaint.created_at).all())


def _visits(start, end):
    from app.models import Visit
    from app.utils.cs_board import dates

    first, last = dates(start, end)
    return (db.session.query(db.func.count(Visit.id))
            .filter(Visit.visit_date >= first, Visit.visit_date <= last).scalar() or 0)


def _per_1000(n, visits):
    return round(n * 1000 / visits, 1) if visits else None


def _counts(rows):
    by = Counter(c.kind for c in rows)
    return {"complaint": by.get("complaint", 0), "suggestion": by.get("suggestion", 0),
            "compliment": by.get("compliment", 0), "total": len(rows)}


def _delta(now, before):
    if now is None or before is None:
        return None
    return round(now - before, 1)


def weeks(rows, start, end):
    """Week by week from the start: how many of each kind."""
    from app.utils.clock import local_date

    out, cursor = [], start
    while cursor < end:
        nxt = min(cursor + timedelta(days=7), end)
        inside = [c for c in rows if cursor <= c.created_at < nxt]
        out.append({"start": local_date(cursor), **_counts(inside)})
        cursor = nxt
    return out


def _by(rows, attr):
    return Counter(getattr(c, attr) for c in rows if getattr(c, attr)).most_common()


def by_centre(rows, start, end):
    """Each part of the clinic with complaints in the period, its count, and
    the survey's figures for the same part and period beside it."""
    from app.utils import cs_board

    survey = {r["centre"].id: r for r in cs_board.by_centre(start, end)}
    counts = Counter(c.cost_centre for c in rows if c.kind == "complaint" and c.cost_centre)
    out = []
    for centre, n in counts.most_common():
        s = survey.get(centre.id) or {}
        sides = [s.get(k) for k in ("medical", "service", "finance") if s.get(k) is not None]
        out.append({"centre": centre, "complaints": n, "answered": s.get("answered") or 0,
                    "judged": bool(s.get("judged")),
                    "survey": round(sum(sides) / len(sides), 1) if sides else None})
    return out


def staff(rows):
    """``[{user, complaint, compliment, suggestion, total, judged}]`` — by
    name, never by count: a list sorted by complaints is a ranking."""
    tally = defaultdict(Counter)
    people = {}
    for c in rows:
        for u in c.staff:
            tally[u.id][c.kind] += 1
            people[u.id] = u
    out = []
    for uid, n in tally.items():
        total = sum(n.values())
        out.append({"user": people[uid], "complaint": n.get("complaint", 0),
                    "compliment": n.get("compliment", 0), "suggestion": n.get("suggestion", 0),
                    "total": total, "judged": total >= MIN_FOR_STAFF})
    out.sort(key=lambda r: (r["user"].full_name or ""))
    return out


def suggestions(rows):
    sug = [c for c in rows if c.kind == "suggestion"]
    decided = [c for c in sug if c.decided_at]
    days = [(c.decided_at - c.created_at).total_seconds() / 86400 for c in decided]
    return {
        "received": len(sug),
        "waiting": sum(1 for c in sug if not c.decided_at and c.status != "closed"),
        "accepted": sum(1 for c in sug if c.decision == "accepted"),
        "rejected": sum(1 for c in sug if c.decision == "rejected"),
        "done": sum(1 for c in sug if c.done_at),
        "days_to_decide": round(sum(days) / len(days), 1) if days else None,
    }


def repeat_families(rows):
    """Children with more than one complaint in the period, most first."""
    n = Counter(c.patient for c in rows if c.kind == "complaint" and c.patient and not c.anonymous)
    return [(p, k) for p, k in n.most_common() if k > 1][:10]


def board(start, end):
    from app.utils import complaint_cases as cases
    from app.utils import cs_board

    rows = _cases(start, end)
    p_start, p_end = cs_board.previous(start, end)
    before = _cases(p_start, p_end)
    visits, visits_before = _visits(start, end), _visits(p_start, p_end)
    now_c, before_c = _counts(rows), _counts(before)
    rate, rate_before = (_per_1000(now_c["complaint"], visits),
                         _per_1000(before_c["complaint"], visits_before))
    summary, summary_before = cases.summary(start, end), cases.summary(p_start, p_end)
    survey = cs_board.overview(start, end)
    complaints = [c for c in rows if c.kind == "complaint"]
    return {
        "counts": now_c,
        "delta": {k: now_c[k] - before_c[k] for k in now_c},
        "visits": visits, "rate": rate, "rate_delta": _delta(rate, rate_before),
        "summary": summary,
        "summary_delta": {k: _delta(summary.get(k), summary_before.get(k))
                          for k in ("first_contact_hours", "close_hours", "closed_in_time_pct",
                                    "resolution_avg")},
        "now": cases.open_counts(),
        "survey": survey,
        "weeks": weeks(rows, start, end),
        "category": _by(complaints, "category"),
        "uncategorised": sum(1 for c in complaints if not c.category),
        "channel": _by(rows, "channel"),
        "severity": _by(complaints, "severity"),
        "side": _by(complaints, "side"),
        "cause": _by(complaints, "root_cause"),
        "centres": by_centre(rows, start, end),
        "staff": staff(rows),
        "suggestions": suggestions(rows),
        "repeat": repeat_families(rows),
    }
