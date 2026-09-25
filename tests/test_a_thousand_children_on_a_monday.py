"""What the load test found, held so it stays found — backlog item 15.

The load test (``tools/loadtest``) runs the clinic's own server against a
made-up clinic two years old and sends it a working morning. Its first run
put eight people at over a minute per screen, and the cause was not the
screens:

* the bell asked, on every page, which children the clinic cannot reach —
  and read each child's guardians **one query per child**: eight thousand
  queries on a clinic that size;
* the bell's list is shared and refreshed every ninety seconds, and when it
  went stale **every request arriving in those seconds worked it out again,
  at once**.

These tests hold both, and the two guards that keep the load test itself
from ever being pointed at a clinic's own records.
"""
import threading
import time
from datetime import date

import pytest


def _children(clinic, n):
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        for i in range(n):
            fam = Family(family_name=f"عائلة {i}")
            db.session.add(fam)
            db.session.flush()
            db.session.add(Parent(family_id=fam.id, full_name=f"والد {i}",
                                  relation="father",
                                  phone=None if i % 3 == 0 else f"0100{i:07d}"))
            db.session.add(Patient(patient_number=f"LT-{n}-{i}",
                                   family_id=fam.id, full_name=f"طفل {i}",
                                   date_of_birth=date(2010, 1, 1),
                                   gender="male", is_active=True))
        db.session.commit()


def _queries(clinic, fn):
    from sqlalchemy import event

    seen = []

    def count(*_):
        seen.append(1)

    with clinic["app"].app_context():
        engine = clinic["db"].engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            result = fn()
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(seen), result


# ------------------------------------------------------- the phone list ----
def test_who_cannot_be_reached_costs_the_same_for_ten_children_or_forty(clinic):
    from app.utils import phonebook

    _children(clinic, 10)
    few, rows_few = _queries(clinic, phonebook.unreachable)
    _children(clinic, 30)
    many, rows_many = _queries(clinic, phonebook.unreachable)
    assert few == many
    # And the answer is the same answer: a third of the families have no
    # number, and those children are the list.
    assert len(rows_many) == len(rows_few) + 10


def test_teens_without_a_number_cost_the_same_too(clinic):
    from app.utils import phonebook

    _children(clinic, 10)
    few, _ = _queries(clinic, phonebook.teens_without_own_phone)
    _children(clinic, 30)
    many, _ = _queries(clinic, phonebook.teens_without_own_phone)
    assert few == many


# ------------------------------------------------------------- the bell ----
@pytest.fixture()
def slow_bell(monkeypatch):
    from app.utils import notifications

    calls = []
    release = threading.Event()

    def compute():
        calls.append(1)
        release.wait(5)
        return [{"key": f"n{len(calls)}"}]

    monkeypatch.setattr(notifications, "_compute", compute)
    notifications.invalidate()
    yield notifications, calls, release
    release.set()
    notifications.invalidate()


def test_a_stale_bell_is_refreshed_once_and_nobody_waits_for_it(slow_bell):
    notifications, calls, release = slow_bell
    release.set()
    assert notifications._all() == [{"key": "n1"}]
    notifications._CACHE["at"] = time.time() - notifications._TTL - 1
    release.clear()

    worker = threading.Thread(target=notifications._all)
    worker.start()
    time.sleep(0.2)                      # the first one is now computing
    started = time.time()
    answers = [notifications._all() for _ in range(5)]
    assert time.time() - started < 1     # nobody else waited for it
    assert answers == [[{"key": "n1"}]] * 5
    release.set()
    worker.join(5)
    assert len(calls) == 2               # worked out once more, not six times
    assert notifications._all() == [{"key": "n2"}]


def test_with_no_bell_at_all_the_others_wait_rather_than_repeat_it(slow_bell):
    notifications, calls, release = slow_bell
    got = []
    threads = [threading.Thread(target=lambda: got.append(notifications._all()))
               for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert got == [[{"key": "n1"}]] * 4


def test_invalidate_still_means_the_next_page_sees_it_fresh(slow_bell):
    notifications, calls, release = slow_bell
    release.set()
    notifications._all()
    notifications.invalidate()
    notifications._all()
    assert len(calls) == 2


# ------------------------------------------------- SQLite's patience ----
@pytest.mark.parametrize("raw, ms", [(None, 15000), ("3000", 3000),
                                     ("0", 15000), ("-5", 15000),
                                     ("soon", 15000)])
def test_the_busy_timeout_is_fifteen_seconds_unless_told(monkeypatch, raw, ms):
    from app import _busy_timeout_ms

    if raw is None:
        monkeypatch.delenv("SQLITE_BUSY_TIMEOUT_MS", raising=False)
    else:
        monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", raw)
    assert _busy_timeout_ms() == ms


# ------------------------------------------- never a clinic's own file ----
def test_the_fake_clinic_is_built_only_in_a_new_file(tmp_path):
    from tools.loadtest.fake_clinic import _refuse

    taken = tmp_path / "clinic.db"
    taken.write_bytes(b"")
    assert _refuse(str(taken))
    assert _refuse(str(tmp_path / "fresh.db")) is None


def test_the_fake_clinic_will_not_build_on_the_clinics_database(tmp_path,
                                                                monkeypatch):
    from tools.loadtest.fake_clinic import _refuse

    target = tmp_path / "live.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target}")
    assert _refuse(str(target))


def test_the_driver_refuses_a_database_nobody_stamped(tmp_path):
    import sqlite3

    from tools.loadtest.drive import is_a_copy

    live = tmp_path / "live.db"
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE settings (key TEXT, value TEXT)")
    con.commit()
    assert not is_a_copy(str(live))
    con.execute("INSERT INTO settings VALUES ('load_test_copy', '1')")
    con.commit()
    con.close()
    assert is_a_copy(str(live))
    assert not is_a_copy(str(tmp_path / "missing.db"))


# ------------------------------------ two cashiers, one "last number" ----
def _taken_first(monkeypatch, module, name, taken):
    """The generator hands out a number already on file once — what the
    second of two simultaneous saves reads — and the real one after."""
    real = getattr(module, name)
    calls = []

    def fake(*args, **kwargs):
        calls.append(1)
        return taken if len(calls) == 1 else real(*args, **kwargs)

    monkeypatch.setattr(module, name, fake)
    return calls


def test_a_checkout_that_lost_the_race_is_done_again_not_refused(clinic,
                                                                 monkeypatch):
    import app.blueprints.finance.routes as finance
    from app.models import Invoice, InvoiceItem, Setting

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("require_shift_to_collect", "0")
        first = Invoice(invoice_number="INV-TAKEN", patient_id=clinic["ids"]["child"])
        db.session.add(first)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=first.id, description="قديمة",
                                   unit_price=1, quantity=1))
        db.session.commit()
    calls = _taken_first(monkeypatch, finance, "generate_invoice_number",
                         "INV-TAKEN")
    # A different child, so the day's own invoice is not simply added to.
    with clinic["app"].app_context():
        from app.models import Patient
        from datetime import date as _d
        other = Patient(patient_number="LT-OTHER", full_name="طفل تاني",
                        date_of_birth=_d(2023, 1, 1), gender="female",
                        is_active=True)
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        other_id = other.id
    reply = clinic["sign_in"]("boss").post(
        f"/finance/collect/{other_id}",
        data={"line_desc": "كشف", "line_price": "200", "line_qty": "1",
              "amount": "200", "method": "cash"})
    assert reply.status_code == 302 and "receipt" in reply.headers["Location"]
    assert len(calls) == 2
    with clinic["app"].app_context():
        mine = Invoice.query.filter_by(patient_id=other_id).all()
        assert len(mine) == 1 and mine[0].invoice_number != "INV-TAKEN"
        assert mine[0].total == 200 and mine[0].paid == 200


def test_a_registration_that_lost_the_race_is_done_again(clinic, monkeypatch):
    import app.utils.patients as patients
    from app.models import Patient

    with clinic["app"].app_context():
        taken = clinic["db"].session.get(Patient, clinic["ids"]["child"]).patient_number
    calls = _taken_first(monkeypatch, patients, "generate_patient_number", taken)
    reply = clinic["sign_in"]("boss").post(
        "/appointments/patient-quick",
        json={"full_name": "طفل جديد", "gender": "male",
              "date_of_birth": "2022-02-02"})
    assert reply.status_code == 200 and reply.get_json()["ok"]
    assert len(calls) == 2


def test_any_other_refusal_is_not_retried(clinic, monkeypatch):
    """Only a clash on a numbered column is done again — anything else is
    the error it always was, raised once."""
    from sqlalchemy.exc import IntegrityError

    from app.utils.sequences import retry_on_number_clash

    calls = []

    @retry_on_number_clash
    def view():
        calls.append(1)
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: x.y"))

    with clinic["app"].app_context(), pytest.raises(IntegrityError):
        view()
    assert len(calls) == 1


def test_the_highest_number_ignores_tails_that_are_not_numbers(clinic):
    from app.models import Invoice
    from app.utils.finance import generate_invoice_number
    from app.utils.sequences import highest

    with clinic["app"].app_context():
        db = clinic["db"]
        first = generate_invoice_number()
        base = first.rstrip("0123456789")
        for number in (f"{base}000007", f"{base}12", f"{base}0099X",
                       f"{base}ABC", f"{base}"):
            db.session.add(Invoice(invoice_number=number,
                                   patient_id=clinic["ids"]["child"]))
        db.session.commit()
        assert highest(Invoice.invoice_number, base) == 12
        assert generate_invoice_number() == f"{base}{13:0{len(first) - len(base)}d}"


def test_two_cashiers_at_once_get_two_numbers(tmp_path, monkeypatch):
    """The race itself, on a real file: the first save holds its number
    uncommitted while the second asks for one. Numbered under the lock,
    the second waits and takes the next — no clash, nothing retried."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/race.db")
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient
        db.session.add(Patient(patient_number="R-1", full_name="طفل",
                               date_of_birth=date(2020, 1, 1),
                               gender="male", is_active=True))
        db.session.commit()
        child = Patient.query.one().id

    first_has_number = threading.Event()
    numbers, errors = [], []

    def cashier(hold):
        try:
            with app.app_context():
                from app.models import Invoice
                from app.utils.finance import generate_invoice_number
                from app.utils.sequences import claim

                invoice = Invoice(patient_id=child)
                claim(invoice, "invoice_number", generate_invoice_number)
                numbers.append(invoice.invoice_number)
                if hold:
                    first_has_number.set()
                    time.sleep(0.8)      # the second arrives in this gap
                db.session.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            first_has_number.set()

    a = threading.Thread(target=cashier, args=(True,))
    a.start()
    first_has_number.wait(5)
    b = threading.Thread(target=cashier, args=(False,))
    b.start()
    a.join(20)
    b.join(20)
    assert errors == []
    assert len(set(numbers)) == 2


# --------------------------------------------------------- the board ----
def _todays_list(clinic, n, start):
    from datetime import time as _t

    from app.models import Appointment, Family, Parent, Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        for i in range(start, start + n):
            fam = Family(family_name=f"أسرة {i}")
            db.session.add(fam)
            db.session.flush()
            db.session.add(Parent(family_id=fam.id, full_name=f"أم {i}",
                                  relation="mother", phone=f"0111{i:07d}"))
            child = Patient(patient_number=f"B-{i}", family_id=fam.id,
                            full_name=f"طفل {i}", date_of_birth=date(2021, 1, 1),
                            gender="female", is_active=True)
            db.session.add(child)
            db.session.flush()
            db.session.add(Appointment(
                patient_id=child.id, doctor_id=clinic["ids"]["doctor"],
                appt_date=local_today(), appt_time=_t(9 + i % 8, 0),
                # A visit type the clinic has not priced — the case that
                # looked its price up once per row.
                appt_type="unpriced_type", status="scheduled"))
        db.session.commit()


def _board_queries(clinic, client):
    from sqlalchemy import event

    seen = []

    def count(*_):
        seen.append(1)

    with clinic["app"].app_context():
        engine = clinic["db"].engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            page = client.get("/appointments/").get_data(as_text=True)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(seen), page


def test_the_day_board_costs_the_same_for_five_rows_or_twenty(clinic,
                                                              bell_held_warm):
    boss = clinic["sign_in"]("boss")
    _todays_list(clinic, 5, 0)
    boss.get("/appointments/")
    few, _ = _board_queries(clinic, boss)
    _todays_list(clinic, 15, 5)
    many, page = _board_queries(clinic, boss)
    assert few == many
    assert "01110000019" in page          # and the phones are still on it
