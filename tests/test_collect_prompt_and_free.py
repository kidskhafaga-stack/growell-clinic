"""Booked — and then what? And what if there is nothing to collect?

Two asks, one idea: the program should carry the desk to the next step
rather than rely on somebody remembering it.

**After a booking.** Reception's next question is always "do I take the money
now?", and answering it meant leaving the form, finding the row again and
pressing collect. The board is now told which booking was just made and asks
once, in place, with the checkout one press away — and the trip back already
existed, because collecting lands on the receipt, which auto-prints and
returns to the board.

**When there is nothing to collect.** A free consultation has no charge, and
a till that lists it anyway asks reception to open a checkout, read a total of
zero and back out — for every one of them. That is the step that teaches
people to ignore the list, so a booking worth nothing is on nobody's chase
list and gets no prompt.

What "worth nothing" means is not decided here. `booking_due` runs the
checkout's own line builder, so a booking counts as collectable exactly when
the checkout would ask for something. A second opinion about the price is how
the till ends up disagreeing with the screen it sends people to.
"""
import os
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


def _service(clinic, name, price, visit_type):
    from app.extensions import db
    from app.models import Service

    svc = Service(name=name, price=price, visit_type=visit_type, is_active=True)
    db.session.add(svc)
    db.session.flush()
    return svc


def _booking(clinic, appt_type, hour=11):
    from app.extensions import db
    from app.models import Appointment, Patient, User

    doctor = User.query.filter_by(username="doc").first()
    appt = Appointment(patient_id=Patient.query.first().id, doctor_id=doctor.id,
                       appt_date=local_today(), appt_time=time(hour, 0),
                       appt_type=appt_type, status="scheduled")
    db.session.add(appt)
    db.session.commit()
    return appt


# ------------------------------------------------------- what it is worth

def test_a_priced_visit_is_worth_collecting(clinic):
    from app.blueprints.finance.routes import booking_due

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        appt = _booking(clinic, "consultation")

        assert booking_due(appt) == 200


def test_a_free_visit_is_worth_nothing(clinic):
    """The case that was being chased for no reason."""
    from app.blueprints.finance.routes import booking_due

    with clinic["app"].app_context():
        _service(clinic, "متابعة مجانية", 0, "follow_up")
        appt = _booking(clinic, "follow_up")

        assert booking_due(appt) == 0


def test_it_reads_the_checkouts_own_lines(clinic):
    """Not a second opinion about the price.

    If this worked the total out its own way, the till and the checkout it
    links to would drift apart, and the number reception is told at the desk
    would stop matching the one on the screen they open.
    """
    import inspect

    from app.blueprints.finance import routes

    assert "_checkout_lines" in inspect.getsource(routes.booking_due)


def test_an_unpriceable_booking_is_shown_rather_than_hidden(clinic):
    """`None` is not zero, and the difference decides who gets chased.

    A booking whose price cannot be worked out — a pricing table half set up,
    a service deleted out from under a visit type — is a thing somebody should
    look at. Treating that as "free" would hide real money behind the same
    filter that exists to hide none.

    The failure is forced rather than waited for: `_checkout_lines` raising is
    exactly the case, and it does not arise from ordinary data.
    """
    from app.blueprints.finance import routes

    with clinic["app"].app_context():
        appt = _booking(clinic, "consultation")
        appt_id = appt.id

        original = routes._checkout_lines

        def explode(*a, **k):
            raise RuntimeError("the price list is unreadable")

        routes._checkout_lines = explode
        try:
            assert routes.booking_due(appt) is None, \
                "an unpriceable booking was reported as costing nothing"
        finally:
            routes._checkout_lines = original

    # And it stays on the chase list, because nobody has said it is free.
    routes._checkout_lines_backup = None
    original = routes._checkout_lines

    def explode(*a, **k):
        raise RuntimeError("the price list is unreadable")

    routes._checkout_lines = explode
    try:
        page = clinic["sign_in"]("desk").get(
            "/finance/cashier", follow_redirects=True).data.decode()
    finally:
        routes._checkout_lines = original

    assert f"/finance/checkout/{appt_id}" in page, \
        "a booking nobody could price was quietly dropped off the till"


# ------------------------------------------------------------- on the till

def test_a_free_booking_is_not_on_the_chase_list(clinic):
    from app.extensions import db

    with clinic["app"].app_context():
        _service(clinic, "متابعة مجانية", 0, "follow_up")
        free = _booking(clinic, "follow_up")
        db.session.commit()
        free_id = free.id

    page = clinic["sign_in"]("desk").get("/finance/cashier",
                                         follow_redirects=True).data.decode()

    assert f"/finance/checkout/{free_id}" not in page, \
        "a visit with nothing to collect is on the cashier's chase list"


def test_a_paid_booking_still_is(clinic):
    """The other half — the filter must not empty the list."""
    from app.extensions import db

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        paid = _booking(clinic, "consultation")
        db.session.commit()
        paid_id = paid.id

    page = clinic["sign_in"]("desk").get("/finance/cashier",
                                         follow_redirects=True).data.decode()

    assert f"/finance/checkout/{paid_id}" in page


# ------------------------------------------------------ the prompt after it

def test_the_board_offers_to_collect_the_booking_just_made(clinic):
    from app.extensions import db
    from app.i18n import t

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        appt = _booking(clinic, "consultation")
        db.session.commit()
        appt_id = appt.id

    page = clinic["sign_in"]("desk").get(
        f"/appointments/?collect={appt_id}", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("appointments.collect_now") in page, \
            "the desk books a family and is told nothing about the money"
    assert f"/finance/checkout/{appt_id}" in page


def test_the_prompt_is_a_question_not_a_redirect(clinic):
    """A family that pays on the way out must not have the checkout forced
    on them at booking time — so "later" is on the same row as "now"."""
    from app.extensions import db
    from app.i18n import t

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        appt = _booking(clinic, "consultation")
        db.session.commit()
        appt_id = appt.id

    page = clinic["sign_in"]("desk").get(
        f"/appointments/?collect={appt_id}", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("appointments.collect_later") in page


def test_a_doctor_is_not_asked_to_collect(clinic):
    from app.extensions import db
    from app.i18n import t

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        appt = _booking(clinic, "consultation")
        db.session.commit()
        appt_id = appt.id

    page = clinic["sign_in"]("doc").get(
        f"/appointments/?collect={appt_id}", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("appointments.collect_now") not in page


def test_a_stale_link_does_not_raise_a_prompt(clinic):
    """The id arrives in a URL, so it is checked rather than trusted."""
    answer = clinic["sign_in"]("desk").get("/appointments/?collect=999999",
                                           follow_redirects=True)

    assert answer.status_code == 200


def test_nonsense_in_the_parameter_is_harmless(clinic):
    answer = clinic["sign_in"]("desk").get("/appointments/?collect=../etc/passwd",
                                           follow_redirects=True)

    assert answer.status_code == 200


def test_a_booking_on_another_day_does_not_prompt_todays_board(clinic):
    """The prompt belongs to the day it was booked for."""
    from app.extensions import db
    from app.i18n import t
    from app.models import Appointment, Patient, User
    from datetime import timedelta

    with clinic["app"].app_context():
        _service(clinic, "كشف", 200, "consultation")
        doctor = User.query.filter_by(username="doc").first()
        appt = Appointment(patient_id=Patient.query.first().id,
                           doctor_id=doctor.id,
                           appt_date=local_today() + timedelta(days=3),
                           appt_time=time(11, 0), appt_type="consultation",
                           status="scheduled")
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id

    page = clinic["sign_in"]("desk").get(
        f"/appointments/?collect={appt_id}", follow_redirects=True).data.decode()

    with clinic["app"].test_request_context("/"):
        assert t("appointments.collect_now") not in page


def test_the_way_back_already_exists(clinic):
    """Collecting lands on the receipt, which auto-prints and returns to the
    board — so the loop closes without a parameter that pretends to close it."""
    import inspect

    from app.blueprints.finance import routes

    source = inspect.getsource(routes.invoice_receipt)
    assert "appointments.index" in source and "auto" in source


@pytest.mark.parametrize("key", ["collect_now", "collect_later",
                                 "collect_now_hint", "booked_now"])
def test_the_wording_exists_in_both_languages(clinic, key):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert key in json.load(fh)["appointments"], f"{lang} is missing {key}"


# ------------------------------------------- when the price changes its mind

def _override(clinic, service, doctor, amount):
    """What this doctor charges for this service, overriding the price list."""
    from app.extensions import db
    from app.models.service import DoctorServiceCommission

    row = DoctorServiceCommission.query.filter_by(
        service_id=service.id, doctor_id=doctor.id).first()
    if row is None:
        row = DoctorServiceCommission(service_id=service.id,
                                      doctor_id=doctor.id)
        db.session.add(row)
    row.price_override = amount
    db.session.commit()
    return row


def test_a_doctor_who_starts_charging_gets_collected(clinic):
    """Asked directly: the consultation was free, now it costs — will the desk
    be told to collect it?

    It will, and for the booking made *before* the price changed too, which is
    the half worth pinning. Nothing about the price is copied onto the
    appointment: `_checkout_lines` asks `price_for(doctor)` each time the till
    is drawn. A snapshot taken at booking would answer zero here forever, and
    the money would quietly never be asked for — the failure nobody reports,
    because no screen looks wrong.
    """
    from app.extensions import db
    from app.models import Appointment, User
    from app.blueprints.finance.routes import booking_due

    with clinic["app"].app_context():
        exam = _service(clinic, "كشف", 200, "consultation")
        doctor = User.query.filter_by(username="doc").first()
        _override(clinic, exam, doctor, 0)          # this one is on the house
        appt = _booking(clinic, "consultation")
        appt_id = appt.id

        assert booking_due(appt) == 0

        _override(clinic, exam, doctor, 250)        # and now it is not
        appt = db.session.get(Appointment, appt_id)

        assert booking_due(appt) == 250, \
            "the price changed and the booking is still worth what it was"


def test_the_till_picks_it_up_without_rebooking(clinic):
    """The end of the same story, on the screen reception actually reads."""
    from app.models import User

    with clinic["app"].app_context():
        exam = _service(clinic, "كشف", 200, "consultation")
        doctor = User.query.filter_by(username="doc").first()
        _override(clinic, exam, doctor, 0)
        appt_id = _booking(clinic, "consultation").id
        exam_id, doctor_id = exam.id, doctor.id

    page = clinic["sign_in"]("desk").get("/finance/cashier",
                                         follow_redirects=True).data.decode()
    assert f"/finance/checkout/{appt_id}" not in page, \
        "a free consultation is on the chase list before the price changed"

    with clinic["app"].app_context():
        from app.extensions import db
        from app.models import Service
        # By id, not by name: the fixture ships a "كشف" of its own, and
        # overriding that one instead would leave this test passing while
        # measuring nothing.
        _override(clinic, db.session.get(Service, exam_id),
                  db.session.get(User, doctor_id), 250)

    page = clinic["sign_in"]("desk").get("/finance/cashier",
                                         follow_redirects=True).data.decode()
    assert f"/finance/checkout/{appt_id}" in page, \
        "the doctor started charging and the till never noticed"


def test_it_goes_the_other_way_too(clinic):
    """A doctor who stops charging drops off the list rather than sitting on
    it as a debt nobody can collect."""
    from app.models import User
    from app.blueprints.finance.routes import booking_due

    with clinic["app"].app_context():
        exam = _service(clinic, "كشف", 200, "consultation")
        doctor = User.query.filter_by(username="doc").first()
        appt = _booking(clinic, "consultation")

        assert booking_due(appt) == 200

        _override(clinic, exam, doctor, 0)

        assert booking_due(appt) == 0


def test_the_price_list_alone_is_enough(clinic):
    """No per-doctor override in sight — the plain price moving must carry
    just as well, since most clinics never set an override at all."""
    from app.extensions import db
    from app.blueprints.finance.routes import booking_due

    with clinic["app"].app_context():
        exam = _service(clinic, "كشف مجاني", 0, "consultation")
        appt = _booking(clinic, "consultation")

        assert booking_due(appt) == 0

        exam.price = 180
        db.session.commit()

        assert booking_due(appt) == 180
