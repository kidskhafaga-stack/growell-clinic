"""Imported money: an explicit choice on the preview, and off unless taken.

The history import carries a decade of another program's takings — 1.6 million
pounds over ten years in the file this was built for. Replaying that as
invoices and journal entries would put the same decade in the income statement
*and* in the accountant's opening balances, so every total the clinic reads is
wrong by ten years of revenue.

So the money stays where the import put it, and the clinic is asked one
question on the last screen before anything is written: may this batch's money
appear on the money screens? Unticked — the default — it is history on the
patient file and nothing else. Ticked, it shows as **its own line**, marked
imported, beside the totals and never inside them.

**Per batch, not per clinic.** A decade of old takings and last month's rows,
imported because the clinic switched over mid-year, are not the same answer,
and one global setting could not hold both.

Most of this file asserts the *off* state, because that is the one a wrong
default would quietly break.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _batch_with_money(clinic, count_money, when=date(2020, 5, 4), price=500.0,
                      share=200.0, paid=500.0):
    """One imported row on a batch, flagged or not."""
    from app.models import ImportBatch, ImportedService
    db = clinic["db"]
    batch = ImportBatch(kind="history", filename="old.xlsx", rows_total=1,
                        count_money=count_money)
    db.session.add(batch)
    db.session.flush()
    db.session.add(ImportedService(
        batch_id=batch.id, patient_id=clinic["ids"]["child"],
        doctor_id=clinic["ids"]["doctor"], service_date=when,
        source_name="كشف", price=price, doctor_share=share,
        paid_cash=paid, paid_company=0, quantity=1))
    db.session.commit()
    return batch


# --- off unless asked ------------------------------------------------------

def test_imported_money_stays_out_of_the_money_screens_by_default(clinic):
    """The default, and the one a wrong choice would break silently.

    Nothing about an unflagged batch may reach a total the clinic reads.
    """
    with clinic["app"].app_context():
        from app.utils.history_money import totals

        _batch_with_money(clinic, count_money=False)
        result = totals()
        assert result["rows"] == 0
        assert result["collected"] == 0
        assert result["batches"] == 0, (
            "an unflagged batch is being offered to the money screens")


def test_a_batch_the_clinic_ticked_is_counted(clinic):
    with clinic["app"].app_context():
        from app.utils.history_money import totals

        _batch_with_money(clinic, count_money=True)
        result = totals()
        assert result["rows"] == 1
        assert result["collected"] == 500.0
        assert result["doctor_share"] == 200.0


def test_the_answer_is_per_import_not_per_clinic(clinic):
    """Ten years of old takings and last month's rows are different answers.

    A global setting could only have said one of them, and whichever it said
    would be wrong for the other import.
    """
    with clinic["app"].app_context():
        from app.utils.history_money import totals

        _batch_with_money(clinic, count_money=False, price=9000.0,
                          share=4000.0, paid=9000.0)     # the old decade
        _batch_with_money(clinic, count_money=True, price=300.0,
                          share=120.0, paid=300.0)       # this year's switch
        result = totals()
        assert result["collected"] == 300.0, (
            "the history-only batch leaked into the counted total")
        assert result["rows"] == 1


# --- the choice is made where it can still be changed ----------------------

def test_the_preview_asks_before_anything_is_written(clinic):
    """On the last screen before the write, not in a settings page nobody
    visits — and with the double-counting spelled out."""
    body = open("app/templates/patients/history_preview.html",
                encoding="utf-8").read()
    assert 'name="count_money"' in body
    assert "history_import.count_money_hint" in body

    import json
    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        ar = json.load(fh)
    hint = ar["history_import"]["count_money_hint"]
    assert "مرتين" in hint, "the hint does not say what goes wrong"


def test_the_commit_records_what_was_ticked(clinic):
    """The checkbox has to survive the round trip, or it is decoration."""
    from app.blueprints.patients import routes

    source = open(routes.__file__, encoding="utf-8").read()
    assert 'count_money=request.form.get("count_money") == "1"' in source


def test_the_column_reaches_clinics_that_already_have_the_program():
    """A new column on an existing table exists only if the migration knows.

    Without the line the flag is unreadable on every clinic running since
    June, and ``count_money`` would raise on the first import.
    """
    from app.utils.schema import ADDITIONS

    assert ("import_batches", "count_money", "BOOLEAN DEFAULT 0") in ADDITIONS


# --- shown beside the books, never inside them -----------------------------

def test_it_never_writes_a_journal_entry(clinic):
    """The refusal the whole design rests on.

    Posting these would make the income statement and the opening balances
    contain the same decade.
    """
    from app.utils import history_money

    source = open(history_money.__file__, encoding="utf-8").read()
    for forbidden in ("JournalEntry", "JournalLine", "Invoice("):
        assert forbidden not in source, (
            f"the imported-money helper reaches for {forbidden}")


def test_the_statement_prints_it_as_its_own_line(clinic):
    """Beside the four totals, marked imported — not added into them."""
    with clinic["app"].app_context():
        _batch_with_money(clinic, count_money=True, when=date(2020, 5, 4))

    boss = clinic["sign_in"]("boss")
    body = boss.get("/finance/statements?doctor_id=%d&date_from=2020-01-01"
                    "&date_to=2020-12-31" % clinic["ids"]["doctor"]).data.decode()
    assert "مستورد (تاريخ سابق)" in body
    assert "500.0" in body or "500" in body


def test_an_unflagged_batch_shows_nothing_on_the_statement(clinic):
    with clinic["app"].app_context():
        _batch_with_money(clinic, count_money=False, when=date(2020, 5, 4))

    boss = clinic["sign_in"]("boss")
    body = boss.get("/finance/statements?doctor_id=%d&date_from=2020-01-01"
                    "&date_to=2020-12-31" % clinic["ids"]["doctor"]).data.decode()
    assert "مستورد (تاريخ سابق)" not in body


@pytest.mark.parametrize("start,end,expected", [
    ("2020-01-01", "2020-12-31", 500.0),   # inside
    ("2021-01-01", "2021-12-31", 0),       # after
    ("2019-01-01", "2019-12-31", 0),       # before
])
def test_it_answers_for_the_period_asked_for(clinic, start, end, expected):
    """A statement for March must not carry a row from 2016.

    The imported dates are the *service* dates, ten years wide, so a helper
    that ignored the range would put a decade on every screen that asked.
    """
    from app.utils.export import parse_date
    from app.utils.history_money import totals

    with clinic["app"].app_context():
        _batch_with_money(clinic, count_money=True, when=date(2020, 5, 4))
        result = totals(parse_date(start), parse_date(end))
        assert result["collected"] == expected
