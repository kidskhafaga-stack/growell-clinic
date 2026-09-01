"""Pausing bookings has to mean it.

Reported from a live screen: the doctor pauses booking, the dashboard shows
"Booking paused", the banner says reception cannot add appointments — **and
reception carries on booking normally.**

The gate was real and written in one place, on ``/new``. Walk-ins go in through
``/walk-in``, which never asked. So the setting was decoration on the busiest
door in the clinic.

That is worse than having no gate at all, and this file is mostly about why: a
guard that covers one of two doors **tells the person who flipped it that
something is being enforced.** The doctor stops watching the list because they
believe the program is holding the line. Nobody would rely on a switch they knew
did nothing.

So the last test here does not test a behaviour — it counts the doors. Any new
way to create an appointment has to go through the same helper, or that test
fails and says so.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """Reception signed in, booking paused, and the doctor on duty all week.

    The schedule matters: ``/new`` re-checks server-side that the slot is
    genuinely free, so without one there are no bookable slots at all and a
    refusal would prove nothing about the gate.
    """
    from datetime import time

    from app.models import DoctorSchedule, Setting

    with clinic["app"].app_context():
        for weekday in range(7):
            clinic["db"].session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=15, is_active=True))
        Setting.set("clinic_booking_open", "0")
        clinic["db"].session.commit()
    clinic["desk"] = clinic["sign_in"]("desk")
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


# Bookings in this file are made for **tomorrow**, not today, and that is not
# arbitrary. `available_slots` drops slots that have already passed when the
# date is today, so a test booking into a 09:00–17:00 schedule passes in the
# morning and fails every evening — which is exactly what happened, in the full
# suite, at 16:55. A test whose result depends on the clock is worse than no
# test: it teaches whoever sees it red to shrug. None of this file is about
# today in particular; the gate does not care which day is being booked.
TOMORROW_OFFSET = 1


def _free_slot(desk, when=None):
    """A slot the server agrees is open, so a refusal can only be the gate."""
    from app.utils.appointments import available_slots

    on_date = when or _bookable_day()
    with desk["app"].app_context():
        slots = available_slots(desk["ids"]["doctor"], on_date)
    assert slots, f"the fixture's doctor has no free slots on {on_date}"
    return slots[0]


def _bookable_day():
    """A day whose slots cannot have gone past while the suite was running."""
    from datetime import timedelta

    return local_today() + timedelta(days=TOMORROW_OFFSET)


def _open_booking(desk):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("clinic_booking_open", "1")
        desk["db"].session.commit()


def _count(desk):
    from app.models import Appointment

    with desk["app"].app_context():
        return Appointment.query.count()


def _walk_in(client, desk):
    return client.post("/appointments/walk-in", data={
        "patient_id": str(desk["ids"]["child"]),
        "doctor_id": str(desk["ids"]["doctor"]),
        "reason": "كحة"}, follow_redirects=True)


def _book(client, desk, when=None):
    on_date = when or _bookable_day()
    return client.post("/appointments/new", data={
        "patient_id": str(desk["ids"]["child"]),
        "doctor_id": str(desk["ids"]["doctor"]),
        "appt_date": on_date.isoformat(),
        "appt_time": _free_slot(desk, on_date),
        "reason": "كشف"}, follow_redirects=True)


# --------------------------------------------------- the door that was open --
def test_a_paused_clinic_refuses_a_walk_in(desk):
    """The reported bug, stated as the rule it broke."""
    before = _count(desk)
    _walk_in(desk["desk"], desk)
    assert _count(desk) == before


def test_reception_is_told_why_the_walk_in_did_not_go_in(desk):
    """A refusal that looks like nothing happening sends somebody to press the
    button again, and then to conclude the program is broken."""
    body = _walk_in(desk["desk"], desk).get_data(as_text=True)
    assert "الحجز متوقف" in body or "متوقف" in body


def test_the_walk_in_works_again_the_moment_booking_resumes(desk):
    """A gate that stays shut after the doctor reopens is the same bug wearing
    the other hat."""
    _open_booking(desk)
    before = _count(desk)
    _walk_in(desk["desk"], desk)
    assert _count(desk) == before + 1


# ------------------------------------------------- the door that was closed --
def test_a_paused_clinic_still_refuses_an_ordinary_booking(desk):
    """What already worked, kept working — the refactor moved this gate into a
    helper and a helper that dropped it would be a silent regression."""
    before = _count(desk)
    _book(desk["desk"], desk)
    assert _count(desk) == before


def test_an_ordinary_booking_works_again_when_resumed(desk):
    _open_booking(desk)
    before = _count(desk)
    _book(desk["desk"], desk)
    assert _count(desk) == before + 1


# ------------------------------------------------------------ the override --
def test_an_admin_can_still_push_a_walk_in_through(desk):
    """The emergency in front of reception is real whatever the setting says.
    The override belongs to the person who can answer for it."""
    before = _count(desk)
    _walk_in(desk["boss"], desk)
    assert _count(desk) == before + 1


def test_an_admin_can_still_book(desk):
    before = _count(desk)
    _book(desk["boss"], desk)
    assert _count(desk) == before + 1


def test_the_override_is_recorded(desk):
    """An override nobody can find afterwards is indistinguishable from the
    gate not having worked."""
    from app.models import ActivityLog

    _walk_in(desk["boss"], desk)
    with desk["app"].app_context():
        assert ActivityLog.query.filter(
            ActivityLog.action == "appointment.walk_in").count() == 1


# ------------------------------------------------- the screen and the switch -
def test_the_dashboard_says_it_is_paused(desk):
    body = desk["desk"].get("/dashboard").get_data(as_text=True)
    assert "متوقف" in body


def test_the_booking_form_knows_it_is_paused(desk):
    """The context value the banner is drawn from. It is passed as a boolean —
    handing the template the function that computes it would read as truthy
    forever and quietly un-paint the banner."""
    body = desk["desk"].get("/appointments/new").get_data(as_text=True)
    assert "متوقف" in body


def test_the_form_stops_saying_so_once_resumed(desk):
    _open_booking(desk)
    body = desk["desk"].get("/appointments/new").get_data(as_text=True)
    assert "الحجز متوقف" not in body


def test_the_toggle_flips_both_ways(desk):
    from app.models import Setting

    desk["boss"].post("/appointments/toggle-booking")
    with desk["app"].app_context():
        assert Setting.get("clinic_booking_open") == "1"
    desk["boss"].post("/appointments/toggle-booking")
    with desk["app"].app_context():
        assert Setting.get("clinic_booking_open") == "0"


# ------------------------------------------------------- counting the doors --
def test_every_way_to_create_an_appointment_asks_the_gate(desk):
    """**This test counts doors, not behaviour.**

    The bug was not a wrong check, it was a missing one — a second way in that
    nobody remembered when the gate was written. Enumerating the behaviours
    would never have caught it, because the missing path had no test to fail.

    So: find every place in the blueprint that constructs an ``Appointment``,
    and require each of their enclosing functions to consult the gate. A third
    booking route added later fails here with a message saying what to do.
    """
    import inspect
    import re

    from app.blueprints.appointments import routes

    source = inspect.getsource(routes)
    lines = source.splitlines()
    creators = [i for i, ln in enumerate(lines) if re.search(r"\bAppointment\(", ln)]
    assert creators, "no appointment creation found — did the module move?"

    unguarded = []
    for index in creators:
        # Walk back to the enclosing `def`, then forward over its body.
        start = index
        while start > 0 and not lines[start].startswith("def "):
            start -= 1
        end = start + 1
        while end < len(lines) and not (lines[end].startswith("def ")
                                        or lines[end].startswith("@")):
            end += 1
        body = "\n".join(lines[start:end])
        if "_booking_blocked()" not in body:
            unguarded.append(lines[start].strip())

    assert not unguarded, (
        "these create an appointment without asking the booking gate — add "
        f"`if _booking_blocked(): return ...` to each: {unguarded}")
