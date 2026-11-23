"""Vaccination indicators — SMART_PATTERNS_PLAN ج-٢.

The vaccination unit's program measured whether families come back, not
only how many doses went in. Each figure here is a card on the performance
board with the period's value, the same period last year, a target the
clinic sets, and a line for the last 12 months:

* **coming back** — of the next doses that fell due in the period (the
  brand's schedule from the child's date of birth, or 28 days after the
  dose before when the child started late), how many were given within
  30 days of falling due. A due date less than 30 days ago is still open
  and not counted either way.
* **on time** — of those who came back, how many within 14 days.
* **series completed** — series started 6 to 12 months ago (the first dose
  given then) that have every scheduled dose of the brand by now.
* **reminders that worked** — families sent a vaccination reminder in the
  period (14 days ago or more) who had a dose given within 14 days of it.

A dose given outside the clinic counts as given: the child is protected, and
the family did come back to the schedule. A figure with nothing behind it is
«—», never 0 %. Targets are the clinic's own; the defaults are the
vaccination program's (45 %, 85 %, 70 %, 40 %).
"""
from collections import defaultdict
from datetime import date, timedelta

from app.models import Setting

RETURN_DAYS = 30
ON_TIME_DAYS = 14
REMINDER_DAYS = 14
LATE_START_GAP = 28
TARGETS = {"return": 45, "on_time": 85, "series": 70, "reminder": 40}
TARGET_KEY = "kpi_target:vaccines.{}"
REMINDER_TYPE = "vaccine_due"


def target(key):
    try:
        return int(Setting.get(TARGET_KEY.format(key), "") or TARGETS[key])
    except ValueError:
        return TARGETS[key]


def set_target(key, raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return False
    if key not in TARGETS or not 0 <= value <= 100:
        return False
    Setting.set(TARGET_KEY.format(key), str(value))
    return True


def _add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, 28)


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else None


def _schedules():
    """``{brand_id: {dose_number: age_months}}``."""
    from app.models import VaccineBrandDose

    out = defaultdict(dict)
    for row in VaccineBrandDose.query.all():
        out[row.brand_id][row.dose_number] = row.age_months
    return out


def _doses(since):
    """Every dose given since ``since``: ``{(patient, vaccine): [rows]}``,
    each list in dose order."""
    from app.models import PatientVaccine

    out = defaultdict(list)
    for row in (PatientVaccine.query
                .filter(PatientVaccine.event_type == "given",
                        PatientVaccine.given_date >= since)
                .with_entities(PatientVaccine.patient_id, PatientVaccine.vaccine_id,
                               PatientVaccine.brand_id, PatientVaccine.dose_number,
                               PatientVaccine.given_date)
                .order_by(PatientVaccine.given_date)):
        out[(row.patient_id, row.vaccine_id)].append(row)
    return out


def _births(patient_ids):
    from app.models import Patient

    if not patient_ids:
        return {}
    return dict(Patient.query.filter(Patient.id.in_(patient_ids))
                .with_entities(Patient.id, Patient.date_of_birth))


def due_events(d_from, d_to, today=None):
    """``[(due, returned_on or None)]`` for the next doses that fell due
    between ``d_from`` and ``d_to`` and whose 30 days have run out."""
    from app.utils.clock import local_today

    today = today or local_today()
    schedules = _schedules()
    # A next dose that falls due in the period may follow a dose given
    # years before (a booster at four after the doses of the first year).
    doses = _doses(d_from - timedelta(days=6 * 365))
    births = _births({p for p, _ in doses})
    out = []
    for (patient_id, _vaccine_id), rows in doses.items():
        born = births.get(patient_id)
        if born is None:
            continue
        given = {r.dose_number: r.given_date for r in rows}
        for r in rows:
            next_age = schedules.get(r.brand_id, {}).get(r.dose_number + 1)
            if next_age is None:
                continue
            due = max(_add_months(born, next_age),
                      r.given_date + timedelta(days=LATE_START_GAP))
            if not d_from <= due <= d_to or due + timedelta(days=RETURN_DAYS) > today:
                continue
            nxt = given.get(r.dose_number + 1)
            came = nxt if nxt is not None and nxt <= due + timedelta(days=RETURN_DAYS) else None
            out.append((due, came))
    return out


def coming_back(d_from, d_to, today=None):
    events = due_events(d_from, d_to, today)
    came = [(due, on) for due, on in events if on is not None]
    on_time = [1 for due, on in came if on <= due + timedelta(days=ON_TIME_DAYS)]
    return {"return": _pct(len(came), len(events)), "due": len(events), "came": len(came),
            "on_time": _pct(len(on_time), len(came)), "on_time_n": len(on_time)}


def series(today=None):
    """Series started 6–12 months ago, and how many are complete."""
    from app.utils.clock import local_today

    today = today or local_today()
    start, end = _add_months(today, -12), _add_months(today, -6)
    schedules = _schedules()
    doses = _doses(start)
    started = done = 0
    for rows in doses.values():
        first = next((r for r in rows if r.dose_number == 1), None)
        if first is None or not start <= first.given_date <= end:
            continue
        plan = schedules.get(first.brand_id, {})
        if len(plan) < 2:
            continue
        started += 1
        if set(plan) <= {r.dose_number for r in rows}:
            done += 1
    return {"series": _pct(done, started), "started": started, "done": done}


def reminders(d_from, d_to, today=None):
    from app.models import MessageLog, PatientVaccine
    from app.utils.clock import local_today, to_local

    today = today or local_today()
    last = min(d_to, today - timedelta(days=REMINDER_DAYS))
    if last < d_from:
        return {"reminder": None, "sent": 0, "came": 0}
    from app.utils.med_board import utc

    # The clinic's days, as stored UTC moments (end exclusive).
    start, end = utc(d_from, last)
    first_sent = {}
    for pid, at in (MessageLog.query
                    .filter(MessageLog.template_type == REMINDER_TYPE,
                            MessageLog.patient_id.isnot(None),
                            MessageLog.created_at >= start, MessageLog.created_at < end)
                    .with_entities(MessageLog.patient_id, MessageLog.created_at)):
        day = (to_local(at) or at).date()
        if d_from <= day <= last and (pid not in first_sent or day < first_sent[pid]):
            first_sent[pid] = day
    if not first_sent:
        return {"reminder": None, "sent": 0, "came": 0}
    came = 0
    given = defaultdict(list)
    for pid, d in (PatientVaccine.query
                   .filter(PatientVaccine.event_type == "given",
                           PatientVaccine.patient_id.in_(first_sent),
                           PatientVaccine.given_date >= d_from)
                   .with_entities(PatientVaccine.patient_id, PatientVaccine.given_date)):
        given[pid].append(d)
    for pid, sent in first_sent.items():
        if any(sent <= d <= sent + timedelta(days=REMINDER_DAYS) for d in given[pid]):
            came += 1
    return {"reminder": _pct(came, len(first_sent)), "sent": len(first_sent), "came": came}


def doses_given(d_from, d_to):
    from app.models import PatientVaccine

    return (PatientVaccine.query
            .filter(PatientVaccine.event_type == "given",
                    PatientVaccine.given_outside.is_(False),
                    PatientVaccine.given_date >= d_from,
                    PatientVaccine.given_date <= d_to).count())


def _year_before(d):
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d - timedelta(days=365)


def monthly(today=None, months=12):
    """``[(month_start, doses, return %)]`` for the last ``months`` months."""
    from app.utils.clock import local_today

    today = today or local_today()
    first = _add_months(today.replace(day=1), -(months - 1))
    events = due_events(first, today, today)
    out = []
    for i in range(months):
        start = _add_months(first, i)
        end = _add_months(start, 1) - timedelta(days=1)
        mine = [on for due, on in events if start <= due <= end]
        came = sum(1 for on in mine if on is not None)
        out.append((start, doses_given(start, end), _pct(came, len(mine))))
    return out


def board(d_from, d_to, today=None):
    """Everything the vaccinations tab shows."""
    back = coming_back(d_from, d_to, today)
    rem = reminders(d_from, d_to, today)
    ser = series(today)
    prev_from, prev_to = _year_before(d_from), _year_before(d_to)
    prev = coming_back(prev_from, prev_to, today)
    prev_rem = reminders(prev_from, prev_to, today)
    return {
        "doses": doses_given(d_from, d_to),
        "doses_before": doses_given(prev_from, prev_to),
        **back, **ser,
        "reminder": rem["reminder"], "sent": rem["sent"], "rem_came": rem["came"],
        "before": {"return": prev["return"], "on_time": prev["on_time"],
                   "reminder": prev_rem["reminder"]},
        "targets": {k: target(k) for k in TARGETS},
        "months": monthly(today),
    }
