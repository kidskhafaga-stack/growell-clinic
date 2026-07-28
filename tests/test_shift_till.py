"""The shift and its drawer.

Three things `TREASURY_PLAN.md` promised and the first pass did not deliver:
a shift knowing which till it is a session on, the last close being offered as
this morning's float, and a shift left open overnight being noticed.

The thread running through all three: **the float and the close are counted by
hand, and the gap between them is the entire point.** Anything the program
fills in for the cashier makes the closing variance a measurement against a
number nobody saw.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def tilled(clinic):
    from app.utils.accounting import ensure_seeded
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
    clinic["desk"] = clinic["sign_in"]("desk")
    return clinic


def _open(tilled, **data):
    return tilled["desk"].post("/finance/shift/open", data=data)


def _shift(tilled):
    from app.models import CashierShift

    return CashierShift.query.order_by(CashierShift.id.desc()).first()


# ----------------------------------------------------- the shift's drawer --
def test_a_shift_opens_on_a_cash_till(tilled):
    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        assert _shift(tilled).account.code == "1010"


def test_a_second_cash_till_can_be_chosen(tilled):
    """Two desks open at once are two shifts, each person short on their own
    drawer rather than on a shared abstraction."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        other = CashAccount(code="1014", name="خزنة الدور التاني", kind="cash",
                            sort_order=9, is_active=True)
        tilled["db"].session.add(other)
        tilled["db"].session.commit()
        other_id = other.id

    _open(tilled, opening_float="500", account_id=str(other_id))
    with tilled["app"].app_context():
        assert _shift(tilled).account_id == other_id


def test_a_shift_cannot_be_opened_on_a_wallet(tilled):
    """Nobody hands over an InstaPay balance at the end of the evening — it
    falls back to a real drawer rather than accepting the nonsense."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        wallet = CashAccount.query.filter_by(code="1011").first().id

    _open(tilled, opening_float="500", account_id=str(wallet))
    with tilled["app"].app_context():
        assert _shift(tilled).account.kind == "cash"


def test_a_clinic_with_no_tills_can_still_open_a_shift(tilled):
    """Tills are new. An install that has not got them must not lose the
    ability to run a till session."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        CashAccount.query.delete()
        tilled["db"].session.commit()

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        shift = _shift(tilled)
        assert shift is not None and shift.account_id is None


# ------------------------------------------------------------ the float ----
def test_the_last_close_is_offered(tilled):
    from app.utils.treasury import suggested_float

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        shift_id = _shift(tilled).id
    tilled["desk"].post(f"/finance/shift/{shift_id}/close",
                        data={"counted_cash": "742.50"})

    with tilled["app"].app_context():
        assert suggested_float() == 742.50


def test_it_is_offered_and_not_applied(tilled):
    """The float is what the cashier counted this morning. A number the
    program filled in makes the closing variance meaningless."""
    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        shift_id = _shift(tilled).id
    tilled["desk"].post(f"/finance/shift/{shift_id}/close",
                        data={"counted_cash": "742.50"})

    # Opening again without typing a float gets zero, not 742.50.
    _open(tilled)
    with tilled["app"].app_context():
        assert _shift(tilled).opening_float == 0


def test_the_suggestion_appears_on_the_screen_as_a_placeholder(tilled):
    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        shift_id = _shift(tilled).id
    tilled["desk"].post(f"/finance/shift/{shift_id}/close",
                        data={"counted_cash": "742.50"})

    body = tilled["desk"].get("/finance/cashier").get_data(as_text=True)
    assert 'placeholder="742.5"' in body


def test_a_clinic_on_its_first_ever_shift_is_offered_nothing(tilled):
    from app.utils.treasury import suggested_float

    with tilled["app"].app_context():
        assert suggested_float() is None


def test_a_shift_closed_without_a_count_is_not_a_suggestion(tilled):
    """Nothing was counted, so there is nothing to carry forward."""
    from app.models import CashierShift
    from app.utils.treasury import suggested_float

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        shift = _shift(tilled)
        shift.status = "closed"
        shift.closed_at = datetime.utcnow()
        tilled["db"].session.commit()
        assert suggested_float() is None


# ---------------------------------------------------- the forgotten shift --
def test_a_shift_open_since_yesterday_is_noticed(tilled):
    from app.utils.treasury import stale_shifts

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        _shift(tilled).opened_at = datetime.utcnow() - timedelta(hours=30)
        tilled["db"].session.commit()
        assert len(stale_shifts()) == 1


def test_a_shift_open_since_this_afternoon_is_not(tilled):
    """It is a shift, not a problem."""
    from app.utils.treasury import stale_shifts

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        assert stale_shifts() == []


def test_it_is_never_closed_automatically(tilled):
    """Closing it would write a counted_cash nobody counted — the program
    inventing the one number the whole exercise depends on."""
    from app.models import CashierShift
    from app.utils.treasury import stale_shifts

    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        _shift(tilled).opened_at = datetime.utcnow() - timedelta(hours=30)
        tilled["db"].session.commit()
        stale_shifts()
        shift = _shift(tilled)
        assert shift.status == "open"
        assert shift.counted_cash is None


def test_the_cashier_screen_says_so(tilled):
    _open(tilled, opening_float="500")
    with tilled["app"].app_context():
        _shift(tilled).opened_at = datetime.utcnow() - timedelta(hours=30)
        tilled["db"].session.commit()

    body = tilled["desk"].get("/finance/cashier").get_data(as_text=True)
    assert "مفتوحة من" in body
