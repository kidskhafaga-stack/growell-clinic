"""One definition of "today", for the two halves of the same day's work.

**The measurement.** The whole test suite fails for about three hours every
night on this machine — twelve tests, all with the same shape:

    assert datetime.date(2026, 8, 10) == datetime.date(2026, 8, 9)

They pass again the moment UTC ticks past midnight. That is not a test problem
being worked around here; it is the program's own split showing through. The
doctor's station asks :func:`local_today` — the date in the timezone the clinic
*set* — while the booking screens asked ``date.today()``, the date in the
timezone the **operating system** is in.

**When that matters.** On a Windows box sitting in the clinic the two are the
same date and nothing is wrong, which is why this survived. They come apart
whenever the machine's zone is not the clinic's: a server left on UTC, a hosted
install, or an admin who picks a zone in settings that the OS does not share.

**What it cost, measured rather than argued.** With the clinic's zone set so
the dates differ, a walk-in was stored with the machine's date, appeared on
reception's board, and did not appear on the doctor's station at all — a child
checked in, sitting in the waiting room, and the doctor's screen saying nobody
was there.

These tests set the clinic's zone to one that disagrees with this machine's
*now*, which reproduces the fault at any hour instead of only after midnight.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# Far enough west that its date is behind UTC for most of the day, and far
# enough east-of-nothing that it has no DST surprises: UTC−10, no DST.
BEHIND = "Pacific/Honolulu"
# UTC+14 — ahead of UTC's date for the first ten hours of each UTC day.
AHEAD = "Pacific/Kiritimati"


def _zone_that_disagrees(app):
    """Whichever of the two currently has a different date from this machine.

    Hard-coding one zone would make this test pass or fail depending on the
    hour it runs at — which is the exact fault it exists to catch.
    """
    from app.models import Setting
    from app.utils.clock import local_today
    for zone in (BEHIND, AHEAD):
        Setting.set("clinic_timezone", zone)
        if local_today() != date.today():
            return zone
    return None


@pytest.fixture()
def elsewhere(clinic):
    """A clinic whose day is not this machine's day."""
    with clinic["app"].app_context():
        zone = _zone_that_disagrees(clinic["app"])
        if zone is None:
            pytest.skip("no configured zone disagrees with the machine now")
        clinic["db"].session.commit()
    return clinic


def test_a_walk_in_lands_on_the_clinics_day_not_the_servers(elsewhere):
    """The bug, end to end.

    Reception registers a walk-in; the row must carry the date the clinic is
    living in, because that is the date every screen showing "today" will ask
    for.
    """
    from app.utils.clock import local_today

    desk = elsewhere["sign_in"]("desk")
    response = desk.post("/appointments/walk-in", data={
        "patient_id": elsewhere["ids"]["child"],
        "doctor_id": elsewhere["ids"]["doctor"],
        "reason": "كحة",
    }, follow_redirects=True)
    assert response.status_code == 200

    with elsewhere["app"].app_context():
        from app.models import Appointment
        appt = (Appointment.query.filter_by(is_walk_in=True)
                .order_by(Appointment.id.desc()).first())
        assert appt is not None, "the walk-in was not created at all"
        assert appt.appt_date == local_today(), (
            "the walk-in was stamped with the machine's date, not the clinic's")


def test_the_child_in_the_waiting_room_reaches_the_doctors_screen(elsewhere):
    """The consequence, which is the reason the date matters.

    Reception's board and the doctor's station were asking different clocks, so
    the same appointment was on one and not the other. This asserts they agree
    — checking only the stored date would let the two drift apart again behind
    a green test.
    """
    desk = elsewhere["sign_in"]("desk")
    desk.post("/appointments/walk-in", data={
        "patient_id": elsewhere["ids"]["child"],
        "doctor_id": elsewhere["ids"]["doctor"],
        "reason": "كحة",
    }, follow_redirects=True)

    with elsewhere["app"].app_context():
        from app.models import Patient
        name = elsewhere["db"].session.get(
            Patient, elsewhere["ids"]["child"]).full_name

    board = desk.get("/appointments/").data.decode()
    station = elsewhere["sign_in"]("doc").get("/visits/station").data.decode()
    assert name in board, "reception cannot see the child they just checked in"
    assert name in station, (
        "the child is checked in and the doctor's station shows nobody")


def test_the_days_default_is_the_clinics_day_everywhere_it_is_asked(elsewhere):
    """Thirty-four callers default through ``parse_date_arg``.

    Fixing the walk-in alone would have left every screen that says "today"
    answering with the machine's date. One helper answers for all of them, so this
    tests the helper rather than thirty-four routes.
    """
    from app.utils.appointments import parse_date_arg
    from app.utils.clock import local_today

    with elsewhere["app"].app_context():
        assert parse_date_arg(None) == local_today()
        assert parse_date_arg("") == local_today()
        assert parse_date_arg("not-a-date") == local_today()
        # An explicit value still wins — this is a default, not an override.
        assert parse_date_arg("2026-01-15") == date(2026, 1, 15)
        assert parse_date_arg(None, default=date(2026, 2, 3)) == date(2026, 2, 3)


def test_the_hour_and_the_day_come_off_the_same_clock(elsewhere):
    """Half a fix would have been worse than none.

    ``available_slots`` hides slots that are already past — it compares the
    booking date against today and the slot time against now. Those were
    ``date.today()`` and ``datetime.now()``: both the machine's, so at least
    consistent. Moving only the date to the clinic's zone would have produced
    a screen whose *day* is the clinic's and whose *hour* is the server's,
    hiding the wrong slots by exactly the offset between them.

    The window is built *around the clinic's current hour* on the clinic's own
    today, so some slots are behind it and some ahead. Asserting on tomorrow
    instead would prove nothing — tomorrow is not "today" under either clock,
    so a split reads exactly the same as a fix. (Written that way first, and
    caught by putting the split back and watching the test stay green.)
    """
    from datetime import datetime

    from app.utils.appointments import available_slots
    from app.utils.clock import local_today, to_local

    with elsewhere["app"].app_context():
        from app.models import DoctorSchedule
        db = elsewhere["db"]
        now = to_local(datetime.utcnow())
        first, last = now.hour - 2, now.hour + 2
        if first < 0 or last > 23:
            pytest.skip("the clinic's hour is too near midnight to straddle")

        today = local_today()
        db.session.add(DoctorSchedule(
            doctor_id=elsewhere["ids"]["doctor"], weekday=today.weekday(),
            start_time=time(first, 0), end_time=time(last, 0),
            slot_minutes=60, is_active=True))
        db.session.commit()

        offered = available_slots(elsewhere["ids"]["doctor"], today)
        assert offered, "every slot was hidden — the filter is not the clock"
        assert len(offered) < last - first, (
            "nothing was hidden; past slots are being offered")
        for label in offered:
            hour, minute = (int(part) for part in label.split(":"))
            assert time(hour, minute) > now.time(), (
                f"{label} is already past in the clinic and is still offered "
                f"— it is only in the future on the machine's clock "
                f"({datetime.now().time().strftime('%H:%M')})")
