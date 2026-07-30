"""Whose drawer is it, and when is the card money late.

Two things `TREASURY_PLAN.md` left for after the first pass.

**Per-till permissions.** A clinic with a desk on each floor has two drawers,
and "reception may work the till" was one permission covering both — so the
ground-floor cashier could count, collect into and bank the first-floor drawer
they never touch. The assignment answers *which* drawer; the capabilities still
answer *what may be done to one*, and the two must not be confused.

The dangerous default is the interesting part: a till nobody is named on stays
open. Every till in every existing clinic has nobody named on it, so a default
of "locked" would take away the drawer people used yesterday.

**The settlement window.** Card takings sit in a clearing till until the bank
sends them, and nobody remembers to check. The window makes "four days late" a
fact on the screen — and stops there. It never posts the settlement itself: the
bank's statement is the authority on what arrived and what the machine kept,
and a program that journals one on a timer is writing down money it has not
seen.
"""
import os
import sys
from datetime import date, timedelta

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
    clinic["boss"] = clinic["sign_in"]("boss")
    clinic["acct"] = clinic["sign_in"]("acct")
    return clinic


def _till_id(tilled, code):
    from app.models import CashAccount

    with tilled["app"].app_context():
        return CashAccount.query.filter_by(code=code).first().id


def _second_drawer(tilled, assign_to=None, owner=None):
    """A drawer on the other floor, optionally assigned to somebody."""
    from app.models import CashAccount, User

    with tilled["app"].app_context():
        drawer = CashAccount(code="1014", name="خزنة الدور التاني", kind="cash",
                             sort_order=9, is_active=True, owner_id=owner)
        if assign_to:
            drawer.users = User.query.filter(User.id.in_(assign_to)).all()
        tilled["db"].session.add(drawer)
        tilled["db"].session.commit()
        return drawer.id


def _assign(tilled, account_id, user_ids):
    from app.models import CashAccount, User

    with tilled["app"].app_context():
        till = tilled["db"].session.get(CashAccount, account_id)
        till.users = User.query.filter(User.id.in_(user_ids)).all()
        tilled["db"].session.commit()


def _user(tilled, key):
    from app.models import User

    return tilled["db"].session.get(User, tilled["ids"][key])


# ------------------------------------------------- who may work a till -----
def test_a_till_nobody_is_named_on_is_open_to_everybody(tilled):
    """The only safe default. Every till in an existing clinic looks like
    this, and locking them would take away yesterday's drawer."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        main = CashAccount.query.filter_by(code="1010").first()
        assert main.may_be_used_by(_user(tilled, "desk"))


def test_naming_somebody_shuts_everybody_else_out(tilled):
    from app.models import CashAccount

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]])
    with tilled["app"].app_context():
        drawer = tilled["db"].session.get(CashAccount, drawer_id)
        assert drawer.may_be_used_by(_user(tilled, "accountant"))
        assert not drawer.may_be_used_by(_user(tilled, "desk"))


def test_the_admin_is_never_locked_out(tilled):
    """Somebody has to be able to fix a till whose assignment is wrong."""
    from app.models import CashAccount

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]])
    with tilled["app"].app_context():
        drawer = tilled["db"].session.get(CashAccount, drawer_id)
        assert drawer.may_be_used_by(_user(tilled, "admin"))


def test_the_person_whose_name_is_on_the_drawer_is_never_locked_out(tilled):
    """An assignment list filled in without the owner is a mistake, not a
    decision to lock the owner out of their own drawer."""
    from app.models import CashAccount

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]],
                               owner=tilled["ids"]["desk"])
    with tilled["app"].app_context():
        drawer = tilled["db"].session.get(CashAccount, drawer_id)
        assert drawer.may_be_used_by(_user(tilled, "desk"))


def test_usable_by_is_the_list_the_pickers_are_built_from(tilled):
    from app.models import CashAccount

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]])
    with tilled["app"].app_context():
        mine = [a.id for a in CashAccount.usable_by(_user(tilled, "desk"))]
        assert drawer_id not in mine
        assert len(mine) == 5           # the five seeded, shared tills


def test_nobody_signed_in_may_work_nothing(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        assert not CashAccount.query.first().may_be_used_by(None)


# ------------------------------------------------------ on the screens -----
def test_the_picker_only_offers_tills_you_may_work(tilled):
    _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]])
    body = tilled["desk"].get("/finance/tills").get_data(as_text=True)
    assert "خزنة الدور التاني" not in body


def test_a_statement_for_somebody_elses_drawer_is_refused(tilled):
    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["accountant"]])
    assert tilled["desk"].get(f"/finance/tills/{drawer_id}").status_code == 403


def test_the_accountant_still_sees_the_whole_treasury(tilled):
    """Finance is a reporting job — an accountant who could only see their own
    drawer could not reconcile anything."""
    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    assert tilled["acct"].get(f"/finance/tills/{drawer_id}").status_code == 200


def test_counting_somebody_elses_drawer_is_refused(tilled):
    """The narrower rule: seeing a till to reconcile it is not the same as
    putting a hand in it and writing down what was found."""
    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    r = tilled["acct"].post(f"/finance/tills/{drawer_id}/count",
                            data={"counted": "100"})
    assert r.status_code == 403


def test_no_count_is_written_when_it_is_refused(tilled):
    from app.models import CashCount

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    tilled["acct"].post(f"/finance/tills/{drawer_id}/count",
                        data={"counted": "100"})
    with tilled["app"].app_context():
        assert CashCount.query.count() == 0


def test_moving_money_out_of_somebody_elses_till_is_refused(tilled):
    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    r = tilled["acct"].post("/finance/tills/move", data={
        "kind": "deposit", "account_id": str(drawer_id), "amount": "100"})
    assert r.status_code == 403


def test_money_may_arrive_in_a_till_you_cannot_work(tilled):
    """Banking your own drawer into a safe you have no access to is exactly
    what the control exists for, not something it should block."""
    from app.models import CashMovement

    safe_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    main_id = _till_id(tilled, "1010")
    tilled["acct"].post("/finance/tills/move", data={
        "kind": "deposit", "account_id": str(main_id), "amount": "500"})
    r = tilled["acct"].post("/finance/tills/move", data={
        "kind": "transfer", "account_id": str(main_id),
        "to_account_id": str(safe_id), "amount": "300"},
        follow_redirects=True)
    assert r.status_code == 200
    with tilled["app"].app_context():
        assert CashMovement.query.filter_by(kind="transfer").count() == 1


# ------------------------------------------------------ the shift's till ---
def test_a_shift_opens_on_the_drawer_you_are_assigned_to(tilled):
    """Not on whichever till the clinic marked as the cash default."""
    from app.models import CashierShift

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["desk"]])
    main_id = _till_id(tilled, "1010")
    _assign(tilled, main_id, [tilled["ids"]["admin"]])

    tilled["desk"].post("/finance/shift/open", data={"opening_float": "500"})
    with tilled["app"].app_context():
        shift = CashierShift.query.order_by(CashierShift.id.desc()).first()
        assert shift.account_id == drawer_id


def test_asking_for_a_drawer_that_is_not_yours_does_not_get_it(tilled):
    from app.models import CashierShift

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    tilled["desk"].post("/finance/shift/open",
                        data={"opening_float": "500",
                              "account_id": str(drawer_id)})
    with tilled["app"].app_context():
        shift = CashierShift.query.order_by(CashierShift.id.desc()).first()
        assert shift.account_id != drawer_id
        assert shift.account.code == "1010"


def test_a_collection_into_a_till_that_is_not_yours_lands_in_the_default(tilled):
    """A refusal here would be the wrong answer: the patient is standing there
    and the money is real. It goes where it would have gone if nobody had
    touched the picker."""
    from app.models import CashAccount

    from app.blueprints.finance.routes import _till_for

    drawer_id = _second_drawer(tilled, assign_to=[tilled["ids"]["admin"]])
    with tilled["app"].app_context():
        main = CashAccount.query.filter_by(code="1010").first().id
    with tilled["app"].test_request_context():
        from flask_login import login_user

        login_user(_user(tilled, "desk"))
        assert _till_for("cash", drawer_id).id == main


# --------------------------------------------------- the settlement window -
def _card_money(tilled, amount=1000, days_ago=0):
    """Card takings sitting in the clearing till, dated ``days_ago``."""
    from app.models import CashMovement

    card_id = _till_id(tilled, "1013")
    with tilled["app"].app_context():
        tilled["db"].session.add(CashMovement(
            kind="deposit", account_id=card_id, amount=amount,
            moved_on=date.today() - timedelta(days=days_ago)))
        tilled["db"].session.commit()
    return card_id


def test_money_that_just_arrived_has_waited_no_days(tilled):
    from app.models import CashAccount
    from app.utils.treasury import settlement_age

    _card_money(tilled)
    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert settlement_age(card) == 0


def test_the_age_is_the_oldest_thing_still_waiting(tilled):
    """Not the newest, and not an average — the question is how long the
    clinic has been owed the oldest of it."""
    from app.models import CashAccount
    from app.utils.treasury import settlement_age

    _card_money(tilled, 500, days_ago=6)
    _card_money(tilled, 800, days_ago=1)
    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert settlement_age(card) == 6


def test_a_settlement_resets_the_clock(tilled):
    """Money that arrived before the last settlement has already gone."""
    from app.models import CashAccount, CashMovement
    from app.utils.treasury import settlement_age

    card_id = _card_money(tilled, 500, days_ago=10)
    bank_id = _till_id(tilled, "1020")
    with tilled["app"].app_context():
        tilled["db"].session.add(CashMovement(
            kind="settle", account_id=card_id, to_account_id=bank_id,
            amount=500, moved_on=date.today() - timedelta(days=8)))
        tilled["db"].session.commit()
    _card_money(tilled, 300, days_ago=2)
    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert settlement_age(card) == 2


def test_an_empty_clearing_till_has_no_age(tilled):
    from app.models import CashAccount
    from app.utils.treasury import settlement_age

    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert settlement_age(card) is None


def test_a_back_dated_movement_never_reads_as_negative_days(tilled):
    from app.models import CashAccount
    from app.utils.treasury import settlement_age

    _card_money(tilled, 500, days_ago=-3)          # dated into the future
    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        assert settlement_age(card) == 0


def test_a_till_with_no_window_is_never_late(tilled):
    """A clinic that has not said how long its machine takes has not asked to
    be nagged, and a made-up industry average would nag them wrongly."""
    from app.utils.treasury import due_settlements

    _card_money(tilled, 1000, days_ago=30)
    with tilled["app"].app_context():
        assert due_settlements() == []


def _window(tilled, days):
    from app.models import CashAccount

    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        card.settle_after_days = days
        tilled["db"].session.commit()


def test_money_inside_the_window_is_not_late(tilled):
    from app.utils.treasury import due_settlements

    _window(tilled, 3)
    _card_money(tilled, 1000, days_ago=1)
    with tilled["app"].app_context():
        assert due_settlements() == []


def test_money_past_the_window_is_late(tilled):
    from app.utils.treasury import due_settlements

    _window(tilled, 2)
    _card_money(tilled, 1000, days_ago=5)
    with tilled["app"].app_context():
        rows = due_settlements()
        assert len(rows) == 1
        assert rows[0]["days"] == 5
        assert rows[0]["account"].code == "1013"


def test_the_day_it_falls_due_counts(tilled):
    """Two days means two days, not three."""
    from app.utils.treasury import due_settlements

    _window(tilled, 2)
    _card_money(tilled, 1000, days_ago=2)
    with tilled["app"].app_context():
        assert len(due_settlements()) == 1


def test_the_suggested_fee_comes_from_the_till(tilled):
    """One bank's machine takes 2.5%, another 1.9%. It is a property of which
    machine this is, not of the code."""
    from app.models import CashAccount
    from app.utils.treasury import pending_settlements

    _window(tilled, 1)
    with tilled["app"].app_context():
        card = CashAccount.query.filter_by(code="1013").first()
        card.fee_percent = 1.9
        tilled["db"].session.commit()
    _card_money(tilled, 1000, days_ago=4)
    with tilled["app"].app_context():
        assert pending_settlements()[0]["fee"] == 19.0


def test_nothing_is_ever_posted_by_the_window_alone(tilled):
    """The whole point. The bank statement is the authority on what arrived
    and what the machine kept — a settlement on a timer is the program writing
    down money it has not seen."""
    from app.models import CashMovement
    from app.utils.treasury import account_balance, due_settlements

    _window(tilled, 1)
    card_id = _card_money(tilled, 1000, days_ago=9)
    with tilled["app"].app_context():
        due_settlements()
        assert CashMovement.query.filter_by(kind="settle").count() == 0
        from app.models import CashAccount
        card = tilled["db"].session.get(CashAccount, card_id)
        assert account_balance(card) == 1000


def test_the_screen_says_it_is_late_and_fills_the_form_in(tilled):
    _window(tilled, 2)
    _card_money(tilled, 1000, days_ago=5)
    body = tilled["boss"].get("/finance/tills").get_data(as_text=True)
    assert "توريد متأخّر" in body
    assert 'value="1000.00"' in body


def test_the_screen_does_not_offer_the_form_when_nothing_is_late(tilled):
    _window(tilled, 9)
    _card_money(tilled, 1000, days_ago=1)
    body = tilled["boss"].get("/finance/tills").get_data(as_text=True)
    assert "توريد متأخّر" not in body


# ------------------------------------------------------------- the form ----
def test_the_admin_can_assign_a_till_to_people(tilled):
    from app.models import CashAccount

    main_id = _till_id(tilled, "1010")
    tilled["boss"].post(f"/finance/tills/{main_id}/save", data={
        "name": "الخزنة الرئيسية", "kind": "cash",
        "users": [str(tilled["ids"]["desk"])], "is_active": "1"})
    with tilled["app"].app_context():
        till = tilled["db"].session.get(CashAccount, main_id)
        assert [u.id for u in till.users] == [tilled["ids"]["desk"]]


def test_clearing_the_assignment_shares_the_till_again(tilled):
    from app.models import CashAccount

    main_id = _till_id(tilled, "1010")
    _assign(tilled, main_id, [tilled["ids"]["desk"]])
    tilled["boss"].post(f"/finance/tills/{main_id}/save", data={
        "name": "الخزنة الرئيسية", "kind": "cash", "is_active": "1"})
    with tilled["app"].app_context():
        till = tilled["db"].session.get(CashAccount, main_id)
        assert till.users == []
        assert till.may_be_used_by(_user(tilled, "accountant"))


def test_the_window_is_saved_and_a_zero_means_unset(tilled):
    from app.models import CashAccount

    card_id = _till_id(tilled, "1013")
    tilled["boss"].post(f"/finance/tills/{card_id}/save", data={
        "name": "الفيزا", "kind": "clearing", "settle_after_days": "3",
        "is_active": "1"})
    with tilled["app"].app_context():
        assert tilled["db"].session.get(
            CashAccount, card_id).settle_after_days == 3
    tilled["boss"].post(f"/finance/tills/{card_id}/save", data={
        "name": "الفيزا", "kind": "clearing", "settle_after_days": "0",
        "is_active": "1"})
    with tilled["app"].app_context():
        assert tilled["db"].session.get(
            CashAccount, card_id).settle_after_days is None


def test_only_the_admin_can_change_who_works_a_till(tilled):
    """Otherwise the control is a suggestion: whoever it locks out could
    unlock themselves."""
    main_id = _till_id(tilled, "1010")
    r = tilled["acct"].post(f"/finance/tills/{main_id}/save", data={
        "name": "مش بتاعتك", "kind": "cash"})
    assert r.status_code == 403
