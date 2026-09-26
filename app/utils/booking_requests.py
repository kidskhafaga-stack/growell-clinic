"""Booking requests: taken, then booked or declined — by a person.

The rules, in one place, so the screens only ask:

* a request names a child on file, or somebody to call back — never nobody;
* it holds no slot; the appointment is made at the moment it is booked, by
  the booking screen, with every check that screen already makes;
* it is decided once — a request booked or declined stays so, and a second
  press of either button changes nothing;
* a decline says why, because the family is owed a reason and the next
  person to read the request is owed it too;
* every step is in the audit log: who took it, who booked it, who declined
  it and why.

Nothing here writes to the family. The plan's line holds from the first
stage: no appointment is confirmed to anyone before it is in the book.
"""
from datetime import datetime

from app.extensions import db
from app.models import ActivityLog, BookingRequest

NAME_MAX = 120
PHONE_MAX = 30
REASON_MAX = 200


def take(user, patient_id=None, contact_name=None, contact_phone=None,
         doctor_id=None, wanted_date=None, appt_type=None, message=None,
         source="desk", ip_address=None):
    """Record a request. Raises ``ValueError`` when it names nobody — a
    request nobody can be booked for or called back about is not one."""
    name = (contact_name or "").strip()[:NAME_MAX] or None
    phone = (contact_phone or "").strip()[:PHONE_MAX] or None
    if not patient_id and not (name and phone):
        raise ValueError("who")
    row = BookingRequest(
        patient_id=patient_id or None,
        contact_name=None if patient_id else name,
        contact_phone=None if patient_id else phone,
        doctor_id=doctor_id or None, wanted_date=wanted_date,
        appt_type=appt_type or None,
        message=(message or "").strip() or None, source=source,
        status="pending", requested_by=getattr(user, "id", None),
        requested_at=datetime.utcnow())
    db.session.add(row)
    db.session.flush()
    ActivityLog.record("booking_request.take", user_id=row.requested_by,
                       entity="booking_request", entity_id=row.id,
                       ip_address=ip_address)
    return row


def decline(row, user, reason, ip_address=None):
    """Say no, and why. Returns the row, or ``None`` when there was nothing
    to decide (already booked or declined). Raises ``ValueError`` without a
    reason."""
    reason = (reason or "").strip()[:REASON_MAX]
    if not reason:
        raise ValueError("reason")
    if row is None or row.status != "pending":
        return None
    row.status = "declined"
    row.decline_reason = reason
    row.decided_by = getattr(user, "id", None)
    row.decided_at = datetime.utcnow()
    ActivityLog.record("booking_request.decline", user_id=row.decided_by,
                       entity="booking_request", entity_id=row.id,
                       detail=reason, ip_address=ip_address)
    return row


def booked(row, appointment, user, ip_address=None):
    """The booking screen made an appointment from this request. Returns the
    row, or ``None`` when it had already been decided — the appointment
    stands either way; it is the request that is not decided twice."""
    if row is None or row.status != "pending":
        return None
    row.status = "booked"
    row.appointment_id = appointment.id
    # The child the desk chose or registered is who the request was about.
    row.patient_id = appointment.patient_id
    row.decided_by = getattr(user, "id", None)
    row.decided_at = datetime.utcnow()
    ActivityLog.record("booking_request.book", user_id=row.decided_by,
                       entity="booking_request", entity_id=row.id,
                       detail=f"appointment {appointment.id}",
                       ip_address=ip_address)
    return row


def pending(doctor_id=None):
    """Requests waiting for somebody, oldest first — the one who has waited
    longest is the one to answer first. With a doctor, that doctor's and the
    ones for any doctor."""
    query = BookingRequest.query.filter(BookingRequest.status == "pending")
    if doctor_id:
        query = query.filter(db.or_(BookingRequest.doctor_id == doctor_id,
                                    BookingRequest.doctor_id.is_(None)))
    return query.order_by(BookingRequest.requested_at,
                          BookingRequest.id).all()


def recent_decisions(limit=30):
    return (BookingRequest.query
            .filter(BookingRequest.status != "pending")
            .order_by(BookingRequest.decided_at.desc(),
                      BookingRequest.id.desc())
            .limit(limit).all())
