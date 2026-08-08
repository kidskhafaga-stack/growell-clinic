"""How long the child waited, and how long the doctor spent.

Four moments are stamped on an appointment as the family moves through the
clinic, and the gaps between them are the whole of this module:

    وصل ──[انتظار ١]── العلامات ──[انتظار ٢]── الطبيب ──[الكشف]── خلص
  checked_in_at        vitals_at            started_at      completed_at

**Why the middle stamp exists.** Without ``vitals_at`` the wait is a single
number covering two queues that belong to two different people — the one at
reception and the one at the doctor's door. A clinic reading "average wait 40
minutes" cannot act on it, because the fix for a slow front desk and the fix
for a doctor running late are not the same fix.

**Why ``started_at`` is stamped by the doctor opening the file.** It used to
be set only by a status button on the board that, in a busy clinic, nobody
ever pressed — so the timings existed as columns and were empty in practice.
Opening the record is an act of the doctor's own, at the moment the
consultation really begins, and nobody at the front desk can move it.

**On reading these numbers as a measure of a doctor.** Waiting is mostly a
measure of booking and reception, not of the doctor. And a *short*
consultation is not a good consultation — a scorecard that rewards shorter
minutes is a scorecard that rewards rushing a sick child. What the numbers
here can honestly answer is whether a doctor runs over the slot that was
booked for them, which is the thing that actually makes everybody else wait.
"""
from datetime import datetime

# Past this, the visit was not long — it was forgotten. A doctor who leaves a
# record open and closes it after lunch would otherwise contribute a single
# 300-minute consultation that moves a whole month's average.
MAX_SANE_MINUTES = 4 * 60


def _gap(start, end):
    """Minutes between two stamps, or None if either is missing or reversed."""
    if not start or not end or end < start:
        return None
    return (end - start).total_seconds() / 60.0


def intervals(appt):
    """Every span this appointment can account for, in minutes.

    ``None`` means "not measurable", which is different from zero and has to
    stay different: a clinic that never recorded vitals should see a blank,
    not a confident 0 that says the nurse was instant.
    """
    return {
        "to_vitals": _gap(appt.checked_in_at, appt.vitals_at),
        "after_vitals": _gap(appt.vitals_at or appt.checked_in_at,
                             appt.started_at),
        "wait": _gap(appt.checked_in_at, appt.started_at),
        "consult": _gap(appt.started_at, appt.completed_at),
        "total": _gap(appt.checked_in_at, appt.completed_at),
    }


def is_sane(appt):
    """Whether this appointment's consult can be counted in an average.

    A visit left open overnight is not evidence about how long consultations
    take. It is counted separately, as a number of forgotten records, because
    that is a real thing a manager should be told.
    """
    consult = _gap(appt.started_at, appt.completed_at)
    if consult is None:
        return False
    if consult > MAX_SANE_MINUTES:
        return False
    # Crossed into another day: same story, caught even when the clock gap
    # happens to look small.
    return appt.started_at.date() == appt.completed_at.date()


def waiting_minutes(appt, now=None):
    """How long this child has been waiting *so far* — for a live screen."""
    if not appt.checked_in_at or appt.started_at:
        return None
    return _gap(appt.checked_in_at, now or datetime.utcnow())


def overlaps(appts):
    """Ids of consultations that ran while the same doctor had another open.

    A doctor interrupted mid-consultation opens a second child's record and
    comes back; the wall clock then charges the first child with the
    interruption. Rather than inventing a pause button whose records nobody
    would trust, the overlap is reported — so a summary can say "this average
    is soft" instead of quietly being wrong.
    """
    out = set()
    by_doctor = {}
    for appt in appts:
        if appt.started_at and appt.completed_at:
            by_doctor.setdefault(appt.doctor_id, []).append(appt)
    for rows in by_doctor.values():
        rows.sort(key=lambda a: a.started_at)
        for i, first in enumerate(rows):
            for second in rows[i + 1:]:
                if second.started_at >= first.completed_at:
                    break               # sorted: nothing later can overlap
                out.add(first.id)
                out.add(second.id)
    return out


def summarise(appts):
    """The clinic-level picture over a set of appointments."""
    sane = [a for a in appts if is_sane(a)]
    overlapping = overlaps(appts)
    forgotten = [a for a in appts
                 if a.started_at and a.completed_at and not is_sane(a)]

    def _median(values):
        values = sorted(v for v in values if v is not None)
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return round(values[mid], 1)
        return round((values[mid - 1] + values[mid]) / 2.0, 1)

    waits = [intervals(a)["wait"] for a in appts]
    return {
        # Median, not mean: one forgotten record or one genuinely hard case
        # should not redraw the picture of an ordinary day.
        "wait": _median(waits),
        "to_vitals": _median([intervals(a)["to_vitals"] for a in appts]),
        "after_vitals": _median([intervals(a)["after_vitals"] for a in appts]),
        "consult": _median([intervals(a)["consult"] for a in sane]),
        # The worst case, not the middle one: the family that waited 54
        # minutes is the complaint the clinic is about to receive.
        "longest_wait": max((w for w in waits if w is not None), default=None),
        "counted": len(sane),
        "forgotten": len(forgotten),
        "overlapping": sum(1 for a in sane if a.id in overlapping),
    }


def over_slot(appt):
    """Minutes the consultation ran past the slot that was booked for it.

    This is the fair version of "how long does this doctor take": the clinic
    chose the slot, and running past it is what pushes the next family's
    appointment back. Negative means they finished inside it.
    """
    consult = _gap(appt.started_at, appt.completed_at)
    if consult is None or not appt.duration_minutes:
        return None
    return round(consult - appt.duration_minutes, 1)


def doctor_timings(date_from, date_to):
    """Per-doctor timings over a period, for the doctors screen.

    Two numbers, and deliberately not a third.

    ``consult`` is **description, not score**. It is the median length of a
    consultation with the spread around it, and nothing on the screen says
    shorter is better — a scorecard that rewards shorter minutes rewards
    rushing a sick child, which is the opposite of what a clinic wants to buy
    with a stopwatch.

    ``over_slot`` is the one that is fair to ask about. The clinic chose the
    slot; running past it is what pushes the next family's appointment back,
    and that is a question about how the day was planned rather than about how
    carefully somebody examined a child.

    **What is missing, and why.** "Did the doctor open the clinic on time"
    would be the third, and it cannot be computed honestly yet: appointment
    times are wall-clock times the clinic typed, while ``started_at`` is
    ``datetime.utcnow()``, and the program has no notion of which timezone it
    is in. Subtracting one from the other would report every doctor in Egypt
    as two or three hours late — a number so wrong it would discredit the rest
    of the screen. It needs a clinic timezone first.
    """
    from app.models import Appointment

    rows = (Appointment.query
            .filter(Appointment.appt_date >= date_from,
                    Appointment.appt_date <= date_to,
                    Appointment.started_at.isnot(None))
            .all())
    overlapping = overlaps(rows)

    by_doctor = {}
    for appt in rows:
        by_doctor.setdefault(appt.doctor_id, []).append(appt)

    out = {}
    for doctor_id, appts in by_doctor.items():
        sane = [a for a in appts if is_sane(a)]
        consults = sorted(_gap(a.started_at, a.completed_at) for a in sane)
        overs = [over_slot(a) for a in sane]
        overs = sorted(o for o in overs if o is not None)
        if not consults:
            continue
        mid = len(consults) // 2
        out[doctor_id] = {
            "consult": round(consults[mid] if len(consults) % 2 else
                             (consults[mid - 1] + consults[mid]) / 2.0, 1),
            "shortest": round(consults[0], 1),
            "longest": round(consults[-1], 1),
            "over_slot": (round(overs[len(overs) // 2], 1) if overs else None),
            "counted": len(sane),
            "forgotten": len(appts) - len(sane),
            "overlapping": sum(1 for a in sane if a.id in overlapping),
        }
    return out
