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
                appt_date=date.today(),
                appt_time=(datetime(2026, 1, 1, 9)
                           + timedelta(minutes=10 * i)).time(),
                status=["scheduled", "waiting", "done"][i % 3],
                appt_type="consultation"))
            db.session.add(Visit(patient_id=children[i % PATIENTS].id,
                                 doctor_id=doctor.id, visit_date=date.today()))

        for i in range(INVOICES):
            invoice = Invoice(invoice_number=f"INV-{i:05d}",
                              patient_id=children[i % PATIENTS].id,
                              doctor_id=doctor.id, invoice_date=date.today())
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
    return {"app": app, "db": db, "client": client}


def count_queries(busy, path):
    """How many statements one page costs."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements = []

    def record(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        resp = busy["client"].get(path, follow_redirects=True)
    finally:
        event.remove(Engine, "before_cursor_execute", record)
    assert resp.status_code == 200, f"{path} → {resp.status_code}"
    return len(statements)


# Ceilings with headroom. One query per row would blow through every one of
# them by an order of magnitude, which is the point.
@pytest.mark.parametrize("path,ceiling", [
    ("/", 40),
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
    count = count_queries(busy, path)
    assert count <= ceiling, (
        f"{path} costs {count} queries with {PATIENTS} patients / "
        f"{INVOICES} invoices on file — something is querying inside a loop")


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
