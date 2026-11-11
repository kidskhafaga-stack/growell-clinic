"""Changes before the month is closed (MONEY_SAFETY_PLAN.md ف-٧).

Asked: «نفّذ الحل الوسط وخلّي في المستشفيات تقدر تعدّل الإجراء ده من
الإعدادات … نخلّي القيود الكاملة تتكتب في بند تاني».

The ledger keeps one entry per document in an open month, as before; every
change to it now leaves a row in a separate book — who, when, before and
after — read on «تعديلات قبل القفل». A hospital may keep it as the full book
(a reversal and a new entry for each change) and download it.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_books_keep_what_they_said import _bill, _post  # noqa: E402


@pytest.fixture()
def books(clinic):
    from app.utils import accounting

    with clinic["app"].app_context():
        accounting.ensure_seeded()
    return clinic


def _entries(fx, bill_id):
    from app.models import JournalEntry

    return JournalEntry.query.filter_by(source_type="invoice", source_id=bill_id).all()


def _written_yesterday(fx, bill_id):
    with fx["app"].app_context():
        for e in _entries(fx, bill_id):
            e.created_at = datetime.utcnow() - timedelta(days=1)
        fx["db"].session.commit()


def test_a_change_is_kept_beside_the_ledger_not_in_it(books):
    from app.models import JournalRevision
    from app.utils.clock import local_today

    bill = _bill(books, local_today(), price=200)
    _post(books, bill)
    _written_yesterday(books, bill)
    _post(books, bill, discount=50)
    with books["app"].app_context():
        entries = _entries(books, bill)
        assert len(entries) == 1, "the ledger still has one entry for the bill"
        assert round(entries[0].total_debit, 2) == 150
        rev = JournalRevision.query.one()
        assert (rev.kind, rev.old_total, rev.new_total) == ("changed", 200, 150)
        assert rev.entry_number == entries[0].entry_number
        assert {ln["code"] for ln in rev.before()} == {ln["code"] for ln in rev.after()}


def test_posting_again_without_a_change_writes_nothing(books):
    from app.models import JournalRevision
    from app.utils.clock import local_today

    bill = _bill(books, local_today())
    _post(books, bill)
    _post(books, bill)
    with books["app"].app_context():
        assert JournalRevision.query.count() == 0


def test_a_closed_month_is_still_corrected_by_a_new_entry_not_a_revision(books):
    from app.models import JournalRevision
    from app.utils.clock import local_today
    from app.utils.periods import close_period, generate_periods

    last_month = local_today().replace(day=1) - timedelta(days=1)
    bill = _bill(books, last_month)
    _post(books, bill)
    with books["app"].app_context():
        generate_periods(last_month.year, "month", "ar")
        from app.utils.periods import period_for

        close_period(period_for(last_month))
        books["db"].session.commit()
    _post(books, bill, discount=50)
    with books["app"].app_context():
        assert len(_entries(books, bill)) == 2, "the closed month's entry stands; a new one adjusts"
        assert JournalRevision.query.count() == 0


def test_the_review_shows_who_and_how_much_and_folds_the_same_day(books):
    from app.utils.clock import local_today

    same_day = _bill(books, local_today(), price=300)
    _post(books, same_day)
    _post(books, same_day, discount=100)              # still being made today
    later = _bill(books, local_today(), price=200)
    _post(books, later)
    _written_yesterday(books, later)
    _post(books, later, discount=20)
    boss = books["sign_in"]("boss")
    page = boss.get("/finance/journal/changes").get_data(as_text=True)
    assert page.count("data-trail-row=") == 1, "only the later change is listed"
    assert "data-trail-folded" in page
    assert "200.00" in page and "180.00" in page
    every = boss.get("/finance/journal/changes?all=1").get_data(as_text=True)
    assert every.count("data-trail-row=") == 2
    assert "data-trail-door" in boss.get("/finance/journal").get_data(as_text=True)


def test_a_deleted_document_leaves_what_its_entry_said(books):
    from app.models import JournalRevision
    from app.utils import accounting
    from app.utils.clock import local_today

    bill = _bill(books, local_today())
    _post(books, bill)
    with books["app"].app_context():
        accounting.unpost("invoice", bill)
        books["db"].session.commit()
        rev = JournalRevision.query.one()
        assert rev.kind == "removed" and rev.old_total == 200 and rev.after() == []


def test_the_open_period_says_how_many_changes_before_closing(books):
    from app.utils.clock import local_today
    from app.utils.periods import generate_periods

    today = local_today()
    with books["app"].app_context():
        generate_periods(today.year, "month", "ar")
        books["db"].session.commit()
    bill = _bill(books, today)
    _post(books, bill)
    _written_yesterday(books, bill)
    _post(books, bill, discount=10)
    page = books["sign_in"]("boss").get(f"/finance/periods?year={today.year}").get_data(as_text=True)
    assert 'data-period-changes="1"' in page


def test_the_full_book_is_a_hospital_s_choice(books):
    from app.models import Setting
    from app.utils import facility
    from app.utils.clock import local_today

    boss = books["sign_in"]("boss")
    with books["app"].app_context():
        Setting.set("facility_configured", "1")
        for m in ("beds", "emergency", "theatres"):
            Setting.set(f"mod_enabled:{m}", "0")
        books["db"].session.commit()
    assert "data-trail-setting" not in boss.get("/settings/").get_data(as_text=True), \
        "a clinic without hospital parts is not offered it"
    boss.post("/settings/", data={"open_month_trail": "full", "active_tab": "policies"})
    assert "data-trail-book-door" not in boss.get("/finance/journal/changes").get_data(as_text=True)

    with books["app"].app_context():
        Setting.set("mod_enabled:beds", "1")
        books["db"].session.commit()
        assert facility.module_enabled("beds")
    assert "data-trail-setting" in boss.get("/settings/").get_data(as_text=True)
    boss.post("/settings/", data={"open_month_trail": "full", "active_tab": "policies"})
    with books["app"].app_context():
        assert Setting.get("open_month_trail") == "full"

    bill = _bill(books, local_today())
    _post(books, bill)
    _written_yesterday(books, bill)
    _post(books, bill, discount=50)
    book = boss.get("/finance/journal/changes?view=book").get_data(as_text=True)
    assert 'data-book-role="reversal"' in book and 'data-book-role="restated"' in book
    csv = boss.get("/finance/journal/changes?format=csv")
    assert csv.mimetype == "text/csv"
    text = csv.get_data(as_text=True)
    assert "200.00" in text and "150.00" in text
