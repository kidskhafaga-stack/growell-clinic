"""Exporting a month, not the whole history.

Item 14 asked for the export section to be brought onto the pattern the rest
of the settings screens ended up on. Looking at it, the layout was the smaller
half of the problem: **there was no date range at all.**

That is the difference between a feature and a button. The only export on offer
was *everything ever*, so an accountant who wants March gets the entire history
and filters it in Excel — the clinic does the work the program was asked to do,
and does it somewhere nobody can check, on a file that also contains every
patient the clinic has ever seen.

Three things follow from adding the range, and each has a test here because
each is a way of getting it subtly wrong:

**The end of the range is inclusive.** Somebody typing 31 January means the
31st. An exclusive bound silently drops the last day of every month anybody
ever exports, and a month that is short by one day looks exactly like a month.

**The counts are counted through the same query.** A screen offering
"invoices (1,240)" beside a one-month range is saying something untrue about
the file it is about to hand over.

**And the range is in the filename**, because four files called
``invoices_export`` in a downloads folder are four files nobody can tell apart
a week later.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TODAY = date.today()
LAST_MONTH = TODAY - timedelta(days=32)


@pytest.fixture()
def ledger(clinic):
    """Rows on both sides of a boundary, so a range has something to exclude."""
    from app.models import Expense, Invoice, InvoiceItem, Patient, Visit

    with clinic["app"].app_context():
        db = clinic["db"]
        old_patient = Patient(patient_number="P-OLD", full_name="طفل قديم",
                              gender="male", date_of_birth=date(2020, 1, 1),
                              is_active=True)
        db.session.add(old_patient)
        db.session.flush()

        # `total` is summed from the lines, not stored — so an invoice worth
        # anything needs a line on it.
        for number, when, amount, status in (
                ("INV-OLD", LAST_MONTH, 100, "paid"),
                ("INV-NEW", TODAY, 200, "unpaid")):
            inv = Invoice(invoice_number=number, patient_id=old_patient.id,
                          invoice_date=when, status=status)
            db.session.add(inv)
            db.session.flush()
            db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                       quantity=1, unit_price=amount))

        db.session.add_all([
            Expense(expense_date=LAST_MONTH, category="rent",
                    description="إيجار قديم", amount=1000),
            Expense(expense_date=TODAY, category="rent",
                    description="إيجار الشهر", amount=1200),
            Visit(patient_id=old_patient.id, doctor_id=clinic["ids"]["doctor"],
                  visit_date=LAST_MONTH, status="closed"),
        ])
        db.session.commit()
    return clinic


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _rows(app, kind, start=None, end=None):
    from app.utils.export import DATASETS

    with app.app_context():
        return list(DATASETS[kind][1](start, end))


def _csv(client, kind, **params):
    params.setdefault("fmt", "csv")
    reply = client.get(f"/settings/data/export/{kind}", query_string=params)
    assert reply.status_code == 200
    return reply


# ------------------------------------------------------------- the range ---
def test_a_range_actually_narrows_the_export(ledger):
    everything = _rows(ledger["app"], "invoices")
    march = _rows(ledger["app"], "invoices", TODAY, TODAY)
    assert len(everything) == 2
    assert [r["invoice_no"] for r in march] == ["INV-NEW"]


def test_the_last_day_of_the_range_is_included(ledger):
    """The one that would pass a careless test and lose a day of every month.
    A month short by one day looks exactly like a month."""
    rows = _rows(ledger["app"], "expenses", LAST_MONTH, TODAY)
    assert len(rows) == 2, "the row dated on the end boundary was dropped"

    only_today = _rows(ledger["app"], "expenses", TODAY, TODAY)
    assert [r["description"] for r in only_today] == ["إيجار الشهر"]


def test_a_datetime_column_still_includes_its_last_day(ledger, clinic):
    """Payments are stamped with a *time*, so "<= the end date" compares
    against midnight and throws away everything after it — a whole day's
    takings, on the day most likely to be the end of the range."""
    from app.models import Invoice, Payment

    with ledger["app"].app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-NEW").first()
        ledger["db"].session.add(Payment(
            invoice_id=inv.id, amount=200, method="cash", kind="payment",
            paid_at=datetime.combine(TODAY, datetime.min.time().replace(hour=16))))
        ledger["db"].session.commit()

    rows = _rows(ledger["app"], "payments", TODAY, TODAY)
    assert len(rows) == 1, "an afternoon payment fell outside its own day"


def test_no_range_means_everything(ledger):
    assert len(_rows(ledger["app"], "invoices")) == 2
    assert len(_rows(ledger["app"], "expenses")) == 2


def test_only_one_end_of_the_range_is_allowed(ledger):
    """"Everything since January" is a real question and should not require
    inventing an end date."""
    since = _rows(ledger["app"], "invoices", TODAY, None)
    assert [r["invoice_no"] for r in since] == ["INV-NEW"]
    until = _rows(ledger["app"], "invoices", None, LAST_MONTH)
    assert [r["invoice_no"] for r in until] == ["INV-OLD"]


def test_a_mistyped_date_falls_back_to_everything(ledger, boss):
    """A download is not worth an error page. A range that cannot be read is
    no range, and the screen still works."""
    from app.utils.export import parse_date

    assert parse_date("not-a-date") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert boss.get("/settings/data",
                    query_string={"from": "yesterday"}).status_code == 200


# ------------------------------------------------------------- the counts --
def test_the_count_matches_the_file(ledger):
    """A screen promising one number and handing over a file with a different
    one in it is worse than a screen with no number."""
    from app.utils.export import dataset_count

    with ledger["app"].app_context():
        for start, end in ((None, None), (TODAY, TODAY), (LAST_MONTH, TODAY)):
            for kind in ("invoices", "expenses", "patients", "visits"):
                assert dataset_count(kind, start, end) == len(
                    _rows(ledger["app"], kind, start, end)), (kind, start, end)


def test_the_screen_counts_within_the_range(ledger, boss):
    body = boss.get("/settings/data",
                    query_string={"from": TODAY.isoformat(),
                                  "to": TODAY.isoformat()}).get_data(as_text=True)
    assert "INV-OLD" not in body
    # One invoice today, not two.
    assert body.count(">1<") >= 1


def test_an_unknown_dataset_is_still_refused(ledger):
    from app.utils.export import dataset_count, export_response

    with ledger["app"].test_request_context("/"):
        assert dataset_count("nonsense") is None
        assert export_response("nonsense") is None


# ------------------------------------------------------------ the download -
def test_the_range_is_in_the_filename(ledger, boss):
    """Four files called invoices_export in a downloads folder are four files
    nobody can tell apart a week later."""
    reply = _csv(boss, "invoices", **{"from": TODAY.isoformat(),
                                      "to": TODAY.isoformat()})
    disposition = reply.headers["Content-Disposition"]
    assert TODAY.isoformat() in disposition
    assert "invoices" in disposition


def test_an_unranged_download_says_so_in_its_name(ledger, boss):
    reply = _csv(boss, "invoices")
    assert "all" in reply.headers["Content-Disposition"]


def test_the_csv_still_opens_in_excel_in_arabic(ledger, boss):
    """The BOM is the whole reason Arabic isn't mojibake when the file is
    double-clicked, and it is the kind of thing a rewrite drops."""
    body = _csv(boss, "expenses").get_data(as_text=True)
    assert body.startswith("﻿")
    assert "إيجار الشهر" in body


def test_the_downloaded_rows_respect_the_range(ledger, boss):
    body = _csv(boss, "expenses", **{"from": TODAY.isoformat()}).get_data(as_text=True)
    assert "إيجار الشهر" in body
    assert "إيجار قديم" not in body


def test_every_dataset_downloads(ledger, boss):
    from app.utils.export import DATASETS

    for kind in DATASETS:
        assert _csv(boss, kind).status_code == 200


# ------------------------------------------------------- what is exported --
def test_a_refund_leaves_as_a_negative_number(ledger):
    """Money out with the same sign as money in is how a day's takings come
    out too high in somebody's spreadsheet — and the spreadsheet is the thing
    that gets believed."""
    from app.models import Invoice, Payment

    with ledger["app"].app_context():
        inv = Invoice.query.filter_by(invoice_number="INV-NEW").first()
        ledger["db"].session.add_all([
            Payment(invoice_id=inv.id, amount=200, method="cash",
                    kind="payment", paid_at=datetime.utcnow()),
            Payment(invoice_id=inv.id, amount=50, method="cash",
                    kind="refund", paid_at=datetime.utcnow()),
        ])
        ledger["db"].session.commit()

    rows = _rows(ledger["app"], "payments")
    amounts = sorted(r["amount"] for r in rows)
    assert amounts == [-50, 200]


def test_the_clinical_note_does_not_leave_in_a_spreadsheet(ledger):
    """A visits export is for counting visits. The complaint text belongs in
    the file, not in a CSV that then lives in somebody's downloads folder."""
    from app.utils.export import DATASETS

    headers = DATASETS["visits"][0]
    for leaked in ("chief_complaint", "clinical_exam", "plan", "notes"):
        assert leaked not in headers, leaked


def test_the_export_is_written_to_the_activity_log_with_its_range(ledger, boss):
    """"Somebody exported the invoices" and "somebody exported March" are
    different events to be reading about afterwards."""
    from app.models import ActivityLog

    _csv(boss, "patients", **{"from": TODAY.isoformat(), "to": TODAY.isoformat()})
    with ledger["app"].app_context():
        row = (ActivityLog.query.filter_by(action="data.export")
               .order_by(ActivityLog.id.desc()).first())
        assert row is not None
        assert "patients" in row.detail
        assert TODAY.isoformat() in row.detail


# ------------------------------------------------------------- the screen --
def test_the_screen_offers_the_datasets_a_clinic_asks_for(ledger, boss):
    """Four datasets covered patients, invoices, appointments and doses.
    Nobody could export what was collected, what was spent, or how many
    visits happened — which is most of what an accountant asks for."""
    from app.utils.export import DATASETS

    for kind in ("visits", "payments", "expenses"):
        assert kind in DATASETS, kind
    assert boss.get("/settings/data").status_code == 200


def test_the_range_survives_onto_the_download_links(ledger, boss):
    """A range that has to be re-entered after every download is a range
    nobody uses twice."""
    body = boss.get("/settings/data",
                    query_string={"from": TODAY.isoformat()}).get_data(as_text=True)
    assert f"from={TODAY.isoformat()}" in body
