""""Today" means today in the clinic, not today in UTC.

Every moment is stored as ``datetime.utcnow()``, which is right: subtracting
one stored moment from another needs no timezone, and waiting times and
consultation lengths were correct without anybody thinking about it.

Where it stops being right is the **date a record is stamped with**, and
anywhere a screen asks what happened *today*. A visit opened at half past
midnight in Cairo is a visit today; dated from ``utcnow()`` it lands on
yesterday and stays there — in the day's list, in the month's revenue, and in
the child's history. The window is two or three hours a night, and a
paediatric clinic is exactly the kind that is open inside it.

``local_today()`` was written when the clinic timezone was added and then used
by nothing at all. It is used by everything now, and these tests are the ones
that would have failed before.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _zone(clinic, name):
    from app.models import Setting

    Setting.set("clinic_timezone", name)
    clinic["db"].session.commit()


def _far_zones():
    """One zone ahead of UTC and one behind, whichever way today is going.

    Picking a fixed pair would make this test pass or fail by the hour it was
    run — the thing the last flaky test in this suite was doing.
    """
    return "Pacific/Kiritimati", "Pacific/Midway"      # +14 and −11


# ============================================== the date on a record =========
def test_a_visit_is_dated_by_the_clinics_calendar(clinic):
    """The one that matters most: it is written down and never revisited."""
    from app.models import Visit
    from app.utils.clock import local_today

    db = clinic["db"]
    ahead, behind = _far_zones()
    with clinic["app"].app_context():
        _zone(clinic, ahead)
        visit = Visit(patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"])
        db.session.add(visit)
        db.session.commit()
        assert visit.visit_date == local_today()

        first_date = visit.visit_date

        _zone(clinic, behind)
        other = Visit(patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"])
        db.session.add(other)
        db.session.commit()
        assert other.visit_date == local_today()

        # Two calendars that disagree is the whole point: the same instant,
        # two dates, and each record carrying the one its clinic would write.
        assert first_date != other.visit_date


def test_the_two_far_zones_really_are_a_day_apart(clinic):
    """Guarding the guard: if both zones gave the same date the tests above
    would pass with the timezone ignored entirely."""
    from app.utils.clock import local_today

    ahead, behind = _far_zones()
    with clinic["app"].app_context():
        _zone(clinic, ahead)
        first = local_today()
        _zone(clinic, behind)
        second = local_today()

    # A day *or two* apart depending on the hour — the zones are 25 hours
    # apart. Asserting exactly one would make this test pass or fail by the
    # time of day, which is the fault it exists to guard against.
    assert first != second, (first, second)
    assert timedelta(days=1) <= (first - second) <= timedelta(days=2)


def test_every_dated_record_uses_the_clinics_day(clinic):
    """Nine models carried their own copy of ``utcnow().date()``. One of them
    left behind is a report that disagrees with the others for two hours a
    night, which is worse than all of them being wrong together."""
    from app.models import (Expense, GrowthRecord, Invoice, Prescription,
                            PurchaseOrder, StoreDocument, Visit)

    dated = [Visit.visit_date, Prescription.rx_date, Invoice.invoice_date,
             Expense.expense_date, GrowthRecord.record_date,
             PurchaseOrder.order_date, StoreDocument.doc_date]
    for column in dated:
        default = column.default
        assert default is not None, f"{column} has no default at all"
        name = getattr(default.arg, "__name__", "")
        assert name == "local_today", \
            f"{column} is still stamped from something else ({name})"


def test_nothing_reads_the_utc_date_any_more(clinic):
    """The sweep, pinned. ``utcnow().date()`` is allowed in exactly two
    places: inside ``local_today`` itself, as the fallback for a zone that
    cannot be resolved, and in the demo-data generator."""
    import re

    root = os.path.join(os.path.dirname(__file__), "..", "app")
    allowed = {os.path.join("app", "utils", "clock.py"),
               os.path.join("app", "utils", "demo.py")}
    offenders = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, os.path.dirname(root))
            if rel in allowed:
                continue
            with open(path, encoding="utf-8") as fh:
                if re.search(r"utcnow\(\)\.date\(\)", fh.read()):
                    offenders.append(rel)

    assert not offenders, ("these still ask UTC what day it is: "
                           + ", ".join(sorted(offenders)))


# ============================================== and it still works ==========
def test_an_unreadable_zone_still_produces_a_date(clinic):
    """Windows without ``tzdata`` cannot resolve any zone. A date is not
    optional — every caller needs *a* day — so this falls back rather than
    raising, and the settings screen is what says the zone is unreadable."""
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        _zone(clinic, "Mars/Olympus_Mons")
        assert local_today() == datetime.utcnow().date()


def test_a_clinic_that_set_no_zone_gets_the_default(clinic):
    """Most clinics never open that setting."""
    from app.utils.clock import DEFAULT_TZ, local_today, to_local

    with clinic["app"].app_context():
        _zone(clinic, "")
        assert local_today() == to_local(datetime.utcnow(), DEFAULT_TZ).date()
        assert DEFAULT_TZ == "Africa/Cairo"
