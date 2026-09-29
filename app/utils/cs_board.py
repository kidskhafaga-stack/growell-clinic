"""The customer-service board: how families rated us, per unit, and the
complaints book — for a period, against the one before it.

It replaces the old satisfaction page, which counted from the first survey
ever sent, clinic-wide, with no date and no unit, and knew nothing of the
money question, the "what bothered you" taps, the reasons families left
against advice, or the complaints book.

**Nothing here is a new fact.** Every number is read from rows written
elsewhere — ``Feedback``, the stays and attendances, ``Complaint`` — so the
board can be wrong only where those are.

**Small numbers are not judged.** A unit with fewer than
:data:`MIN_TO_COLOUR` answers is shown uncoloured, and a doctor with fewer
than :data:`MIN_FOR_DOCTOR` has no average at all: two unhappy families are
not a verdict on a department or a person.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from app.extensions import db

MIN_TO_COLOUR = 10
MIN_FOR_DOCTOR = 5
#: What a colour means, on the stars' own scale.
GOOD_FROM = 4.3
FAIR_FROM = 3.6
SIDES = ("medical", "service", "finance")
#: The survey column behind each side.
COLUMN = {"medical": "doctor_rating", "service": "service_rating",
          "finance": "finance_rating"}


# -------------------------------------------------------------- periods ---
def period(raw_from=None, raw_to=None, today=None):
    """``(start, end)`` datetimes — end exclusive — for a from/to pair of
    ``YYYY-MM-DD`` strings; the last 90 days when they are missing or
    wrong. ``to`` before ``from`` is swapped rather than refused."""
    from app.utils.clock import local_today, to_utc

    today = today or local_today()

    def parse(raw):
        try:
            return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

    d_to = parse(raw_to) or today
    d_from = parse(raw_from) or (d_to - timedelta(days=89))
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    # The clinic's midnights, as the UTC the rows are stored in — a parent
    # who answered at 01:30 answered on the day the clinic's clock says.
    return (to_utc(datetime.combine(d_from, datetime.min.time())),
            to_utc(datetime.combine(d_to + timedelta(days=1), datetime.min.time())))


def dates(start, end):
    """The first and last day of a window, on the clinic's calendar."""
    from app.utils.clock import local_date

    return local_date(start), local_date(end) - timedelta(days=1)


def previous(start, end):
    """The period of the same length just before."""
    span = end - start
    return start - span, start


# ------------------------------------------------------------- the rows ---
def _outpatient_id():
    from app.utils import cost_centres
    return cost_centres.centre_id("outpatient")


def _rows(start, end, centre_id=None):
    """The surveys sent in the period, as light tuples. A visit survey
    carries no centre and belongs to the outpatient clinics."""
    from app.models import Feedback

    q = (db.session.query(Feedback.id, Feedback.status, Feedback.doctor_rating,
                          Feedback.service_rating, Feedback.finance_rating,
                          Feedback.nps, Feedback.concerns, Feedback.cost_centre_id,
                          Feedback.doctor_id, Feedback.submitted_at)
         .filter(Feedback.created_at >= start, Feedback.created_at < end))
    outpatient = _outpatient_id()
    rows = q.all()
    if centre_id is not None:
        rows = [r for r in rows if (r.cost_centre_id or outpatient) == centre_id]
    return rows, outpatient


def _centre(row, outpatient):
    return row.cost_centre_id or outpatient


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _nps(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    promoters = sum(1 for v in values if v >= 9)
    detractors = sum(1 for v in values if v <= 6)
    return round((promoters - detractors) * 100.0 / len(values))


def _figures(rows):
    answered = [r for r in rows if r.status == "submitted"]
    return {
        "sent": len(rows),
        "answered": len(answered),
        "rate": round(len(answered) * 100 / len(rows)) if rows else None,
        "medical": _avg(r.doctor_rating for r in answered),
        "service": _avg(r.service_rating for r in answered),
        "finance": _avg(r.finance_rating for r in answered),
        "nps": _nps(r.nps for r in answered),
    }


def _delta(now, before):
    if now is None or before is None:
        return None
    return round(now - before, 1)


def overview(start, end, centre_id=None):
    """The headline figures, each with its change from the period before."""
    rows, _ = _rows(start, end, centre_id)
    now = _figures(rows)
    before = _figures(_rows(*previous(start, end), centre_id)[0])
    now["delta"] = {k: _delta(now[k], before[k])
                    for k in ("rate", "medical", "service", "finance", "nps")}
    from app.models import Complaint
    cq = Complaint.query.filter(Complaint.created_at >= start,
                                Complaint.created_at < end,
                                Complaint.kind == "complaint")
    pq = Complaint.query.filter(Complaint.created_at >= previous(start, end)[0],
                                Complaint.created_at < start,
                                Complaint.kind == "complaint")
    if centre_id is not None:
        cq = cq.filter(Complaint.cost_centre_id == centre_id)
        pq = pq.filter(Complaint.cost_centre_id == centre_id)
    now["complaints"] = cq.count()
    now["delta"]["complaints"] = now["complaints"] - pq.count()
    left = leave_reasons(start, end, centre_id)
    now["left"] = sum(n for _k, n in left)
    return now


def trend(start, end, centre_id=None):
    """Week by week from the start: the average of each side, over the
    answers that came back that week. A week with no answers has gaps, not
    zeros — nobody rated it, which is not the same as rating it nothing."""
    from app.utils.clock import local_date

    rows, _ = _rows(start, end, centre_id)
    weeks = []
    cursor = start
    while cursor < end:
        nxt = min(cursor + timedelta(days=7), end)
        inside = [r for r in rows if r.status == "submitted" and r.submitted_at
                  and cursor <= r.submitted_at < nxt]
        weeks.append({"start": local_date(cursor),
                      "count": len(inside),
                      **{side: _avg(getattr(r, COLUMN[side]) for r in inside)
                         for side in SIDES}})
        cursor = nxt
    return weeks


def concerns(start, end, centre_id=None):
    """``[(side, key, count)]``, most often first — from the "what bothered
    you" taps, whose keys are fixed so they can be counted."""
    rows, _ = _rows(start, end, centre_id)
    counts = Counter()
    for r in rows:
        for token in (r.concerns or "").split(","):
            dim, _, key = token.partition(":")
            if dim and key:
                counts[(dim, key)] += 1
    names = {"doctor": "medical", "service": "service", "finance": "finance"}
    return [(names.get(dim, dim), dim, key, n)
            for (dim, key), n in counts.most_common()]


# -------------------------------------------------- leaving against advice ---
def _left(start, end):
    """``[(centre_id, reason)]`` for every stay and attendance that ended
    against advice in the period."""
    from app.models import Admission, EmergencyVisit
    from app.utils import cost_centres

    out = []
    for adm in (Admission.query.filter(Admission.outcome == "self_discharge",
                                       Admission.discharged_at >= start,
                                       Admission.discharged_at < end).all()):
        unit = cost_centres.unit_on(adm, None)
        centre = cost_centres.for_unit(unit).id if unit is not None else None
        out.append((centre, adm.leave_reason))
    er = cost_centres.centre_id("emergency")
    for visit in (EmergencyVisit.query.filter(
            EmergencyVisit.disposition.in_(("self_discharge", "left_unseen")),
            EmergencyVisit.departed_at >= start,
            EmergencyVisit.departed_at < end).all()):
        out.append((er, visit.leave_reason))
    return out


def leave_reasons(start, end, centre_id=None):
    """``[(reason key or None, count)]``, most first. ``None`` is a family
    whose reason nobody wrote down — counted, so it cannot hide."""
    counts = Counter(reason for centre, reason in _left(start, end)
                     if centre_id is None or centre == centre_id)
    return counts.most_common()


# ------------------------------------------------------------ per unit ---
def by_centre(start, end):
    """One row per part of the clinic that had surveys, complaints or a
    family leaving against advice in the period."""
    from app.models import Complaint, CostCentre

    rows, outpatient = _rows(start, end)
    grouped = defaultdict(list)
    for r in rows:
        grouped[_centre(r, outpatient)].append(r)
    complaints = Counter(
        cid for (cid,) in db.session.query(Complaint.cost_centre_id)
        .filter(Complaint.created_at >= start, Complaint.created_at < end,
                Complaint.kind == "complaint").all())
    left = Counter(centre for centre, _r in _left(start, end))
    ids = (set(grouped) | {c for c in complaints if c} | {c for c in left if c})
    centres = {c.id: c for c in CostCentre.query.filter(CostCentre.id.in_(ids)).all()} if ids else {}
    out = []
    for cid in ids:
        centre = centres.get(cid)
        if centre is None:
            continue
        fig = _figures(grouped.get(cid, []))
        top = Counter()
        for r in grouped.get(cid, []):
            for token in (r.concerns or "").split(","):
                if ":" in token:
                    top[token] += 1
        out.append({"centre": centre, **fig,
                    "judged": fig["answered"] >= MIN_TO_COLOUR,
                    "complaints": complaints.get(cid, 0),
                    "left": left.get(cid, 0),
                    "top": top.most_common(1)[0][0] if top else None})
    out.sort(key=lambda r: (-(r["answered"] or 0), r["centre"].sort_order))
    return out


def by_doctor(start, end, centre_id=None):
    """Each doctor's medical score — only once there are enough answers to
    mean something — and how often a family said they were not told enough."""
    from app.models import User

    rows, _ = _rows(start, end, centre_id)
    grouped = defaultdict(list)
    for r in rows:
        if r.doctor_id and r.status == "submitted":
            grouped[r.doctor_id].append(r)
    people = {u.id: u for u in User.query.filter(User.id.in_(list(grouped))).all()} if grouped else {}
    out = []
    for doctor_id, answers in grouped.items():
        if doctor_id not in people:
            continue
        count = len(answers)
        out.append({
            "doctor": people[doctor_id], "count": count,
            "medical": _avg(r.doctor_rating for r in answers) if count >= MIN_FOR_DOCTOR else None,
            "judged": count >= MIN_FOR_DOCTOR,
            "not_explained": sum(1 for r in answers
                                 if "doctor:explain" in (r.concerns or "").split(",")),
            "low": sum(1 for r in answers
                       if r.doctor_rating is not None and r.doctor_rating <= 2),
        })
    out.sort(key=lambda r: (not r["judged"], -(r["medical"] or 0), -r["count"]))
    return out


def comments(start, end, centre_id=None, limit=8):
    from app.models import Feedback

    rows, outpatient = _rows(start, end, centre_id)
    ids = [r.id for r in rows if r.status == "submitted"]
    if not ids:
        return []
    return (Feedback.query.filter(Feedback.id.in_(ids),
                                  Feedback.comment.isnot(None))
            .order_by(Feedback.submitted_at.desc()).limit(limit).all())


def colour(value, judged=True):
    if value is None or not judged:
        return "none"
    if value >= GOOD_FROM:
        return "good"
    if value >= FAIR_FROM:
        return "fair"
    return "poor"


# ------------------------------------------------------------ complaints ---
def complaints(start, end, centre_id=None):
    """The complaints book for the period: the figures, where they came
    from, which unit, and every one still open — oldest first."""
    from app.models import Complaint
    from app.models.complaint import OPEN_STATUSES
    from app.utils import complaint_cases as cases

    q = Complaint.query.filter(Complaint.created_at >= start,
                               Complaint.created_at < end)
    if centre_id is not None:
        q = q.filter(Complaint.cost_centre_id == centre_id)
    rows = q.all()
    summary = cases.summary(start, end) if centre_id is None else None
    if summary is None:
        # The same figures, over this unit's cases only.
        summary = _summary_of(rows)
    open_q = Complaint.query.filter(Complaint.status.in_(OPEN_STATUSES))
    if centre_id is not None:
        open_q = open_q.filter(Complaint.cost_centre_id == centre_id)
    now = datetime.utcnow()
    hours, days = cases.first_contact_hours(), cases.close_days()
    still_open = open_q.order_by(Complaint.created_at.asc()).limit(50).all()
    return {
        "summary": summary,
        "by_channel": Counter(c.channel for c in rows).most_common(),
        "by_centre": Counter(c.cost_centre for c in rows
                             if c.kind == "complaint").most_common(),
        "by_side": Counter(c.side for c in rows
                           if c.kind == "complaint").most_common(),
        "open": [{"case": c, "late": cases.is_late(c, now, hours, days),
                  "hours": (now - c.created_at).total_seconds() / 3600}
                 for c in still_open],
    }


def _summary_of(rows):
    from app.utils import complaint_cases as cases

    days = cases.close_days()
    complaints_ = [c for c in rows if c.kind == "complaint"]
    closed = [c for c in complaints_ if c.closed_at]
    rated = [c.resolution_rating for c in rows if c.resolution_rating]

    def hours(pairs):
        vals = [(b - a).total_seconds() / 3600 for a, b in pairs if a and b]
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "total": len(rows), "open": sum(1 for c in rows if c.is_open),
        "late": sum(1 for c in rows if cases.is_late(c)),
        "first_contact_hours": hours((c.created_at, c.first_contact_at) for c in complaints_),
        "close_hours": hours((c.created_at, c.closed_at) for c in complaints_),
        "closed_in_time_pct": (round(sum(1 for c in closed if c.closed_at <= c.close_due(days))
                                     * 100 / len(closed)) if closed else None),
        "resolution_avg": round(sum(rated) / len(rated), 1) if rated else None,
        "resolution_count": len(rated),
        "by_kind": Counter(c.kind for c in rows),
        "reopened": sum(1 for c in rows if c.reopened_count),
    }


# ---------------------------------------------------------- the people ---
def responses(start, end, centre_id=None, side=None, low=False, concern=None,
              doctor_id=None):
    """The answers behind a number on the board, as a query — so the list
    pages and exports like every other list."""
    from app.models import Feedback

    q = Feedback.query.filter(Feedback.created_at >= start,
                              Feedback.created_at < end,
                              Feedback.status == "submitted")
    if centre_id is not None:
        if centre_id == _outpatient_id():
            q = q.filter(db.or_(Feedback.cost_centre_id == centre_id,
                                Feedback.cost_centre_id.is_(None)))
        else:
            q = q.filter(Feedback.cost_centre_id == centre_id)
    if side in COLUMN and low:
        q = q.filter(getattr(Feedback, COLUMN[side]) <= 2)
    if concern:
        q = q.filter(Feedback.concerns.like(f"%{concern}%"))
    if doctor_id:
        q = q.filter(Feedback.doctor_id == doctor_id)
    return q.order_by(Feedback.submitted_at.desc())
