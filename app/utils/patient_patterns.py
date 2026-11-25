"""Patient patterns — SMART_PATTERNS_PLAN ج-٥ (ب).

Four questions the clinic's own records already answer, each with its
reason written next to it — counted, never guessed, and nothing recorded
by the program:

* **who will probably not come** — an appointment in the next 7 days whose
  family missed before (2 or more of their last appointments, or a third of
  them), on a day and time that the clinic's families miss more often, and
  whether the reminder went out. For an extra reminder or a call, and for
  filling the time if they say no;
* **who is about to drop a series or a programme** — a next vaccine dose
  due within 30 days (or already late) for a child who was late on the dose
  before (14 days or more), or who has no phone to be reminded on; a
  programme with no session in 21 days. For the «السلاسل الواقعة» calls;
* **always in the emergency department** — 3 visits or more in 90 days:
  a count for the doctor who follows the child, with no judgement attached;
* **the season** — next month in the years before: how many visits, the
  diagnoses and the medicines written most — for the store's order and the
  doctors' schedule.

Growth charts and their limits are not here: their reference is WHO/CDC,
not a learned pattern.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

HORIZON_DAYS = 7
HISTORY_DAYS = 730
MISSED_MIN = 2
MISSED_SHARE = 1 / 3
SLOT_SHARE = 0.25
SLOT_MIN = 20
EVENING_HOUR = 14
LATE_DAYS = 14
DUE_AHEAD = 30
PROGRAM_GAP = 21
ER_COUNT = 3
ER_DAYS = 90
SEASON_YEARS = 3
SEASON_TOP = 8


def _today(today):
    from app.utils.clock import local_today

    return today or local_today()


def _period(t):
    return "evening" if t is not None and t.hour >= EVENING_HOUR else "morning"


# ------------------------------------------------- will probably not come --
def no_show_risk(today=None):
    """``[{appt, missed, kept, reasons, level}]`` for the next 7 days, the
    likeliest first. ``level`` is ``high`` (their own record) or ``medium``
    (one missed, or the slot alone)."""
    from app.models import Appointment, MessageLog
    from app.utils.appt_reminder import TYPE as REMINDER

    today = _today(today)
    upcoming = (Appointment.query
                .filter(Appointment.appt_date >= today,
                        Appointment.appt_date <= today + timedelta(days=HORIZON_DAYS),
                        Appointment.status == "scheduled")
                .order_by(Appointment.appt_date, Appointment.appt_time).all())
    if not upcoming:
        return []
    since = today - timedelta(days=HISTORY_DAYS)
    past = (Appointment.query
            .filter(Appointment.appt_date >= since, Appointment.appt_date < today,
                    Appointment.status.in_(("completed", "no_show")))
            .with_entities(Appointment.patient_id, Appointment.status,
                           Appointment.appt_date, Appointment.appt_time).all())
    mine = defaultdict(Counter)
    slots = defaultdict(Counter)
    for pid, status, d, t in past:
        mine[pid][status] += 1
        slots[(d.weekday(), _period(t))][status] += 1
    reminded = {aid for (aid,) in MessageLog.query
                .filter(MessageLog.template_type == REMINDER,
                        MessageLog.appointment_id.in_([a.id for a in upcoming]))
                .with_entities(MessageLog.appointment_id)}
    out = []
    for a in upcoming:
        own = mine.get(a.patient_id, Counter())
        missed, kept = own["no_show"], own["completed"]
        slot = slots.get((a.appt_date.weekday(), _period(a.appt_time)), Counter())
        slot_n = slot["no_show"] + slot["completed"]
        slot_share = slot["no_show"] / slot_n if slot_n >= SLOT_MIN else None
        reasons, level = [], None
        if missed >= MISSED_MIN and missed / (missed + kept) >= MISSED_SHARE:
            level = "high"
            reasons.append(("missed", {"missed": missed, "of": missed + kept}))
        elif missed:
            level = "medium"
            reasons.append(("missed", {"missed": missed, "of": missed + kept}))
        if slot_share is not None and slot_share >= SLOT_SHARE:
            level = level or "medium"
            reasons.append(("slot", {"pct": round(100 * slot_share)}))
        if level is None:
            continue
        if a.id not in reminded:
            reasons.append(("no_reminder", {}))
        out.append({"appt": a, "missed": missed, "kept": kept, "level": level,
                    "reasons": reasons})
    out.sort(key=lambda r: (r["level"] != "high", r["appt"].appt_date, r["appt"].appt_time))
    return out


# ------------------------------------------- about to drop a series ------
def series_at_risk(today=None):
    """``[{patient, vaccine, due, late_before, no_phone}]`` — the next dose
    of a series this child began, due within 30 days or already late, where
    the dose before was late or there is no phone to remind on."""
    from app.models import Patient, Vaccine
    from app.utils import vaccine_kpis as vk

    today = _today(today)
    schedules = vk._schedules()
    doses = vk._doses(today - timedelta(days=6 * 365))
    births = vk._births({p for p, _ in doses})
    found = []
    for (pid, vid), rows in doses.items():
        born = births.get(pid)
        if born is None or not rows:
            continue
        last = rows[-1]
        plan = schedules.get(last.brand_id, {})
        next_age = plan.get(last.dose_number + 1)
        if next_age is None:
            continue
        due = max(vk._add_months(born, next_age),
                  last.given_date + timedelta(days=vk.LATE_START_GAP))
        if due > today + timedelta(days=DUE_AHEAD) or due < today - timedelta(days=vk.RETURN_DAYS * 6):
            continue
        late_before = None
        if last.dose_number > 1:
            prev_age = plan.get(last.dose_number)
            if prev_age is not None:
                was_due = vk._add_months(born, prev_age)
                gap = (last.given_date - was_due).days
                if gap >= LATE_DAYS:
                    late_before = gap
        found.append((pid, vid, due, late_before))
    if not found:
        return []
    patients = {p.id: p for p in Patient.query.filter(
        Patient.id.in_({f[0] for f in found}), Patient.is_active.is_(True))}
    vaccines = {v.id: v for v in Vaccine.query.filter(Vaccine.id.in_({f[1] for f in found}))}
    out = []
    for pid, vid, due, late_before in found:
        p = patients.get(pid)
        if p is None:
            continue
        no_phone = not p.contact_phone
        if late_before is None and not no_phone:
            continue
        out.append({"patient": p, "vaccine": vaccines.get(vid), "due": due,
                    "late_before": late_before, "no_phone": no_phone,
                    "overdue": due < today})
    out.sort(key=lambda r: r["due"])
    return out


def programs_at_risk(today=None):
    """``[{enrollment, last, days}]`` — an open programme with no session
    in 21 days."""
    from app.models.care_program import ProgramEnrollment, ProgramSession
    from app.utils.clock import to_local

    today = _today(today)
    open_ = ProgramEnrollment.query.filter(ProgramEnrollment.ended_on.is_(None)).all()
    out = []
    for e in open_:
        last = (ProgramSession.query.filter_by(enrollment_id=e.id)
                .order_by(ProgramSession.at.desc()).first())
        since = (to_local(last.at) or last.at).date() if last else e.started_on
        days = (today - since).days
        if days >= PROGRAM_GAP:
            out.append({"enrollment": e, "last": since if last else None, "days": days})
    out.sort(key=lambda r: -r["days"])
    return out


# ------------------------------------------- always in the emergency ------
def er_visits(patient_id, today=None):
    """How many times this child came to the emergency department in the
    last 90 days — the count, or 0 below three."""
    from app.models import EmergencyVisit
    from app.utils.med_board import utc

    today = _today(today)
    start, end = utc(today - timedelta(days=ER_DAYS), today)
    n = (EmergencyVisit.query
         .filter(EmergencyVisit.patient_id == patient_id,
                 EmergencyVisit.arrived_at >= start, EmergencyVisit.arrived_at < end)
         .count())
    return n if n >= ER_COUNT else 0


def frequent_er(today=None):
    """``[(patient, count)]`` — three visits or more in 90 days."""
    from app.extensions import db
    from app.models import EmergencyVisit, Patient
    from app.utils.med_board import utc

    today = _today(today)
    start, end = utc(today - timedelta(days=ER_DAYS), today)
    rows = (db.session.query(EmergencyVisit.patient_id, db.func.count(EmergencyVisit.id))
            .filter(EmergencyVisit.arrived_at >= start, EmergencyVisit.arrived_at < end,
                    EmergencyVisit.patient_id.isnot(None))
            .group_by(EmergencyVisit.patient_id)
            .having(db.func.count(EmergencyVisit.id) >= ER_COUNT).all())
    if not rows:
        return []
    patients = {p.id: p for p in Patient.query.filter(Patient.id.in_([r[0] for r in rows]))}
    return sorted(((patients[pid], n) for pid, n in rows if pid in patients),
                  key=lambda r: -r[1])


# ------------------------------------------------------------- season -----
def _next_month(today):
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def season(today=None):
    """Next month in the years before: ``{month, years: [(year, visits)],
    average, diagnoses: [(code, title, n)], drugs: [(name, n)]}``."""
    from app.extensions import db
    from app.models import (Diagnosis, Prescription, PrescriptionItem, Visit,
                            VisitMedication)

    today = _today(today)
    month = _next_month(today)
    years, visit_ids = [], []
    for back in range(1, SEASON_YEARS + 1):
        start = date(month.year - back, month.month, 1)
        end = _next_month(start)
        ids = [vid for (vid,) in Visit.query
               .filter(Visit.visit_date >= start, Visit.visit_date < end,
                       Visit.channel.notin_(("lab",)))
               .with_entities(Visit.id)]
        if ids:
            years.append((start.year, len(ids)))
            visit_ids.extend(ids)
    out = {"month": month, "years": years,
           "average": round(sum(n for _, n in years) / len(years)) if years else None,
           "diagnoses": [], "drugs": []}
    if not visit_ids:
        return out
    dx, titles = Counter(), {}
    drugs = Counter()
    for i in range(0, len(visit_ids), 500):
        chunk = visit_ids[i:i + 500]
        for code, title in (Diagnosis.query.filter(Diagnosis.visit_id.in_(chunk))
                            .with_entities(Diagnosis.code, Diagnosis.title)):
            key = (code or "").strip().upper() or (title or "").strip()
            if key:
                dx[key] += 1
                titles.setdefault(key, title)
        # A medicine written in the room is carried to the prescription:
        # counted once a visit, whichever of the two holds it.
        per_visit = defaultdict(set)
        for vid, name in (VisitMedication.query.filter(VisitMedication.visit_id.in_(chunk))
                          .with_entities(VisitMedication.visit_id, VisitMedication.name)):
            if name:
                per_visit[vid].add(name.strip())
        for vid, name in (db.session.query(Prescription.visit_id, PrescriptionItem.drug_name)
                          .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
                          .filter(Prescription.visit_id.in_(chunk))):
            if name:
                per_visit[vid].add(name.strip())
        for names in per_visit.values():
            drugs.update(names)
    out["diagnoses"] = [(k, titles.get(k, ""), n) for k, n in dx.most_common(SEASON_TOP)]
    out["drugs"] = drugs.most_common(SEASON_TOP)
    return out
