"""Money counted at night must be counted under the night it was worked.

Found while sweeping the suite under `pytest --tz=Pacific/Midway`, which forces
the clinic's clock and the server's eleven hours apart all day instead of
waiting for the three hours a night when Cairo and UTC disagree on their own.
The grep that was supposed to find this class — *look for `date.today()`* —
found nothing in `shift_rollup.py`, because there is none in it. The mixing is
one layer down: the module builds a window out of dates a person typed and
compares it against `CashierShift.opened_at`, which the database stores as
naive **UTC**.

**What that costs.** A shift opened at half past midnight in Cairo is opened at
half past ten the previous evening in UTC. Ask the report for that day and the
shift is not in it; ask for the day before and there it is, sitting in a total
that belongs to a different night's takings and a different person's record.
The report exists to answer "is this desk short", and every over and short from
the late shift was being filed against the wrong day. A paediatric clinic is
exactly the sort that is open in that window.

**It is not one report.** The same three lines — combine a local date with
`time.min`, combine with `time.max`, compare against a UTC column — are in the
cashier screen, the drawer summary it prints, and the end-of-day report. They
are all fixed together here because they are all the same sentence, and a
clinic reconciling one against another would find them disagreeing by exactly
one late shift.

The conversion already existed and was already being used correctly two files
away: `app/utils/live.py` wraps the same `datetime.combine` in `to_utc`. What
was missing was nothing clever.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# A shift the clinic worked just after midnight, and the same moment as the
# database stores it. Cairo is UTC+2 in March, so this is 22:30 the day before.
CAIRO_NIGHT = date(2026, 3, 11)
OPENED_UTC = datetime(2026, 3, 10, 22, 30)


@pytest.fixture()
def till(clinic):
    """One shift, opened after midnight in the clinic, with money in it."""
    from app.models import CashAccount, CashierShift, Invoice, Payment, Setting

    with clinic["app"].app_context():
        Setting.set("clinic_timezone", "Africa/Cairo")
        account = CashAccount(code="1010", name="الخزنة", kind="cash",
                              is_active=True)
        clinic["db"].session.add(account)
        clinic["db"].session.flush()
        shift = CashierShift(account_id=account.id,
                             opened_by=clinic["ids"]["admin"],
                             shift_number="SHIFT-2026-000001",
                             opened_at=OPENED_UTC, status="closed",
                             opening_float=0, counted_cash=100,
                             closed_at=OPENED_UTC + timedelta(hours=4))
        clinic["db"].session.add(shift)
        invoice = Invoice(invoice_number="INV-2026-000001",
                          patient_id=clinic["ids"]["child"], status="paid")
        clinic["db"].session.add(invoice)
        clinic["db"].session.flush()
        clinic["db"].session.add(Payment(invoice_id=invoice.id, amount=100,
                                         method="cash", kind="payment",
                                         paid_at=OPENED_UTC + timedelta(hours=1),
                                         shift_id=shift.id))
        clinic["db"].session.commit()
        clinic["ids"]["shift"] = shift.id
        clinic["ids"]["till"] = account.id
    return clinic


def _summary(kit, on_date):
    from app.utils.shift_rollup import summary

    with kit["app"].app_context():
        return summary(on_date, on_date)


def test_the_shift_is_found_under_the_night_it_was_worked(till):
    """The bug itself. Half past midnight in the clinic is that day's shift."""
    found = _summary(till, CAIRO_NIGHT)

    assert found["totals"]["shifts"] == 1, (
        "a shift opened after midnight in the clinic is missing from that "
        "day's reconciliation")
    assert [s.id for s in found["shifts"]] == [till["ids"]["shift"]]


def test_and_not_under_the_day_before(till):
    """The other half, and the one that makes it a *wrong* answer rather than
    a missing one: the money was being counted against the previous night."""
    found = _summary(till, CAIRO_NIGHT - timedelta(days=1))

    assert found["totals"]["shifts"] == 0, (
        "the shift is filed under the previous day, in somebody else's total")


def test_a_window_still_holds_what_it_should(till):
    """The fix must not shrink the window. A range that contains the night
    contains the shift."""
    found = _summary(till, CAIRO_NIGHT)
    from app.utils.shift_rollup import summary

    with till["app"].app_context():
        wide = summary(CAIRO_NIGHT - timedelta(days=3),
                       CAIRO_NIGHT + timedelta(days=3))
    assert wide["totals"]["shifts"] == 1
    assert found["totals"]["collected"] == wide["totals"]["collected"] == 100.0


def test_the_end_of_day_report_agrees_with_the_rollup(till):
    """Two screens, one night. They read the same shift out of the same table
    and disagreed by a whole late shift, which is how a clinic stops trusting
    both."""
    page = till["sign_in"]("boss").get(
        f"/finance/eod?date={CAIRO_NIGHT.isoformat()}").get_data(as_text=True)

    with till["app"].app_context():
        from app.models import CashierShift

        number = till["db"].session.get(
            CashierShift, till["ids"]["shift"]).shift_number or ""
    assert number and number in page, \
        "the end-of-day report for that night does not contain that night's shift"


def test_the_drawer_for_that_night_holds_its_payment(till):
    """And the money with it: a payment taken at half past one in the morning
    belongs to that morning's drawer."""
    from app.blueprints.finance.routes import _drawer_summary

    with till["app"].app_context():
        drawer = _drawer_summary(CAIRO_NIGHT)

    assert drawer["collected"] == 100.0, \
        "the night's payment is not in the night's drawer"


# ------------------------------------------- the same sentence, three files

def _financial(kit, on_date):
    """The finance report's payment-method totals for one day, read from the
    route rather than the page: `100` appears in the rendered HTML for half a
    dozen unrelated reasons, and asserting on it there passed whatever the
    code did."""
    from app.blueprints.reports import routes as reports

    with kit["app"].app_context():
        with kit["app"].test_request_context(
                f"/reports/financial?date_from={on_date.isoformat()}"
                f"&date_to={on_date.isoformat()}"):
            date_from, date_to = reports._range()
            paid_from, paid_to = reports._utc_window(date_from, date_to)
        from app.models import Payment

        return round(sum(p.amount or 0 for p in Payment.query.filter(
            Payment.paid_at >= paid_from, Payment.paid_at <= paid_to).all()), 2)


def test_the_money_report_counts_that_nights_payment_in_that_night(till):
    """The finance report had the identical three lines against `paid_at`. It
    is the report a clinic reconciles the drawer against, so the two of them
    disagreeing by a late shift is worse than either being wrong alone."""
    assert _financial(till, CAIRO_NIGHT) == 100.0, \
        "the night's payment is missing from that day's finance report"
    assert _financial(till, CAIRO_NIGHT - timedelta(days=1)) == 0.0, \
        "it is counted against the day before instead"


def test_the_export_hands_over_the_same_night(till):
    """And the raw export, which is what an accountant actually leaves with.
    An export that disagreed with the report it was exported from would be
    the worst of the three."""
    from app.utils.export import dataset_count

    with till["app"].app_context():
        night = dataset_count("payments", CAIRO_NIGHT, CAIRO_NIGHT)
        before = dataset_count("payments", CAIRO_NIGHT - timedelta(days=1),
                               CAIRO_NIGHT - timedelta(days=1))

    assert night == 1, "the night's payment is not in that night's export"
    assert before == 0, "it is exported under the day before instead"


def test_no_screen_reads_a_local_date_as_though_it_were_utc():
    """The guard, and the reason it is written as a scan rather than as five
    more cases: this bug is not a mistake anybody makes once. It is what you
    get every time somebody writes the obvious three lines — combine a date
    with `time.min`, combine with `time.max`, compare — against a column that
    holds UTC. It was in four places, written four times, by the same reflex.

    What marks a window, and separates it from the other reason to combine a
    date with a time, is the **time**: `time.min` or `time.max` means "the
    whole of this day" and is only ever the edge of a range. A combine with a
    real clock time — `appt.appt_time` — is one appointment's own moment, and
    `appt_reminder` and `waiting` both build one correctly and are not this
    test's business. So the scan looks for the min/max shape, and every one of
    those must go through `to_utc`.
    """
    import re

    roots = ("app/blueprints", "app/utils")
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    WINDOW = re.compile(r"datetime\.combine\([^)]*\b(?:datetime\.)?(?:time\.)?"
                        r"(?:min|max)(?:\.time\(\))?")
    # `series._as_dt` turns a date into a datetime for a chart's x-axis, not
    # for a query. Named so that adding to this list is a decision rather than
    # a habit.
    ALLOWED = {("app/utils/series.py", "datetime.combine(value, time.min)")}

    offenders = []
    for root in roots:
        for folder, _dirs, files in os.walk(os.path.join(here, root)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, here)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                # Comments and docstrings talk about this at length.
                text = re.sub(r"(?s)\"\"\".*?\"\"\"", "", text)
                text = re.sub(r"(?m)^\s*#.*$", "", text)
                for hit in WINDOW.finditer(text):
                    # `to_utc(` has to sit *immediately* in front of the
                    # combine, not merely somewhere nearby. Checked loosely
                    # first, and that was worth catching: with a window of
                    # ninety characters the `from app.utils.clock import
                    # to_utc` two lines above a broken call was enough to
                    # excuse it, so the guard passed on the very code it was
                    # written to reject. Whitespace is allowed between them
                    # because these calls wrap.
                    before = text[max(0, hit.start() - 200):hit.start()]
                    statement = " ".join(
                        text[hit.start():hit.start() + 90].split())
                    if before.rstrip().endswith("to_utc("):
                        continue
                    if any(rel == a and b in statement for a, b in ALLOWED):
                        continue
                    offenders.append(f"{rel}: {statement}")

    assert not offenders, (
        "these build a window from the clinic's dates and compare it against "
        "stored UTC, so everything recorded in the small hours lands on the "
        "wrong day: " + "; ".join(offenders))
