"""Every shilling in the books — the journal entry that failed in silence.

The till posts to the journal after the bill is saved, and a posting that
fails is rolled back so a family is never refused over bookkeeping. Right
for the family. But it failed **without a trace**: the revenue report reads
invoices, the profit-and-loss reads the journal, and the two drifted apart by
exactly what went missing, with nobody told why.

And it did fail, under exactly the load a clinic has at its busiest: entry
numbers were "the last one, plus one", read before the lock was taken, so
two cashiers collecting at once got the same entry number and the second
entry was refused — and swallowed.

These tests hold the three answers:

* entry numbers are taken under the lock, so that failure cannot happen;
* a failure that does happen is written down (``ledger.failed``);
* the journal screen lists every document the ledger is missing, and posts
  them again — safely, as often as it is pressed.
"""
import threading
import time
from datetime import date, datetime, timedelta

import pytest


def _invoice(clinic, amount=200, when=None, pay=True):
    from app.models import Invoice, InvoiceItem, Payment
    from app.utils.finance import generate_invoice_number

    with clinic["app"].app_context():
        db = clinic["db"]
        inv = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=clinic["ids"]["child"],
                      created_at=when or datetime.utcnow())
        db.session.add(inv)
        db.session.flush()
        if amount:
            db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                       unit_price=amount, quantity=1))
        if pay and amount:
            db.session.add(Payment(invoice_id=inv.id, amount=amount,
                                   method="cash",
                                   paid_at=when or datetime.utcnow()))
        db.session.commit()
        return inv.id


def _post(clinic, invoice_id):
    from app.models import Invoice
    from app.utils.billing import post_to_ledger

    with clinic["app"].app_context():
        post_to_ledger("invoice", clinic["db"].session.get(Invoice, invoice_id))


@pytest.fixture()
def books(clinic):
    """A clinic whose ledger is running: the chart is seeded and one bill
    has been posted the ordinary way."""
    from app.utils.accounting import ensure_seeded

    with clinic["app"].app_context():
        ensure_seeded()
    first = _invoice(clinic, when=datetime.utcnow() - timedelta(hours=1))
    _post(clinic, first)
    clinic["ids"]["first_invoice"] = first
    return clinic


def _gaps(clinic):
    from app.utils import ledger_gaps

    with clinic["app"].app_context():
        return {k: [o.id for o in v] for k, v in ledger_gaps.missing().items()}


def _entries(clinic, kind, source_id):
    from app.models import JournalEntry

    with clinic["app"].app_context():
        return JournalEntry.query.filter_by(source_type=kind,
                                            source_id=source_id).count()


# ------------------------------------------------ nothing to find ----
def test_a_ledger_that_never_started_is_missing_nothing(clinic):
    _invoice(clinic)
    assert _gaps(clinic) == {"invoice": [], "payment": [], "expense": []}


def test_a_ledger_posted_as_it_should_be_is_missing_nothing(books):
    assert _gaps(books) == {"invoice": [], "payment": [], "expense": []}


# ------------------------------------------------ a posting that failed ----
def test_a_failed_posting_is_written_down_and_listed(books, monkeypatch):
    from app.models import ActivityLog
    from app.utils import accounting

    def broken(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(accounting, "post_invoice", broken)
    later = _invoice(books)
    _post(books, later)                       # the bill is saved; this fails
    with books["app"].app_context():
        row = ActivityLog.query.filter_by(action="ledger.failed").one()
        assert row.entity == "invoice" and row.entity_id == later
        assert "database is locked" in row.detail
    gaps = _gaps(books)
    assert gaps["invoice"] == [later]
    # Its payment failed with it: posting stopped at the invoice.
    assert len(gaps["payment"]) == 1


def test_posting_again_closes_the_gap_and_never_doubles(books, monkeypatch):
    from app.utils import accounting, ledger_gaps

    real = accounting.post_invoice
    monkeypatch.setattr(accounting, "post_invoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    later = _invoice(books)
    _post(books, later)
    monkeypatch.setattr(accounting, "post_invoice", real)
    with books["app"].app_context():
        assert ledger_gaps.repair() == (2, 0)
        assert ledger_gaps.repair() == (0, 0)
    assert _gaps(books) == {"invoice": [], "payment": [], "expense": []}
    assert _entries(books, "invoice", later) == 1


def test_one_that_still_fails_stays_on_the_list(books, monkeypatch):
    from app.utils import accounting, ledger_gaps

    monkeypatch.setattr(accounting, "post_invoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    later = _invoice(books, pay=False)
    _post(books, later)
    with books["app"].app_context():
        posted, left = ledger_gaps.repair()
    assert (posted, left) == (0, 1)
    assert _gaps(books)["invoice"] == [later]


# ------------------------------------------------ what is not a gap ----
def test_before_the_ledger_started_is_not_missing(books):
    old = _invoice(books, when=datetime.utcnow() - timedelta(days=30))
    assert old not in _gaps(books)["invoice"]


def test_a_bill_of_nothing_is_not_missing(books):
    empty = _invoice(books, amount=0)
    assert empty not in _gaps(books)["invoice"]


def test_a_payment_of_nothing_is_not_missing(books):
    from app.models import Payment

    with books["app"].app_context():
        row = Payment(invoice_id=books["ids"]["first_invoice"], amount=0,
                      method="cash")
        books["db"].session.add(row)
        books["db"].session.commit()
        zero = row.id
    assert zero not in _gaps(books)["payment"]


def test_a_repost_that_fails_is_written_down_too(books, monkeypatch):
    from app.models import ActivityLog
    from app.utils import accounting, ledger_gaps

    monkeypatch.setattr(accounting, "post_invoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    later = _invoice(books, pay=False)
    _post(books, later)
    with books["app"].app_context():
        ledger_gaps.repair()
        assert ActivityLog.query.filter_by(action="ledger.failed",
                                           entity_id=later).count() == 2


# ------------------------------------------------ the screen ----
def test_the_journal_shows_the_gap_and_the_owner_closes_it(books, monkeypatch):
    from app.utils import accounting

    real = accounting.post_invoice
    monkeypatch.setattr(accounting, "post_invoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    later = _invoice(books)
    _post(books, later)
    monkeypatch.setattr(accounting, "post_invoice", real)
    boss = books["sign_in"]("boss")
    page = boss.get("/finance/journal").get_data(as_text=True)
    assert 'data-ledger-gaps="2"' in page
    assert 'data-gap-kind="invoice"' in page
    boss.post("/finance/journal/repair")
    page = boss.get("/finance/journal").get_data(as_text=True)
    assert "data-ledger-gaps" not in page


def test_only_an_administrator_posts_to_the_ledger(books, monkeypatch):
    from app.utils import accounting

    monkeypatch.setattr(accounting, "post_invoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    later = _invoice(books, pay=False)
    _post(books, later)
    monkeypatch.undo()
    reply = books["sign_in"]("acct").post("/finance/journal/repair")
    assert reply.status_code == 403
    assert _gaps(books)["invoice"] == [later]


# ------------------------------------------------ the cause, closed ----
def test_the_entry_number_ignores_tails_that_are_not_numbers(books):
    from app.models import JournalEntry
    from app.utils.accounting import _je_number

    with books["app"].app_context():
        db = books["db"]
        for number in ("JE-000050", "JE-7X", "JE-ABC"):
            db.session.add(JournalEntry(entry_number=number,
                                        entry_date=date.today()))
        db.session.commit()
        assert _je_number() == "JE-000051"


def test_two_cashiers_at_once_both_reach_the_ledger(tmp_path, monkeypatch):
    """The race that lost entries, on a real file: the first posting holds
    its entry number uncommitted while the second posts through the till's
    own path. Numbered under the lock, the second waits and takes the next —
    nothing refused, nothing swallowed."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/books.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.utils.accounting import ensure_seeded
        ensure_seeded()

    first_numbered = threading.Event()
    numbers, errors = [], []

    def first():
        try:
            with app.app_context():
                from app.models import JournalEntry
                from app.utils.accounting import _je_number
                from app.utils.sequences import claim

                entry = JournalEntry(entry_date=date.today(), memo="أول",
                                     source_type="manual", source_id=1)
                claim(entry, "entry_number", _je_number)
                numbers.append(entry.entry_number)
                first_numbered.set()
                time.sleep(0.8)          # the second arrives in this gap
                db.session.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            first_numbered.set()

    def second():
        try:
            with app.app_context():
                from app.utils.accounting import post_entry

                entry = post_entry("manual", 2, "تاني",
                                   [("1010", 100, 0, "x"), ("1030", 0, 100, "x")])
                numbers.append(entry.entry_number)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    a = threading.Thread(target=first)
    a.start()
    first_numbered.wait(5)
    b = threading.Thread(target=second)
    b.start()
    a.join(20)
    b.join(20)
    assert errors == []
    assert len(set(numbers)) == 2
