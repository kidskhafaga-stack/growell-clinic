"""A family asking for an appointment — before anybody has given them one.

``BOOKING_APPROVAL_PLAN.md``, stage one. A child with a fever and a child due
a follow-up jab write the same sentence — *«عايزة أقرب موعد»* — and a machine
that books Thursday for the one who needs today has done harm the family has
already been told is fine. So what arrives is a **request**; a person reads
it and books it, or says no and why.

**Its own table, not an appointment with a new status.** The plan called it
a status, and the point of that was that a request must not hold a slot.
Twenty-three files read appointments, and not all of them ask about status —
the child's file lists every appointment it has — so a request stored as one
would appear as a booking on every screen that forgot to exclude it. Kept
apart, no screen can mistake it for one; approving it makes the appointment
through the ordinary booking screen, with every check that screen makes.

**The family need not be on file.** A request is often the first contact;
the name and phone they gave are kept, and the child is chosen or registered
when it is booked.
"""
from datetime import datetime

from app.extensions import db

#: pending → booked (an appointment was made from it) or declined (with why).
#: Where the doctor approves too (``booking_requests.policy_for``):
#: pending → with_doctor (sent by the desk) → approved (by that doctor) → booked.
REQUEST_STATUSES = ("pending", "with_doctor", "approved", "booked",
                    "declined")

#: Still waiting for somebody to do something.
OPEN_STATUSES = ("pending", "with_doctor", "approved")

#: Where it came in: the desk, a WhatsApp conversation in the inbox, or —
#: a door the plan leaves open — a request page.
REQUEST_SOURCES = ("desk", "whatsapp", "page")

#: What the desk did with the program's suggested time, when it booked —
#: stage five's question, "how often does the desk change the suggestion?":
#: ``kept`` it, moved the ``time`` on the same day, another ``day``, another
#: ``doctor``; or ``none`` — nothing was free to suggest.
SUGGESTION_OUTCOMES = ("kept", "time", "day", "doctor", "none")

#: A person's word on "is this an emergency": ``yes`` raises it, ``no``
#: overrules the program's guess. Empty is nobody said — the guess stands.
URGENT_MARKS = ("yes", "no")


class BookingRequest(db.Model):
    __tablename__ = "booking_requests"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"),
                           index=True)
    # Who asked, in their own words, when the child is not on file yet.
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(30))

    # What they asked for. Every one of these may be empty: "as soon as
    # possible, any doctor" is a request too.
    doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    wanted_date = db.Column(db.Date)
    appt_type = db.Column(db.String(20))
    # The family's words, as they came. The desk decides from these, and
    # stage two's triage will read them.
    message = db.Column(db.Text)
    source = db.Column(db.String(12), default="desk", nullable=False)

    status = db.Column(db.String(12), default="pending", nullable=False,
                       index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    requested_at = db.Column(db.DateTime, default=datetime.utcnow,
                             nullable=False)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime)
    decline_reason = db.Column(db.String(200))
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"))

    # Sent to the doctor by the desk, and the doctor's yes — kept apart from
    # ``decided_*``, which is the final answer (booked or declined).
    forwarded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    forwarded_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime)
    approval_note = db.Column(db.String(200))

    # Stage two's emergency rule: the program raises a request whose words
    # say "emergency" (``app/utils/triage.py``, the inbox's own list); a
    # person can raise one, or say it is not — and who said it is kept.
    urgent_mark = db.Column(db.String(4))
    urgent_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    urgent_at = db.Column(db.DateTime)
    # The WhatsApp conversation it was taken from (the inbox's thread key),
    # so the thread can show where its request stands.
    conversation_key = db.Column(db.String(64), index=True)

    # Stage five's measure: the time the program suggested when the desk
    # opened the booking, and what the desk did with it. Kept once, when
    # the request is booked — the answer to "how often is it changed?" is
    # read from these after two months, not guessed.
    suggested_doctor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    suggested_date = db.Column(db.Date)
    suggested_time = db.Column(db.String(5))
    suggestion_outcome = db.Column(db.String(8), index=True)

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    requester = db.relationship("User", foreign_keys=[requested_by])
    decider = db.relationship("User", foreign_keys=[decided_by])
    forwarder = db.relationship("User", foreign_keys=[forwarded_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    urgent_marker = db.relationship("User", foreign_keys=[urgent_by])
    appointment = db.relationship("Appointment")

    def who(self, lang="ar"):
        """The name to show: the child on file, or the name they gave."""
        if self.patient is not None:
            return self.patient.display_name(lang)
        return self.contact_name or ""

    def __repr__(self):
        return f"<BookingRequest {self.id} {self.status}>"
