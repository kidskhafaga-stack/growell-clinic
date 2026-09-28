"""An expense deleted, or changed, takes its ledger entry with it.

Found while building cost centres: deleting an expense from the expenses
screen deleted the row and **left its journal entry behind**. The expenses
screen stopped showing the cost; the income statement went on counting it;
nothing anywhere said why the two differed. The journal screen's gap finder
only ever looked the other way — a document with no entry — so an entry with
no document was invisible. Editing had the same fault more quietly: the row
changed and the ledger kept the first amount.

What is held here:

* deleting takes the entry out in the same step, and says so in the log;
* editing rebuilds the entry in place — same number, new amount, date and
  cost centre;
* a closed period refuses both, as it always did — and moving an expense
  *into* a closed period is refused too;
* an expense paid out of a shift that is counted and closed is not changed
  or deleted: that count is signed;
* the entries already left behind are found on the journal screen, and the
  owner can remove them — except inside a closed period, which keeps what
  it said.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def books(clinic):
    from app.utils import accounting

    with clinic["app"].app_context():
        accounting.ensure_seeded()
    return clinic


def _add(clinic, amount="300", on=None, method="bank"):
    from app.models import Expense

    clinic["sign_in"]("boss").post("/finance/expenses/new", data={
        "category": "supplies", "amount": amount, "description": "كواشف",
        "payment_method": method, "expense_date": (on or "")})
    with clinic["app"].app_context():
        return Expense.query.order_by(Expense.id.desc()).first().id


def _entry(clinic, expense_id):
    from app.models import JournalEntry

    with clinic["app"].app_context():
        row = JournalEntry.query.filter_by(source_type="expense",
                                           source_id=expense_id).first()
        if row is None:
            return None
        return {"number": row.entry_number, "date": row.entry_date,
                "lines": sorted((ln.account.code, ln.debit, ln.credit,
                                 ln.cost_centre_id) for ln in row.lines)}


def _expenses_in_books(clinic):
    """What the income statement counts as operating expenses."""
    from app.models import Account, JournalLine

    with clinic["app"].app_context():
        account = Account.query.filter_by(code="5010").one()
        return round(sum(ln.debit - ln.credit for ln in
                         JournalLine.query.filter_by(account_id=account.id)), 2)


def _close(clinic, start, end):
    from app.models import AccountingPeriod

    with clinic["app"].app_context():
        clinic["db"].session.add(AccountingPeriod(
            name="مقفول", kind="month", start_date=start, end_date=end,
            status="closed"))
        clinic["db"].session.commit()


# ------------------------------------------------------------- deleting ----
def test_deleting_an_expense_takes_its_entry_with_it(books):
    from app.models import ActivityLog, Expense

    kept = _add(books, "100")
    gone = _add(books, "300")
    assert _expenses_in_books(books) == 400
    books["sign_in"]("boss").post(f"/finance/expenses/{gone}/delete")
    with books["app"].app_context():
        assert books["db"].session.get(Expense, gone) is None
        log = ActivityLog.query.filter_by(action="expense.delete").one()
        assert log.entity_id == gone and "entries=1" in log.detail
    assert _entry(books, gone) is None
    assert _entry(books, kept) is not None
    assert _expenses_in_books(books) == 100


def test_a_closed_month_keeps_its_expense_and_its_entry(books):
    last_month = local_today().replace(day=1) - timedelta(days=5)
    expense = _add(books, "250", on=last_month.isoformat())
    _close(books, last_month.replace(day=1), last_month)
    books["sign_in"]("boss").post(f"/finance/expenses/{expense}/delete")
    from app.models import Expense

    with books["app"].app_context():
        assert books["db"].session.get(Expense, expense) is not None
    assert _entry(books, expense) is not None


def test_an_expense_out_of_a_counted_shift_is_left_as_it_is(books):
    from app.models import CashierShift, Expense

    expense = _add(books, "80")
    with books["app"].app_context():
        shift = CashierShift(shift_number="S-CLOSED", opening_float=0,
                             opened_by=books["ids"]["desk"], status="closed")
        books["db"].session.add(shift)
        books["db"].session.flush()
        books["db"].session.get(Expense, expense).shift_id = shift.id
        books["db"].session.commit()
    client = books["sign_in"]("boss")
    page = client.post(f"/finance/expenses/{expense}/delete",
                       follow_redirects=True).get_data(as_text=True)
    assert "ورديته اتقفلت" in page
    client.post(f"/finance/expenses/{expense}/edit", data={
        "category": "supplies", "amount": "999", "payment_method": "bank"})
    with books["app"].app_context():
        assert books["db"].session.get(Expense, expense).amount == 80
    assert _entry(books, expense) is not None
    assert _expenses_in_books(books) == 80


# -------------------------------------------------------------- editing ----
def test_editing_an_expense_rebuilds_its_entry_in_place(books):
    from app.utils import cost_centres

    expense = _add(books, "300")
    before = _entry(books, expense)
    with books["app"].app_context():
        lab = cost_centres.centre_id("lab")
        books["db"].session.commit()
    books["sign_in"]("boss").post(f"/finance/expenses/{expense}/edit", data={
        "category": "supplies", "amount": "450", "payment_method": "bank",
        "expense_date": local_today().isoformat(), "cost_centre_id": lab})
    after = _entry(books, expense)
    assert after["number"] == before["number"]
    debit = [ln for ln in after["lines"] if ln[0] == "5010"][0]
    assert (debit[1], debit[3]) == (450.0, lab)
    assert _expenses_in_books(books) == 450


def test_moving_an_expense_into_a_closed_month_is_refused(books):
    from app.models import Expense

    expense = _add(books, "120")
    last_month = local_today().replace(day=1) - timedelta(days=3)
    _close(books, last_month.replace(day=1), last_month)
    books["sign_in"]("boss").post(f"/finance/expenses/{expense}/edit", data={
        "category": "supplies", "amount": "120", "payment_method": "bank",
        "expense_date": last_month.isoformat()})
    with books["app"].app_context():
        assert books["db"].session.get(Expense, expense).expense_date == local_today()
    assert _entry(books, expense)["date"] == local_today()


# ----------------------------------------------------- left behind before --
def _orphan(clinic, source_id, on=None, amount=70):
    """An entry whose expense was deleted the old way."""
    from app.utils import accounting

    with clinic["app"].app_context():
        accounting.post_entry("expense", source_id, "قديم", [
            ("5010", amount, 0, "قديم"), ("1010", 0, amount, "قديم")],
            entry_date=on)


def test_entries_left_behind_are_found_and_removed(books):
    _orphan(books, 90001)
    kept = _add(books, "100")
    page = books["sign_in"]("boss").get("/finance/journal").get_data(as_text=True)
    assert 'data-left-behind="1"' in page
    assert _expenses_in_books(books) == 170
    books["sign_in"]("boss").post("/finance/journal/left-behind")
    assert _expenses_in_books(books) == 100
    assert _entry(books, kept) is not None
    page = books["sign_in"]("boss").get("/finance/journal").get_data(as_text=True)
    assert "data-left-behind" not in page
    from app.models import ActivityLog

    with books["app"].app_context():
        assert "removed=1" in ActivityLog.query.filter_by(
            action="ledger.left_behind").one().detail


def test_a_closed_month_keeps_what_was_left_behind_in_it(books):
    last_month = local_today().replace(day=1) - timedelta(days=4)
    _orphan(books, 90002, on=last_month)
    _orphan(books, 90003)
    _close(books, last_month.replace(day=1), last_month)
    page = books["sign_in"]("boss").post("/finance/journal/left-behind",
                                         follow_redirects=True).get_data(as_text=True)
    assert "فترة مقفولة" in page
    from app.utils import ledger_gaps

    with books["app"].app_context():
        assert [e.source_id for e in ledger_gaps.left_behind()] == [90002]


def test_only_the_owner_removes_them(books):
    _orphan(books, 90004)
    reply = books["sign_in"]("acct").post("/finance/journal/left-behind")
    assert reply.status_code in (302, 403)
    from app.utils import ledger_gaps

    with books["app"].app_context():
        assert len(ledger_gaps.left_behind()) == 1


def test_an_entry_whose_expense_exists_is_never_left_behind(books):
    """The finder looks at expenses only: a manual entry, an invoice or a
    payment is not an expense entry however its number happens to match."""
    from app.utils import accounting, ledger_gaps

    expense = _add(books, "60")
    with books["app"].app_context():
        accounting.post_entry("invoice", 90005, "فاتورة", [
            ("1030", 10, 0, "x"), ("4010", 0, 10, "x")])
        assert ledger_gaps.left_behind() == []
    assert _entry(books, expense) is not None
