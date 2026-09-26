"""The vaccination fee, kept — not made and thrown away on every visit.

The vaccination fee (``رسم تطعيم``) is the service every vaccine line is
billed under, and a clinic that never set one up — the wizard's vaccination
box left unticked — has one made for it the first time it is needed
(``finance._vaccine_service``).

It was made, and then lost, on every screen that only shows things. The
booking form, the checkout and the invoice builder all ask for it to draw
themselves; nothing on those screens is saved, so the new row went back out
with the request. The page had already been handed its number — a service
that did not exist — and it happened again on the next visit, holding the
database's write lock while the page was drawn; and whatever was saved next
took that number.

Now, made on a screen that only shows things, it is kept at once. Made while
something is being saved, it is saved with the rest, as it always was.
"""
import os
import re
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _fees(clinic):
    from app.models import Service

    with clinic["app"].app_context():
        return [(s.id, s.code, s.visit_type) for s in Service.query.filter_by(
            category="vaccination_fee").all()]


def test_the_booking_form_keeps_what_it_made(clinic):
    assert _fees(clinic) == []                      # never set up
    client = clinic["sign_in"]("desk")
    assert client.get("/appointments/new").status_code == 200
    [(fee_id, code, visit_type)] = _fees(clinic)
    assert code == "SVC-VACFEE" and visit_type == "vaccination"

    # Opened again: the same one — not a second, and not a number that
    # points at nothing.
    page = client.get("/appointments/new").get_data(as_text=True)
    assert _fees(clinic) == [(fee_id, code, visit_type)]
    box = re.search(r'<input type="checkbox" name="extra_services" '
                    r'value="(\d+)"\s+data-opens-vaccine="1"', page)
    assert box and int(box.group(1)) == fee_id


def test_the_checkout_keeps_what_it_made(clinic):
    from app.extensions import db
    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(10, 0),
                           appt_type="followup", status="waiting")
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id

    client = clinic["sign_in"]("boss")
    assert client.get(f"/finance/checkout/{appt_id}").status_code == 200
    [(fee_id, _code, _vt)] = _fees(clinic)
    page = client.get(f"/finance/checkout/{appt_id}").get_data(as_text=True)
    assert f'"id": {fee_id}' in page
    assert len(_fees(clinic)) == 1


def test_a_clinic_that_has_one_writes_nothing_to_open_the_form(clinic):
    """The keeping is for the clinic that had none. One that has it only
    reads it, and opening the booking form takes no write lock."""
    from sqlalchemy import event

    from app.extensions import db

    client = clinic["sign_in"]("desk")
    client.get("/appointments/new")                  # made and kept, once
    with clinic["app"].app_context():
        engine = db.engine
    writes = []

    def hear(_conn, _cur, statement, *_rest):
        if statement.split(None, 1)[0].upper() in ("INSERT", "UPDATE",
                                                   "DELETE"):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", hear)
    try:
        client.get("/appointments/new")
    finally:
        event.remove(engine, "before_cursor_execute", hear)
    assert writes == []


def test_a_save_that_fails_keeps_nothing(clinic):
    """Made while something is being saved, it is saved with the rest — and
    if the rest is thrown away, so is it. The screens that only show things
    are the only ones that keep it on their own."""
    from app.blueprints.finance.routes import _vaccine_service
    from app.extensions import db

    with clinic["app"].test_request_context(method="POST"):
        _vaccine_service()
        db.session.rollback()
    assert _fees(clinic) == []
