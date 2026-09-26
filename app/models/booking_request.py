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
REQUEST_STATUSES = ("pending", "booked", "declined")

#: Where it came in. Only the desk exists yet; the others are the two doors
#: the plan leaves open (the official WhatsApp API, or a request page).
REQUEST_SOURCES = ("desk", "whatsapp", "page")


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

    patient = db.relationship("Patient")
    doctor = db.relationship("User", foreign_keys=[doctor_id])
    requester = db.relationship("User", foreign_keys=[requested_by])
    decider = db.relationship("User", foreign_keys=[decided_by])
    appointment = db.relationship("Appointment")

    def who(self, lang="ar"):
        """The name to show: the child on file, or the name they gave."""
        if self.patient is not None:
            return self.patient.display_name(lang)
        return self.contact_name or ""

    def __repr__(self):
        return f"<BookingRequest {self.id} {self.status}>"
