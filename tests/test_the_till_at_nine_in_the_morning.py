"""The till at nine in the morning — a hundred and twenty bookings, one screen.

Found by the load test (``docs/LOAD_TEST.md``): the cashier screen was the
heaviest page left. It lists today's bookings nobody has billed, and to know
which of them are worth chasing it adds up what each one would cost — through
the checkout's own line builder, so the till and the checkout never disagree.

Right answer, and a thousand questions to reach it: the builder asked the
database seven or eight things about one child at a time — is there a stay
bill, is there a bill today, what is this visit type's service, any doses,
any doctor-added services, any package, any operation — once per booking.
A hundred and twenty bookings came to 991 queries and most of a second, on
the screen reception opens all day.

Now each question is asked once for the whole list. These tests hold the two
things that matter: **every booking comes to exactly what it came to before**
— whatever is on it — and the number of questions no longer grows with the
number of bookings.
"""
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import event

from app.utils.clock import local_today


def _kid(db, n):
    from app.models import Patient

    kid = Patient(patient_number=f"T{n}", full_name=f"طفل {n}", gender="male",
                  date_of_birth=datetime(2024, 1, 1).date(), is_active=True)
    db.session.add(kid)
    db.session.flush()
    return kid


def _booking(clinic, kid, minute=0):
    from app.models import Appointment

    appt = Appointment(patient_id=kid.id, doctor_id=clinic["ids"]["doctor"],
                       appt_date=local_today(), appt_time=time(9, minute),
                       appt_type="new", status="scheduled")
    clinic["db"].session.add(appt)
    clinic["db"].session.flush()
    return appt


@pytest.fixture()
def morning(clinic):
    """One booking for each thing a checkout can find on a child."""
    from app.models import (Admission, Invoice, InvoiceItem, Investigation,
                            Operation, PatientPackage, Payment,
                            PatientVaccine, Prescription, PrescriptionItem, Service, Setting,
                            StoreItem, Theatre, User, Visit,
                            VisitInvestigation, VisitService)
    from app.utils.pricing import set_visit_type_service

    db = clinic["db"]
    ids = clinic["ids"]
    with clinic["app"].app_context():
        for module in ("theatres", "labs", "pharmacy"):
            Setting.set(f"mod_enabled:{module}", "1")
        exam = db.session.get(Service, ids["exam"])
        set_visit_type_service("new", exam)
        made = {}

        # Nothing but the exam.
        made["plain"] = _booking(clinic, _kid(db, 1), 0).id

        # Three stay bills: an older one still owing, the latest one owing
        # (it carries the exam — so the exam is not charged again), and a
        # newer one already settled, which is never offered.
        kid = _kid(db, 2)
        stay = Admission(patient_id=kid.id)
        db.session.add(stay)
        db.session.flush()
        for number, service_id, paid in (("S-1", ids["nebul"], 0),
                                         ("S-2", exam.id, 0),
                                         ("S-3", ids["nebul"], 150)):
            bill = Invoice(invoice_number=number, patient_id=kid.id,
                           admission_id=stay.id,
                           invoice_date=local_today() - timedelta(days=2))
            db.session.add(bill)
            db.session.flush()
            db.session.add(InvoiceItem(invoice_id=bill.id,
                                       service_id=service_id,
                                       description="بند", unit_price=150,
                                       quantity=1))
            if paid:
                db.session.add(Payment(invoice_id=bill.id, amount=paid,
                                       method="cash"))
        made["stay"] = _booking(clinic, kid, 5).id

        # Already a bill today carrying the exam — the exam is not charged
        # twice. Two of them, so "the latest" has to be the latest.
        kid = _kid(db, 3)
        for number, with_exam in (("D-1", False), ("D-2", True)):
            bill = Invoice(invoice_number=number, patient_id=kid.id,
                           invoice_date=local_today())
            db.session.add(bill)
            db.session.flush()
            if with_exam:
                db.session.add(InvoiceItem(invoice_id=bill.id,
                                           service_id=exam.id,
                                           description="كشف", unit_price=200,
                                           quantity=1))
        made["billed_today"] = _booking(clinic, kid, 10).id

        # A dose given yesterday, priced, never charged — and one given
        # a week ago, which is too old to be offered.
        kid = _kid(db, 4)
        for days in (1, 7):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=ids["pcv"], brand_id=ids["brand"],
                dose_number=1, event_type="given", given_outside=False,
                given_date=local_today() - timedelta(days=days),
                doctor_id=ids["doctor"]))
        made["dose"] = _booking(clinic, kid, 15).id

        # The doctor added a nebuliser session on this booking's visit.
        kid = _kid(db, 5)
        appt = _booking(clinic, kid, 20)
        visit = Visit(patient_id=kid.id, doctor_id=ids["doctor"],
                      visit_date=local_today(), appointment_id=appt.id)
        db.session.add(visit)
        db.session.flush()
        db.session.add(VisitService(visit_id=visit.id,
                                    service_id=ids["nebul"], name="جلسة تنفس",
                                    quantity=2))
        # And one already charged, which must not come back.
        charged = Invoice(invoice_number="V-1", patient_id=kid.id,
                          invoice_date=local_today() - timedelta(days=1))
        db.session.add(charged)
        db.session.flush()
        db.session.add(VisitService(visit_id=visit.id, invoice_id=charged.id,
                                    service_id=ids["nebul"], name="جلسة قديمة",
                                    quantity=1))
        made["service"] = appt.id

        # A package of exams already paid for — beside one for another
        # service, and an older package of exams whose window has closed.
        kid = _kid(db, 6)
        other = PatientPackage(patient_id=kid.id, service_id=ids["nebul"],
                               name="باقة تنفس", sessions_total=3,
                               sold_on=local_today())
        lapsed = PatientPackage(patient_id=kid.id, service_id=exam.id,
                                name="باقة قديمة", sessions_total=3,
                                sold_on=local_today() - timedelta(days=90),
                                expires_on=local_today() - timedelta(days=1))
        exams = PatientPackage(patient_id=kid.id, service_id=exam.id,
                               name="باقة", sessions_total=3,
                               sold_on=local_today())
        db.session.add_all([other, lapsed, exams])
        db.session.flush()
        clinic["package"] = exams.id
        made["package"] = _booking(clinic, kid, 25).id

        # A child with no booking today, and one of everything owed —
        # none of it is the till's business this morning.
        kid = _kid(db, 10)
        clinic["not_booked"] = kid.id
        visit = Visit(patient_id=kid.id, doctor_id=ids["doctor"],
                      visit_date=local_today())
        db.session.add(visit)
        db.session.flush()
        clinic["not_booked_visit"] = visit.id

        # A day case done this morning, and an anaesthetist on it.
        kid = _kid(db, 7)
        knife = Service(name="طهارة", code="SVC-C", price=900,
                        category="procedure", is_active=True)
        anaes = Service(name="تخدير", code="SVC-ANAES", price=400,
                        category="procedure", is_active=True)
        gas = User(username="gas", full_name="د. تخدير", role="doctor",
                   is_active=True)
        gas.set_password("secret")
        room = Theatre(name="غرفة", is_active=True)
        db.session.add_all([knife, anaes, gas, room])
        db.session.flush()
        db.session.add(Operation(patient_id=kid.id, theatre_id=room.id,
                                 procedure="طهارة", status="done",
                                 on_date=local_today(), service_id=knife.id,
                                 surgeon_id=ids["doctor"],
                                 anaesthetist_id=gas.id))
        made["operation"] = _booking(clinic, kid, 30).id
        db.session.add(Operation(patient_id=clinic["not_booked"],
                                 theatre_id=room.id, procedure="أخرى",
                                 status="done", on_date=local_today(),
                                 service_id=knife.id,
                                 surgeon_id=ids["doctor"]))

        # A blood test drawn and not charged.
        kid = _kid(db, 8)
        cbc = Investigation(name_ar="صورة دم", service_id=ids["nebul"])
        db.session.add(cbc)
        db.session.flush()
        visit = Visit(patient_id=kid.id, doctor_id=ids["doctor"],
                      visit_date=local_today())
        db.session.add(visit)
        db.session.flush()
        db.session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=kid.id, investigation_id=cbc.id,
            name="صورة دم", collected_at=datetime.utcnow()))
        made["test"] = _booking(clinic, kid, 35).id
        db.session.add(VisitInvestigation(
            visit_id=clinic["not_booked_visit"],
            patient_id=clinic["not_booked"], investigation_id=cbc.id,
            name="صورة دم", collected_at=datetime.utcnow()))

        # A bottle handed over at our own counter.
        kid = _kid(db, 9)
        bottle = StoreItem(name="شراب", unit="زجاجة", item_type="drug",
                           sell_price=60, purchase_price=25, is_active=True)
        db.session.add(bottle)
        rx = Prescription(patient_id=kid.id, doctor_id=ids["doctor"],
                          created_at=datetime.utcnow())
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id, drug_name="شراب",
                                        store_item_id=bottle.id, quantity=2,
                                        dispensed_at=datetime.utcnow()))
        made["dispensed"] = _booking(clinic, kid, 40).id
        rx = Prescription(patient_id=clinic["not_booked"],
                          doctor_id=ids["doctor"], created_at=datetime.utcnow())
        db.session.add(rx)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=rx.id, drug_name="شراب",
                                        store_item_id=bottle.id, quantity=1,
                                        dispensed_at=datetime.utcnow()))

        db.session.commit()
    clinic["appts"] = made
    return clinic


def _lines(fx, batched):
    from app.blueprints.finance.routes import _asked_once, _checkout_lines
    from app.models import Appointment

    with fx["app"].test_request_context():
        appts = (Appointment.query
                 .filter(Appointment.id.in_(fx["appts"].values()))
                 .order_by(Appointment.id).all())
        by_id = {a.id: a for a in appts}
        if not batched:
            return {name: _checkout_lines(by_id[aid], "ar")
                    for name, aid in fx["appts"].items()}
        with _asked_once(appts):
            return {name: _checkout_lines(by_id[aid], "ar")
                    for name, aid in fx["appts"].items()}


def test_every_booking_comes_to_what_it_came_to_before(morning):
    """Line by line, not only the total: the till's answer is the checkout's
    answer, and asked once for the list it has to be the same answer."""
    one_by_one = _lines(morning, batched=False)
    all_at_once = _lines(morning, batched=True)
    assert all_at_once == one_by_one


def test_each_case_in_the_fixture_found_what_it_is_there_for(morning):
    """Otherwise the test above could pass by every booking coming to the
    exam and nothing else."""
    lines = _lines(morning, batched=True)

    def keys(name, key):
        return [line.get(key) for line in lines[name] if line.get(key)]

    assert [line["unit_price"] for line in lines["plain"]] == [200]
    assert lines["stay"] == [] and lines["billed_today"] == []
    assert len(keys("dose", "dose_id")) == 1
    assert len(keys("service", "vs_id")) == 1
    assert keys("package", "pkg_id") == [morning["package"]]
    assert lines["package"][0]["unit_price"] == 0
    assert len(keys("operation", "op_id")) == 1
    assert len(lines["operation"]) == 3           # exam, surgery, anaesthetic
    assert len(keys("test", "test_id")) == 1
    assert len(keys("dispensed", "rx_line_id")) == 1


def test_the_till_asks_only_about_the_children_on_its_list(morning):
    """A child with no booking today owes an operation, a test and a bottle;
    fetching them would give the same totals and cost the whole clinic's
    backlog on every visit to the screen."""
    from app.blueprints.finance.routes import _ask_for_the_list
    from app.models import Appointment

    with morning["app"].test_request_context():
        appts = Appointment.query.all()
        answers = _ask_for_the_list(appts)
        on_list = {a.patient_id for a in appts}
        for name in ("operations", "tests", "dispensed", "todays_invoice"):
            assert set(answers[name]) == on_list, name


def test_nothing_is_kept_after_the_till_has_added_up(morning):
    from flask import g

    from app.blueprints.finance.routes import _ASKED, _asked_once
    from app.models import Appointment

    with morning["app"].test_request_context():
        appts = Appointment.query.all()
        with _asked_once(appts):
            assert getattr(g, _ASKED, None) is not None
        assert getattr(g, _ASKED, None) is None


def test_a_service_made_while_adding_up_is_seen_by_the_next_booking(clinic):
    """The one write the builder can make: a clinic with no vaccination fee
    gets one on the spot, and it becomes that visit type's base charge. A
    kept "no service for this type" must not outlive that."""
    from flask import g

    from app.blueprints.finance.routes import (_ASKED, _asked,
                                               _asked_once, _vaccine_service)
    from app.models import Appointment
    from app.utils.pricing import service_for_visit_type

    with clinic["app"].test_request_context():
        appt = _booking(clinic, _kid(clinic["db"], 1))
        with _asked_once([appt]):
            assert _asked("visit_type_service", "vaccination",
                          lambda: service_for_visit_type("vaccination")) is None
            made = _vaccine_service()
            assert "visit_type_service" not in getattr(g, _ASKED)
            assert _asked("visit_type_service", "vaccination",
                          lambda: service_for_visit_type("vaccination")) is made
        assert Appointment.query.count() == 1


def _queries_for(clinic, how_many, first=100):
    from app.blueprints.finance.routes import _unbilled_bookings
    from app.extensions import db
    from app.models import PatientVaccine, Service
    from app.utils.pricing import set_visit_type_service

    with clinic["app"].app_context():
        set_visit_type_service("new", db.session.get(Service,
                                                     clinic["ids"]["exam"]))
        for n in range(how_many):
            kid = _kid(db, first + n)
            _booking(clinic, kid, n % 60)
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=clinic["ids"]["pcv"],
                brand_id=clinic["ids"]["brand"], dose_number=1,
                event_type="given", given_outside=False,
                given_date=local_today(), doctor_id=clinic["ids"]["doctor"]))
        db.session.commit()

    count = [0]

    def tally(*_a, **_k):
        count[0] += 1

    with clinic["app"].test_request_context():
        _unbilled_bookings(local_today())            # settings, warmed
        db.session.expunge_all()
        event.listen(db.engine, "before_cursor_execute", tally)
        try:
            rows = _unbilled_bookings(local_today())
        finally:
            event.remove(db.engine, "before_cursor_execute", tally)
    assert len(rows) == how_many
    return count[0]


def test_twenty_bookings_ask_what_three_do(clinic):
    """The whole point: the questions do not grow with the day."""
    few = _queries_for(clinic, 3)
    with clinic["app"].app_context():
        from app.models import Appointment
        clinic["db"].session.query(Appointment).delete()
        clinic["db"].session.commit()
    many = _queries_for(clinic, 20, first=200)
    assert many == few, (few, many)
