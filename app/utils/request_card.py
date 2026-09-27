"""The card beside a booking request — ``BOOKING_APPROVAL_PLAN.md`` stage two.

A request says who asked and what for. Answering it meant opening the child's
file for their age and last visit, the vaccination tab for the dose that is
due, and the day board for a free time — three screens for one reply. The
card puts those on the request:

* **the child:** age, last visit (when, with whom), and a booking they
  already hold — a family that asks twice is not booked twice;
* **the dose that is due**, from the child's own vaccination plan — the same
  function the file's "next due" card reads, not a second opinion;
* **the soonest free time**: with the doctor asked for, or — asked for "any
  doctor" — with whichever doctor is free first; from the day the family
  asked for, or today if that day has passed.

It **suggests; a person books.** The time is offered as a button that opens
the ordinary booking screen with it filled in, and that screen makes every
check it makes for any booking — the slot still free, the doctor still
approving. Nothing here writes, and nothing here goes to the family.

The emergency rule the plan puts before all of this ("the urgent does not
wait for a model") needs the clinic's own words for what is urgent, and is
not written until it has them.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.extensions import db
from app.utils.clock import local_today


@dataclass
class Suggestion:
    """A free time, and with whom."""
    doctor_id: int
    date: str
    time: str
    #: The booking screen will refuse it until this doctor has said yes.
    needs_approval: bool = False


@dataclass
class Card:
    last_visit: Optional[date] = None
    last_visit_doctor: Optional[str] = None
    #: ``(date, time label, doctor name)`` of a booking already held.
    booked: Optional[tuple] = None
    #: ``(vaccine name, dose number, due date, status)``.
    next_dose: Optional[tuple] = None
    suggestion: Optional[Suggestion] = None


def _last_visits(patient_ids):
    """``{patient_id: Visit}`` — each child's latest visit up to today, in
    one question rather than one per request."""
    from app.models import Visit

    if not patient_ids:
        return {}
    latest = (db.session.query(Visit.patient_id,
                               db.func.max(Visit.visit_date).label("day"))
              .filter(Visit.patient_id.in_(patient_ids),
                      Visit.visit_date <= local_today())
              .group_by(Visit.patient_id).subquery())
    rows = (Visit.query.join(latest, db.and_(
                Visit.patient_id == latest.c.patient_id,
                Visit.visit_date == latest.c.day))
            .order_by(Visit.id.desc()).all())
    out = {}
    for visit in rows:
        out.setdefault(visit.patient_id, visit)
    return out


def _booked(patient_ids):
    """``{patient_id: Appointment}`` — the next booking each child holds."""
    from app.models import Appointment

    if not patient_ids:
        return {}
    rows = (Appointment.query
            .filter(Appointment.patient_id.in_(patient_ids),
                    Appointment.appt_date >= local_today(),
                    Appointment.status.notin_(("cancelled", "no_show")))
            .order_by(Appointment.appt_date, Appointment.appt_time).all())
    out = {}
    for appt in rows:
        out.setdefault(appt.patient_id, appt)
    return out


def _next_dose(patient, lang):
    """The dose the child's plan says is due next, or ``None``. A plan that
    cannot be read leaves the line off; it does not stop the card."""
    from app.utils.vaccines import next_due_dose, patient_plan

    try:
        due = next_due_dose(patient_plan(patient, lang))
    except Exception:  # noqa: BLE001 - the card must draw without it
        return None
    if not due:
        return None
    due_date, vaccine, _brand, dose = due
    return (vaccine.display_name(lang) if vaccine else "",
            dose.get("dose_number"), due_date, dose.get("status"))


def _from(request):
    """The day to look from: the one asked for, unless it has passed."""
    today = local_today()
    wanted = request.wanted_date
    return wanted if wanted and wanted > today else today


def suggest(request, cache=None):
    """The soonest free time for this request, or ``None`` if nothing is free
    in the look-ahead. ``cache`` is shared across one screen's requests: two
    families asking the same doctor from the same day are one search."""
    from app.utils import booking_requests
    from app.utils.appointments import first_available_doctor, next_available

    cache = {} if cache is None else cache
    start = _from(request)
    key = (request.doctor_id, start)
    if key not in cache:
        if request.doctor_id:
            found = next_available(request.doctor_id, start)
            cache[key] = found and {**found, "doctor_id": request.doctor_id}
        else:
            cache[key] = first_available_doctor(start)
    found = cache[key]
    if not found:
        return None
    return Suggestion(
        doctor_id=found["doctor_id"], date=found["date"], time=found["time"],
        needs_approval=booking_requests.needs_doctor(request,
                                                     found["doctor_id"]))


def cards(requests, lang="ar"):
    """``{request id: Card}`` for the requests on one screen."""
    patient_ids = sorted({r.patient_id for r in requests if r.patient_id})
    visits = _last_visits(patient_ids)
    booked = _booked(patient_ids)
    doses = {}
    cache = {}
    out = {}
    for req in requests:
        card = Card()
        if req.patient_id:
            visit = visits.get(req.patient_id)
            if visit is not None:
                card.last_visit = visit.visit_date
                card.last_visit_doctor = (visit.doctor.display_name(lang)
                                          if visit.doctor else None)
            appt = booked.get(req.patient_id)
            if appt is not None:
                card.booked = (appt.appt_date, appt.time_label,
                               appt.doctor.display_name(lang)
                               if appt.doctor else "")
            if req.patient_id not in doses:
                doses[req.patient_id] = _next_dose(req.patient, lang)
            card.next_dose = doses[req.patient_id]
        card.suggestion = suggest(req, cache)
        out[req.id] = card
    return out
