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

**The urgent first** (stage two). "The urgent does not wait for a model": a
written rule, the same word list the WhatsApp inbox reads
(``app/utils/triage.py``), puts a request whose words say emergency above
every other. The rule only ever **raises**; a person may say it is not
urgent, or mark one urgent the words missed — and who said it is kept. It
tells the desk; it sends the family nothing.
"""
from datetime import datetime

from app.extensions import db
from app.models import ActivityLog, BookingRequest, Setting, User
from app.models.booking_request import (OPEN_STATUSES, REQUEST_SOURCES,
                                        URGENT_MARKS)

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
         source="desk", ip_address=None, conversation_key=None):
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
        message=(message or "").strip() or None,
        source=source if source in REQUEST_SOURCES else "desk",
        conversation_key=(conversation_key or "").strip()[:64] or None,
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


def urgent_word(row):
    """The emergency word the family's message carries, or ``None``."""
    from app.utils.triage import urgent_word as _word

    return _word(row.message)


def said_parts(text, word):
    """``[(piece, is_the_word)]``: the family's words, cut where the
    emergency word is, so the screen can mark it without writing markup
    into their words. Found however it was capitalised."""
    if not text:
        return []
    if not word:
        return [(text, False)]
    out, low, needle, at = [], text.lower(), word.lower(), 0
    while True:
        hit = low.find(needle, at)
        if hit < 0:
            break
        if hit > at:
            out.append((text[at:hit], False))
        out.append((text[hit:hit + len(word)], True))
        at = hit + len(word)
    if at < len(text):
        out.append((text[at:], False))
    return out


def is_urgent(row):
    """A person said so, or the words did and nobody has said otherwise."""
    if row.urgent_mark == "yes":
        return True
    return row.urgent_mark != "no" and urgent_word(row) is not None


def _urgent_first(rows):
    """The same order, with the urgent ones lifted above the rest. A stable
    sort: among the urgent, and among the rest, the longest wait still
    comes first."""
    return sorted(rows, key=lambda row: not is_urgent(row))


def mark_urgent(row, user, urgent, ip_address=None):
    """A person's word: urgent, or not. Returns the row, or ``None`` when it
    is no longer waiting for anybody."""
    if row is None or row.status not in OPEN_STATUSES:
        return None
    mark = URGENT_MARKS[0] if urgent else URGENT_MARKS[1]
    row.urgent_mark = mark
    row.urgent_by = getattr(user, "id", None)
    row.urgent_at = datetime.utcnow()
    ActivityLog.record("booking_request.urgent", user_id=row.urgent_by,
                       entity="booking_request", entity_id=row.id,
                       detail=mark, ip_address=ip_address)
    return row


def pending(doctor_id=None):
    """Requests waiting for somebody: the urgent first, then oldest first —
    the one who has waited longest is the one to answer first. With a
    doctor, that doctor's and the ones for any doctor."""
    query = BookingRequest.query.filter(
        BookingRequest.status.in_(OPEN_STATUSES))
    if doctor_id:
        query = query.filter(db.or_(BookingRequest.doctor_id == doctor_id,
                                    BookingRequest.doctor_id.is_(None)))
    return _urgent_first(query.order_by(BookingRequest.requested_at,
                                        BookingRequest.id).all())


def awaiting(doctor_id):
    """What the desk has sent this doctor to approve: the urgent first, then
    oldest first."""
    if not doctor_id:
        return []
    return _urgent_first(
        BookingRequest.query
        .filter(BookingRequest.status == "with_doctor",
                BookingRequest.doctor_id == doctor_id)
        .order_by(BookingRequest.forwarded_at, BookingRequest.id).all())


#: Where a request can stand, in order. A request whose doctor does not
#: approve goes from taken to booked.
STEPS_WITH_DOCTOR = ("taken", "with_doctor", "approved", "booked")
STEPS_DESK = ("taken", "booked")
_REACHED = {"pending": "taken", "with_doctor": "with_doctor",
            "approved": "approved", "booked": "booked"}


def steps(row, doctor_approves):
    """``[(step, state)]`` for the little progress line: ``done``,
    ``current`` or ``todo``. A declined request is not on this line — the
    screen says declined, and why."""
    names = STEPS_WITH_DOCTOR if doctor_approves or row.status in (
        "with_doctor", "approved") else STEPS_DESK
    reached = _REACHED.get(row.status)
    if reached not in names:
        return []
    at = names.index(reached)
    return [(name, "done" if i < at or row.status == "booked" else
             "current" if i == at else "todo")
            for i, name in enumerate(names)]


def for_conversation(key, patient_id=None, phone=None):
    """The requests taken from this WhatsApp conversation, newest first.

    A thread's key is the child once the number is on their file, and the
    number before that — so a request taken while the number was unknown is
    found by the number (however it is spelled), and one taken for the child
    from WhatsApp by the child."""
    if not key:
        return []
    from app.utils.inbox import phone_variants

    keys = [key] + phone_variants(phone)
    cond = BookingRequest.conversation_key.in_(keys)
    if patient_id:
        cond = db.or_(cond, db.and_(BookingRequest.patient_id == patient_id,
                                    BookingRequest.source == "whatsapp"))
    return (BookingRequest.query.filter(cond)
            .order_by(BookingRequest.requested_at.desc(),
                      BookingRequest.id.desc()).limit(5).all())


def recent_decisions(limit=30):
    return (BookingRequest.query
            .filter(BookingRequest.status.notin_(OPEN_STATUSES))
            .order_by(BookingRequest.decided_at.desc(),
                      BookingRequest.id.desc())
            .limit(limit).all())
