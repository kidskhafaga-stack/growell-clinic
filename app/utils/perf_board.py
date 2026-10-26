"""The performance board (REPORTS_PLAN.md ت-٨).

Asked for after the owner sent another program's «Performance» screens:
*«نقدر نغش منها حاجه للعيادة وللمستشفيات والمراكز؟»* — and then: *«الاقسام فى
المستشفى … كل واحد وخدماته هتترسم حسب القسم»*.

Two halves:

* **the clinic** — every copy has it: the visits by their type, how long each
  type took against the time booked for it, the shortest and the longest,
  the visits day by day, the hours worked and the gaps between, and, today,
  when the doctors will be done with who is waiting;
* **a tab per department the copy runs** — each tied to its module, and each
  read from the place that already answers it (``hospital_kpis``,
  ``med_board.wards``, ``lab_tat``) so no two screens disagree.

**Not a ranking of doctors by speed.** A shorter consultation is not a
better one (``utils/waiting.py``). What is shown is whether a type of visit
runs over the slot booked for it — the thing that makes everybody else wait.
Money is shown only to whoever holds the finance rights.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from app.extensions import db

#: How far back «how long this type usually takes» looks, for today's
#: finish time, and how many visits it needs before it trusts itself over
#: the slot booked for the type.
TYPICAL_DAYS = 30
TYPICAL_MIN = 5

#: Statuses that mean the child is not coming through the door.
NOT_SEEN = ("cancelled", "no_show")


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return round(values[mid], 1)
    return round((values[mid - 1] + values[mid]) / 2.0, 1)


def _appts(d_from, d_to, doctor_id=None):
    from app.models import Appointment

    q = Appointment.query.filter(Appointment.appt_date >= d_from,
                                 Appointment.appt_date <= d_to,
                                 Appointment.status.notin_(NOT_SEEN))
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)
    return q.all()


def _consult(appt):
    from app.utils.waiting import intervals, is_sane

    return intervals(appt)["consult"] if is_sane(appt) else None


def _revenue_by_appt(appt_ids):
    """``{appointment id: billed}`` — the bills tied to each visit, directly
    or through the visit record."""
    from app.models import Invoice, Visit

    if not appt_ids:
        return {}
    ids = list(appt_ids)
    out = defaultdict(float)
    for inv in Invoice.query.filter(Invoice.appointment_id.in_(ids)).all():
        out[inv.appointment_id] += inv.total or 0
    for inv, aid in (db.session.query(Invoice, Visit.appointment_id)
                     .join(Visit, Invoice.visit_id == Visit.id)
                     .filter(Invoice.appointment_id.is_(None),
                             Visit.appointment_id.in_(ids)).all()):
        out[aid] += inv.total or 0
    return {k: round(v, 2) for k, v in out.items()}


def clinic(d_from, d_to, doctor_id=None, money=False):
    """The clinic half for the period."""
    from app.utils import visit_types

    appts = _appts(d_from, d_to, doctor_id)
    revenue = _revenue_by_appt({a.id for a in appts}) if money else {}
    groups = defaultdict(list)
    for a in appts:
        groups[a.appt_type or ""].append(a)

    def figures(rows):
        took = [c for c in (_consult(a) for a in rows) if c is not None]
        over = sum(1 for a in rows if (c := _consult(a)) is not None
                   and a.duration_minutes and c > a.duration_minutes)
        return {
            "n": len(rows),
            "done": sum(1 for a in rows if a.status == "completed"),
            "counted": len(took),
            "median": _median(took),
            "shortest": round(min(took), 1) if took else None,
            "longest": round(max(took), 1) if took else None,
            "booked": _median([a.duration_minutes for a in rows if a.duration_minutes]),
            "over": over,
            "over_pct": round(100.0 * over / len(took), 1) if took else None,
            "revenue": round(sum(revenue.get(a.id, 0) for a in rows), 2) if money else None,
        }

    types = []
    for key, rows in groups.items():
        row = figures(rows)
        row.update(key=key, label=visit_types.label(key) if key else "—",
                   color=visit_types.color(key) if key else None)
        types.append(row)
    types.sort(key=lambda r: -r["n"])

    per_day = Counter(a.appt_date for a in appts if a.status == "completed")
    days = []
    day = d_from
    while day <= d_to:
        days.append((day, per_day.get(day, 0)))
        day += timedelta(days=1)

    return {"all": figures(appts), "types": types, "days": days,
            "work": work_and_gaps(appts)}


def work_and_gaps(appts):
    """For each doctor's day: from the first visit begun to the last one
    finished, how much of it was spent with a child and how much between.
    Averaged over the doctor-days that have both ends."""
    from app.utils.waiting import is_sane

    by_day = defaultdict(list)
    for a in appts:
        if is_sane(a):
            by_day[(a.doctor_id, a.appt_date)].append(a)
    spans, busy = [], []
    for rows in by_day.values():
        start = min(a.started_at for a in rows)
        end = max(a.completed_at for a in rows)
        span = (end - start).total_seconds() / 60
        if span <= 0:
            continue
        # Overlapping visits counted once: walk them in order.
        worked, edge = 0.0, None
        for a in sorted(rows, key=lambda r: r.started_at):
            s = a.started_at if edge is None or a.started_at > edge else edge
            if a.completed_at > s:
                worked += (a.completed_at - s).total_seconds() / 60
            edge = a.completed_at if edge is None else max(edge, a.completed_at)
        spans.append(span)
        busy.append(min(worked, span))
    if not spans:
        return None
    n = len(spans)
    span, work = sum(spans) / n, sum(busy) / n
    return {"days": n, "span": round(span), "busy": round(work),
            "idle": round(max(span - work, 0)),
            "busy_pct": round(100.0 * work / span, 1) if span else None}


def typical_minutes(today):
    """``{visit type: minutes}`` — how long each type took lately (the
    median of the last :data:`TYPICAL_DAYS` days), where enough were timed."""
    rows = _appts(today - timedelta(days=TYPICAL_DAYS), today - timedelta(days=1))
    took = defaultdict(list)
    for a in rows:
        c = _consult(a)
        if c is not None:
            took[a.appt_type or ""].append(c)
    return {k: _median(v) for k, v in took.items() if len(v) >= TYPICAL_MIN}


def finish_today(doctor_id=None):
    """Today, per doctor: who is waiting, who is inside, and when the last of
    them should be done — each child at the time their type usually takes
    (else the slot booked for it). An estimate, said so on the screen."""
    from app.models import Appointment, User
    from app.utils.clock import local_now, local_today, to_local

    today = local_today()
    q = Appointment.query.filter(Appointment.appt_date == today,
                                 Appointment.checked_in_at.isnot(None),
                                 Appointment.completed_at.is_(None),
                                 Appointment.status.notin_(NOT_SEEN))
    if doctor_id:
        q = q.filter(Appointment.doctor_id == doctor_id)
    rows = q.all()
    if not rows:
        return []
    usual = typical_minutes(today)
    now = local_now().replace(tzinfo=None)
    by_doctor = defaultdict(lambda: {"waiting": 0, "inside": 0, "minutes": 0.0})
    for a in rows:
        need = usual.get(a.appt_type or "") or a.duration_minutes or 15
        slot = by_doctor[a.doctor_id]
        if a.started_at:
            slot["inside"] += 1
            began = (to_local(a.started_at) or a.started_at).replace(tzinfo=None)
            slot["minutes"] += max(need - (now - began).total_seconds() / 60, 0)
        else:
            slot["waiting"] += 1
            slot["minutes"] += need
    names = {u.id: u for u in User.query.filter(User.id.in_(list(by_doctor))).all()}
    out = []
    for did, slot in by_doctor.items():
        out.append({"doctor": names.get(did), "waiting": slot["waiting"],
                    "inside": slot["inside"], "minutes": round(slot["minutes"]),
                    "done_at": now + timedelta(minutes=slot["minutes"])})
    out.sort(key=lambda r: r["done_at"], reverse=True)
    return out


def doctors_in(d_from, d_to):
    from app.models import Appointment, User

    ids = [i for (i,) in db.session.query(Appointment.doctor_id).filter(
        Appointment.appt_date >= d_from, Appointment.appt_date <= d_to).distinct().all() if i]
    return User.query.filter(User.id.in_(ids)).order_by(User.full_name).all() if ids else []


# ------------------------------------------------------------ departments --
def _orders(d_from, d_to, kind):
    from app.models import Visit, VisitInvestigation
    from app.utils import lab_tat

    rows = (VisitInvestigation.query.join(Visit, VisitInvestigation.visit_id == Visit.id)
            .filter(Visit.visit_date >= d_from, Visit.visit_date <= d_to,
                    VisitInvestigation.kind == kind).all())
    names = Counter((r.name or "").strip() or "—" for r in rows)
    return {"n": len(rows),
            "resulted": sum(1 for r in rows if r.resulted_at),
            "tat": _median([lab_tat.minutes(r) for r in rows]),
            "top": names.most_common(5)}


def _store():
    from app.models.store import StoreItem

    items = StoreItem.query.filter_by(is_active=True).all()
    return {"items": len(items),
            "value": round(sum(i.stock_value for i in items), 2),
            "low": sum(1 for i in items if i.is_low)}


def _pharmacy(d_from, d_to):
    from app.models.prescription import PrescriptionItem
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    rows = (PrescriptionItem.query.filter(PrescriptionItem.dispensed_at >= start,
                                          PrescriptionItem.dispensed_at < end).all())
    return {"lines": len(rows), "prescriptions": len({r.prescription_id for r in rows})}


def _programs(d_from, d_to):
    from app.models.care_program import ProgramEnrollment, ProgramSession
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    sessions = ProgramSession.query.filter(ProgramSession.at >= start,
                                           ProgramSession.at < end).all()
    enrolled = ProgramEnrollment.query.count()
    return {"sessions": len(sessions),
            "children": len({s.enrollment_id for s in sessions}),
            "enrolled": enrolled}


def _ambulance(d_from, d_to):
    from app.models.ambulance import AmbulanceCall
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    calls = AmbulanceCall.query.filter(AmbulanceCall.received_at >= start,
                                       AmbulanceCall.received_at < end).all()
    reach = [(c.at_scene_at - c.received_at).total_seconds() / 60
             for c in calls if c.at_scene_at and c.at_scene_at >= c.received_at]
    return {"calls": len(calls), "reach": _median(reach)}


#: The department tabs, in order: (key, the modules that open it, icon).
PARTS = (
    ("emergency", ("emergency",), "heart-pulse"),
    ("units", ("ward", "nicu", "icu", "beds"), "hospital"),
    ("theatres", ("theatres",), "scissors"),
    ("labs", ("labs",), "droplet"),
    ("imaging", ("imaging",), "radioactive"),
    ("pharmacy", ("pharmacy",), "capsule"),
    ("store", ("inventory",), "box-seam"),
    ("programs", ("programs",), "calendar2-heart"),
    ("ambulance", ("ambulance",), "truck"),
)


def parts():
    """The department tabs this copy runs — none for a clinic that runs
    only the clinic."""
    from app.utils.facility import module_enabled

    return [(key, icon) for key, modules, icon in PARTS
            if any(module_enabled(m) for m in modules)]


def part(key, d_from, d_to):
    """One department's figures for the period."""
    from app.utils import hospital_kpis, med_board

    if key == "emergency":
        return hospital_kpis.emergency(d_from, d_to)
    if key == "units":
        return {"rows": med_board.wards(d_from, d_to)}
    if key == "theatres":
        return hospital_kpis.theatres(d_from, d_to)
    if key in ("labs", "imaging"):
        return _orders(d_from, d_to, "lab" if key == "labs" else "imaging")
    if key == "pharmacy":
        return _pharmacy(d_from, d_to)
    if key == "store":
        return _store()
    if key == "programs":
        return _programs(d_from, d_to)
    if key == "ambulance":
        return _ambulance(d_from, d_to)
    return None
