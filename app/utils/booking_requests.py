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

**Who says yes** (``BOOKING_APPROVAL_PLAN.md`` stage three). Decided for the
clinic: *the desk, and then the doctor* — and each doctor may change that for
themselves, because the clinics and hospitals this runs in work differently:
one doctor leaves their diary to the desk, another wants to see every request
first. So:

* the clinic's rule (``booking_approval``: ``both`` unless it says
  ``reception``), and a doctor's own choice over it;
* where the doctor approves, the desk sends the request to them, they say yes
  (or no, and why), and only then can it be booked — **for that doctor**: a
  yes from one doctor is not a yes to book the family with another;
* the booking screen refuses a request that still needs its doctor, so the
  rule holds however the desk reached the form.
"""
from datetime import datetime

from app.extensions import db
from app.models import ActivityLog, BookingRequest, Setting, User
from app.models.booking_request import OPEN_STATUSES

#: "both": the desk, then the doctor. "reception": the desk alone.
POLICIES = ("both", "reception")
#: The clinic's rule when it has not said otherwise — as decided for it.
DEFAULT_POLICY = "both"
NOTE_MAX = 200

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


def clinic_policy():
    """The clinic's rule: ``reception`` only when it says so."""
    chosen = (Setting.get("booking_approval", "") or "").strip()
    return chosen if chosen in POLICIES else DEFAULT_POLICY


def policy_for(doctor):
    """Whether ``doctor`` (a user or an id) approves requests too: their own
    choice, else the clinic's. No doctor yet — "any doctor" — is the clinic's
    rule; the doctor it is booked with decides in the end."""
    if doctor is not None and not isinstance(doctor, User):
        doctor = db.session.get(User, doctor)
    own = getattr(doctor, "booking_approval", None)
    return own if own in POLICIES else clinic_policy()


def needs_doctor(row, doctor_id):
    """Would booking ``row`` with ``doctor_id`` go past a yes that doctor has
    not given? A yes from another doctor is not this one's."""
    if not doctor_id or policy_for(doctor_id) != "both":
        return False
    return not (row.status == "approved" and row.approved_by == doctor_id)


def forward(row, user, doctor_id=None, ip_address=None):
    """The desk sends a request to the doctor to approve. Returns the row, or
    ``None`` when it was not waiting for the desk. Raises ``ValueError``
    without a doctor — "any doctor" has to become somebody to be asked."""
    if row is None or row.status != "pending":
        return None
    doctor_id = doctor_id or row.doctor_id
    if not doctor_id:
        raise ValueError("doctor")
    row.doctor_id = doctor_id
    row.status = "with_doctor"
    row.forwarded_by = getattr(user, "id", None)
    row.forwarded_at = datetime.utcnow()
    ActivityLog.record("booking_request.forward", user_id=row.forwarded_by,
                       entity="booking_request", entity_id=row.id,
                       detail=f"doctor {doctor_id}", ip_address=ip_address)
    return row


def approve(row, doctor, note=None, ip_address=None):
    """The doctor says yes. Only the doctor it was sent to, and only while it
    is with them; returns ``None`` otherwise."""
    if (row is None or row.status != "with_doctor" or doctor is None
            or row.doctor_id != doctor.id):
        return None
    row.status = "approved"
    row.approved_by = doctor.id
    row.approved_at = datetime.utcnow()
    row.approval_note = (note or "").strip()[:NOTE_MAX] or None
    ActivityLog.record("booking_request.approve", user_id=doctor.id,
                       entity="booking_request", entity_id=row.id,
                       detail=row.approval_note, ip_address=ip_address)
    return row


def decline(row, user, reason, ip_address=None):
    """Say no, and why — the desk at any point before it is booked, or the
    doctor it was sent to. Returns the row, or ``None`` when there was
    nothing to decide (already booked or declined). Raises ``ValueError``
    without a reason."""
    reason = (reason or "").strip()[:REASON_MAX]
    if not reason:
        raise ValueError("reason")
    if row is None or row.status not in OPEN_STATUSES:
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
    stands either way; it is the request that is not decided twice.

    The booking screen has already refused a request that still needed its
    doctor (``needs_doctor``); this is the record of what it allowed."""
    if row is None or row.status not in ("pending", "approved"):
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
    query = BookingRequest.query.filter(
        BookingRequest.status.in_(OPEN_STATUSES))
    if doctor_id:
        query = query.filter(db.or_(BookingRequest.doctor_id == doctor_id,
                                    BookingRequest.doctor_id.is_(None)))
    return query.order_by(BookingRequest.requested_at,
                          BookingRequest.id).all()


def awaiting(doctor_id):
    """What the desk has sent this doctor to approve, oldest first."""
    if not doctor_id:
        return []
    return (BookingRequest.query
            .filter(BookingRequest.status == "with_doctor",
                    BookingRequest.doctor_id == doctor_id)
            .order_by(BookingRequest.forwarded_at, BookingRequest.id).all())


def recent_decisions(limit=30):
    return (BookingRequest.query
            .filter(BookingRequest.status.notin_(OPEN_STATUSES))
            .order_by(BookingRequest.decided_at.desc(),
                      BookingRequest.id.desc())
            .limit(limit).all())
