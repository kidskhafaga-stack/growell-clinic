"""A booking is for today or later, and the box opens on today.

Found by accident, which is how this kind of thing is always found: *"لاقيت
نفسي ممكن احجز بتاريخ قبل اليوم — هل احنا عاملينه عن قصد؟"* — no, nothing
stopped it, and nothing was meant to allow it.

**Why it matters more than it looks.** A past date is essentially always a
slip: a year typed as 2025, or a month picked one column to the left. And it is
a slip that *hides*. The booking lands on a day nobody is going to open again,
so it is not on any list the desk reads, the family is expected on a date that
has been and gone, and the first anybody hears of it is that they did not
arrive.

**Today stays bookable**, into the slots that have not gone by. That second
half was already true and is not this change: `available_slots` has always
dropped a time earlier today. What was missing was the whole day before it.

**And the date box opens on today.** It opened empty, which meant the slot list
under it — the main control on the screen — could say nothing at all until
somebody filled a box that gave no sign it was the one holding everything up.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A doctor with a schedule, so there are slots to book into."""
    from app.extensions import db
    from app.models import DoctorSchedule, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        doctor_id = visit.doctor_id
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=doctor_id, weekday=weekday,
                start_time=__import__("datetime").time(9, 0),
                end_time=__import__("datetime").time(17, 0),
                slot_minutes=30, is_active=True))
        db.session.commit()
    clinic["doctor_id"] = doctor_id
    clinic["today"] = local_today()
    return clinic


def _book(desk, on_date, slot="09:00"):
    return desk["sign_in"]("boss").post("/appointments/new", data={
        "patient_id": desk["ids"]["child"],
        "doctor_id": desk["doctor_id"],
        "appt_date": on_date.isoformat(),
        "appt_time": slot,
    }, follow_redirects=True)


def _free_slot(desk, on_date):
    """A slot the engine agrees is free — asked rather than assumed, because
    on `today` the answer depends on what time the test is running."""
    from app.utils.appointments import available_slots

    with desk["app"].app_context():
        return next(iter(available_slots(desk["doctor_id"], on_date)), None)


def _count(desk):
    from app.models import Appointment

    with desk["app"].app_context():
        return Appointment.query.count()


# ------------------------------------------------- the day that has gone

def test_yesterday_is_refused(desk):
    """The report, as a test."""
    before = _count(desk)

    _book(desk, desk["today"] - timedelta(days=1))

    assert _count(desk) == before, "an appointment was booked into the past"


def test_a_year_mistyped_is_refused(desk):
    """The actual shape of the mistake: 2025 for 2026, which lands the family
    a year ago and appears on no list anybody reads."""
    before = _count(desk)

    _book(desk, desk["today"].replace(year=desk["today"].year - 1))

    assert _count(desk) == before


def test_today_is_allowed(desk):
    """The new rule is about the day, and today is not a day that has gone.
    Most bookings a desk makes are for today."""
    slot = _free_slot(desk, desk["today"])
    if slot is None:                    # run after the last slot of the day
        pytest.skip("no slot left today on this clock")
    before = _count(desk)

    _book(desk, desk["today"], slot=slot)

    assert _count(desk) == before + 1


def test_a_slot_that_has_gone_by_today_was_already_refused(desk):
    """Not this change, and worth pinning so it is not read as one. The engine
    has always dropped a time earlier today, and the new day check must not
    have quietly replaced that with something looser."""
    from app.utils.appointments import available_slots

    with desk["app"].app_context():
        offered = available_slots(desk["doctor_id"], desk["today"])
        tomorrow = available_slots(desk["doctor_id"],
                                   desk["today"] + timedelta(days=1))

    assert set(offered) <= set(tomorrow), \
        "today offers a slot tomorrow does not — a time that has gone by"


def test_tomorrow_is_allowed(desk):
    before = _count(desk)

    _book(desk, desk["today"] + timedelta(days=1))

    assert _count(desk) == before + 1


def test_the_refusal_says_why(desk):
    page = _book(desk, desk["today"] - timedelta(days=3)).get_data(as_text=True)

    assert "عدّى" in page or "has passed" in page, \
        "the booking was refused without saying what was wrong"


# ------------------------------------------------------- rescheduling

def test_an_appointment_cannot_be_moved_backwards_into_the_past(desk):
    """The same slip wearing different clothes — and here it also destroys the
    date it came from, because `rescheduled_from` keeps one previous value."""
    from app.extensions import db
    from app.models import Appointment

    _book(desk, desk["today"] + timedelta(days=1))
    with desk["app"].app_context():
        appt = Appointment.query.order_by(Appointment.id.desc()).first()
        appt_id, was = appt.id, appt.appt_date

    desk["sign_in"]("boss").post(f"/appointments/{appt_id}/reschedule", data={
        "doctor_id": desk["doctor_id"],
        "appt_date": (desk["today"] - timedelta(days=1)).isoformat(),
        "appt_time": "10:00",
    }, follow_redirects=True)

    with desk["app"].app_context():
        moved = db.session.get(Appointment, appt_id)
        assert moved.appt_date == was, "an appointment was moved into the past"
        assert moved.rescheduled_from is None, \
            "a refused move still wrote over where it came from"


# ------------------------------------------------- the box opens on today

def test_the_date_box_opens_on_today(desk):
    """It opened empty, so the slot list — the main control on the screen —
    could say nothing until somebody filled a box that gave no sign it was the
    one holding everything up."""
    page = desk["sign_in"]("boss").get("/appointments/new").get_data(as_text=True)

    assert f'value="{desk["today"].isoformat()}"' in page


def test_a_day_chosen_on_the_board_wins_over_today(desk):
    """Booking *from* a particular day is somebody saying which day they mean,
    and the screen must not argue with them."""
    wanted = desk["today"] + timedelta(days=5)

    page = desk["sign_in"]("boss").get(
        f"/appointments/new?date={wanted.isoformat()}").get_data(as_text=True)

    assert f'value="{wanted.isoformat()}"' in page


def test_the_picker_greys_out_the_days_the_server_refuses(desk):
    """`min` is a hint a browser honours and nothing more — the server refuses
    them regardless — but a date that cannot be clicked beats an error after
    the fact."""
    page = desk["sign_in"]("boss").get("/appointments/new").get_data(as_text=True)

    assert f'min="{desk["today"].isoformat()}"' in page


def test_a_refused_booking_does_not_lose_what_was_typed(desk):
    """The error path re-renders the form. Sending somebody back to an empty
    screen after one bad field is how a desk retypes a booking three times."""
    page = _book(desk, desk["today"] - timedelta(days=1)).get_data(as_text=True)

    assert 'name="appt_date"' in page and 'min=' in page


# --------------------------------------------------- and the shape of it

def test_the_screen_says_which_day_that_date_is(desk):
    """A desk reads "2026-09-03" and cannot tell it is a Thursday — and
    Thursday is the thing they are actually deciding about."""
    page = desk["sign_in"]("boss").get("/appointments/new").get_data(as_text=True)

    assert "dayLabel()" in page, "the date shows its digits and nothing else"


def test_the_date_is_read_as_a_local_day(desk):
    """`new Date("2026-09-03")` reads a bare date as **UTC**, which lands on
    the previous day for anyone west of Greenwich and names the wrong weekday.
    Pinned because it is invisible in the timezone this is written in."""
    page = desk["sign_in"]("boss").get("/appointments/new").get_data(as_text=True)

    assert "new Date(p[0], p[1] - 1, p[2])" in page, \
        "the date is parsed as UTC, so the weekday is wrong half the world over"


def test_a_row_that_appears_does_not_shove_its_neighbour_sideways(desk):
    """`.form-grid` is a rigid two-column grid, so a cell that appears and
    disappears pushes what follows into the other column: picking
    "vaccination" moved the reason box from left to right while somebody was
    filling the form in."""
    page = desk["sign_in"]("boss").get("/appointments/new").get_data(as_text=True)

    row = page.split('id="vaccineRow"')[1][:120]
    assert "grid-column:1/-1" in row, \
        "the vaccine row still reflows the fields after it"
