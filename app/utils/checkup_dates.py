"""«المريض بيعمل الفحص إمتى» — the last time this child was seen, and when
the clinic expects them next, and why (IMPROVEMENTS_BACKLOG ٦).

The answer was spread over three screens: the last visit in the visits list,
the follow-up the doctor asked for on that visit (``utils/followup``), and the
next vaccine in the vaccination tab. One line on the child's file now puts
them together:

* **the last check-up** — the date and the doctor;
* **the next one** — the earliest of: an appointment already booked, the
  follow-up date the doctor gave that nobody has come for yet, and the next
  vaccine dose due — with which of the three it is, and by how many days it
  has been missed when the date has passed.

Nothing new is stored and no date is the program's own: each one is a date a
doctor wrote, a booking somebody made, or the vaccine plan the clinic keeps.
"""
from datetime import date


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def last_visit(patient, today):
    from app.models import Visit

    return (Visit.query.filter(Visit.patient_id == patient.id,
                               Visit.visit_date <= today)
            .order_by(Visit.visit_date.desc(), Visit.id.desc()).first())


def _booked(patient, today):
    from app.models import Appointment

    return (Appointment.query
            .filter(Appointment.patient_id == patient.id,
                    Appointment.appt_date >= today,
                    Appointment.status.in_(("scheduled", "waiting")))
            .order_by(Appointment.appt_date, Appointment.appt_time).first())


def _asked_back(patient, today):
    """The latest visit whose follow-up date is still owed — told, overdue or
    missed, never one they came back for or that is already booked."""
    from app.models import Visit
    from app.utils import followup

    rows = (Visit.query.filter(Visit.patient_id == patient.id,
                               Visit.followup_due.isnot(None))
            .order_by(Visit.visit_date.desc(), Visit.id.desc()).limit(5).all())
    for visit in rows:
        state = followup.state(visit, on_date=today)
        if state in (followup.TOLD, followup.OVERDUE, followup.MISSED):
            return visit
        if state in (followup.CAME, followup.BOOKED):
            return None
    return None


def for_patient(patient, vaccine_next=None, today=None, lang="ar"):
    """``{"last": {...} | None, "next": {...} | None}``.

    ``next`` is ``{"date", "kind" ("booked"|"followup"|"vaccine"), "who",
    "what", "late_days"}``; ``vaccine_next`` is what the file already worked
    out (``vaccines.next_due_dose``), passed in so it is not worked out twice.
    """
    from app.utils.clock import local_today

    today = today or local_today()
    out = {"last": None, "next": None}
    seen = last_visit(patient, today)
    if seen is not None:
        out["last"] = {"date": seen.visit_date,
                       "who": seen.doctor.display_name(lang) if seen.doctor else ""}
    options = []
    booked = _booked(patient, today)
    if booked is not None:
        options.append({"date": booked.appt_date, "kind": "booked",
                        "who": booked.doctor.display_name(lang) if booked.doctor else "",
                        "what": booked.time_label})
    asked = _asked_back(patient, today)
    if asked is not None and booked is None:
        options.append({"date": asked.followup_due, "kind": "followup",
                        "who": asked.doctor.display_name(lang) if asked.doctor else "",
                        "what": ""})
    if vaccine_next:
        due = _as_date(vaccine_next[0])
        if due is not None:
            vaccine = vaccine_next[1]
            name = vaccine.display_name(lang) if hasattr(vaccine, "display_name") else str(vaccine or "")
            options.append({"date": due, "kind": "vaccine", "who": "", "what": name})
    if options:
        nxt = min(options, key=lambda o: o["date"])
        nxt["late_days"] = (today - nxt["date"]).days if nxt["date"] < today else 0
        out["next"] = nxt
    return out


def missed_patient_ids(limit=500):
    """The children a doctor asked back whose date has passed with nobody
    seen — the same answer as the follow-ups screen (``followup.outstanding``)."""
    from app.utils import followup

    return list(dict.fromkeys(v.patient_id for v in followup.outstanding(limit=limit)))


__all__ = ["for_patient", "last_visit", "missed_patient_ids"]
