"""Closing the books at the rhythm the clinic actually hands over at.

Reported: *"the accounting periods have to allow for the month, the half-year,
the quarter and the full year — and only 2026 shows, why can't it do several
years? And there has to be a search."*

Three separate faults behind that.

**Only one year could ever exist.** The year dropdown was built from the years
that already *had* periods, plus this one. So 2027 was not in the list, and the
"create the year's months" button only ever created the year you were looking
at — which could only be the one already there. A clinic opening next year's
books, or entering last year's, had no way in. The list is a range now.

**And the wider periods were not merely missing — adding them would have
lied.** The lock asked for *the* period covering a date and took whichever
started latest. February's month starts after its quarter does, so with both
present the month is the one found: closing الربع الأول would have locked
nothing at all, while the screen said "closed". A lock you can slip past by
choosing a different granularity is not a lock, and this is worse than no
feature — the books would have been reported closed and still accepted a
back-dated invoice. Any closed period covering the date refuses it now.

**And the dash.** Separately reported: *"the doctor always shows a dash."* The
money screens asked for ``role == "doctor"`` while the rest of the program has
long counted a practitioner as somebody who sees patients — role-typed **or**
flagged ``is_practitioner``, which is how a clinic marks an owner-admin who
also runs a clinic day. In such a clinic the appointment board listed them and
every finance screen showed an empty dropdown.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _make(clinic, year, kind):
    from app.utils.periods import generate_periods

    with clinic["app"].app_context():
        made = generate_periods(year, kind)
        clinic["db"].session.commit()
        return made


def _periods(clinic, year=None):
    from app.models import AccountingPeriod

    with clinic["app"].app_context():
        rows = AccountingPeriod.query.order_by(AccountingPeriod.start_date).all()
        return [{"name": p.name, "kind": p.kind, "start": p.start_date,
                 "end": p.end_date, "status": p.status, "id": p.id}
                for p in rows if year is None or p.start_date.year == year]


# ===================================================== the four granularities
def test_a_year_can_be_cut_into_months(clinic):
    assert _make(clinic, 2027, "month") == 12


def test_a_year_can_be_cut_into_quarters(clinic):
    assert _make(clinic, 2027, "quarter") == 4


def test_a_year_can_be_cut_into_halves(clinic):
    assert _make(clinic, 2027, "half") == 2


def test_a_year_can_be_one_period(clinic):
    assert _make(clinic, 2027, "year") == 1


def test_the_quarters_cover_the_year_end_to_end(clinic):
    """A quarter that stops on the 30th of a 31-day month leaves a day nobody
    can close — and that day accepts money forever."""
    _make(clinic, 2027, "quarter")
    rows = _periods(clinic, 2027)
    assert rows[0]["start"] == date(2027, 1, 1)
    assert rows[-1]["end"] == date(2027, 12, 31)
    for earlier, later in zip(rows, rows[1:]):
        assert (later["start"] - earlier["end"]).days == 1, "a gap between them"


def test_the_halves_split_the_year_in_two(clinic):
    _make(clinic, 2027, "half")
    rows = _periods(clinic, 2027)
    assert rows[0]["end"] == date(2027, 6, 30)
    assert rows[1]["start"] == date(2027, 7, 1)


def test_february_knows_about_leap_years(clinic):
    """Hard-coding 28 loses the 29th every four years — a day money can be
    written into after the books are signed."""
    _make(clinic, 2028, "month")
    feb = [p for p in _periods(clinic, 2028) if p["start"].month == 2][0]
    assert feb["end"] == date(2028, 2, 29)


def test_the_four_kinds_live_side_by_side(clinic):
    """A clinic that reviews monthly *and* signs off the year needs both."""
    for kind in ("month", "quarter", "half", "year"):
        _make(clinic, 2027, kind)
    assert len(_periods(clinic, 2027)) == 19


def test_creating_twice_does_not_duplicate(clinic):
    """The button is pressed twice by somebody who did not see the first
    flash. Two Marches would be two locks disagreeing."""
    _make(clinic, 2027, "month")
    assert _make(clinic, 2027, "month") == 0
    assert len(_periods(clinic, 2027)) == 12


def test_each_period_says_what_it_is(clinic):
    _make(clinic, 2027, "quarter")
    assert {p["kind"] for p in _periods(clinic, 2027)} == {"quarter"}


def test_an_unknown_kind_falls_back_to_months(clinic):
    assert _make(clinic, 2027, "fortnight") == 12


# ============================================== the lock the wider ones need
def _lock(clinic, on_date):
    from app.utils.periods import is_locked

    with clinic["app"].app_context():
        return is_locked(on_date)


def _close(clinic, name):
    from app.models import AccountingPeriod
    from app.utils.periods import close_period

    with clinic["app"].app_context():
        period = AccountingPeriod.query.filter_by(name=name).one()
        close_period(period)
        clinic["db"].session.commit()


def test_closing_a_quarter_locks_the_months_inside_it(clinic):
    """The fault that made this feature worth writing carefully. The lock took
    *the* period covering a date — whichever started latest — so February's own
    month, which starts after its quarter, was the one found. Closing the
    quarter locked nothing while the screen said closed."""
    _make(clinic, 2027, "month")
    _make(clinic, 2027, "quarter")
    _close(clinic, "الربع الأول 2027")

    assert _lock(clinic, date(2027, 2, 14)) is True


def test_closing_the_year_locks_a_day_in_the_middle_of_it(clinic):
    _make(clinic, 2027, "month")
    _make(clinic, 2027, "year")
    _close(clinic, "سنة 2027")

    assert _lock(clinic, date(2027, 8, 3)) is True


def test_closing_a_month_still_locks_that_month(clinic):
    """The behaviour that already existed must survive the change."""
    _make(clinic, 2027, "month")
    _close(clinic, "مارس 2027")

    assert _lock(clinic, date(2027, 3, 15)) is True


def test_an_open_wider_period_does_not_unlock_a_closed_month(clinic):
    """Both directions. A closed March inside an open 2027 is still closed —
    otherwise creating the year would quietly reopen every month in it."""
    _make(clinic, 2027, "month")
    _make(clinic, 2027, "year")
    _close(clinic, "مارس 2027")

    assert _lock(clinic, date(2027, 3, 15)) is True


def test_a_day_in_an_open_period_is_writable(clinic):
    """A lock that is always on is a program nobody can use."""
    _make(clinic, 2027, "month")
    _make(clinic, 2027, "year")
    assert _lock(clinic, date(2027, 5, 5)) is False


def test_nothing_is_locked_when_no_period_exists(clinic):
    """A clinic that does not work this way must never notice the feature."""
    assert _lock(clinic, date(2027, 5, 5)) is False


def test_the_reason_given_is_the_period_that_is_actually_closed(clinic):
    """Telling somebody "مارس 2027 is closed" when what they hit was the year
    sends them to reopen the wrong thing."""
    from app.utils.periods import locked_period

    _make(clinic, 2027, "month")
    _make(clinic, 2027, "year")
    _close(clinic, "سنة 2027")

    with clinic["app"].app_context():
        assert locked_period(date(2027, 3, 15)).name == "سنة 2027"


def test_the_narrowest_closed_period_is_the_one_named(clinic):
    """With both closed, the month is the more useful answer."""
    from app.utils.periods import locked_period

    _make(clinic, 2027, "month")
    _make(clinic, 2027, "year")
    _close(clinic, "سنة 2027")
    _close(clinic, "مارس 2027")

    with clinic["app"].app_context():
        assert locked_period(date(2027, 3, 15)).name == "مارس 2027"


def test_a_closed_quarter_refuses_a_back_dated_payment(clinic, boss):
    """Through the till, not through the helper: the point of the lock is what
    happens when somebody tries to write money."""
    from app.models import Invoice, InvoiceItem

    with clinic["app"].app_context():
        db = clinic["db"]
        inv = Invoice(invoice_number="INV-Q1", patient_id=clinic["ids"]["child"],
                      invoice_date=date(2027, 2, 10),
                      created_by=clinic["ids"]["admin"])
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=200, quantity=1))
        db.session.commit()
        invoice_id = inv.id

    _make(clinic, 2027, "month")
    _make(clinic, 2027, "quarter")
    _close(clinic, "الربع الأول 2027")

    boss.post(f"/finance/invoices/{invoice_id}/payment",
              data={"amount": "200", "method": "cash"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert clinic["db"].session.get(Invoice, invoice_id).paid == 0


# ================================================ any year, not just this one
def test_more_than_one_year_can_be_chosen(clinic):
    """The dropdown was built from the years that already had periods plus
    this one — so 2027 was not offered, and the only way to create a year's
    periods was to be looking at it already."""
    from app.utils.periods import selectable_years

    with clinic["app"].app_context():
        years = selectable_years()
    assert len(years) > 1
    assert date.today().year + 1 in years
    assert date.today().year - 1 in years


def test_a_year_that_has_periods_is_always_offered(clinic):
    """Even one outside the default range — otherwise a clinic that closed
    2019 cannot reach it to reopen it."""
    from app.utils.periods import selectable_years

    _make(clinic, 2015, "year")
    with clinic["app"].app_context():
        assert 2015 in selectable_years()


def test_the_screen_offers_the_years(clinic, boss):
    body = boss.get("/finance/periods").get_data(as_text=True)
    assert f'value="{date.today().year + 1}"' in body


def test_the_screen_creates_the_kind_it_was_asked_for(clinic, boss):
    boss.post("/finance/periods", data={"action": "generate", "year": "2027",
                                        "kind": "quarter"},
              follow_redirects=True)
    assert {p["kind"] for p in _periods(clinic, 2027)} == {"quarter"}


def test_the_screen_creates_for_a_year_that_had_nothing(clinic, boss):
    boss.post("/finance/periods", data={"action": "generate", "year": "2029",
                                        "kind": "month"},
              follow_redirects=True)
    assert len(_periods(clinic, 2029)) == 12


# ============================================================ finding one ===
def test_the_list_can_be_filtered_to_one_kind(clinic, boss):
    """Nineteen periods across four granularities is a wall to read."""
    for kind in ("month", "quarter", "half", "year"):
        _make(clinic, 2027, kind)

    body = boss.get("/finance/periods",
                    query_string={"year": 2027, "kind": "half"}).get_data(as_text=True)
    assert "النصف الأول 2027" in body
    assert "مارس 2027" not in body


def test_the_list_can_be_filtered_to_what_is_still_open(clinic, boss):
    _make(clinic, 2027, "month")
    _close(clinic, "مارس 2027")

    body = boss.get("/finance/periods",
                    query_string={"year": 2027, "status": "closed"}).get_data(as_text=True)
    assert "مارس 2027" in body
    assert "أبريل 2027" not in body


def test_a_period_can_be_searched_for_by_name(clinic, boss):
    _make(clinic, 2027, "month")
    body = boss.get("/finance/periods",
                    query_string={"year": 2027, "q": "سبتمبر"}).get_data(as_text=True)
    assert "سبتمبر 2027" in body
    assert "يناير 2027" not in body


def test_an_unknown_filter_does_not_empty_the_screen(clinic, boss):
    """A typed-in query string must not be a way to make the books vanish."""
    _make(clinic, 2027, "month")
    body = boss.get("/finance/periods",
                    query_string={"year": 2027, "kind": "fortnight"}).get_data(as_text=True)
    assert "مارس 2027" in body


# ================================================================ the dash ==
def test_a_practitioner_who_is_not_role_typed_is_still_a_doctor(clinic):
    """Reported as "the doctor always shows a dash". The money screens asked
    for role == "doctor" and nothing else, while a clinic marks an owner-admin
    who also runs a clinic day with `is_practitioner` — the board listed them,
    finance showed an empty dropdown."""
    from app.blueprints.finance.routes import _doctors_active
    from app.models import User

    with clinic["app"].app_context():
        owner = User(username="owner", full_name="د. مالك العيادة",
                     role="admin", is_active=True, is_practitioner=True)
        owner.set_password("secret")
        clinic["db"].session.add(owner)
        clinic["db"].session.commit()

        names = [u.full_name for u in _doctors_active()]
    assert "د. مالك العيادة" in names


def test_the_money_screens_and_the_board_agree_on_who_is_a_doctor(clinic):
    """Two definitions that can drift are two screens that will eventually
    disagree about who saw the patient."""
    from app.blueprints.finance.routes import _doctors_active
    from app.utils.appointments import list_doctors

    with clinic["app"].app_context():
        assert [u.id for u in _doctors_active()] == [u.id for u in list_doctors()]


def test_an_ordinary_admin_is_not_offered_as_a_doctor(clinic):
    """The flag is what says "this one sees patients". Without it the
    super-admin would appear on every bill as the treating doctor."""
    from app.blueprints.finance.routes import _doctors_active

    with clinic["app"].app_context():
        roles = {u.role for u in _doctors_active()}
    assert "admin" not in roles


def test_commission_settings_see_practitioners_too(clinic):
    """Otherwise the screen that sets a doctor's rate offers a different set of
    people from the screen that collects their money."""
    from app.blueprints.finance.routes import _doctors
    from app.models import User

    with clinic["app"].app_context():
        owner = User(username="owner2", full_name="د. شريك", role="admin",
                     is_active=True, is_practitioner=True)
        owner.set_password("secret")
        clinic["db"].session.add(owner)
        clinic["db"].session.commit()

        assert "د. شريك" in [u.full_name for u in _doctors()]


def test_an_inactive_doctor_keeps_their_commission_row(clinic):
    """A rate that vanished on deactivation would silently stop being the rate
    their historical invoices were priced at."""
    from app.blueprints.finance.routes import _doctors
    from app.models import User

    with clinic["app"].app_context():
        gone = User(username="retired", full_name="د. متقاعد", role="doctor",
                    is_active=False)
        gone.set_password("secret")
        clinic["db"].session.add(gone)
        clinic["db"].session.commit()

        assert "د. متقاعد" in [u.full_name for u in _doctors()]


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("kind", "generate_kind", "kind_month", "kind_quarter",
                    "kind_half", "kind_year", "search_ph"):
            assert data["periods"].get(key), f"{lang}.periods.{key}"
