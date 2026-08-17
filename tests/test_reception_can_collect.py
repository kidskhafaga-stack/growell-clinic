"""The door was open and nothing on the screen led to it.

Reported twice, as two symptoms of one bug: *"the collect button doesn't show
after the booking"*, and *"the money owed doesn't show either, when the doctor
has done something inside the clinic"*.

Reception holds the ``cashier`` capability, which is deliberately enough for
the till without handing over the whole finance module — the decorator that
guards those routes says so in as many words, and every one of them is
``@cashier_access``. But three *buttons* were drawn only for
``can_access('finance')``:

* the collect button on the appointment board,
* "invoice this visit" on the visit — what the doctor added,
* the invoice link on the patient profile.

So a receptionist who could open any of those screens by typing the address
was shown no way to reach them. One condition, three copies, all three wrong,
which is why the fix is a single property on ``User`` rather than three
repaired templates.

The second half is that a booking appeared on no till list at all. The screen
showed unpaid *invoices* and clinical items given without one; a booking is
neither until somebody bills it. Reception had to leave the till, find the row
on the board, collect, and walk back — for each family.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A receptionist, and a child booked for today with nothing billed."""
    from app.extensions import db
    from app.models import Appointment, Patient, User

    with clinic["app"].app_context():
        rec = User.query.filter_by(username="desk").first()
        kid = Patient.query.first()
        doctor = User.query.filter_by(username="doc").first()
        appt = Appointment(patient_id=kid.id, doctor_id=doctor.id,
                           appt_date=local_today(), appt_time=time(10, 0),
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        clinic["appt"] = appt.id
        clinic["kid"] = kid.id
        clinic["rec_has_finance"] = rec.can_access("finance")
    return clinic


# --------------------------------------------------------------- the rule

def test_reception_may_collect_without_the_whole_finance_module(desk):
    """The premise. If reception had the module this bug could not exist."""
    from app.models import User

    with desk["app"].app_context():
        rec = User.query.filter_by(username="desk").first()

        assert rec.can("cashier") is True
        assert rec.can_access("finance") is False, \
            "reception has the whole finance module, so this tests nothing"
        assert rec.can_collect is True


def test_the_rule_is_one_property_not_three_conditions(desk):
    """Three templates asked the same question and got it wrong three times."""
    from app.models import User

    with desk["app"].app_context():
        rec = User.query.filter_by(username="desk").first()
        doctor = User.query.filter_by(username="doc").first()
        boss = User.query.filter_by(username="boss").first()

        assert rec.can_collect is True
        assert boss.can_collect is True
        assert doctor.can_collect is False, \
            "a doctor was handed the till by a permissions change"


# ----------------------------------------------------- the three buttons

def test_the_collect_button_is_on_the_appointment_board(desk):
    """The reported symptom: booked, and no way to take the money."""
    page = desk["sign_in"]("desk").get("/appointments/",
                                       follow_redirects=True).data.decode()

    assert f"/finance/checkout/{desk['appt']}" in page, \
        "reception books a family and is shown no way to collect from them"


def test_what_the_doctor_added_reaches_reception_on_the_till(desk):
    """The second reported symptom, and it is NOT the visit screen.

    Reception has no `visits` module at all, so the "invoice this visit"
    button was never their route to it — a claim worth correcting rather than
    quietly dropping. Their route is the till, which already lists services a
    doctor added without an invoice; what was missing was only the *link* out
    of it, which is drawn for whoever may collect.
    """
    from app.extensions import db
    from app.models import Service, User, Visit, VisitService

    with desk["app"].app_context():
        assert not User.query.filter_by(username="desk").first().can_access("visits"), \
            "reception can open visits now, so this test is aimed at the wrong screen"

        doctor = User.query.filter_by(username="doc").first()
        service = Service.query.first()
        visit = Visit(patient_id=desk["kid"], doctor_id=doctor.id,
                      visit_date=local_today(), status="completed")
        db.session.add(visit)
        db.session.flush()
        db.session.add(VisitService(visit_id=visit.id, service_id=service.id,
                                    name=service.name, quantity=1))
        db.session.commit()

    page = desk["sign_in"]("desk").get("/finance/cashier",
                                       follow_redirects=True).data.decode()

    assert f"/finance/collect/{desk['kid']}" in page, \
        "what the doctor added is not collectable from the till"


def test_the_visit_button_follows_the_same_rule(desk):
    """The visit screen's own collect button was gated the same wrong way.

    It matters for whoever holds both visits and the till — an admin, or a
    clinic's own role — rather than for reception, who never sees this screen.
    """
    from app.extensions import db
    from app.models import User, Visit

    with desk["app"].app_context():
        doctor = User.query.filter_by(username="doc").first()
        visit = Visit(patient_id=desk["kid"], doctor_id=doctor.id,
                      visit_date=local_today(), status="completed")
        db.session.add(visit)
        db.session.commit()
        vid = visit.id

    page = desk["sign_in"]("boss").get(f"/visits/{vid}").data.decode()

    assert f"/finance/collect/{desk['kid']}" in page


def test_the_patient_profile_links_its_invoices(desk):
    """Third copy of the same condition."""
    from app.extensions import db
    from app.models import Invoice
    from app.utils.finance import generate_invoice_number

    with desk["app"].app_context():
        inv = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=desk["kid"], invoice_date=local_today(),
                      status="unpaid")
        db.session.add(inv)
        db.session.commit()
        iid = inv.id

    page = desk["sign_in"]("desk").get(f"/patients/{desk['kid']}").data.decode()

    assert f"/finance/invoices/{iid}" in page, \
        "reception cannot open an invoice from the patient's own file"


def test_a_doctor_is_not_given_the_collect_button(desk):
    """Widening a permission must not widen it past who asked."""
    page = desk["sign_in"]("doc").get("/appointments/",
                                      follow_redirects=True).data.decode()

    assert f"/finance/checkout/{desk['appt']}" not in page


# ------------------------------------------------- the booking on the till

def test_todays_booking_is_on_the_till(desk):
    """So the desk works down one screen instead of walking to the board.

    The booking needs a price. A visit worth nothing is deliberately kept off
    this list — see `test_collect_prompt_and_free` — so an unpriced one could
    not show whether the list works.
    """
    from app.extensions import db
    from app.models import Appointment, Service

    with desk["app"].app_context():
        service = Service.query.first()
        service.visit_type = "consultation"
        service.price = 200
        db.session.get(Appointment, desk["appt"]).appt_type = "consultation"
        db.session.commit()

    page = desk["sign_in"]("desk").get("/finance/cashier",
                                       follow_redirects=True).data.decode()

    assert f"/finance/checkout/{desk['appt']}" in page, \
        "a booking nobody has billed is on no list the cashier can see"


def test_a_booking_already_billed_drops_off_it(desk):
    """A list that never shrinks stops being a work list."""
    from app.extensions import db
    from app.models import Invoice, InvoiceItem
    from app.utils.finance import generate_invoice_number

    with desk["app"].app_context():
        inv = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=desk["kid"], invoice_date=local_today(),
                      status="unpaid")
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   quantity=1, unit_price=200))
        db.session.commit()

    page = desk["sign_in"]("desk").get("/finance/cashier",
                                       follow_redirects=True).data.decode()
    section = page.split("unbilled")[0]

    assert f"/finance/checkout/{desk['appt']}" not in section, \
        "a booking that has been billed is still listed as unbilled"


def test_the_till_still_opens_when_nothing_is_booked(desk):
    """An empty day must not be an empty screen or a crash."""
    from app.extensions import db
    from app.models import Appointment

    with desk["app"].app_context():
        db.session.delete(db.session.get(Appointment, desk["appt"]))
        db.session.commit()

    assert desk["sign_in"]("desk").get(
        "/finance/cashier", follow_redirects=True).status_code == 200


def test_the_till_reads_the_boards_own_answer(desk):
    """Two readings of "has this been paid" would eventually disagree in
    front of a family, so the till asks the board rather than deciding."""
    import inspect

    from app.blueprints.finance import routes

    source = inspect.getsource(routes._unbilled_bookings)
    assert "_payment_status" in source, \
        "the till works out the payment state a second time"
