"""The books keep what they said (MONEY_SAFETY_PLAN.md ف-٥).

Measured before: a bill of a closed month, covered later by an approval, had
its journal entry quietly rewritten from 200 to 50 — the month the owner had
signed now said something else, and nothing showed it had changed.

Now an entry in an open month is still rebuilt in place, as it always was;
an entry in a closed month stays as it was, and one entry dated today
carries the difference.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def books(clinic):
    from app.utils import accounting

    with clinic["app"].app_context():
        accounting.ensure_seeded()
    return clinic


def _bill(fx, day, price=200):
    from app.models import Invoice, InvoiceItem

    db = fx["db"]
    with fx["app"].app_context():
        n = Invoice.query.count() + 1
        inv = Invoice(patient_id=fx["ids"]["child"], invoice_number=f"INV-B{n}",
                      invoice_date=day, status="unpaid")
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, service_id=fx["ids"]["exam"],
                                   description="كشف", quantity=1, unit_price=price,
                                   discount_value=0))
        db.session.commit()
        return inv.id


def _post(fx, bill_id, discount=None):
    from app.models import Invoice
    from app.utils import accounting

    db = fx["db"]
    with fx["app"].app_context():
        inv = db.session.get(Invoice, bill_id)
        if discount is not None:
            inv.items[0].discount_value = discount
            db.session.commit()
        accounting.post_invoice(inv)


def _entries(fx, bill_id):
    from app.models import JournalEntry

    with fx["app"].app_context():
        rows = (JournalEntry.query.filter_by(source_type="invoice", source_id=bill_id)
                .order_by(JournalEntry.id).all())
        return [(e.entry_date, sorted((ln.account.code, ln.debit, ln.credit) for ln in e.lines))
                for e in rows]


def _net(entries, code):
    return round(sum(d - c for _day, lines in entries for k, d, c in lines if k == code), 2)


def test_a_bill_that_grows_today_stays_one_entry(books):
    bill = _bill(books, local_today())
    _post(books, bill)
    _post(books, bill, discount=50)
    entries = _entries(books, bill)
    assert len(entries) == 1
    assert _net(entries, "1030") == 150


def test_an_older_bill_in_an_open_month_is_still_rebuilt_in_place(books):
    day = local_today() - timedelta(days=40)
    bill = _bill(books, day)
    _post(books, bill)
    _post(books, bill, discount=150)
    entries = _entries(books, bill)
    assert entries == [(day, sorted([("1030", 50, 0), ("4010", 0, 50)]))]


def _close(fx, day):
    from app.models import AccountingPeriod
    from app.utils.periods import close_period

    with fx["app"].app_context():
        db = fx["db"]
        p = AccountingPeriod(name="قديم", start_date=day.replace(day=1),
                             end_date=day + timedelta(days=1), status="open")
        db.session.add(p)
        db.session.commit()
        close_period(p)
        db.session.commit()


def test_a_closed_month_says_what_it_said(books):
    day = local_today() - timedelta(days=40)
    bill = _bill(books, day)
    _post(books, bill)
    _close(books, day)
    _post(books, bill, discount=150)
    entries = _entries(books, bill)
    assert len(entries) == 2
    assert entries[0] == (day, sorted([("1030", 200, 0), ("4010", 0, 200)]))
    assert entries[1] == (local_today(), sorted([("1030", 0, 150), ("4010", 150, 0)]))
    assert _net(entries, "1030") == 50
    # Posted again with nothing changed: nothing written.
    _post(books, bill)
    assert len(_entries(books, bill)) == 2
    # Changed again: the correction is another entry, never a rewrite.
    _post(books, bill, discount=100)
    entries = _entries(books, bill)
    assert len(entries) == 3 and entries[0][1] == sorted([("1030", 200, 0), ("4010", 0, 200)])
    assert _net(entries, "1030") == 100


def test_the_trial_balance_stays_balanced_through_corrections(books):
    from app.models import JournalLine

    day = local_today() - timedelta(days=40)
    bill = _bill(books, day)
    _post(books, bill)
    _close(books, day)
    _post(books, bill, discount=20)
    _post(books, bill, discount=0)
    with books["app"].app_context():
        d = sum(ln.debit for ln in JournalLine.query.all())
        c = sum(ln.credit for ln in JournalLine.query.all())
        assert round(d - c, 2) == 0
    assert _net(_entries(books, bill), "1030") == 200
