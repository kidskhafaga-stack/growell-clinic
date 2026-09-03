"""How the clinic behaves once it has a couple of years of records in it.

Every screen here was fast on a laptop with fifty patients on file. The
problem only appears at the size a real clinic reaches after two years — and
it appears at the worst possible moment, which is when the waiting room is
full and everybody is using the program at once.

What is measured is **queries**, not milliseconds. A stopwatch on a shared CI
runner measures the runner; the query count measures the code, and the query
count is what was actually wrong: the appointment board asked the database a
thousand and thirty-four times to draw sixty rows.

The numbers below are ceilings with room in them, not targets. They exist to
fail when somebody reintroduces a query inside a loop, which is the one
performance mistake that is invisible in development and fatal in a clinic.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402

# Small enough to build in a second, big enough that one-query-per-row shows
# up as a number nobody can miss.
PATIENTS = 120
APPOINTMENTS = 40
INVOICES = 120


@pytest.fixture()
def busy(tmp_path, monkeypatch):
    """A clinic with a working day's worth of rows in it."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/perf.db")
    app = create_app("testing")
    assert str(tmp_path) in app.config["SQLALCHEMY_DATABASE_URI"]

    with app.app_context():
        db.create_all()
        from app.models import (Appointment, Invoice, InvoiceItem, Patient,
                                Payment, Service, User, Visit)

        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        doctor = User(username="doc", full_name="دكتور", role="doctor",
                      is_active=True)
        doctor.set_password("secret")
        db.session.add_all([boss, doctor])
        db.session.flush()
        service = Service(name="كشف", category="consultation", price=200,
                          commission_type="percent", commission_value=40,
                          is_active=True)
        db.session.add(service)

        children = []
        for i in range(PATIENTS):
            child = Patient(patient_number=f"P{i:05d}", full_name=f"طفل {i}",
                            gender="male" if i % 2 else "female",
                            date_of_birth=date(2022, 1, 1) + timedelta(days=i),
                            is_active=True)
            db.session.add(child)
            children.append(child)
        db.session.flush()

        for i in range(APPOINTMENTS):
            db.session.add(Appointment(
                patient_id=children[i % PATIENTS].id, doctor_id=doctor.id,
                appt_date=local_today(),
                appt_time=(datetime(2026, 1, 1, 9)
                           + timedelta(minutes=10 * i)).time(),
                status=["scheduled", "waiting", "done"][i % 3],
                appt_type="consultation"))
            db.session.add(Visit(patient_id=children[i % PATIENTS].id,
                                 doctor_id=doctor.id, visit_date=local_today()))

        for i in range(INVOICES):
            invoice = Invoice(invoice_number=f"INV-{i:05d}",
                              patient_id=children[i % PATIENTS].id,
                              doctor_id=doctor.id, invoice_date=local_today())
            db.session.add(invoice)
            db.session.flush()
            invoice.items.append(InvoiceItem(description="كشف", unit_price=200,
                                             quantity=1,
                                             service_id=service.id,
                                             commission_amount=80))
            if i % 2:
                invoice.payments.append(Payment(amount=200, method="cash"))
            invoice.recalc_status()
        db.session.commit()

    client = app.test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)

    # The bell is held warm for the length of the test, deliberately.
    #
    # Its feed is worked out live and kept in a *process-level* cache for
    # ninety seconds, so what a page costs depends on how long ago somebody
    # else asked — sixteen queries more when the ninety seconds happen to run
    # out inside the request being measured. That made this file report a
    # different number on the build machine than on the laptop, and the
    # difference was the clock, not the code. The recompute is a fixed cost
    # and it has a ceiling of its own below; the per-row ceilings measure the
    # page without it, from a state that is the same on every machine.
    from app.utils import notifications
    monkeypatch.setattr(notifications, "_TTL", 10 ** 6)
    notifications.invalidate()
    with app.app_context():
        notifications._all()
    try:
        yield {"app": app, "db": db, "client": client}
    finally:
        # Nothing after this test inherits a feed computed against a database
        # that no longer exists.
        notifications.invalidate()


def statements_for(busy, path):
    """Every statement one page costs, in the order it was issued."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements = []

    def record(conn, cursor, statement, params, context, many):
        # The parameters travel with the statement because the interesting
        # repetition is often *the same query with a different key* — fifteen
        # reads of the settings table are one shape and fifteen different
        # questions, and only the parameters tell them apart.
        statements.append((statement, params))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        resp = busy["client"].get(path, follow_redirects=True)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert resp.status_code == 200, f"{path} → {resp.status_code}"
    return statements


def count_queries(busy, path):
    """How many statements one page costs."""
    return len(statements_for(busy, path))


def what_repeated(statements, top=6):
    """The statements a failing page asked most, shortened to their shape.

    A ceiling that fails on a build machine and passes on the laptop used to
    report one number and nothing else, which is the least useful half of what
    the listener already had in its hands. The whole point of the ceiling is
    that a query is running inside a loop; naming it costs nothing and is the
    first thing anybody reading the failure needs.
    """
    from collections import Counter

    counts = Counter()
    examples = {}
    for sql, params in statements:
        shape = " ".join(sql.split())[:90]
        counts[shape] += 1
        examples.setdefault(shape, []).append(params)
    lines = []
    for shape, n in counts.most_common(top):
        if n < 2:
            continue
        # Grouped by the statement and *not* by its parameters, because a
        # query inside a loop is the same statement with a different id every
        # time — grouping by both would report it as a hundred separate
        # queries, which is the one thing this must not say. The parameters
        # come back as examples instead: they are what tells nineteen reads of
        # the settings table apart from nineteen reads of the same row.
        shown = ", ".join(repr(p) for p in examples[shape][:3])
        lines.append(f"  ×{n}  {shape}\n        e.g. {shown[:80]}")
    return "\n".join(lines) or "  (nothing repeated — every query differs)"


# Ceilings with headroom. One query per row would blow through every one of
# them by an order of magnitude, which is the point.
#
# The home page went from 40 to 41 when the first **opt-in** module arrived.
# That one is not slack: a module that is off until somebody switches it on
# cannot know it is off without reading whether anybody did, and every page
# draws the sidebar. It is one constant read, not a read per row — which is
# the distinction these numbers exist to hold. The same change made the
# switches cheaper everywhere it matters: a configured clinic asked one key
# per module and now asks one query for all of them (see
# `test_the_module_switches_are_one_query`).
@pytest.mark.parametrize("path,ceiling", [
    ("/", 41),
    ("/patients/", 60),
    ("/appointments/", 90),
    ("/visits/", 40),
    ("/finance/invoices", 50),
    ("/finance/cashier", 90),
    ("/finance/", 40),
    ("/inventory/", 40),
    ("/reports/", 40),
    ("/messages/", 40),
    ("/growth/", 40),
    ("/prescriptions/drugs", 40),
])
def test_a_screen_does_not_query_once_per_row(busy, path, ceiling):
    statements = statements_for(busy, path)
    assert len(statements) <= ceiling, (
        f"{path} costs {len(statements)} queries with {PATIENTS} patients / "
        f"{INVOICES} invoices on file — something is querying inside a loop."
        f"\nMost repeated:\n{what_repeated(statements)}")


def test_the_bell_recomputing_is_a_fixed_cost(busy):
    """What the page costs on the request that rebuilds the notification feed.

    Every ninety seconds one unlucky visitor pays for the whole feed — vaccines
    due, stock running low, unpaid invoices, birthdays this week. That is a
    fair trade only while the rebuild is a *constant*: it scans whole tables
    and counts in Python, and the moment one of those scans becomes a query
    per patient it is 120 queries landing on somebody's dashboard with no
    warning, on the screen the program opens to.

    Measured cold on purpose, which is the opposite of every other ceiling in
    this file.
    """
    from app.utils import notifications

    notifications.invalidate()
    statements = statements_for(busy, "/")
    assert len(statements) <= 70, (
        f"the dashboard costs {len(statements)} queries on the request that "
        f"rebuilds the bell, with {PATIENTS} patients on file — the rebuild "
        f"is meant to be a fixed number of table reads."
        f"\nMost repeated:\n{what_repeated(statements)}")


def test_the_settings_are_read_once_per_request(busy):
    """Setting.get() is called from templates, decorators and pricing, so it
    used to fetch the same handful of rows hundreds of times to draw one
    page. It is remembered for the length of a request."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements = []

    def record(conn, cursor, statement, params, context, many):
        if "FROM settings" in statement:
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        busy["client"].get("/finance/cashier", follow_redirects=True)
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert len(statements) <= 25, (
        f"{len(statements)} settings queries for one page")


def test_the_same_setting_is_not_fetched_twice(busy):
    from app.models import Setting

    with busy["app"].test_request_context("/"):
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        hits = []

        def record(conn, cursor, statement, params, context, many):
            if "FROM settings" in statement:
                hits.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            for _ in range(10):
                Setting.get("clinic_name")
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert len(hits) == 1, f"asked {len(hits)} times for one setting"


def test_a_setting_just_saved_reads_back_as_saved(busy):
    """Remembering it for the request must not hide a write made in the same
    request — a settings screen has to show what it just saved."""
    from app.models import Setting

    with busy["app"].test_request_context("/"):
        assert Setting.get("clinic_motto", "none") == "none"
        Setting.set("clinic_motto", "أطفالنا أمانة")
        busy["db"].session.flush()
        assert Setting.get("clinic_motto") == "أطفالنا أمانة"


def test_nothing_is_remembered_between_requests(busy):
    """The memory lasts one request. Anything longer and two people editing
    the clinic's settings would see each other's stale values."""
    from app.models import Setting

    with busy["app"].test_request_context("/"):
        Setting.set("clinic_motto", "الأولى")
        busy["db"].session.commit()

    with busy["app"].test_request_context("/"):
        Setting.set("clinic_motto", "التانية")
        busy["db"].session.commit()

    with busy["app"].test_request_context("/"):
        assert Setting.get("clinic_motto") == "التانية"


def test_the_permission_lookup_is_not_repeated_per_row(busy):
    """Every permission check on every row of every list asks which role the
    user has."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements = []

    def record(conn, cursor, statement, params, context, many):
        if "FROM roles" in statement:
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        busy["client"].get("/appointments/", follow_redirects=True)
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert len(statements) <= 5, f"{len(statements)} role lookups for one page"


def test_listing_invoices_does_not_load_each_ones_lines(busy):
    """An invoice's total is summed in Python from its lines and payments, so
    a list of invoices showing money is two lazy loads per row unless they
    are loaded up front."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements = []

    def record(conn, cursor, statement, params, context, many):
        if "FROM invoice_items" in statement or "FROM payments" in statement:
            statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        busy["client"].get("/finance/invoices", follow_redirects=True)
    finally:
        event.remove(Engine, "before_cursor_execute", record)

    assert len(statements) <= 6, (
        f"{len(statements)} line/payment queries — one per invoice on the page")


def test_the_live_poll_stays_cheap(busy):
    """Every open screen runs this every twelve seconds, all day."""
    assert count_queries(busy, "/appointments/poll") <= 12


def test_the_module_switches_are_one_query(clinic):
    """Fifteen modules, one read.

    The sidebar asks `module_enabled` about every module while drawing any
    page, and each answer used to be its own cached key — so a configured
    clinic paid one query per module on every screen in the program. They are
    one table read, and the first opt-in module is what made anybody look.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.models import Setting
    from app.models.permissions import MODULES
    from app.utils.facility import module_enabled

    with clinic["app"].app_context():
        Setting.set("facility_type", "pediatric_center")
        for module in MODULES:
            Setting.set(f"mod_enabled:{module}", "1")
        clinic["db"].session.commit()

    hits = []

    def record(conn, cursor, statement, params, context, many):
        if "settings" in statement.lower():
            hits.append(statement)

    with clinic["app"].test_request_context("/"):
        event.listen(Engine, "before_cursor_execute", record)
        try:
            for module in MODULES:
                module_enabled(module)
        finally:
            event.remove(Engine, "before_cursor_execute", record)

    # One for the group of switches, one for `is_configured`. Never one each.
    assert len(hits) <= 2, (
        f"{len(hits)} settings queries for {len(MODULES)} modules — the "
        f"switches are being read one at a time again")
