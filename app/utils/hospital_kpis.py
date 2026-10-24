"""The hospital's indicators (HOSPITAL_PLAN.md ٥‑د, REPORTS_PLAN.md ت-٦).

Asked so that a clinic running at clinic level never sees them: *«زود ده فى
البلان بتاع المستشفى علشان ما يخشش على الى عنده البرنامج شغال على مستوى
العيادة بس»*. So **each section exists only when its department is switched
on** (`facility.module_enabled`): the emergency's times with ``emergency``,
the theatres with ``theatres``, the return to intensive care with ``icu`` or
``nicu``, the safety rates per 1000 bed days with ``beds``.

What the medical board already shows (stays, occupancy, deaths, readmission,
triage levels and where children went) is not repeated here.

**A number, not a judgement.** No figure here is called good or bad: the
hospital's targets live in its quality measures, and an indicator without one
is a number to read. A figure with nothing under it is «—», never zero.

Everything is read off what was recorded; nothing is typed for this page —
except the one time the plan named as missing, when the doctor first saw a
child in the emergency (`EmergencyVisit.seen_at`).
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.extensions import db

#: A child back in the emergency within this many hours of leaving it.
ER_BACK_HOURS = 72
#: Back in intensive care within this many hours of leaving it.
ICU_BACK_HOURS = 48
#: The first case of the day «on time» when it starts within this of its time.
ON_TIME_MINUTES = 15
#: Changeovers longer than this are a gap in the list, not a changeover.
TURNOVER_CAP_MINUTES = 240
CRITICAL = ("icu", "nicu")


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return round(values[mid], 1)
    return round((values[mid - 1] + values[mid]) / 2, 1)


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _per_thousand(count, days):
    return round(count * 1000 / days, 2) if days else None


def parts():
    """Which sections this hospital has — each tied to its department."""
    from app.utils.facility import module_enabled

    return {"emergency": module_enabled("emergency"),
            "theatres": module_enabled("theatres"),
            "critical": module_enabled("icu") or module_enabled("nicu"),
            "safety": module_enabled("beds")}


def any_part():
    return any(parts().values())


# ------------------------------------------------------------- emergency --
def emergency(d_from, d_to):
    """From the door to the triage, to the doctor, and out; who left unseen;
    who was back within :data:`ER_BACK_HOURS` hours."""
    from app.models.emergency_visit import LEFT_UNSEEN, EmergencyVisit
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    rows = (EmergencyVisit.query
            .filter(EmergencyVisit.arrived_at >= start, EmergencyVisit.arrived_at < end)
            .all())
    total = len(rows)
    to_triage = [r.wait_to_triage for r in rows]
    to_doctor = [r.wait_to_doctor for r in rows]
    stayed = [int((r.departed_at - r.arrived_at).total_seconds() // 60)
              for r in rows if r.departed_at]
    unseen = sum(1 for r in rows if r.disposition == LEFT_UNSEEN)
    # Back: an earlier attendance of the same child that ended (or began, when
    # nobody wrote the leaving) within the hours before this arrival.
    back = 0
    patients = {r.patient_id for r in rows}
    earlier = defaultdict(list)
    if patients:
        for pid, aid, came, went in (db.session.query(
                EmergencyVisit.patient_id, EmergencyVisit.id, EmergencyVisit.arrived_at,
                EmergencyVisit.departed_at)
                .filter(EmergencyVisit.patient_id.in_(patients),
                        EmergencyVisit.arrived_at < end).all()):
            earlier[pid].append((aid, came, went or came))
    window = timedelta(hours=ER_BACK_HOURS)
    for r in rows:
        if any(aid != r.id and came < r.arrived_at and r.arrived_at - left <= window
               for aid, came, left in earlier.get(r.patient_id, [])):
            back += 1
    return {
        "total": total,
        "triage_median": _median(to_triage),
        "triaged": sum(1 for v in to_triage if v is not None),
        "doctor_median": _median(to_doctor),
        "seen": sum(1 for v in to_doctor if v is not None),
        "stay_median": _median(stayed),
        "left": len(stayed),
        "unseen": unseen, "unseen_pct": _pct(unseen, total),
        "back": back, "back_pct": _pct(back, total),
        "back_hours": ER_BACK_HOURS,
    }


# -------------------------------------------------------------- theatres --
def _local(moment):
    from app.utils.clock import to_local

    return to_local(moment) if moment is not None else None


def theatres(d_from, d_to):
    """The lists of the period: done, cancelled and why, postponed; the time
    used of the time booked; the first case of each day on time; and the
    changeover between one case and the next in the same theatre."""
    from app.models.theatre import Operation

    ops = (Operation.query
           .filter(Operation.on_date >= d_from, Operation.on_date <= d_to).all())
    total = len(ops)
    done = [o for o in ops if o.status == "done"]
    postponed = [o for o in ops if o.postponed_to_id]
    cancelled = [o for o in ops if o.status == "cancelled" and not o.postponed_to_id]
    reasons = Counter(" ".join((o.cancel_reason or "").split()) or "—"
                      for o in cancelled + postponed)
    booked = used = 0
    for o in done:
        if o.minutes and o.started_at and o.finished_at:
            booked += o.minutes
            used += max((o.finished_at - o.started_at).total_seconds() / 60, 0)
    # The first case of each theatre-day, by its booked time.
    days = defaultdict(list)
    for o in done:
        days[(o.theatre_id, o.on_date)].append(o)
    firsts = on_time = 0
    turnovers = []
    for (_theatre, on_date), cases in days.items():
        timed = [o for o in cases if o.start_time and o.started_at]
        if timed:
            first = min(timed, key=lambda o: o.start_time)
            firsts += 1
            began = _local(first.started_at)
            planned = datetime.combine(on_date, first.start_time)
            if began is not None and (began.replace(tzinfo=None) - planned) <= \
                    timedelta(minutes=ON_TIME_MINUTES):
                on_time += 1
        ran = sorted((o for o in cases if o.started_at and o.finished_at),
                     key=lambda o: o.started_at)
        for prev, nxt in zip(ran, ran[1:]):
            gap = (nxt.started_at - prev.finished_at).total_seconds() / 60
            if 0 <= gap <= TURNOVER_CAP_MINUTES:
                turnovers.append(gap)
    return {
        "total": total, "done": len(done),
        "cancelled": len(cancelled), "cancelled_pct": _pct(len(cancelled), total),
        "postponed": len(postponed), "postponed_pct": _pct(len(postponed), total),
        "reasons": reasons.most_common(5),
        "used_pct": _pct(used, booked), "used_hours": round(used / 60, 1),
        "booked_hours": round(booked / 60, 1),
        "first_cases": firsts, "on_time": on_time, "on_time_pct": _pct(on_time, firsts),
        "turnover_median": _median(turnovers), "turnovers": len(turnovers),
        "on_time_minutes": ON_TIME_MINUTES,
    }


# ------------------------------------------------- back in intensive care --
def _stays(start=None, end=None):
    """``[(admission_id, patient_id, unit_id, unit_kind, since, until)]`` — every
    bed a child was in, in order, with the kind of its unit."""
    from app.models import Admission, BedStay
    from app.models.place import Bed, Space, Unit

    q = (db.session.query(BedStay.admission_id, Admission.patient_id, Unit.id,
                          Unit.kind, BedStay.since, BedStay.until)
         .join(Admission, Admission.id == BedStay.admission_id)
         .join(Bed, BedStay.bed_id == Bed.id)
         .join(Space, Bed.space_id == Space.id)
         .join(Unit, Space.unit_id == Unit.id))
    if start is not None:
        q = q.filter(db.or_(BedStay.until.is_(None), BedStay.until >= start))
    if end is not None:
        q = q.filter(BedStay.since < end)
    return q.order_by(Admission.patient_id, BedStay.since).all()


def critical(d_from, d_to):
    """Children who left intensive care (ICU or NICU) for another bed in the
    period, and how many were back in intensive care within
    :data:`ICU_BACK_HOURS` hours — on the same stay or a new one."""
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    window = timedelta(hours=ICU_BACK_HOURS)
    rows = _stays(start - window, end + window)
    by_patient = defaultdict(list)
    for row in rows:
        by_patient[row[1]].append(row)
    out = {kind: {"left": 0, "back": 0} for kind in CRITICAL}
    for beds in by_patient.values():
        for i, (aid, _pid, _unit, kind, _since, until) in enumerate(beds):
            if kind not in CRITICAL or until is None or not start <= until < end:
                continue
            after = beds[i + 1:]
            nxt = after[0] if after else None
            # Moved within intensive care (another bed of it) is not leaving.
            if nxt is not None and nxt[3] in CRITICAL and nxt[4] - until <= timedelta(minutes=5):
                continue
            out[kind]["left"] += 1
            if any(b[3] in CRITICAL and timedelta(0) <= b[4] - until <= window
                   for b in after):
                out[kind]["back"] += 1
    for kind in CRITICAL:
        out[kind]["back_pct"] = _pct(out[kind]["back"], out[kind]["left"])
    return {"units": out, "hours": ICU_BACK_HOURS}


# ------------------------------------------------- safety per 1000 days ----
def _bed_days(start, end):
    """``({unit_kind: days}, total)`` — the days children spent in beds in the
    period, by the kind of unit."""
    days = Counter()
    now = datetime.utcnow()
    for _aid, _pid, _unit, kind, since, until in _stays(start, end):
        hours = (min(until or now, end) - max(since, start)).total_seconds() / 3600
        if hours > 0:
            days[kind] += hours / 24
    return days, sum(days.values())


def _unit_at(admission_id, moment, stays):
    for aid, _pid, _unit, kind, since, until in stays:
        if aid == admission_id and since <= moment and (until is None or moment < until):
            return kind
    return None


def safety(d_from, d_to):
    """Falls, pressure injuries and medication errors that reached a child,
    per 1000 bed days — for the hospital and by kind of unit. From the
    incident reports and the medication-error reports as they were filed."""
    from app.models import Incident
    from app.models.med_error import MedicationError
    from app.models.place import Unit
    from app.utils.med_board import utc

    start, end = utc(d_from, d_to)
    days, total_days = _bed_days(start, end)
    kinds = dict(db.session.query(Unit.id, Unit.kind).all())
    counts = {"fall": Counter(), "pressure_injury": Counter(), "med_error": Counter()}
    for category, unit_id in (db.session.query(Incident.category, Incident.unit_id)
                              .filter(Incident.occurred_at >= start, Incident.occurred_at < end,
                                      Incident.affected == "patient",
                                      Incident.category.in_(("fall", "pressure_injury")))
                              .all()):
        counts[category][kinds.get(unit_id)] += 1
    stays = _stays(start, end)
    for aid, happened in (db.session.query(MedicationError.admission_id,
                                           MedicationError.happened_at)
                          .filter(MedicationError.happened_at >= start,
                                  MedicationError.happened_at < end,
                                  MedicationError.reached_patient.is_(True)).all()):
        counts["med_error"][_unit_at(aid, happened, stays) if aid else None] += 1
    rows = []
    for kind in sorted(days, key=lambda k: -days[k]):
        rows.append({"kind": kind, "days": round(days[kind], 1),
                     **{key: {"n": counts[key].get(kind, 0),
                              "rate": _per_thousand(counts[key].get(kind, 0), days[kind])}
                        for key in counts}})
    whole = {key: {"n": sum(counts[key].values()),
                   "rate": _per_thousand(sum(counts[key].values()), total_days)}
             for key in counts}
    return {"rows": rows, "days": round(total_days, 1), "whole": whole}


def board(d_from, d_to, on=None):
    """Every section this hospital has, for the period. A department it does
    not run is ``None`` and is not drawn."""
    on = on if on is not None else parts()
    return {
        "emergency": emergency(d_from, d_to) if on["emergency"] else None,
        "theatres": theatres(d_from, d_to) if on["theatres"] else None,
        "critical": critical(d_from, d_to) if on["critical"] else None,
        "safety": safety(d_from, d_to) if on["safety"] else None,
    }
