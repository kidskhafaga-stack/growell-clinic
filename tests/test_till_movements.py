"""Money moved on purpose, and who is allowed to move it.

Everything else that touches a till is a side-effect of something the clinic
was doing anyway — a patient paid, a supplier was settled. This is the other
kind: money moved *because somebody decided to move it*. Banking the drawer,
topping up change, and the one that made the card account possible at all —
settling it into the bank, minus what the processor took.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def tilled(clinic):
    """Tills seeded, the drawer holding 1,000, and the manager signed in."""
    from app.models import CashAccount
    from app.utils.accounting import ensure_seeded
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
        drawer = CashAccount.query.filter_by(code="1010").first()
        drawer.opening_balance = 1000
        card = CashAccount.query.filter_by(code="1013").first()
        card.opening_balance = 1000
        clinic["db"].session.commit()
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _acct(tilled, code):
    from app.models import CashAccount

    return CashAccount.query.filter_by(code=code).first()


def _move(tilled, **kwargs):
    """Record a movement inside an app context, returning the error key or None."""
    from app.utils import treasury

    with tilled["app"].app_context():
        src = _acct(tilled, kwargs.pop("src", "1010"))
        dst_code = kwargs.pop("dst", None)
        dst = _acct(tilled, dst_code) if dst_code else None
        try:
            treasury.record_movement(
                kwargs.pop("kind", "transfer"), src, kwargs.pop("amount", 100),
                to_account=dst, **kwargs)
            return None
        except treasury.MovementError as exc:
            return str(exc)


def _balance(tilled, code):
    from app.utils.treasury import account_balance

    with tilled["app"].app_context():
        return account_balance(_acct(tilled, code))


# ------------------------------------------------------ moving the money ---
def test_banking_the_drawer_moves_it(tilled):
    assert _move(tilled, kind="transfer", src="1010", dst="1020",
                 amount=400) is None
    assert _balance(tilled, "1010") == 600.0
    assert _balance(tilled, "1020") == 400.0


def test_a_deposit_only_adds(tilled):
    assert _move(tilled, kind="deposit", src="1010", amount=250) is None
    assert _balance(tilled, "1010") == 1250.0


def test_a_withdrawal_only_takes(tilled):
    assert _move(tilled, kind="withdraw", src="1010", amount=250) is None
    assert _balance(tilled, "1010") == 750.0


def test_settling_the_card_account_loses_the_processors_cut(tilled):
    """1,000 leaves the card account and 975 reaches the bank. This is the
    whole reason settlement is not just a transfer."""
    assert _move(tilled, kind="settle", src="1013", dst="1020",
                 amount=1000, fee=25) is None
    assert _balance(tilled, "1013") == 0.0
    assert _balance(tilled, "1020") == 975.0


def test_the_fee_is_booked_as_a_cost_not_lost(tilled):
    """Money that leaves one account and does not arrive in another has to go
    somewhere, or the books stop balancing."""
    from app.models import JournalLine

    _move(tilled, kind="settle", src="1013", dst="1020", amount=1000, fee=25)
    with tilled["app"].app_context():
        fee_lines = [ln for ln in JournalLine.query.all()
                     if ln.account.code == "5010" and ln.debit == 25]
        assert fee_lines, "the processor's cut must be an expense"


def test_one_row_serves_both_tills(tilled):
    """Not two rows. A transfer cannot then exist half-recorded."""
    from app.models import CashMovement

    _move(tilled, kind="transfer", src="1010", dst="1020", amount=100)
    with tilled["app"].app_context():
        assert CashMovement.query.count() == 1


# ------------------------------------------------------------- refusals ----
def test_a_till_cannot_transfer_to_itself(tilled):
    assert _move(tilled, kind="transfer", src="1010", dst="1010") == "same_till"


def test_a_transfer_needs_somewhere_to_go(tilled):
    assert _move(tilled, kind="transfer", src="1010") == "no_target"


def test_money_cannot_leave_a_till_that_does_not_have_it(tilled):
    assert _move(tilled, kind="transfer", src="1010", dst="1020",
                 amount=5000) == "insufficient"
    assert _balance(tilled, "1010") == 1000.0


def test_a_deposit_is_exempt_from_that(tilled):
    """It is the one kind that adds, so an empty till is not a reason to
    refuse it."""
    assert _move(tilled, kind="deposit", src="1011", amount=500) is None


def test_only_a_clearing_till_settles(tilled):
    assert _move(tilled, kind="settle", src="1010", dst="1020") == "not_clearing"


def test_a_fee_that_swallows_the_transfer_is_refused(tilled):
    """It means the numbers are wrong, not that the clinic moved nothing."""
    assert _move(tilled, kind="transfer", src="1010", dst="1020",
                 amount=100, fee=100) == "bad_fee"
    assert _move(tilled, kind="transfer", src="1010", dst="1020",
                 amount=100, fee=-5) == "bad_fee"


def test_a_fee_on_a_deposit_makes_no_sense(tilled):
    assert _move(tilled, kind="deposit", src="1010", amount=100,
                 fee=5) == "fee_needs_transfer"


def test_zero_is_not_a_movement(tilled):
    assert _move(tilled, kind="deposit", src="1010", amount=0) == "bad_amount"


def test_two_currencies_are_refused_rather_than_guessed(tilled):
    """Rates, revaluation and an FX difference account do not exist yet. A
    clear refusal beats a wrong number."""
    with tilled["app"].app_context():
        _acct(tilled, "1020").currency = "USD"
        tilled["db"].session.commit()
    assert _move(tilled, kind="transfer", src="1010", dst="1020",
                 amount=100) == "cross_currency"


# ------------------------------------------------------------- the books ---
def test_a_transfer_balances_in_the_ledger(tilled):
    from app.models import JournalEntry

    _move(tilled, kind="transfer", src="1010", dst="1020", amount=400)
    with tilled["app"].app_context():
        entry = JournalEntry.query.filter_by(source_type="cash_movement").first()
        assert entry is not None
        debits = sum(ln.debit or 0 for ln in entry.lines)
        credits = sum(ln.credit or 0 for ln in entry.lines)
        assert round(debits, 2) == round(credits, 2) == 400.0


# ------------------------------------------------------- what has not come --
def test_the_card_account_shows_up_as_money_not_arrived(tilled):
    from app.utils.treasury import pending_settlements

    with tilled["app"].app_context():
        rows = pending_settlements()
        assert len(rows) == 1
        assert rows[0]["account"].code == "1013"
        assert rows[0]["target"].code == "1020"
        assert rows[0]["orphan"] is False


def test_a_clearing_till_with_nowhere_to_settle_is_called_out(tilled):
    """It can never be cleared to zero, and that is worth saying out loud
    rather than leaving as a balance that only grows."""
    from app.utils.treasury import pending_settlements

    with tilled["app"].app_context():
        _acct(tilled, "1013").settles_into_id = None
        tilled["db"].session.commit()
        assert pending_settlements()[0]["orphan"] is True


def test_a_settled_account_drops_off_the_list(tilled):
    from app.utils.treasury import pending_settlements

    _move(tilled, kind="settle", src="1013", dst="1020", amount=1000, fee=25)
    with tilled["app"].app_context():
        assert pending_settlements() == []


# ---------------------------------------------------------- who may move ---
def test_reception_collects_but_does_not_move(tilled):
    """Taking money from patients and moving the clinic's own money are
    different jobs. Whoever does the first is not automatically trusted with
    the second."""
    from app.models import CashAccount

    with tilled["app"].app_context():
        src = CashAccount.query.filter_by(code="1010").first().id
        dst = CashAccount.query.filter_by(code="1020").first().id

    desk = tilled["sign_in"]("desk")
    resp = desk.post("/finance/tills/move",
                     data={"kind": "transfer", "account_id": str(src),
                           "to_account_id": str(dst), "amount": "100"})

    assert resp.status_code in (302, 403)
    assert _balance(tilled, "1010") == 1000.0, "nothing moved"


def test_the_accountant_may(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        src = CashAccount.query.filter_by(code="1010").first().id
        dst = CashAccount.query.filter_by(code="1020").first().id

    acct = tilled["sign_in"]("acct")
    acct.post("/finance/tills/move",
              data={"kind": "transfer", "account_id": str(src),
                    "to_account_id": str(dst), "amount": "100"})

    assert _balance(tilled, "1010") == 900.0


def test_writing_off_a_difference_is_a_narrower_permission_than_moving(tilled):
    """An adjustment line is exactly how a shortage disappears, so whoever
    counts the drawer must not be the one who erases what they were short."""
    from app.models.permissions import role_has_capability

    assert role_has_capability("accountant", "treasury_move") is True
    assert role_has_capability("accountant", "treasury_adjust") is False
    assert role_has_capability("reception", "treasury_move") is False
    assert role_has_capability("admin", "treasury_adjust") is True


# --------------------------------------------------------------- screens ---
def test_the_movement_form_is_on_the_tills_screen(tilled):
    body = tilled["boss"].get("/finance/tills").get_data(as_text=True)
    assert "/finance/tills/move" in body


def test_reception_does_not_see_the_form(tilled):
    body = tilled["sign_in"]("desk").get("/finance/tills").get_data(as_text=True)
    assert "/finance/tills/move" not in body


def test_a_movement_shows_on_both_statements(tilled):
    from app.models import CashAccount

    _move(tilled, kind="transfer", src="1010", dst="1020", amount=400)
    with tilled["app"].app_context():
        src = CashAccount.query.filter_by(code="1010").first().id
        dst = CashAccount.query.filter_by(code="1020").first().id

    out = tilled["boss"].get(f"/finance/tills/{src}").get_data(as_text=True)
    into = tilled["boss"].get(f"/finance/tills/{dst}").get_data(as_text=True)
    assert "600.00" in out          # what the drawer held after
    assert "400.00" in into


def test_a_bad_movement_tells_the_user_which_rule_it_broke(tilled):
    from app.models import CashAccount

    with tilled["app"].app_context():
        src = CashAccount.query.filter_by(code="1010").first().id

    body = tilled["boss"].post("/finance/tills/move",
                               data={"kind": "transfer", "account_id": str(src),
                                     "to_account_id": str(src), "amount": "50"},
                               follow_redirects=True).get_data(as_text=True)
    assert "نفسها" in body


def test_the_date_is_honoured(tilled):
    from app.models import CashMovement

    _move(tilled, kind="deposit", src="1010", amount=100,
          moved_on=date(2026, 1, 5))
    with tilled["app"].app_context():
        assert CashMovement.query.first().moved_on == date(2026, 1, 5)
