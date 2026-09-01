"""The bank's version of the till against the program's.

A till's balance is the program's claim. The statement is the world's. Nobody
finds out that a transfer never arrived, that a fee was taken twice, or that a
collection was recorded and the money went elsewhere, without putting the two
side by side — and nobody does that by hand once a month has more than a
handful of lines in it.

Two rules the whole feature exists to keep, and most of these tests are about
one of them:

**Nothing is matched when the answer is ambiguous.** One movement at the same
amount within a few days is a match. Two is a question for a person. A
reconciliation that quietly picked one of two identical amounts would report
"all matched" while pointing at the wrong movement, which is worse than
reporting nothing at all.

**Nothing posts a journal entry.** A line with no match is a question, and the
answer is sometimes "record the bank charge" and sometimes "the bank made a
mistake". A reconciliation that invented entries to balance itself would be
describing its own arithmetic rather than the clinic's money.
"""
import io
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def tilled(clinic):
    from app.utils.accounting import ensure_seeded
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
    clinic["desk"] = clinic["sign_in"]("desk")
    clinic["acct"] = clinic["sign_in"]("acct")
    clinic["boss"] = clinic["sign_in"]("boss")
    return clinic


def _bank_id(tilled, code="1020"):
    from app.models import CashAccount

    with tilled["app"].app_context():
        return CashAccount.query.filter_by(code=code).first().id


def _upload(text, name="statement.csv"):
    """A statement file as the browser would hand it over."""
    from werkzeug.datastructures import FileStorage

    return FileStorage(stream=io.BytesIO(text.encode("utf-8-sig")),
                       filename=name, content_type="text/csv")


def _import(tilled, text, code="1020", name="statement.csv"):
    from app.models import CashAccount
    from app.utils import bank_import

    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code=code).first()
        return bank_import.import_lines(account, _upload(text, name),
                                        user_id=tilled["ids"]["accountant"])


def _movement(tilled, amount, when=None, code="1020", kind="deposit"):
    """A movement the program recorded, so the statement has something to hit."""
    from app.models import CashAccount, CashMovement

    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code=code).first()
        mv = CashMovement(kind=kind, account_id=account.id, amount=abs(amount),
                          moved_on=when or local_today())
        tilled["db"].session.add(mv)
        tilled["db"].session.commit()
        return mv.id


# ----------------------------------------------------------- the parser ----
def test_a_signed_amount_column_reads_straight_through():
    from app.utils.bank_import import parse_matrix

    rows, skipped = parse_matrix(
        ["Date", "Description", "Amount"],
        [["2026-07-28", "POS settlement", "1975.00"],
         ["2026-07-29", "Bank charge", "-25.00"]])
    assert skipped == 0
    assert [r["amount"] for r in rows] == [1975.0, -25.0]


def test_debit_and_credit_columns_fold_into_one_sign():
    """Which column it was in is a property of the export format, not of what
    happened — a debit is money leaving whatever sign the bank printed."""
    from app.utils.bank_import import parse_matrix

    rows, _ = parse_matrix(
        ["التاريخ", "البيان", "مدين", "دائن"],
        [["28/07/2026", "تحصيل فيزا", "", "1975.00"],
         ["29/07/2026", "مصاريف بنكية", "25.00", ""]])
    assert [r["amount"] for r in rows] == [1975.0, -25.0]


def test_arabic_headers_arabic_digits_and_commas_all_read():
    from app.utils.bank_import import parse_matrix

    rows, _ = parse_matrix(
        ["تاريخ العملية", "الشرح", "القيمة", "الرصيد"],
        [["٢٨/٠٧/٢٠٢٦", "تحويل", "١٢,٣٤٥٫٦٧", "٩٩٩٩٩"]])
    assert rows[0]["amount"] == 12345.67
    assert rows[0]["date"] == date(2026, 7, 28)
    assert rows[0]["balance"] == 99999.0


def test_brackets_mean_negative():
    """Accountants' notation, and every export that came out of Excel."""
    from app.utils.bank_import import parse_amount

    assert parse_amount("(1,250.00)") == -1250.0


def test_a_currency_stuck_on_the_end_is_not_a_reason_to_fail():
    from app.utils.bank_import import parse_amount

    assert parse_amount("500 EGP") == 500.0
    assert parse_amount("ج.م ٧٥٠") == 750.0


def test_a_decimal_comma_is_not_a_thousands_comma():
    from app.utils.bank_import import parse_amount

    assert parse_amount("1,50") == 1.5          # decimal comma
    assert parse_amount("1,234") == 1234.0      # thousands


def test_a_row_with_no_date_is_skipped_not_guessed(tilled):
    """A statement line with no date is a subtotal or a header repeat.
    Inventing one would put money in the reconciliation the bank never
    mentioned."""
    from app.utils.bank_import import parse_matrix

    rows, skipped = parse_matrix(
        ["Date", "Amount"],
        [["2026-07-28", "100"], ["", "999"], ["Total", "1099"]])
    assert len(rows) == 1 and skipped == 2


def test_a_zero_amount_row_is_skipped():
    from app.utils.bank_import import parse_matrix

    rows, skipped = parse_matrix(["Date", "Amount"],
                                 [["2026-07-28", "0.00"]])
    assert rows == [] and skipped == 1


def test_a_statement_with_no_date_column_is_refused():
    from app.utils.bank_import import StatementError, parse_matrix

    with pytest.raises(StatementError) as exc:
        parse_matrix(["Description", "Amount"], [["x", "1"]])
    assert "no_date_column" in str(exc.value)


def test_a_statement_with_no_amount_column_is_refused():
    from app.utils.bank_import import StatementError, parse_matrix

    with pytest.raises(StatementError) as exc:
        parse_matrix(["Date", "Description"], [["2026-07-28", "x"]])
    assert "no_amount_column" in str(exc.value)


# ---------------------------------------------------------- the storing ----
_TWO_LINES = ("Date,Description,Amount\n"
              "2026-07-28,POS settlement,1975.00\n"
              "2026-07-29,Bank charge,-25.00\n")


def test_a_statement_is_stored_line_by_line(tilled):
    from app.models import BankLine

    added, skipped, repeats = _import(tilled, _TWO_LINES)
    assert (added, skipped, repeats) == (2, 0, 0)
    with tilled["app"].app_context():
        assert BankLine.query.count() == 2


def test_importing_the_same_file_twice_adds_nothing(tilled):
    from app.models import BankLine

    _import(tilled, _TWO_LINES)
    added, _skipped, repeats = _import(tilled, _TWO_LINES)
    assert (added, repeats) == (0, 2)
    with tilled["app"].app_context():
        assert BankLine.query.count() == 2


def test_two_identical_transactions_on_one_day_are_two_lines(tilled):
    """The trap a unique index would fall into: two genuine 200s are two
    transactions, and swallowing the second would understate the statement."""
    from app.models import BankLine

    twice = ("Date,Description,Amount\n"
             "2026-07-28,Cash deposit,200.00\n"
             "2026-07-28,Cash deposit,200.00\n")
    added, _s, _r = _import(tilled, twice)
    assert added == 2
    with tilled["app"].app_context():
        assert BankLine.query.count() == 2


def test_reimporting_a_file_with_honest_duplicates_still_ends_with_two(tilled):
    from app.models import BankLine

    twice = ("Date,Description,Amount\n"
             "2026-07-28,Cash deposit,200.00\n"
             "2026-07-28,Cash deposit,200.00\n")
    _import(tilled, twice)
    added, _s, repeats = _import(tilled, twice)
    assert (added, repeats) == (0, 2)
    with tilled["app"].app_context():
        assert BankLine.query.count() == 2


def test_a_longer_statement_over_a_shorter_one_adds_only_the_new_lines(tilled):
    """The normal case: last month's file re-imported with this month on the
    end."""
    from app.models import BankLine

    _import(tilled, _TWO_LINES)
    longer = _TWO_LINES + "2026-07-30,Transfer in,500.00\n"
    added, _s, repeats = _import(tilled, longer)
    assert (added, repeats) == (1, 2)
    with tilled["app"].app_context():
        assert BankLine.query.count() == 3


def test_a_cash_drawer_has_no_statement(tilled):
    """It has a count, which is a different screen and a different act."""
    from app.utils.bank_import import StatementError

    with pytest.raises(StatementError) as exc:
        _import(tilled, _TWO_LINES, code="1010")
    assert "not_reconcilable" in str(exc.value)


def test_a_file_of_the_wrong_kind_is_refused(tilled):
    from app.utils.bank_import import StatementError

    with pytest.raises(StatementError):
        _import(tilled, _TWO_LINES, name="statement.pdf")


# --------------------------------------------------------- the matching ----
def test_one_movement_at_the_same_amount_is_a_candidate(tilled):
    from app.models import BankLine
    from app.utils import bank_import

    _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1975.00\n")
    with tilled["app"].app_context():
        line = BankLine.query.first()
        assert len(bank_import.candidates(line)) == 1


def test_a_different_amount_is_not_a_candidate(tilled):
    """Exact to the piastre. "Close enough" on money is how a reconciliation
    comes to point at the wrong transaction."""
    from app.models import BankLine
    from app.utils import bank_import

    _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1974.00\n")
    with tilled["app"].app_context():
        assert bank_import.candidates(BankLine.query.first()) == []


def test_a_movement_a_few_days_off_still_counts(tilled):
    """A transfer typed on Thursday reaches the statement on Sunday."""
    from app.models import BankLine
    from app.utils import bank_import

    _movement(tilled, 800, when=local_today() - timedelta(days=2))
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Transfer,800.00\n")
    with tilled["app"].app_context():
        assert len(bank_import.candidates(BankLine.query.first())) == 1


def test_a_movement_far_outside_the_window_does_not(tilled):
    from app.models import BankLine
    from app.utils import bank_import

    _movement(tilled, 800, when=local_today() - timedelta(days=40))
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Transfer,800.00\n")
    with tilled["app"].app_context():
        assert bank_import.candidates(BankLine.query.first()) == []


def test_the_nearest_date_is_offered_first(tilled):
    from app.models import BankLine
    from app.utils import bank_import

    _movement(tilled, 300, when=local_today() - timedelta(days=3))
    near = _movement(tilled, 300, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit,300.00\n")
    with tilled["app"].app_context():
        found = bank_import.candidates(BankLine.query.first())
        assert found[0]["id"] == near


def test_auto_match_takes_the_only_answer(tilled):
    from app.models import BankLine
    from app.models import CashAccount
    from app.utils import bank_import

    mv_id = _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1975.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        assert bank_import.auto_match(account) == 1
        line = BankLine.query.first()
        assert line.status == "matched"
        assert line.link == ("mv_deposit", mv_id)


def test_auto_match_refuses_to_guess_between_two(tilled):
    """The rule the whole feature rests on. Two identical amounts is a
    question for a person, and picking one would let the screen report
    "reconciled" while pointing at the wrong movement."""
    from app.models import BankLine, CashAccount
    from app.utils import bank_import

    _movement(tilled, 500, when=local_today())
    _movement(tilled, 500, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit,500.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        assert bank_import.auto_match(account) == 0
        assert BankLine.query.first().status == "unmatched"


def test_two_lines_cannot_both_claim_one_movement(tilled):
    """Otherwise a statement with two 500s and a program with one would
    reconcile to nothing outstanding."""
    from app.models import BankLine, CashAccount
    from app.utils import bank_import

    _movement(tilled, 500, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit A,500.00\n"
            f"{date.today()},Deposit B,500.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        assert bank_import.auto_match(account) == 1
        statuses = sorted(ln.status for ln in BankLine.query.all())
        assert statuses == ["matched", "unmatched"]


def test_matching_the_same_movement_by_hand_is_refused(tilled):
    from app.models import BankLine
    from app.utils import bank_import

    mv_id = _movement(tilled, 500, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit A,500.00\n"
            f"{date.today()},Deposit B,500.00\n")
    with tilled["app"].app_context():
        first, second = BankLine.query.order_by(BankLine.id).all()
        bank_import.match(first, "mv_deposit", mv_id)
        with pytest.raises(bank_import.StatementError) as exc:
            bank_import.match(second, "mv_deposit", mv_id)
        assert "movement_taken" in str(exc.value)


def test_a_match_can_always_be_undone(tilled):
    """A wrong match that could not be undone would be a permanent lie about
    which payment reached the bank."""
    from app.models import BankLine
    from app.utils import bank_import

    mv_id = _movement(tilled, 500, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit,500.00\n")
    with tilled["app"].app_context():
        line = BankLine.query.first()
        bank_import.match(line, "mv_deposit", mv_id)
        bank_import.unmatch(line)
        assert line.status == "unmatched" and line.link is None


def test_setting_a_line_aside_needs_words(tilled):
    """"Ignored" on its own tells the next person nothing."""
    from app.models import BankLine
    from app.utils import bank_import

    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Loan instalment,-3000.00\n")
    with tilled["app"].app_context():
        line = BankLine.query.first()
        with pytest.raises(bank_import.StatementError) as exc:
            bank_import.ignore(line, "   ")
        assert "need_note" in str(exc.value)
        bank_import.ignore(line, "قسط قرض — مش من حسابات العيادة")
        assert line.status == "ignored" and line.note


def test_nothing_is_posted_to_the_ledger_by_any_of_this(tilled):
    """A line with no match is a question. The answer is sometimes "record the
    bank charge" and sometimes "the bank made a mistake" — the program is in no
    position to choose."""
    from app.models import BankLine, CashAccount, JournalEntry
    from app.utils import bank_import

    _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1975.00\n"
            f"{date.today()},Mystery charge,-40.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        # Counted after importing, so what is measured is what reconciling
        # does — matching, auto-matching and setting aside, all of it.
        before = JournalEntry.query.count()
        bank_import.auto_match(account)
        bank_import.ignore(BankLine.query.filter(BankLine.amount < 0).first(),
                           "مصروف بنكي هنسجّله بنفسنا")
        assert JournalEntry.query.count() == before


# ---------------------------------------------------- both sides at once ---
def test_a_line_the_program_never_recorded_is_named(tilled):
    from app.models import CashAccount
    from app.utils import bank_import

    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Bank charge,-25.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        result = bank_import.reconciliation(account)
        assert len(result["unmatched"]) == 1
        assert result["unmatched"][0].options == []


def test_a_movement_the_statement_never_mentioned_is_named(tilled):
    """The more alarming side: the clinic recorded money that never arrived."""
    from app.models import CashAccount
    from app.utils import bank_import

    _movement(tilled, 900, when=local_today() - timedelta(days=1))
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Bank charge,-25.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        result = bank_import.reconciliation(account)
        assert [r["amount"] for r in result["missing"]] == [900.0]


def test_a_movement_after_the_last_statement_line_is_not_called_missing(tilled):
    """It has not had its chance to arrive yet, and crying wolf on every
    reconciliation is how people stop reading it."""
    from app.models import CashAccount
    from app.utils import bank_import

    _movement(tilled, 900, when=local_today() + timedelta(days=5))
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Bank charge,-25.00\n")
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        assert bank_import.reconciliation(account)["missing"] == []


def test_a_till_with_no_statement_yet_calls_nothing_missing(tilled):
    from app.models import CashAccount
    from app.utils import bank_import

    _movement(tilled, 900, when=local_today())
    with tilled["app"].app_context():
        account = CashAccount.query.filter_by(code="1020").first()
        result = bank_import.reconciliation(account)
        assert result["missing"] == [] and result["lines"] == []


def test_a_line_set_aside_is_out_of_the_statement_total(tilled):
    from app.models import BankLine, CashAccount
    from app.utils import bank_import

    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Deposit,1000.00\n"
            f"{date.today()},Loan instalment,-3000.00\n")
    with tilled["app"].app_context():
        loan = BankLine.query.filter(BankLine.amount < 0).first()
        bank_import.ignore(loan, "قسط قرض")
        account = CashAccount.query.filter_by(code="1020").first()
        assert bank_import.reconciliation(account)["statement_total"] == 1000.0


# -------------------------------------------------------- on the screen ----
def test_the_screen_opens_for_a_bank_till(tilled):
    body = tilled["acct"].get(
        f"/finance/tills/{_bank_id(tilled)}/reconcile").get_data(as_text=True)
    assert "مطابقة كشف البنك" in body


def test_the_screen_does_not_exist_for_a_cash_drawer(tilled):
    """A drawer has no statement — it has a count, on the other screen."""
    cash = _bank_id(tilled, "1010")
    assert tilled["acct"].get(
        f"/finance/tills/{cash}/reconcile").status_code == 404


def test_reception_cannot_reconcile(tilled):
    """Collecting money and reconciling the bank are different jobs."""
    assert tilled["desk"].get(
        f"/finance/tills/{_bank_id(tilled)}/reconcile").status_code == 403


def test_a_statement_can_be_uploaded_through_the_form(tilled):
    from app.models import BankLine

    bank = _bank_id(tilled)
    tilled["acct"].post(
        f"/finance/tills/{bank}/reconcile/import",
        data={"statement": (io.BytesIO(_TWO_LINES.encode()), "s.csv")},
        content_type="multipart/form-data", follow_redirects=True)
    with tilled["app"].app_context():
        assert BankLine.query.count() == 2


def test_a_statement_the_parser_cannot_read_says_which_column_is_missing(tilled):
    bank = _bank_id(tilled)
    body = tilled["acct"].post(
        f"/finance/tills/{bank}/reconcile/import",
        data={"statement": (io.BytesIO(b"Notes,Who\nx,y\n"), "s.csv")},
        content_type="multipart/form-data",
        follow_redirects=True).get_data(as_text=True)
    assert "مالقيتش عمود تاريخ" in body


def test_uploading_nothing_says_so(tilled):
    bank = _bank_id(tilled)
    body = tilled["acct"].post(
        f"/finance/tills/{bank}/reconcile/import", data={},
        content_type="multipart/form-data",
        follow_redirects=True).get_data(as_text=True)
    assert "اختار ملف الأول" in body


def test_the_auto_button_reports_what_it_matched(tilled):
    bank = _bank_id(tilled)
    _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1975.00\n")
    body = tilled["acct"].post(f"/finance/tills/{bank}/reconcile/auto",
                               follow_redirects=True).get_data(as_text=True)
    assert "اتطابق 1 سطر" in body


def test_a_line_can_be_matched_from_the_screen(tilled):
    from app.models import BankLine

    mv_id = _movement(tilled, 1975, when=local_today())
    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},POS settlement,1975.00\n")
    with tilled["app"].app_context():
        line_id = BankLine.query.first().id
    tilled["acct"].post(f"/finance/bank-line/{line_id}/match",
                        data={"movement": f"mv_deposit:{mv_id}"},
                        follow_redirects=True)
    with tilled["app"].app_context():
        assert tilled["db"].session.get(BankLine, line_id).status == "matched"


def test_an_unknown_action_on_a_line_is_a_404(tilled):
    from app.models import BankLine

    _import(tilled, "Date,Description,Amount\n"
            f"{date.today()},Charge,-25.00\n")
    with tilled["app"].app_context():
        line_id = BankLine.query.first().id
    assert tilled["acct"].post(
        f"/finance/bank-line/{line_id}/burn").status_code == 404


def test_the_reconcile_link_shows_on_a_bank_till_and_not_on_a_drawer(tilled):
    bank = tilled["acct"].get(
        f"/finance/tills/{_bank_id(tilled)}").get_data(as_text=True)
    cash = tilled["acct"].get(
        f"/finance/tills/{_bank_id(tilled, '1010')}").get_data(as_text=True)
    assert "مطابقة الكشف" in bank
    assert "مطابقة الكشف" not in cash
