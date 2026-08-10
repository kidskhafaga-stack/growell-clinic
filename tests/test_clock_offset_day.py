"""The clinic's day and the server's day are not the same day.

Every test in here forces the clinic's timezone far enough from UTC that the
two calendars disagree **whatever hour the suite is run at**. That is the whole
point of the file.

Two real bugs were found on 2026-08-11 at 00:20 Cairo, by a full run that
happened to cross local midnight — and they had been sitting there for
months, reachable for about three hours a night:

* ``_todays_invoice`` looked the day's bill up with the *server's* date while
  ``Invoice.invoice_date`` is written with the *clinic's*. For those hours it
  found nothing, so the second collection of the evening opened a **second
  invoice for the same visit** — precisely what that function's docstring says
  it exists to prevent. Two bills, one visit, and a statement nobody can read.
* ``day_bounds`` combined the clinic's date with midnight and compared it
  straight against ``Payment.paid_at``, which is UTC. So money taken in the
  first three hours of a clinic day fell outside the window the live board
  asks about: the desk took cash and the doctor's screen sat there stale.

Both were caught by tests that only *could* catch them in that one hour. A
regression would have gone unnoticed until the next time somebody ran the
suite after midnight — which is to say, by accident. So these pin the zone.

``Pacific/Kiritimati`` is UTC+14: its calendar date is ahead of UTC's for ten
hours out of every twenty-four, and never behind. ``Pacific/Midway`` is UTC-11
and behind for eleven. Between them the mismatch is reachable at any hour, in
both directions, which is what makes this file a guard rather than a
coincidence.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

AHEAD = "Pacific/Kiritimati"      # UTC+14
BEHIND = "Pacific/Midway"         # UTC-11


def _bill_form(ids, price="200"):
    """The collection screen's full form — every line field it expects.

    Copied from the shape the finance tests already use: a partial payload is
    accepted and quietly raises nothing, which is how the first version of
    this file passed its clock assertions against zero invoices.
    """
    return {
        "doctor_id": ids["doctor"], "discount_id": "none",
        "line_service_id": [str(ids["exam"])],
        "line_desc": ["كشف"], "line_price": [price], "line_qty": ["1"],
        "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
    }



def _set_tz(clinic, name):
    with clinic["app"].app_context():
        from app.models import Setting
        Setting.set("clinic_timezone", name)
        clinic["db"].session.commit()


def _days_apart(clinic):
    """Is the clinic's date actually different from the server's right now?"""
    with clinic["app"].app_context():
        from app.utils.clock import local_today
        return local_today() != datetime.utcnow().date()


# --- the premise ----------------------------------------------------------

@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_one_of_the_two_zones_always_disagrees_with_utc(clinic, zone):
    """Guards the guard.

    If neither zone ever differed from UTC, every assertion below would pass
    for the wrong reason and this file would be decoration.
    """
    _set_tz(clinic, zone)
    with clinic["app"].app_context():
        from app.utils.clock import local_today
        clinic_day = local_today()
    server_day = datetime.utcnow().date()
    assert abs((clinic_day - server_day).days) <= 1


def test_at_least_one_zone_differs_at_this_very_hour(clinic):
    """At any hour of the day, one of the two is on another date."""
    differs = []
    for zone in (AHEAD, BEHIND):
        _set_tz(clinic, zone)
        differs.append(_days_apart(clinic))
    assert any(differs), (
        "neither zone disagrees with UTC — the file cannot test what it claims")


# --- the day's one bill ---------------------------------------------------

@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_the_days_second_charge_joins_the_first_bill(clinic, zone):
    """One visit, one invoice — in the clinic's day, not the server's."""
    _set_tz(clinic, zone)
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]

    for _ in range(2):
        desk.post(f"/finance/collect/{ids['child']}", data=_bill_form(ids),
                  follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Invoice
        assert Invoice.query.count() == 1, (
            f"{zone}: a second bill was opened for the same visit")


@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_the_bill_is_stamped_with_the_clinics_day(clinic, zone):
    _set_tz(clinic, zone)
    ids = clinic["ids"]
    clinic["sign_in"]("desk").post(f"/finance/collect/{ids['child']}",
                                   data=_bill_form(ids), follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Invoice
        from app.utils.clock import local_today
        assert Invoice.query.one().invoice_date == local_today()


# --- the live board sees the money ---------------------------------------

@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_a_payment_taken_now_falls_inside_the_clinics_day(clinic, zone):
    """``day_bounds`` against a UTC timestamp.

    Asserted on the range itself rather than through the board, because the
    board needs a whole appointment to exist before it looks at money — and
    the thing that broke was this arithmetic.
    """
    _set_tz(clinic, zone)
    with clinic["app"].app_context():
        from app.utils.clock import local_today
        from app.utils.live import day_bounds

        start, end = day_bounds(local_today())
        now = datetime.utcnow()          # what Payment.paid_at is written with
        assert start <= now <= end, (
            f"{zone}: money taken this minute is outside the clinic's own day")


@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_the_days_range_is_a_day_long(clinic, zone):
    """A conversion applied to one end and not the other would still pass the
    test above for most of the day."""
    _set_tz(clinic, zone)
    with clinic["app"].app_context():
        from app.utils.live import day_bounds

        start, end = day_bounds(date(2026, 3, 15))
        span = end - start
        assert timedelta(hours=23) < span < timedelta(hours=25), (
            f"{zone}: the clinic day came out {span} long")


@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_two_consecutive_days_do_not_overlap(clinic, zone):
    """Overlapping windows would count a payment on both days."""
    _set_tz(clinic, zone)
    with clinic["app"].app_context():
        from app.utils.live import day_bounds

        _, first_end = day_bounds(date(2026, 3, 15))
        second_start, _ = day_bounds(date(2026, 3, 16))
        assert first_end < second_start


# --- and the appointment board agrees ------------------------------------

@pytest.mark.parametrize("zone", [AHEAD, BEHIND])
def test_todays_board_is_the_clinics_today(clinic, zone):
    """What the doctor opens in the morning is their morning."""
    _set_tz(clinic, zone)
    with clinic["app"].app_context():
        from app.utils.appointments import parse_date_arg
        from app.utils.clock import local_today

        assert parse_date_arg(None) == local_today()
