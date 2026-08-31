"""The checkout screen was a stack of boxes; the booking screen is a task.

The booking form was laid out as three numbered sections in the order the job
actually has — who is coming, when, what for — after being a flat grid of
seven controls that read as a list of fields rather than a description of
anything. The till screen was still in the old shape: services, then
discounts and totals, then payment, each in its own card, none of them saying
they were part of one sequence.

Reported as exactly that: *"شاشة التحصيل محتاجه تتنظم بنفس الطريقة بتاعت
الحجز"*.

**The numbering is honest here**, which is the only reason it is used. The
total cannot be read before the charges are chosen, and money cannot be taken
before the total is known — these are steps in an order, not three boxes
wearing digits. The refund panel is deliberately outside the numbering: it is
a different act on the same screen, not step four of taking money.
"""
import pytest


@pytest.fixture
def booked(clinic):
    """A child with an appointment, which is what reception collects against."""
    from datetime import time

    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        appointment = Appointment(
            patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
            appt_date=local_today(), appt_time=time(10, 0),
            appt_type="new", status="scheduled")
        clinic["db"].session.add(appointment)
        clinic["db"].session.commit()
        clinic["ids"]["appt"] = appointment.id
    return clinic


def _screen(clinic, who="desk"):
    reply = clinic["sign_in"](who).get(f"/finance/checkout/{clinic['ids']['appt']}")
    assert reply.status_code == 200, f"the till screen did not open: {reply.status_code}"
    return reply.get_data(as_text=True)


def test_the_three_steps_are_there_and_in_order(booked):
    """What for, what it comes to, then the money. In that order on the page,
    because a screen whose steps are numbered out of sequence is worse than
    one that never numbered them."""
    page = _screen(booked)
    positions = [page.find(f'md-step">{n}<') for n in (1, 2, 3)]
    assert all(p > -1 for p in positions), f"missing steps: {positions}"
    assert positions == sorted(positions), "the steps are not in order"


def test_each_step_says_what_it_is_for(booked):
    """A number with no name is decoration."""
    page = _screen(booked)
    for heading in ("على إيه", "الإجمالي"):
        assert heading in page


def test_the_refund_is_not_a_step(booked):
    """It is a different act on the same screen — money going the other way —
    and numbering it would read as the last thing you do when taking money.

    Asserted by counting: a fourth step appearing means somebody folded
    another card into the sequence without asking whether it belongs in it.
    """
    page = _screen(booked)
    assert 'md-step">4<' not in page


def test_the_sections_are_closed(booked):
    """A `<section>` opened and closed with `</div>` renders, and then every
    box below it sits inside the one above. It is the kind of break that looks
    like a styling problem and is a structural one."""
    page = _screen(booked)
    # The opening tag, not the class prefix: `md-section-head` starts with
    # `md-section` too, so counting the prefix counts each section twice and
    # the assertion never means anything.
    assert page.count('<section class="md-section') == page.count("</section>")


def test_it_uses_the_same_grammar_as_the_booking_screen(booked):
    """Not a second look that happens to have numbers in it. The booking form
    already owns this pattern and its CSS; a screen that reimplemented it
    would drift from it the first time either was touched."""
    booking = booked["sign_in"]("desk").get(
        "/appointments/new").get_data(as_text=True)
    till = _screen(booked)
    for marker in ("md-section", "md-section-head", "md-step"):
        assert marker in booking, f"the booking screen lost {marker}"
        assert marker in till, f"the till screen does not use {marker}"


def test_the_money_step_still_takes_money(booked):
    """The point of the whole screen, asserted after moving its markup
    around — a layout change that quietly dropped a field would leave a till
    that looks tidier and cannot collect."""
    page = _screen(booked)
    assert 'name="amount"' in page
    assert 'name="method"' in page
