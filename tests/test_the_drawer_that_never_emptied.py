"""Closing a shift, and the half of it the program never did.

A cashier closes their shift: they count the drawer, keep enough change to
open tomorrow, and hand the rest to the safe. The program did the first two
thirds of that — it stored the count and worked out the over/short — and then
watched the money go across the counter without writing anything down.

So the drawer's balance grew for ever. A reception till open for a year read
as holding a year of takings, and the safe, which is where the clinic's money
actually is, had never seen a single day's money. Every screen built on those
balances was reporting a clinic that does not exist.

These tests are about the transfer that was missing, and about the one thing
that quietly breaks the moment it exists: the next shift's opening float. It
used to be suggested as *what the last shift was counted at*, which was right
only because nothing ever left the drawer. Once the takings go to the safe,
suggesting the count would open tomorrow expecting the whole evening's money,
and every shift after it would look short by the same figure.
"""
from datetime import date

import pytest

from app.utils.clock import local_today  # noqa: E402


# --------------------------------------------------------------- helpers --
def _tills(clinic, sweep=True, safe_active=True, safe_code="1015"):
    """A reception drawer that cash lands in, and the safe behind it.

    Returns ``(drawer_id, safe_id)``. The drawer claims the ``cash`` method,
    which is what makes a payment land in it rather than nowhere.

    ``safe_code`` matters only to the ledger: ``post_entry`` skips quietly
    when a code is not in the chart of accounts, so the one test that reads
    journal lines asks for a code the chart carries.
    """
    from app.models import CashAccount

    with clinic["app"].app_context():
        db = clinic["db"]
        drawer = CashAccount(code="1010", name="درج الاستقبال", kind="cash",
                             default_methods="cash", is_active=True)
        safe = CashAccount(code=safe_code, name="الخزنة الرئيسية", kind="cash",
                           is_active=safe_active)
        db.session.add_all([drawer, safe])
        db.session.flush()
        if sweep:
            drawer.sweeps_into_id = safe.id
        db.session.commit()
        return drawer.id, safe.id


def _balance(clinic, account_id):
    from app.models import CashAccount
    from app.utils import treasury

    with clinic["app"].app_context():
        account = clinic["db"].session.get(CashAccount, account_id)
        return treasury.account_balance(account)


def _open(client, float_amount="100", account_id=None):
    data = {"opening_float": float_amount}
    if account_id:
        data["account_id"] = str(account_id)
    return client.post("/finance/shift/open", data=data, follow_redirects=True)


def _bill_and_pay(client, ids, price="200"):
    """Raise a bill and collect it in cash, in one pass through the till."""
    return client.post(f"/finance/collect/{ids['child']}", data={
        "patient_id": ids["child"], "doctor_id": ids["doctor"],
        "line_service_id": [str(ids["exam"])], "line_desc": ["كشف"],
        "line_price": [price], "line_qty": ["1"], "line_no_commission": ["0"],
        "line_brand_id": [""], "line_dose_id": [""], "line_vs_id": [""],
        "line_dose_number": [""], "discount_id": "none",
        "amount": price, "method": "cash"}, follow_redirects=True)


def _the_shift(clinic):
    from app.models import CashierShift

    with clinic["app"].app_context():
        return CashierShift.query.order_by(CashierShift.id.desc()).first().id


def _close(client, shift_id, counted, keep=None):
    data = {"counted_cash": str(counted)}
    if keep is not None:
        data["keep_float"] = str(keep)
    return client.post(f"/finance/shift/{shift_id}/close", data=data,
                       follow_redirects=True)


def _shift_state(clinic, shift_id):
    from app.models import CashierShift

    with clinic["app"].app_context():
        shift = clinic["db"].session.get(CashierShift, shift_id)
        return {"status": shift.status, "counted": shift.counted_cash,
                "variance": shift.variance, "handed": shift.handed_over,
                "left": shift.left_in_drawer,
                "handover_id": shift.handover_id,
                "to": (shift.handover.to_account_id
                       if shift.handover else None)}


@pytest.fixture
def desk(clinic):
    return clinic["sign_in"]("boss")


# ------------------------------------------------- the money actually moves --
def test_closing_a_shift_hands_the_takings_to_the_safe(desk, clinic):
    """The point of the whole exercise: after the close, the safe holds the
    day's money and the drawer holds its change."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)

    assert _balance(clinic, safe) == 0.0
    _close(desk, shift, counted="300")

    assert _balance(clinic, safe) == 200.0
    assert _balance(clinic, drawer) == 0.0


def test_the_float_stays_behind_for_tomorrow(desk, clinic):
    """The drawer is not emptied. A reception that opens with nothing in it
    cannot give a patient their change, so the float it opened on stays."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    state = _shift_state(clinic, shift)
    assert state["handed"] == 200.0
    assert state["left"] == 100.0


def test_the_cashier_decides_what_change_to_keep(desk, clinic):
    """The float that opened the shift is the default, not the rule. The
    person holding the drawer can see whether it is in usable notes."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300", keep="150")

    assert _shift_state(clinic, shift)["handed"] == 150.0
    assert _balance(clinic, safe) == 150.0


def test_the_shift_records_where_its_money_went(desk, clinic):
    """The report has to be able to say the takings are in the safe. Without
    the link it can only say what was counted, and the reader is left to
    guess whether the money is still in the drawer."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    state = _shift_state(clinic, shift)
    assert state["handover_id"] is not None
    assert state["to"] == safe


def test_the_report_names_the_safe_the_money_went_to(desk, clinic):
    """And says it on the screen, not only in the database."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    page = desk.get(f"/finance/shift/{shift}").get_data(as_text=True)
    assert "الخزنة الرئيسية" in page


# ------------------------------------------- what the next shift is offered --
def test_tomorrow_is_offered_the_change_not_the_takings(desk, clinic):
    """The bug this change would have introduced, pinned.

    The opening float used to be suggested as the last shift's *counted*
    figure, which was only ever right because nothing left the drawer. Suggest
    it now and reception opens tomorrow expecting the whole evening's money —
    and is short by exactly the takings, every single day.
    """
    from app.utils import treasury

    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    with clinic["app"].app_context():
        assert treasury.suggested_float(account_id=drawer) == 100.0


def test_a_till_that_sweeps_nowhere_still_suggests_its_count(desk, clinic):
    """And the old answer is still the right one for a drawer that keeps its
    cash: it handed nothing over, so what was counted is what is there."""
    from app.utils import treasury

    drawer, _safe = _tills(clinic, sweep=False)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    with clinic["app"].app_context():
        assert treasury.suggested_float(account_id=drawer) == 300.0


# ------------------------------------------------------ when nothing moves --
def test_a_drawer_with_no_safe_keeps_its_money(desk, clinic):
    """Every till in an existing clinic. Nothing moves, nothing is recorded,
    and nobody is told off for it — turning the sweep on for a clinic because
    a column appeared would move their money without being asked."""
    drawer, safe = _tills(clinic, sweep=False)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    state = _shift_state(clinic, shift)
    assert state["status"] == "closed"
    assert state["handover_id"] is None
    assert _balance(clinic, drawer) == 200.0
    assert _balance(clinic, safe) == 0.0


def test_a_drawer_holding_only_its_float_hands_over_nothing(desk, clinic):
    """A shift that took no money has nothing to hand over. Posting a zero
    transfer would put a row on the safe's statement saying nothing happened,
    which is worse than the silence."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    shift = _the_shift(clinic)
    _close(desk, shift, counted="100")

    assert _shift_state(clinic, shift)["handover_id"] is None
    assert _balance(clinic, safe) == 0.0


def test_a_quiet_evening_is_not_reported_as_an_error(desk, clinic):
    """And the cashier is not told off for it.

    ``record_movement`` refuses a zero transfer, correctly — but reaching it
    at all means the close ends on a red *"the amount must be over zero"*,
    every evening a drawer takes no cash. Having nothing to hand over is not
    a mistake, so it is decided before anything is asked to refuse it.
    """
    from app.utils import treasury

    drawer, _safe = _tills(clinic)
    _open(desk, "100", drawer)
    shift = _the_shift(clinic)
    page = _close(desk, shift, counted="100").get_data(as_text=True)

    assert "المبلغ لازم يكون أكبر من صفر" not in page

    with clinic["app"].app_context():
        from app.models import CashierShift

        # Returns, rather than raising: the caller has nothing to handle.
        assert treasury.hand_over(
            clinic["db"].session.get(CashierShift, shift)) is None


def test_an_inactive_safe_is_not_swept_into(desk, clinic):
    """A till switched off is a till nobody is watching. Money sent to one
    would be out of the drawer and out of sight."""
    drawer, safe = _tills(clinic, safe_active=False)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    assert _shift_state(clinic, shift)["handover_id"] is None
    assert _balance(clinic, safe) == 0.0


def test_a_till_cannot_hand_over_to_itself(desk, clinic):
    """Configured by a mis-click, and it would read as the drawer emptying
    into the drawer — a movement that means nothing and balances to nothing."""
    from app.models import CashAccount

    drawer, _safe = _tills(clinic)
    with clinic["app"].app_context():
        till = clinic["db"].session.get(CashAccount, drawer)
        till.sweeps_into_id = till.id
        clinic["db"].session.commit()

    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    page = _close(desk, shift, counted="300").get_data(as_text=True)

    assert _shift_state(clinic, shift)["handover_id"] is None
    assert _balance(clinic, drawer) == 200.0
    # A misconfigured till is the admin's problem, not something to put in
    # front of the cashier at the end of every shift.
    assert "مش هينفع تحوّل الخزنة لنفسها" not in page

    from app.utils import treasury

    with clinic["app"].app_context():
        from app.models import CashierShift

        assert treasury.hand_over(
            clinic["db"].session.get(CashierShift, shift)) is None


# ------------------------------------------------- counted, not expected ----
def test_a_short_drawer_hands_over_what_is_actually_in_it(desk, clinic):
    """The cashier hands over the notes in their hand.

    Handing over the *expected* figure would transfer 200 out of a drawer
    holding 170 — papering over a 30 shortage by moving money that is not
    there, and leaving the safe's balance a number nobody counted.
    """
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="270")          # 30 short

    state = _shift_state(clinic, shift)
    assert state["variance"] == -30.0
    assert state["handed"] == 170.0
    assert _balance(clinic, safe) == 170.0


def test_the_shortage_stays_in_the_drawer_as_an_open_question(desk, clinic):
    """And it is not written off on the way past.

    After a short close the drawer's books still carry the 30. That is the
    honest answer — the money is missing and nobody has explained it yet —
    and it is what keeps the difference somebody's to account for instead of
    quietly absorbed by the transfer.
    """
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="270")

    assert _balance(clinic, drawer) == 30.0


# ------------------------------------------------- the close never breaks ---
def test_a_transfer_that_cannot_post_does_not_reopen_the_shift(desk, clinic):
    """Closing a shift is a fact about a drawer that has been counted.

    Keeping less than the float asks the books to move money they have no
    record of arriving — the opening float is physically in the drawer but
    was never posted to it. The transfer is refused, which is right. The
    close is not, because it already happened at the counter.
    """
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    reply = _close(desk, shift, counted="300", keep="0")

    assert reply.status_code == 200
    state = _shift_state(clinic, shift)
    assert state["status"] == "closed"
    assert state["counted"] == 300.0
    assert state["handover_id"] is None


def test_closing_an_already_closed_shift_does_not_sweep_twice(desk, clinic):
    """A double-submitted close would otherwise send the takings to the safe
    a second time, out of a drawer that no longer has them."""
    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")
    _close(desk, shift, counted="300")

    assert _balance(clinic, safe) == 200.0


# ------------------------------------------------------------- the books ----
def test_the_handover_is_journalled_on_both_sides(desk, clinic):
    """A transfer that moves the drawer without moving the safe is a ledger
    that no longer balances. The movement posts to both codes or the books
    are wrong from that evening on."""
    from app.models import CashierShift, JournalEntry, JournalLine
    from app.utils import accounting

    with clinic["app"].app_context():
        accounting.ensure_seeded()
    drawer, safe = _tills(clinic, safe_code="1020")
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    with clinic["app"].app_context():
        handover_id = clinic["db"].session.get(CashierShift, shift).handover_id
        entry = JournalEntry.query.filter_by(source_type="cash_movement",
                                             source_id=handover_id).one()
        by_code = {line.account.code: (line.debit or 0, line.credit or 0)
                   for line in JournalLine.query.filter_by(entry_id=entry.id)}
    assert by_code["1020"] == (200.0, 0)        # into the safe
    assert by_code["1010"] == (0, 200.0)        # out of the drawer


def test_the_handover_shows_on_the_safes_statement(desk, clinic):
    """The safe's statement is where a manager checks the day arrived. A
    transfer nothing lists is a transfer nobody can verify."""
    from app.models import CashAccount
    from app.utils import treasury

    drawer, safe = _tills(clinic)
    _open(desk, "100", drawer)
    _bill_and_pay(desk, clinic["ids"], "200")
    shift = _the_shift(clinic)
    _close(desk, shift, counted="300")

    with clinic["app"].app_context():
        account = clinic["db"].session.get(CashAccount, safe)
        rows = treasury.movements(account)
    assert [(r["kind"], r["amount"]) for r in rows] == [("mv_transfer", 200.0)]


# ----------------------------------------------------------- reachability ---
def test_the_safe_can_be_named_on_the_till_screen(desk, clinic):
    """A column no screen sets is a feature nobody has. This is the one the
    whole thing hangs off: until a drawer names its safe, nothing sweeps."""
    drawer, safe = _tills(clinic, sweep=False)

    page = desk.get(f"/finance/tills/{drawer}").get_data(as_text=True)
    assert 'name="sweeps_into_id"' in page

    desk.post(f"/finance/tills/{drawer}/save", data={
        "name": "درج الاستقبال", "kind": "cash", "opening_balance": "0",
        "is_active": "1", "sweeps_into_id": str(safe)},
        follow_redirects=True)

    from app.models import CashAccount

    with clinic["app"].app_context():
        assert clinic["db"].session.get(CashAccount, drawer).sweeps_into_id == safe


def test_the_close_form_asks_what_to_keep_only_when_there_is_a_safe(desk, clinic):
    """A clinic that keeps its cash in the drawer must not be asked to decide
    something with no effect."""
    drawer, _safe = _tills(clinic, sweep=False)
    _open(desk, "100", drawer)
    shift = _the_shift(clinic)

    without = desk.get(f"/finance/shift/{shift}").get_data(as_text=True)
    assert 'name="keep_float"' not in without

    from app.models import CashAccount

    with clinic["app"].app_context():
        till = clinic["db"].session.get(CashAccount, drawer)
        till.sweeps_into_id = _safe
        clinic["db"].session.commit()

    with_safe = desk.get(f"/finance/shift/{shift}").get_data(as_text=True)
    assert 'name="keep_float"' in with_safe
