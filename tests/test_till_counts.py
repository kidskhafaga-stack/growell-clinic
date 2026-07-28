"""Counting a till, and what happens when it does not agree.

A balance the program computed is a claim. A stocktake is somebody checking it
against the world, and the two disagreeing is the only way a clinic ever finds
out that money went missing.

And the shift finally stops blaming the cashier for doing their job: 175 paid
to a supplier out of the drawer used to leave the count 175 short.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def tilled(clinic):
    from app.models import CashAccount
    from app.utils.accounting import ensure_seeded
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
        CashAccount.query.filter_by(code="1010").first().opening_balance = 1000
        clinic["db"].session.commit()
    clinic["boss"] = clinic["sign_in"]("boss")
    clinic["acct"] = clinic["sign_in"]("acct")
    clinic["desk"] = clinic["sign_in"]("desk")
    return clinic


def _drawer(tilled):
    from app.models import CashAccount

    return CashAccount.query.filter_by(code="1010").first()


def _count(tilled, counted, **kwargs):
    """Record a stocktake and hand back its id.

    An id, not the object: the fixture's context closes and a model loaded in
    it would be read in one session and written from another.
    """
    from app.utils import treasury

    with tilled["app"].app_context():
        return treasury.record_count(_drawer(tilled), counted, **kwargs).id


def _get_count(tilled, count_id):
    from app.models import CashCount

    return db_session(tilled).get(CashCount, count_id)


def db_session(tilled):
    return tilled["db"].session


# ------------------------------------------------------------ the count ----
def test_a_count_that_matches_has_no_difference(tilled):
    cid = _count(tilled, 1000)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        assert count.difference == 0
        assert count.needs_explaining is False


def test_a_short_till_records_the_shortfall(tilled):
    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        assert count.difference == -300
        assert count.is_short is True
        assert count.needs_explaining is True


def test_an_over_till_records_that_too(tilled):
    """Money that should not be there is as much a discrepancy as money
    missing — it usually means something was never recorded."""
    cid = _count(tilled, 1100)
    with tilled["app"].app_context():
        assert _get_count(tilled, cid).difference == 100


def test_the_expected_figure_is_frozen_onto_the_count(tilled):
    """Recomputing it later would silently rewrite what the count found the
    next time a back-dated movement landed."""
    from app.utils import treasury

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        treasury.record_movement("deposit", _drawer(tilled), 500)
        count = _get_count(tilled, cid)
        assert count.expected == 1000, "the count must not move under it"
        assert count.difference == -300


def test_counting_never_resolves_the_difference_on_its_own(tilled):
    """Counting and writing off are two acts. The first must not quietly do
    the second."""
    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        assert _get_count(tilled, cid).status == "open"


def test_counting_does_not_change_the_balance(tilled):
    from app.utils.treasury import account_balance

    _count(tilled, 700)
    with tilled["app"].app_context():
        assert account_balance(_drawer(tilled)) == 1000.0


# --------------------------------------------------------- explaining it ---
def test_writing_off_a_shortage_moves_the_balance_to_the_count(tilled):
    from app.utils import treasury
    from app.utils.treasury import account_balance

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        treasury.explain_count(count, "عجز في الدرج، اتبلّغ المدير",
                               user_id=tilled["ids"]["admin"])
        assert account_balance(_drawer(tilled)) == 700.0
        assert count.status == "adjusted"


def test_an_overage_is_written_the_other_way(tilled):
    from app.utils import treasury
    from app.utils.treasury import account_balance

    cid = _count(tilled, 1100)
    with tilled["app"].app_context():
        treasury.explain_count(_get_count(tilled, cid), "فلوس اتلاقت في درج تاني",
                               user_id=tilled["ids"]["admin"])
        assert account_balance(_drawer(tilled)) == 1100.0


def test_accepting_without_writing_off_leaves_the_money_alone(tilled):
    """A miscount is explained without pretending money moved."""
    from app.utils import treasury
    from app.utils.treasury import account_balance

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        treasury.explain_count(count, "غلطة في العدّ، اتعدّ تاني",
                               user_id=tilled["ids"]["admin"], write_off=False)
        assert count.status == "accepted"
        assert account_balance(_drawer(tilled)) == 1000.0


def test_a_reason_is_required(tilled):
    """"Adjusted" with no words next to it is the audit trail failing at the
    one moment it exists for."""
    from app.utils import treasury

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        with pytest.raises(treasury.MovementError) as exc:
            treasury.explain_count(count, "   ", user_id=tilled["ids"]["admin"])
        assert str(exc.value) == "need_reason"
        assert count.status == "open"


def test_a_difference_cannot_be_closed_twice(tilled):
    from app.utils import treasury

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        treasury.explain_count(count, "سبب", user_id=tilled["ids"]["admin"])
        with pytest.raises(treasury.MovementError) as exc:
            treasury.explain_count(count, "سبب تاني",
                                   user_id=tilled["ids"]["admin"])
        assert str(exc.value) == "already_resolved"


def test_the_write_off_shows_on_the_statement(tilled):
    """A write-off that hid itself would defeat the point of having one."""
    from app.utils import treasury
    from app.utils.treasury import movements

    cid = _count(tilled, 700)
    with tilled["app"].app_context():
        treasury.explain_count(_get_count(tilled, cid), "عجز",
                               user_id=tilled["ids"]["admin"])
        kinds = [m["kind"] for m in movements(_drawer(tilled))]
        assert "mv_withdraw" in kinds


def test_who_counted_and_who_explained_are_kept_apart(tilled):
    from app.utils import treasury

    cid = _count(tilled, 700, user_id=tilled["ids"]["desk"])
    with tilled["app"].app_context():
        count = _get_count(tilled, cid)
        treasury.explain_count(count, "عجز", user_id=tilled["ids"]["admin"])
        assert count.counted_by == tilled["ids"]["desk"]
        assert count.resolved_by == tilled["ids"]["admin"]


def test_open_differences_lists_only_the_unexplained(tilled):
    from app.utils import treasury

    _count(tilled, 1000)                         # matches — not a difference
    short = _count(tilled, 700)
    with tilled["app"].app_context():
        assert len(treasury.open_differences()) == 1
        treasury.explain_count(_get_count(tilled, short), "عجز",
                               user_id=tilled["ids"]["admin"])
        assert treasury.open_differences() == []


# ------------------------------------------------------------- who may -----
def test_reception_may_count(tilled):
    """Counting is what the person holding the drawer does."""
    from app.models import CashAccount, CashCount

    with tilled["app"].app_context():
        till = CashAccount.query.filter_by(code="1010").first().id
    tilled["desk"].post(f"/finance/tills/{till}/count", data={"counted": "700"})
    with tilled["app"].app_context():
        assert CashCount.query.count() == 1


def test_reception_may_not_erase_what_it_was_short(tilled):
    """The one that matters. An adjustment line is exactly how a shortage
    disappears."""
    from app.models import CashCount

    count_id = _count(tilled, 700, user_id=tilled["ids"]["desk"])

    resp = tilled["desk"].post(f"/finance/tills/count/{count_id}/explain",
                               data={"reason": "معلش", "write_off": "1"})

    assert resp.status_code in (302, 403)
    with tilled["app"].app_context():
        assert db_session(tilled).get(CashCount, count_id).status == "open"


def test_the_accountant_cannot_either(tilled):
    """They may move money between tills; erasing a shortage is narrower
    still."""
    from app.models import CashCount

    count_id = _count(tilled, 700)

    tilled["acct"].post(f"/finance/tills/count/{count_id}/explain",
                        data={"reason": "معلش", "write_off": "1"})

    with tilled["app"].app_context():
        assert db_session(tilled).get(CashCount, count_id).status == "open"


def test_the_manager_can(tilled):
    from app.models import CashCount

    count_id = _count(tilled, 700)

    tilled["boss"].post(f"/finance/tills/count/{count_id}/explain",
                        data={"reason": "عجز اتبلّغ", "write_off": "1"})

    with tilled["app"].app_context():
        assert db_session(tilled).get(CashCount, count_id).status == "adjusted"


# ------------------------------------------- the drawer stops being blamed --
def test_cash_paid_to_a_supplier_comes_off_the_drawers_count(tilled):
    """The 175 this whole thing started from: until now the shift still
    expected them to be in the drawer, so the count came up short and the
    variance landed on the cashier for doing their job."""
    from app.models import CashierShift, Supplier

    with tilled["app"].app_context():
        supplier = Supplier(name="مورد")
        tilled["db"].session.add(supplier)
        tilled["db"].session.commit()
        sid = supplier.id

    tilled["boss"].post("/finance/shift/open", data={"opening_float": "1000"})
    tilled["boss"].post(f"/finance/payables/{sid}/pay",
                        data={"amount": "175", "method": "cash"})

    with tilled["app"].app_context():
        shift = CashierShift.query.first()
        assert shift.cash_paid_out == 175.0
        assert shift.expected_cash == 825.0


def test_an_expense_paid_in_cash_does_the_same(tilled):
    from app.models import CashierShift

    tilled["boss"].post("/finance/shift/open", data={"opening_float": "500"})
    tilled["boss"].post("/finance/expenses/new",
                        data={"category": "other", "description": "كهربا",
                              "amount": "60", "payment_method": "cash"})

    with tilled["app"].app_context():
        assert CashierShift.query.first().expected_cash == 440.0


def test_money_paid_by_transfer_leaves_the_count_where_it_was(tilled):
    """It never touched the drawer."""
    from app.models import CashierShift

    tilled["boss"].post("/finance/shift/open", data={"opening_float": "500"})
    tilled["boss"].post("/finance/expenses/new",
                        data={"category": "other", "description": "إيجار",
                              "amount": "60", "payment_method": "transfer"})

    with tilled["app"].app_context():
        assert CashierShift.query.first().expected_cash == 500.0


def test_two_shifts_in_a_day_are_not_charged_each_others_payments(tilled):
    """Matched by shift, not by date. An expense carries a date and a shift
    carries a time."""
    from app.models import CashierShift

    tilled["boss"].post("/finance/shift/open", data={"opening_float": "500"})
    tilled["boss"].post("/finance/expenses/new",
                        data={"category": "other", "description": "أولى",
                              "amount": "60", "payment_method": "cash"})
    with tilled["app"].app_context():
        first = CashierShift.query.first()
        first_id = first.id
    tilled["boss"].post(f"/finance/shift/{first_id}/close",
                        data={"counted_cash": "440"})
    tilled["boss"].post("/finance/shift/open", data={"opening_float": "500"})

    with tilled["app"].app_context():
        shifts = CashierShift.query.order_by(CashierShift.id).all()
        assert shifts[0].cash_paid_out == 60.0
        assert shifts[1].cash_paid_out == 0.0


# --------------------------------------------------------------- screens ---
def test_the_count_form_is_on_the_till_statement(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        till = CashAccount.query.filter_by(code="1010").first().id
    body = tilled["boss"].get(f"/finance/tills/{till}").get_data(as_text=True)
    assert "/count" in body


def test_unexplained_differences_show_on_the_tills_screen(tilled):
    _count(tilled, 700)
    body = tilled["boss"].get("/finance/tills").get_data(as_text=True)
    assert "-300.00" in body


def test_reception_sees_the_difference_but_not_the_button(tilled):
    _count(tilled, 700)
    body = tilled["desk"].get("/finance/tills").get_data(as_text=True)
    assert "-300.00" in body
    assert "/explain" not in body
