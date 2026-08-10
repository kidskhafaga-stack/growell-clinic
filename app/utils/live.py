"""What "the screen is current" means, in one place.

The clinic's screens stay fresh by asking, every few seconds, whether anything
they show has changed — a short fingerprint of the day, compared against the
last one. Cheap: column-only queries over indexed columns, and the page
reloads only when the answer differs. Idle polling costs almost nothing.

The catch is that a fingerprint is only as honest as what it covers. The
doctor's board covered the appointments and nothing else, while the board
itself also shows **who has paid** — so reception could raise the bill and
take the money and the doctor's screen went on saying "not billed" until
somebody pressed refresh. The screen looked live, which is worse than a
screen that plainly isn't: nobody refreshes a screen they believe.

So the rule here: whatever a screen *shows*, its fingerprint *covers*.
"""
import hashlib
from datetime import datetime

from app.utils.clock import to_utc


def _digest(parts):
    return hashlib.md5(repr(parts).encode()).hexdigest()


def day_bounds(on_date):
    """The clinic's day, as the naive UTC range the database stores.

    ``on_date`` is a **clinic** date — it comes from ``local_today`` — while
    ``Payment.paid_at`` is written with ``datetime.utcnow()``. Combining the
    date with midnight and comparing that directly asks for "UTC midnight to
    UTC midnight of that calendar date", which is not the clinic's day at all
    once the two zones differ.

    For a Cairo clinic on a UTC server the mismatch is the first three hours
    of every working day: money collected between midnight and 03:00 fell
    outside the window, so the live board did not notice a payment and the
    doctor's screen sat there stale while the desk was taking cash. Found by a
    test at 00:20 Cairo, which is the only hour it can be found in.
    """
    return (to_utc(datetime.combine(on_date, datetime.min.time())),
            to_utc(datetime.combine(on_date, datetime.max.time())))


def board_fingerprint(on_date, doctor_id=None):
    """Everything the doctor's board and the appointment board show.

    Three things, because the board shows three things:

    * the queue — who is booked, and where each of them has got to;
    * the billing — whether a charge exists for them at all;
    * the money — what has actually been collected against it.

    The last two are why this exists. An invoice raised at the desk does not
    touch any appointment row, and a payment against an already-partial
    invoice does not even change the invoice's status — so neither was
    visible to a fingerprint built from appointments, or from invoice status
    alone. The payment ids are in here for exactly that case.
    """
    from app.extensions import db
    from app.models import Appointment, Invoice, Payment

    appts = (db.session.query(Appointment.id, Appointment.status,
                              Appointment.appt_time,
                              Appointment.patient_id)
             .filter(Appointment.appt_date == on_date))
    if doctor_id:
        appts = appts.filter(Appointment.doctor_id == doctor_id)
    queue = sorted(appts.all())

    # Only the patients on this board: a busy clinic's other invoices are none
    # of this screen's business, and scanning them would make the cheap poll
    # expensive.
    patient_ids = {row[3] for row in queue}
    bills, paid = [], []
    if patient_ids:
        bills = sorted(
            db.session.query(Invoice.id, Invoice.status)
            .filter(Invoice.patient_id.in_(patient_ids),
                    Invoice.invoice_date == on_date).all())
        start, end = day_bounds(on_date)
        paid = sorted(
            db.session.query(Payment.id)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .filter(Invoice.patient_id.in_(patient_ids),
                    Payment.paid_at >= start, Payment.paid_at <= end).all())

    return _digest((queue, bills, paid))


def patient_fingerprint(patient_id):
    """Everything the patient's file shows that somebody else can change.

    The complaint this exists for: the doctor records a visit, and the admin
    with the same file open sees nothing until they press refresh. Nobody
    presses refresh on a screen that has never been stale before.

    Covers the file's sections rather than one table, for the reason at the top
    of this module — a fingerprint narrower than the screen is how a screen
    comes to look live while lying. Ids and timestamps only: no joins, no
    scanning of anything the screen does not display.
    """
    from app.extensions import db
    from app.models import (Consent, DeviceStudy, Invoice, Patient,
                            Prescription, Visit)

    parts = []
    for model, column in ((Visit, Visit.patient_id),
                          (Prescription, Prescription.patient_id),
                          (DeviceStudy, DeviceStudy.patient_id),
                          (Consent, Consent.patient_id),
                          (Invoice, Invoice.patient_id)):
        rows = (db.session.query(model.id, model.updated_at)
                if hasattr(model, "updated_at")
                else db.session.query(model.id))
        parts.append(sorted(rows.filter(column == patient_id).all()))
    # The child's own row: a corrected birth date or a new guardian changes
    # what the top of the file says.
    parts.append(db.session.query(Patient.id, Patient.updated_at)
                 .filter(Patient.id == patient_id).all())
    return _digest(parts)


def visit_fingerprint(visit_id):
    """What one visit's record shows: its own row and everything hung off it.

    A doctor and an admin can be in the same visit at once — one recording,
    one watching — and the second needs to know the first has written
    something.
    """
    from app.extensions import db
    from app.models import (DeviceStudy, Prescription, Visit,
                            VisitInvestigation, VisitMedication, VisitService)

    parts = [db.session.query(Visit.id, Visit.status, Visit.updated_at)
             .filter(Visit.id == visit_id).all()]
    for model, column in ((VisitService, VisitService.visit_id),
                          (VisitMedication, VisitMedication.visit_id),
                          (VisitInvestigation, VisitInvestigation.visit_id),
                          (DeviceStudy, DeviceStudy.visit_id),
                          (Prescription, Prescription.visit_id)):
        parts.append(sorted(db.session.query(model.id)
                            .filter(column == visit_id).all()))
    return _digest(parts)


# The screens a fingerprint can be asked for, and how to build it. Kept as a
# map so the endpoint serving them cannot be talked into running something
# else by a crafted URL.
FINGERPRINTS = {
    "patient": patient_fingerprint,
    "visit": visit_fingerprint,
}
