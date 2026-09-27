"""Paid at the desk, so here — arrival and payment in one step.

``IMPROVEMENTS_BACKLOG.md`` item 1: *"collecting does not mark the booking
arrived — still two steps, not one."* Reception took the money for today's
visit and then had to find the same booking on the board and press
"arrived"; forgotten, the child was not in the queue.

What is held here:

* money taken at the desk — at the checkout, or as a payment on the bill —
  for **today's** booking that is **still only booked** marks it arrived:
  the check-in time stamped, the log written, reception told;
* a booking for another day, paid in advance, is not arrived;
* a child already waiting, inside, missed or cancelled is left where they
  are — it only moves a booking forward from "booked";
* "pay later" — no money taken — marks nothing;
* money paid online, from home, is not the family at the desk;
* a clinic that turns it off keeps the two steps.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_paid_through_a_gateway import (  # noqa: E402,F401
    _make_link, _notify, _paid, _rows, bill, stand_in)


@pytest.fixture()
def desk(clinic):
    """A booking for today and one for tomorrow, and a shift open at the
    till — without one the till refuses cash and says so."""
    from app.models import Appointment, CashierShift
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        ids = {}
        for name, day, hour in (("today", 0, 11), ("tomorrow", 1, 11)):
            appt = Appointment(patient_id=clinic["ids"]["child"],
                               doctor_id=clinic["ids"]["doctor"],
                               appt_date=local_today() + timedelta(days=day),
                               appt_time=time(hour, 0), status="scheduled",
                               appt_type="consultation")
            db.session.add(appt)
            db.session.flush()
            ids[name] = appt.id
        db.session.add(CashierShift(opened_by=clinic["ids"]["admin"],
                                    opening_float=0, status="open"))
        db.session.commit()
    clinic["appt"] = ids
    return clinic


def _checkout(clinic, appt_id, amount="200", method="cash", client=None):
    return (client or clinic["sign_in"]("boss")).post(
        f"/finance/checkout/{appt_id}",
        data={"line_desc": ["كشف"], "line_service_id": [clinic["ids"]["exam"]],
              "line_price": ["200"], "line_qty": ["1"],
              "line_no_commission": ["0"], "line_brand_id": [""],
              "line_dose_id": [""], "line_vs_id": [""],
              "line_dose_number": [""], "discount_id": "none",
              "amount": [amount], "method": [method]},
        follow_redirects=True)


def _appt(clinic, name):
    from app.extensions import db
    from app.models import Appointment

    with clinic["app"].app_context():
        a = db.session.get(Appointment, clinic["appt"][name])
        return a.status, a.checked_in_at


def _set_status(clinic, name, status):
    from app.extensions import db
    from app.models import Appointment

    with clinic["app"].app_context():
        db.session.get(Appointment, clinic["appt"][name]).status = status
        db.session.commit()


# ------------------------------------------------------------ one step ----
def test_paid_at_the_checkout_for_today_is_arrived(desk):
    from app.models import ActivityLog

    client = desk["sign_in"]("boss")
    _checkout(desk, desk["appt"]["today"], client=client)
    status, checked_in = _appt(desk, "today")
    assert status == "waiting" and checked_in is not None
    # The receipt prints first and hands back to the board, which says so.
    board = client.get("/appointments/").get_data(as_text=True)
    assert "واتعلّم إنه وصل" in board
    with desk["app"].app_context():
        log = ActivityLog.query.filter_by(action="appointment.status",
                                          entity_id=desk["appt"]["today"]).one()
        assert "paid at the desk" in log.detail


def test_a_payment_on_the_bill_for_today_is_arrived_too(desk):
    from app.models import Invoice

    _checkout(desk, desk["appt"]["today"], amount="")          # pay later
    assert _appt(desk, "today")[0] == "scheduled"
    with desk["app"].app_context():
        inv = Invoice.query.filter_by(
            appointment_id=desk["appt"]["today"]).one()
        inv_id = inv.id
    desk["sign_in"]("boss").post(f"/finance/invoices/{inv_id}/payment",
                                 data={"amount": ["200"], "method": ["cash"]})
    assert _appt(desk, "today")[0] == "waiting"


# ------------------------------------------------------------ not moved ----
def test_paid_in_advance_for_another_day_is_not_arrived(desk):
    _checkout(desk, desk["appt"]["tomorrow"])
    status, checked_in = _appt(desk, "tomorrow")
    assert status == "scheduled" and checked_in is None


@pytest.mark.parametrize("status", ["in_progress", "no_show", "cancelled"])
def test_a_booking_past_booked_is_left_where_it_is(desk, status):
    _set_status(desk, "today", status)
    _checkout(desk, desk["appt"]["today"])
    assert _appt(desk, "today")[0] == status


def test_pay_later_marks_nothing(desk):
    _checkout(desk, desk["appt"]["today"], amount="")
    assert _appt(desk, "today") == ("scheduled", None)


def test_a_clinic_that_turns_it_off_keeps_two_steps(desk):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("arrive_on_payment", "0")
        desk["db"].session.commit()
    client = desk["sign_in"]("boss")
    _checkout(desk, desk["appt"]["today"], client=client)
    assert _appt(desk, "today")[0] == "scheduled"
    assert "واتعلّم إنه وصل" not in client.get("/appointments/").get_data(as_text=True)


def test_the_setting_is_on_the_settings_page_and_on_by_default(desk):
    page = desk["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    box = page[page.index("data-arrive-on-payment"):]
    box = box[:box.index("</div>")]
    assert 'name="arrive_on_payment"' in box and "checked" in box


# ------------------------------------------------------------ not the desk --
def test_paid_online_from_home_is_not_arrived(bill):
    """The family paid through the gateway's page — from home, as far as
    anybody knows. That is money on the bill, not a child in the queue."""
    from app.extensions import db
    from app.models import Appointment, Invoice
    from app.utils.clock import local_today

    with bill["app"].app_context():
        appt = Appointment(patient_id=bill["ids"]["child"],
                           doctor_id=bill["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(12, 0),
                           status="scheduled", appt_type="consultation")
        db.session.add(appt)
        db.session.flush()
        db.session.get(Invoice, bill["invoice"]).appointment_id = appt.id
        db.session.commit()
        appt_id = appt.id
    _make_link(bill)
    reference = _rows(bill)[0][0]
    assert _notify(bill, _paid(reference)).status_code == 200
    with bill["app"].app_context():
        assert db.session.get(Invoice, bill["invoice"]).status == "paid"
        assert db.session.get(Appointment, appt_id).status == "scheduled"
