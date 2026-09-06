"""A consultation that costs nothing, wearing a Collect button.

Reported off the board: *"الاستشارة ليه معلمة إنها ما تحصلتش مع إننا عالجنا
الحتة دي للخدمات اللي سعرها صفر؟"* — a booking for a visit type the clinic
prices at zero, tagged **بدون فاتورة** with **حصّل واطبع** beside it.

The tag was true and useless. There is no invoice, and there never will be:
nothing is owed, so nobody will ever raise one. What the desk reads is a row
that still wants something doing, on a day already full of rows that do.

**The rule existed and one screen had it.** The till works out what a booking
would come to — through the checkout's own line builder, so "worth collecting"
means the same thing on both screens — and drops the ones that come to zero
from its chase list, with a comment saying why: *"a till that lists it anyway
is asking reception to open a checkout, look at a total of zero and back out,
for every one of them"*. The board asked a different question: *is there an
invoice?* And for a free visit the honest answer to that one is the wrong
answer to the question being asked.

**And "not priced" stays "no invoice".** A clinic that has not set its prices
up must not have every row on its board call itself free of charge — so only
an actual zero counts, never a price the program could not work out.
"""
import os
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def board(clinic):
    """Two bookings today: one on a priced visit type, one on a free one."""
    from app.models import Appointment, Service
    from app.utils.pricing import set_visit_type_service

    db = clinic["db"]
    with clinic["app"].app_context():
        paid_svc = db.session.get(Service, clinic["ids"]["exam"])
        free_svc = Service(name="استشارة", category="consultation", price=0,
                           commission_type="none", commission_value=0,
                           is_active=True)
        db.session.add(free_svc)
        db.session.flush()
        set_visit_type_service("new", paid_svc)
        set_visit_type_service("consultation", free_svc)

        made = {}
        for kind, at in (("new", time(15, 0)), ("consultation", time(18, 40))):
            appt = Appointment(patient_id=clinic["ids"]["child"],
                               doctor_id=clinic["ids"]["doctor"],
                               appt_date=local_today(), appt_time=at,
                               appt_type=kind, status="scheduled")
            db.session.add(appt)
            db.session.flush()
            made[kind] = appt.id
        db.session.commit()
        clinic["appt"] = made
    return clinic


def _state(fx, kind):
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    with fx["app"].test_request_context():
        appt = fx["db"].session.get(Appointment, fx["appt"][kind])
        return _payment_status([appt], local_today())[appt.id]["state"]


def test_a_visit_priced_at_nothing_is_not_waiting_to_be_collected(board):
    """The report, as an assertion."""
    assert _state(board, "consultation") == "free"


def test_a_visit_that_does_cost_something_still_wants_collecting(board):
    """The other half, and the reason this is a condition rather than the
    button going away: a booking nobody has billed is exactly what the desk
    needs to see."""
    assert _state(board, "new") == "none"


def test_the_board_offers_no_till_for_a_free_visit(board):
    """What the desk actually sees. The badge says free of charge and there is
    nothing to press, because there is nothing to do."""
    page = board["sign_in"]("boss").get(
        f"/appointments/?date={local_today()}").get_data(as_text=True)
    rows = page.split("18:40")
    assert len(rows) > 1, "the free booking is not on the board"
    cell = rows[1][:1400]
    assert "pay_free" in cell or "bi-gift" in cell
    assert "collect_print" not in cell and "checkout" not in cell


def test_the_board_still_offers_the_till_for_a_priced_one(board):
    page = board["sign_in"]("boss").get(
        f"/appointments/?date={local_today()}").get_data(as_text=True)
    cell = page.split("15:00")[1][:1400]
    assert "checkout" in cell, "a booking that owes money has no till button"


def test_a_price_that_cannot_be_worked_out_is_not_called_free(board):
    """Not priced is not free. A clinic mid-setup would otherwise see every
    row on its board declare itself free of charge — which is the same fault
    as the one being fixed, facing the other way."""
    from app.blueprints.appointments.routes import _costs_nothing
    from app.models import Appointment

    with board["app"].test_request_context():
        appt = board["db"].session.get(Appointment,
                                       board["appt"]["consultation"])
        appt.appt_type = "nothing"
        assert _costs_nothing(appt) is False


def test_the_board_and_the_till_answer_with_one_voice(board):
    """The reason this is `booking_due` and not a second reading: the till
    already decides what "worth collecting" means, and two answers to that
    eventually disagree in front of a family."""
    from app.blueprints.appointments.routes import _costs_nothing
    from app.blueprints.finance.routes import booking_due
    from app.models import Appointment

    with board["app"].test_request_context():
        for kind in ("new", "consultation"):
            appt = board["db"].session.get(Appointment, board["appt"][kind])
            due = booking_due(appt, "ar")
            assert _costs_nothing(appt) is (due is not None and due <= 0)


def test_a_free_booking_is_not_counted_as_unpaid_on_the_day(board):
    """The number at the top of the board is what a manager reads first."""
    page = board["sign_in"]("boss").get(
        f"/appointments/?date={local_today()}").get_data(as_text=True)
    assert page.count("18:40") >= 1
    # One booking owes money today; the free one is not it.
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    with board["app"].test_request_context():
        appts = [board["db"].session.get(Appointment, i)
                 for i in board["appt"].values()]
        states = _payment_status(appts, local_today())
        unpaid = [a.id for a in appts
                  if states[a.id]["state"] in ("unpaid", "partial", "none")]
        assert unpaid == [board["appt"]["new"]]


def test_the_board_does_not_price_every_row_to_find_the_free_ones(board):
    """Caught by the query-count guard next door, and worth its own name.

    The authoritative answer costs a checkout build per row — invoices, visit
    services, vaccines — and a full morning is forty rows. So a cheap
    **necessary** condition runs first: no base charge means not priced, a
    base that costs something cannot come to zero, and anything booked on top
    might cost money. Only what survives that is priced properly.

    The gate never answers on its own, and it is wrong only in the safe
    direction: it can send a row to the real check that turns out to owe
    money, and never the other way.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    def cost(appts):
        seen = []

        def record(conn, cursor, statement, params, context, many):
            if "FROM invoices" in statement:
                seen.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            _payment_status(appts, local_today())
        finally:
            event.remove(Engine, "before_cursor_execute", record)
        return len(seen)

    with board["app"].test_request_context():
        db = board["db"]
        both = [db.session.get(Appointment, i) for i in board["appt"].values()]
        small = cost(both)

        # Twenty more of the *priced* type — a full morning. Not one of them
        # can be free, so not one of them may cost a query.
        extra = []
        for i in range(20):
            row = Appointment(patient_id=board["ids"]["child"],
                              doctor_id=board["ids"]["doctor"],
                              appt_date=local_today(), appt_time=time(9, i),
                              appt_type="new", status="scheduled")
            db.session.add(row)
            extra.append(row)
        db.session.flush()
        big = cost(both + extra)

    assert big == small, (
        f"{big} invoice queries for {len(both) + len(extra)} rows against "
        f"{small} for {len(both)} — the board is pricing every row")


def test_a_booking_with_something_added_is_never_called_free(board):
    """The gate's safe direction, as a property: an extra service booked onto
    a free visit type means money might be owed, and the row keeps its till."""
    from app.blueprints.appointments.routes import _costs_nothing
    from app.models import Appointment

    with board["app"].test_request_context():
        appt = board["db"].session.get(Appointment,
                                       board["appt"]["consultation"])
        appt.extra_service_ids = str(board["ids"]["nebul"])
        assert _costs_nothing(appt) is False
