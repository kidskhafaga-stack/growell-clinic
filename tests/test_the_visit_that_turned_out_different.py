"""Reception should never have to work out what the money does.

The board showed a **cancelled** appointment marked **Paid**, side by side,
with no action about the money and nothing anywhere saying the clinic was
holding cash for a visit that was not going to happen. Cancelling touches the
reminders, the reason and the log; it has never once looked at the invoice.

And the day-to-day case is the same shape: a child is booked and charged for
one thing at the desk, and the doctor decides another in the room — a
discount, a free consultation, a longer visit that costs more. Every one of
those leaves the bill describing something that did not happen, and reception
in the middle doing arithmetic.

So these tests are written as the counter, not as the code: the eight things
that actually happen at a desk, and the one sentence the program must put on
the screen for each. The verdict is the whole product — a checker that only
answered "there is a difference" would leave the thinking exactly where it
was.

The money itself is not tested here because this module does not move any: it
corrects the line, and refunding and collecting stay the one path they already
were.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk():
    """A clinic with a 200 consultation, a 150 review and a free follow-up."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, User

        doctor = User(username="doc", full_name="د. أحمد", role="doctor",
                      is_active=True)
        doctor.set_password("secret")
        db.session.add(doctor)

        services = {}
        for key, name, price in (("exam", "كشف", 200.0),
                                 ("review", "استشارة", 150.0),
                                 ("free", "استشارة مجانية", 0.0),
                                 ("long", "زيارة ممتدة", 300.0)):
            svc = Service(name=name, category="consultation", price=price,
                          commission_type="percent", commission_value=40,
                          visit_type=key)
            db.session.add(svc)
            services[key] = svc

        child = Patient(patient_number="P0001", full_name="طفل",
                        date_of_birth=date(2023, 1, 1), gender="male")
        db.session.add(child)
        db.session.commit()
        ids = {"doctor": doctor.id, "child": child.id,
               **{k: v.id for k, v in services.items()}}
    return {"app": app, "db": db, "ids": ids}


def _billed(desk, service_key="exam", paid=None, appt_type="exam"):
    """A booking, its invoice line, and whatever has been collected."""
    from app.models import Appointment, Invoice, InvoiceItem, Payment, Service

    ids = desk["ids"]
    service = Service.query.get(ids[service_key])
    appt = Appointment(patient_id=ids["child"], doctor_id=ids["doctor"],
                       appt_date=date(2026, 9, 7), appt_time=time(15, 0),
                       appt_type=appt_type, status="scheduled")
    desk["db"].session.add(appt)
    desk["db"].session.flush()

    from app.utils.finance import generate_invoice_number

    invoice = Invoice(invoice_number=generate_invoice_number(),
                      patient_id=ids["child"], doctor_id=ids["doctor"],
                      appointment_id=appt.id)
    desk["db"].session.add(invoice)
    desk["db"].session.flush()

    item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                       description=service.name, quantity=1,
                       unit_price=service.price,
                       commission_amount=service.doctor_share(service.price))
    desk["db"].session.add(item)
    if paid:
        desk["db"].session.add(Payment(invoice_id=invoice.id, amount=paid,
                                       kind="payment", method="cash"))
    desk["db"].session.flush()
    return appt, invoice, item


# ------------------------------------------------- the eight at the counter --
def test_a_discount_the_doctor_gave_comes_back_as_a_refund(desk):
    """Booked and paid 200; the doctor knocks 50 off in the room."""
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        _, _, item = _billed(desk, paid=200)
        p = settle.propose(item, 150)
    assert (p.verdict, p.amount) == ("refund", 50.0)


def test_a_paid_visit_that_became_free_refunds_all_of_it(desk):
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        from app.models import Service
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["free"]))
    assert (p.verdict, p.amount) == ("refund", 200.0)


def test_a_cheaper_service_refunds_only_the_difference(desk):
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["review"]))
    assert (p.verdict, p.amount) == ("refund", 50.0)


def test_a_dearer_service_collects_the_difference(desk):
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["long"]))
    assert (p.verdict, p.amount) == ("collect", 100.0)


def test_the_same_price_asks_for_nothing(desk):
    """"تمام مسدّدة" — the visit changed shape and the money did not."""
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        _, _, item = _billed(desk, paid=200)
        p = settle.propose(item, 200)
    assert (p.verdict, p.amount) == ("nothing", 0.0)


def test_a_cancelled_paid_visit_hands_it_all_back(desk):
    """The row in the screenshot: cancelled and paid, and nothing said so."""
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        p = settle.propose_cancellation(appt)
    assert (p.verdict, p.amount) == ("refund", 200.0)


def test_a_cheaper_service_on_an_unpaid_visit_still_collects(desk):
    """Nothing was paid, so a cheaper service is not a refund — it is a
    smaller bill that is still owed."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=None)
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["review"]))
    assert (p.verdict, p.amount) == ("collect", 150.0)


def test_a_part_paid_visit_that_got_cheaper_is_still_owed(desk):
    """The one that catches a desk out: the price went **down** and the family
    still owes money. Reading it as a refund hands cash to a debtor."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=100)
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["review"]))
    assert (p.verdict, p.amount) == ("collect", 50.0)


# ------------------------------------------------------------ the edges --
def test_a_visit_nobody_charged_for_has_nothing_to_settle(desk):
    """No invoice at all is not the same as an invoice for zero: the second
    is a decision somebody made and the first is an absence."""
    from app.models import Appointment
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt = Appointment(patient_id=desk["ids"]["child"],
                           doctor_id=desk["ids"]["doctor"],
                           appt_date=date(2026, 9, 7), appt_time=time(9, 0),
                           appt_type="exam", status="scheduled")
        desk["db"].session.add(appt)
        desk["db"].session.flush()
        p = settle.propose_cancellation(appt)
    assert p.verdict == "unbilled"
    assert p.amount == 0.0


def test_a_free_visit_that_was_never_paid_asks_for_nothing(desk):
    """Owed nothing, collected nothing. Neither a refund nor a collection."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=None)
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["free"]))
    assert (p.verdict, p.amount) == ("settled", 0.0)


def test_other_lines_on_the_bill_are_left_alone(desk):
    """A vaccine on the same invoice was a separate decision. Correcting the
    visit must not reach it, and must not be paid for out of it."""
    from app.models import InvoiceItem, Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=500)
        desk["db"].session.add(InvoiceItem(
            invoice_id=invoice.id, description="تطعيم", quantity=1,
            unit_price=300))
        desk["db"].session.flush()
        # 200 visit + 300 vaccine = 500 owed, 500 paid. Visit becomes free.
        p = settle.propose_service_change(appt, Service.query.get(desk["ids"]["free"]))
        assert (p.verdict, p.amount) == ("refund", 200.0)
        settle.apply(p, service=Service.query.get(desk["ids"]["free"]))
        vaccine = [i for i in invoice.items if i.description == "تطعيم"][0]
    assert vaccine.unit_price == 300


# -------------------------------------------------- what applying it does --
def test_applying_it_rewrites_the_line_to_what_happened(desk):
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, invoice, item = _billed(desk, paid=200)
        review = Service.query.get(desk["ids"]["review"])
        settle.apply(settle.propose_service_change(appt, review), service=review)
        desk["db"].session.flush()
    assert item.unit_price == 150
    assert item.service_id == review.id
    assert invoice.total == 150


def test_the_doctors_share_follows_the_new_service(desk):
    """40% of 150, not of 200 — and **not zero**. The vaccine settlement zeroes
    commission, which is right for a vaccine and would rob a doctor of their
    cut of a consultation."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, item = _billed(desk, paid=200)
        review = Service.query.get(desk["ids"]["review"])
        settle.apply(settle.propose_service_change(appt, review), service=review)
        desk["db"].session.flush()
    assert item.commission_amount == 60.0


def test_a_visit_that_became_free_earns_no_share(desk):
    """Falls out of the same rule — a percentage of nothing."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, item = _billed(desk, paid=200)
        free = Service.query.get(desk["ids"]["free"])
        settle.apply(settle.propose_service_change(appt, free), service=free)
        desk["db"].session.flush()
    assert item.commission_amount == 0.0


def test_applying_it_moves_no_money(desk):
    """The whole design: it corrects the line, and refunding stays the one
    path it already was. A settlement that paid people would be a second way
    money leaves this clinic."""
    from app.models import Payment, Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=200)
        before = Payment.query.filter_by(invoice_id=invoice.id).count()
        free = Service.query.get(desk["ids"]["free"])
        settle.apply(settle.propose_service_change(appt, free), service=free)
        desk["db"].session.flush()
        after = Payment.query.filter_by(invoice_id=invoice.id).count()
    assert (before, after) == (1, 1)


def test_the_refund_owed_is_what_the_invoice_itself_says(desk):
    """The proposal and the invoice must not be two opinions. After applying,
    the bill's own balance is the number to hand back."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=200)
        review = Service.query.get(desk["ids"]["review"])
        proposal = settle.propose_service_change(appt, review)
        settle.apply(proposal, service=review)
        desk["db"].session.flush()
        owed_back = round(invoice.paid - invoice.total, 2)
    assert owed_back == proposal.amount


def test_an_old_discount_is_not_taken_off_the_new_price(desk):
    """The correction replaces the price outright. A percentage left on the
    line would come off the new service too, for a reason nobody could find."""
    from app.models import Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        appt, _, item = _billed(desk, paid=200)
        item.discount_value = 10
        item.discount_is_percent = True
        desk["db"].session.flush()
        review = Service.query.get(desk["ids"]["review"])
        settle.apply(settle.propose_service_change(appt, review), service=review)
        desk["db"].session.flush()
    assert item.net == 150.0


# ---------------------------------------------------------- the vocabulary --
def test_every_verdict_the_engine_produces_is_declared(desk):
    """The screen renders from ``VERDICTS``; one missing from it renders as a
    blank line exactly where an instruction belongs."""
    from app.models import Service
    from app.utils import service_settlement as settle

    produced = set()
    with desk["app"].app_context():
        for paid, price in ((200, 150), (200, 200), (200, 0), (None, 150),
                            (100, 150), (None, 0)):
            _, _, item = _billed(desk, paid=paid)
            produced.add(settle.propose(item, price).verdict)
        produced.add(settle.propose(None, 0).verdict)
    assert produced == set(settle.VERDICTS)


# ------------------------------------------------ what the board must show --
def test_a_cancelled_paid_visit_is_flagged_on_the_board(desk):
    """The screenshot, as a test: "ملغي" and "مدفوع" on one row with nothing
    said about the money. The badge is true about the collection and silent
    about the thing that needs doing."""
    from app.blueprints.appointments.routes import _payment_status

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        appt.status = "cancelled"
        desk["db"].session.flush()
        snapshot = _payment_status([appt], appt.appt_date)
    assert snapshot[appt.id]["held"] is True


def test_a_no_show_that_was_paid_for_is_flagged_too(desk):
    """Same money, same silence — the family did not come and the cash is
    still on the counter."""
    from app.blueprints.appointments.routes import _payment_status

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        appt.status = "no_show"
        desk["db"].session.flush()
        snapshot = _payment_status([appt], appt.appt_date)
    assert snapshot[appt.id]["held"] is True


def test_a_cancelled_visit_nobody_paid_for_is_not_flagged(desk):
    """Nothing was collected, so there is nothing being held. Flagging it
    would put a warning on every cancellation the clinic ever makes."""
    from app.blueprints.appointments.routes import _payment_status

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=None)
        appt.status = "cancelled"
        desk["db"].session.flush()
        snapshot = _payment_status([appt], appt.appt_date)
    assert snapshot[appt.id]["held"] is False


def test_a_paid_visit_that_is_going_ahead_is_not_flagged(desk):
    """The ordinary row: paid, and happening. Nothing to warn about."""
    from app.blueprints.appointments.routes import _payment_status

    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        snapshot = _payment_status([appt], appt.appt_date)
    assert snapshot[appt.id]["held"] is False


def test_a_cancelled_visit_already_refunded_is_not_flagged(desk):
    """Once the money has gone back the clinic is holding nothing, and a
    warning that stays after it was dealt with is a warning people stop
    reading."""
    from app.models import Payment
    from app.blueprints.appointments.routes import _payment_status

    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=200)
        appt.status = "cancelled"
        desk["db"].session.add(Payment(invoice_id=invoice.id, amount=200,
                                       kind="refund", method="cash"))
        desk["db"].session.flush()
        snapshot = _payment_status([appt], appt.appt_date)
    assert snapshot[appt.id]["held"] is False


# --------------------------------------------- what reception sees and does --
def _signed_in(desk, role="admin"):
    from app.models import User

    with desk["app"].app_context():
        user = User(username="boss", full_name="المدير", role=role,
                    is_active=True)
        user.set_password("secret")
        desk["db"].session.add(user)
        desk["db"].session.commit()
    client = desk["app"].test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)
    return client


def test_the_program_says_the_answer_not_the_arithmetic(desk):
    """Reception picks the service and is told which way the money goes and
    how much — the whole point of the feature."""
    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, review_id = appt.id, desk["ids"]["review"]
    body = _signed_in(desk).get(
        f"/appointments/{appt_id}/service-proposal?service_id={review_id}"
    ).get_json()
    assert body["ok"] is True
    assert body["verdict"] == "refund"
    assert body["amount"] == 50.0
    assert body["says"]          # a sentence, not a bare number


def test_asking_changes_nothing(desk):
    """It is a question. The bill must be untouched until somebody agrees."""
    with desk["app"].app_context():
        appt, invoice, item = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, review_id, invoice_id = appt.id, desk["ids"]["review"], invoice.id
    _signed_in(desk).get(
        f"/appointments/{appt_id}/service-proposal?service_id={review_id}")
    with desk["app"].app_context():
        from app.models import Invoice
        assert Invoice.query.get(invoice_id).total == 200


def test_agreeing_corrects_the_bill(desk):
    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, review_id, invoice_id = appt.id, desk["ids"]["review"], invoice.id
    resp = _signed_in(desk).post(f"/appointments/{appt_id}/change-service",
                                 data={"service_id": review_id})
    assert resp.status_code in (302, 303)
    with desk["app"].app_context():
        from app.models import Invoice
        assert Invoice.query.get(invoice_id).total == 150


def test_money_owed_lands_on_the_till_screen(desk):
    """This route never hands money over. It corrects the line and sends the
    desk to the screen that collects and refunds every other bill — with its
    approval rule, its threshold and its notice to the doctor."""
    with desk["app"].app_context():
        appt, invoice, _ = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, free_id, invoice_id = appt.id, desk["ids"]["free"], invoice.id
    resp = _signed_in(desk).post(f"/appointments/{appt_id}/change-service",
                                 data={"service_id": free_id})
    assert f"/invoice" in resp.headers.get("Location", "")
    with desk["app"].app_context():
        from app.models import Payment
        assert Payment.query.filter_by(invoice_id=invoice_id,
                                       kind="refund").count() == 0


def test_a_change_that_costs_nothing_goes_back_to_the_board(desk):
    """Nothing to hand over, so nobody is sent to the till."""
    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, exam_id = appt.id, desk["ids"]["exam"]
    resp = _signed_in(desk).post(f"/appointments/{appt_id}/change-service",
                                 data={"service_id": exam_id})
    assert "/invoice" not in resp.headers.get("Location", "")


def test_a_visit_with_no_invoice_says_so_rather_than_failing(desk):
    from app.models import Appointment

    with desk["app"].app_context():
        appt = Appointment(patient_id=desk["ids"]["child"],
                           doctor_id=desk["ids"]["doctor"],
                           appt_date=date(2026, 9, 7), appt_time=time(11, 0),
                           appt_type="exam", status="scheduled")
        desk["db"].session.add(appt)
        desk["db"].session.commit()
        appt_id, review_id = appt.id, desk["ids"]["review"]
    body = _signed_in(desk).get(
        f"/appointments/{appt_id}/service-proposal?service_id={review_id}"
    ).get_json()
    assert body["ok"] is False
    assert body["message"]


def test_correcting_a_bill_needs_the_till_capability(desk):
    """It changes what a family owes. A doctor's login is not a door to that."""
    with desk["app"].app_context():
        appt, _, _ = _billed(desk, paid=200)
        desk["db"].session.commit()
        appt_id, review_id = appt.id, desk["ids"]["review"]
    client = desk["app"].test_client()
    client.post("/login", data={"username": "doc", "password": "secret"},
                follow_redirects=True)
    resp = client.post(f"/appointments/{appt_id}/change-service",
                       data={"service_id": review_id})
    assert resp.status_code in (302, 401, 403)
    with desk["app"].app_context():
        from app.models import Invoice
        assert Invoice.query.first().total == 200
