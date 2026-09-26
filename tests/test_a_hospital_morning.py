"""A hospital morning — the three screens the hospital load test found slow.

``docs/LOAD_TEST.md``, the second run: at a hospital's size the program held
together (nothing lost, nothing locked) but three screens were slow, and none
of them for a reason a clinic could have felt:

* **the clinical pharmacy's ward list** asked, for every child in a bed,
  which bed, which room and which unit — three questions a bed, a hundred and
  ninety-one for one page. Now the same handful however many beds;
* **a doctor's day board** asked the database for that doctor's personal
  grants once for every button on every row. Now once a request, and a grant
  made in the same request is still seen;
* **the day board's cards** found a day's and a month's invoices by reading
  every invoice the clinic ever wrote, because ``invoice_date`` had no index,
  and a doctor's month by walking all that doctor's appointments since the
  clinic opened. The indexes are declared on the models — and, because
  ``create_all`` never adds an index to a table that already exists, the
  schema sync now adds any plain index a model declares and a clinic's
  database lacks. It never adds a unique one.

And the new-or-returning count stopped sending the month's children back to
the database as a list: at a hospital that is tens of thousands of numbers in
one question, more than SQLite accepts.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


class _Counter:
    """Every statement sent while it is open, as text."""

    def __init__(self, app):
        self.app = app
        self.seen = []

    def _hear(self, _conn, _cursor, statement, *_rest):
        self.seen.append(statement)

    def __enter__(self):
        from sqlalchemy import event

        from app.extensions import db

        with self.app.app_context():
            self.engine = db.engine
        event.listen(self.engine, "before_cursor_execute", self._hear)
        return self

    def __exit__(self, *_exc):
        from sqlalchemy import event

        event.remove(self.engine, "before_cursor_execute", self._hear)

    def about(self, table):
        return [s for s in self.seen if f"FROM {table}" in s]


# ------------------------------------------------------------ the ward ----
@pytest.fixture()
def wards(clinic):
    """Two units, four beds, nobody in them yet."""
    from app.models import Service, Setting
    from app.models.place import Bed, Space, Unit

    db = clinic["db"]
    with clinic["app"].app_context():
        for module in ("observations", "beds", "ward", "pharmacy",
                       "prescriptions"):
            Setting.set(f"mod_enabled:{module}", "1")
        night = Service(name="ليلة داخلي", category="other", price=500)
        db.session.add(night)
        db.session.flush()
        beds = []
        for unit_name, kind in (("الداخلي", "ward"), ("الحضانة", "nicu")):
            unit = Unit(name=unit_name, kind=kind, rate_service_id=night.id)
            db.session.add(unit)
            db.session.flush()
            space = Space(unit_id=unit.id, name=f"غرفة {unit_name}",
                          kind="room")
            db.session.add(space)
            db.session.flush()
            for n in (1, 2):
                bed = Bed(space_id=space.id, name=f"{unit_name}-{n}")
                db.session.add(bed)
                db.session.flush()
                beds.append(bed.id)
        db.session.commit()
    clinic["beds"] = beds
    return clinic


def _admit(wards, n):
    """Put a child with one drug on the chart in the first ``n`` empty beds."""
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place
    from app.utils import drug_round

    db = wards["db"]
    with wards["app"].app_context():
        taken = wards.setdefault("taken", 0)
        for i in range(taken, taken + n):
            kid = Patient(patient_number=f"W{i}", full_name=f"طفل العنبر {i}",
                          gender="female", date_of_birth=date(2024, 1, 1),
                          is_active=True)
            db.session.add(kid)
            db.session.flush()
            stay = place.admit(kid, db.session.get(Bed, wards["beds"][i]),
                               when=datetime.utcnow() - timedelta(days=1))
            drug_round.order(stay, "أموكسيسيلين", dose="250 mg",
                             every_hours=8,
                             when=datetime.utcnow() - timedelta(hours=2))
        db.session.commit()
        wards["taken"] = taken + n


def test_the_pharmacy_ward_asks_the_same_for_one_bed_or_four(wards):
    client = wards["sign_in"]("boss")
    _admit(wards, 1)
    client.get("/pharmacy/ward")                  # settle anything first-time
    with _Counter(wards["app"]) as one:
        page = client.get("/pharmacy/ward")
    assert page.status_code == 200
    _admit(wards, 3)
    with _Counter(wards["app"]) as four:
        page = client.get("/pharmacy/ward").get_data(as_text=True)
    assert len(four.seen) == len(one.seen), four.seen[len(one.seen):]
    # And every bed still says where it is: the unit, the bed, the child.
    for unit, n in (("الداخلي", 1), ("الداخلي", 2), ("الحضانة", 1),
                    ("الحضانة", 2)):
        assert f"{unit} · {unit}-{n}" in page
    for i in range(4):
        assert f"طفل العنبر {i}" in page


def test_the_units_filter_still_filters(wards):
    _admit(wards, 4)
    page = wards["sign_in"]("boss").get(
        "/pharmacy/ward?kind=nicu").get_data(as_text=True)
    assert "الحضانة · الحضانة-1" in page
    assert "الداخلي · الداخلي-1" not in page


# ------------------------------------------------------------ the grants ----
@pytest.fixture()
def busy_doctor(clinic):
    """A doctor with a full morning, trusted with the till on their own."""
    from app.models import Appointment, Patient, UserCapability
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        for n in range(8):
            kid = Patient(patient_number=f"D{n}", full_name=f"مريض {n}",
                          gender="male", date_of_birth=date(2023, 1, 1),
                          is_active=True)
            db.session.add(kid)
            db.session.flush()
            db.session.add(Appointment(
                patient_id=kid.id, doctor_id=clinic["ids"]["doctor"],
                appt_date=local_today(), appt_time=time(9 + n, 0),
                appt_type="followup", status="scheduled"))
        db.session.add(UserCapability(user_id=clinic["ids"]["doctor"],
                                      capability="cashier"))
        db.session.commit()
    return clinic


def test_a_doctors_board_asks_for_their_grants_once(busy_doctor):
    client = busy_doctor["sign_in"]("doc")
    client.get("/appointments/")
    with _Counter(busy_doctor["app"]) as heard:
        page = client.get("/appointments/").get_data(as_text=True)
    assert len(heard.about("user_capabilities")) == 1
    # And the grant is still what it was for: the doctor can take the money,
    # so every row offers to.
    assert page.count("/finance/checkout/") >= 8


def test_a_grant_is_seen_by_the_request_that_made_it(clinic):
    """Remembered for a request — and a grant or a revocation made during
    that request is seen by the rest of it, written or not yet written."""
    from app.extensions import db
    from app.models import User, UserCapability

    with clinic["app"].test_request_context():
        doc = db.session.get(User, clinic["ids"]["doctor"])
        assert not doc.can("cashier")
        grant = UserCapability(user_id=doc.id, capability="cashier")
        db.session.add(grant)
        assert doc.can("cashier")                   # added, not yet written
        db.session.commit()
        assert doc.can("cashier")                   # written
        db.session.delete(grant)
        assert not doc.can("cashier")               # removed, not yet written
        db.session.commit()
        assert not doc.can("cashier")               # removed and written
        db.session.add(UserCapability(user_id=doc.id, capability="cashier"))
        db.session.commit()
        assert doc.can("cashier")                   # and back again


def test_one_persons_grants_are_not_anothers(clinic):
    from app.extensions import db
    from app.models import User, UserCapability

    with clinic["app"].test_request_context():
        db.session.add(UserCapability(user_id=clinic["ids"]["doctor"],
                                      capability="cashier"))
        db.session.commit()
        doc = db.session.get(User, clinic["ids"]["doctor"])
        acct = db.session.get(User, clinic["ids"]["accountant"])
        assert doc.can("cashier")
        assert acct.granted_capabilities == set()


# ------------------------------------------------------------ the indexes ----
_WANTED = {("invoices", "ix_invoices_invoice_date"),
           ("invoices", "ix_invoices_doctor_date"),
           ("appointments", "ix_appointments_doctor_date")}


def _indexes(table):
    from sqlalchemy import inspect

    from app.extensions import db

    return {ix["name"] for ix in inspect(db.engine).get_indexes(table)}


def test_an_old_database_gets_the_indexes_its_models_ask_for(clinic):
    """A clinic's ``invoices`` table was made before the index was; the next
    start adds it, and what was there is untouched."""
    from sqlalchemy import text

    from app.extensions import db
    from app.models import Invoice
    from app.utils.schema import apply_schema

    with clinic["app"].app_context():
        db.session.add(Invoice(invoice_number="OLD-1",
                               patient_id=clinic["ids"]["child"],
                               invoice_date=date(2025, 5, 5)))
        db.session.commit()
        for _table, name in _WANTED:
            db.session.execute(text(f"DROP INDEX {name}"))
        db.session.commit()
        assert not any(name in _indexes(table) for table, name in _WANTED)

        apply_schema()

        for table, name in _WANTED:
            assert name in _indexes(table), name
        assert Invoice.query.one().invoice_number == "OLD-1"
        apply_schema()                              # and again changes nothing
        for table, name in _WANTED:
            assert name in _indexes(table), name


def test_a_unique_index_is_never_added_to_an_old_table(clinic):
    """A unique index on a table that already holds a duplicate would stop
    the program starting. The model's unique rules stay where they were."""
    from sqlalchemy import text

    from app.extensions import db
    from app.utils.schema import apply_schema

    with clinic["app"].app_context():
        db.session.execute(text("DROP INDEX ix_invoices_invoice_number"))
        db.session.commit()
        apply_schema()
        assert "ix_invoices_invoice_number" not in _indexes("invoices")


# ------------------------------------------------------------ new or not ----
def test_new_and_returning_children(clinic):
    """New means no real visit before the window — a cancelled one or a
    missed one does not make a child a returning patient."""
    from app.blueprints.appointments.routes import _visit_breakdown
    from app.models import Appointment, Patient
    from app.utils.clock import local_today

    db = clinic["db"]
    today = local_today()
    first = today.replace(day=1)
    before = first - timedelta(days=20)
    with clinic["app"].app_context():
        kids = {}
        for name in ("first_ever", "cancelled_before", "no_show_before",
                     "seen_before", "seen_earlier_this_month"):
            kid = Patient(patient_number=name, full_name=name, gender="male",
                          date_of_birth=date(2023, 1, 1), is_active=True)
            db.session.add(kid)
            db.session.flush()
            kids[name] = kid.id

        def book(name, on, status, hour=9):
            db.session.add(Appointment(
                patient_id=kids[name], doctor_id=clinic["ids"]["doctor"],
                appt_date=on, appt_time=time(hour, 0), appt_type="followup",
                status=status))

        for name in kids:
            book(name, today, "scheduled", hour=10)
        book("cancelled_before", before, "cancelled")
        book("no_show_before", before, "no_show")
        book("seen_before", before, "completed")
        if first < today:
            book("seen_earlier_this_month", first, "completed")
        db.session.commit()

    with clinic["app"].test_request_context():
        got = _visit_breakdown(None, today)["newold"]
    returning_today = 2 if first < today else 1
    assert got["day"] == {"new": 5 - returning_today, "old": returning_today,
                          "total": 5}
    assert got["month"] == {"new": 4, "old": 1, "total": 5}


def test_nobody_booked_is_nobody_new(clinic):
    from app.blueprints.appointments.routes import _visit_breakdown
    from app.utils.clock import local_today

    with clinic["app"].test_request_context():
        got = _visit_breakdown(None, local_today())["newold"]
    assert got == {"day": {"new": 0, "old": 0, "total": 0},
                   "month": {"new": 0, "old": 0, "total": 0}}
