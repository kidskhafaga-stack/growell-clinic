"""A family who paid on Thursday for a Saturday appointment, twice asked to pay.

Reported from the desk, with the two screens side by side:

    "حجزت حالة النهارده 9/3/2026 وعمل تحصيل ومفيش للدكتور موعد غير يوم
     5/9/2026 وعملت تحصيل من «شاشة التحصيل» ومسمعتش انها دفعت. وظاهرة بدون
     خدمات انى احصل — ده ايه الباج ده ولا علشان مش فاتح وردية؟"

Not the shift. The shift gate says so in its own words when it is what stops
you, and it said nothing here.

**Two screens, two rules.** The board matched a patient's invoices **by
date** — the date being shown, or any invoice still outstanding. The money was
taken on Thursday, for an appointment on Saturday, and the invoice carries the
day the money was taken. So on the Saturday board the invoice matched neither
half of that rule, and the row read *"بدون فاتورة"* with a Collect button
beside it. Pressing it opened the collect screen, which asks a different
question — is there an invoice today to append to — found one, and refused:
*"كل اللي الزيارة دي بتحصّله موجود فعلاً على فاتورة INV-2026-0020"*.

Both screens were right on their own terms. What was missing is the fact
underneath them: **nothing recorded which appointment a bill was raised for.**
The board was guessing from a date, and a date is exactly what differs when a
family pays in advance.

So the invoice now carries the appointment, and the board asks that first. The
old date rule stays as the answer for every invoice raised before the link
existed — a clinic upgrading does not lose the badge on its history.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """An appointment two days out — the doctor's next free day."""
    from app.models import Appointment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        saturday = local_today() + timedelta(days=2)
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=saturday,
                           appt_time=__import__("datetime").time(15, 0),
                           status="scheduled", appt_type="consultation")
        clinic["db"].session.add(appt)
        # A shift open at the till. Without one the program refuses to collect
        # at all and says so — *"افتح ورديتك أولاً قبل أي تحصيل"* — which is
        # the other thing this bug was suspected of being, and is not: the gate
        # speaks in its own words when it is the thing stopping you.
        from app.models import CashierShift

        clinic["db"].session.add(CashierShift(
            opened_by=clinic["ids"]["admin"], opening_float=0, status="open"))
        clinic["db"].session.commit()
        clinic["appt_id"] = appt.id
        clinic["saturday"] = saturday
    return clinic


def _collect(clinic, appt_id, amount="200"):
    """Pay at the desk today, from the collect screen, for that appointment."""
    return clinic["sign_in"]("boss").post(
        f"/finance/checkout/{appt_id}",
        data={"line_desc": ["كشف"], "line_service_id": [clinic["ids"]["exam"]],
              "line_price": [amount], "line_qty": ["1"],
              "line_no_commission": ["0"], "line_brand_id": [""],
              "line_dose_id": [""], "line_vs_id": [""],
              "line_dose_number": [""], "discount_id": "none",
              "amount": [amount], "method": ["cash"]},
        follow_redirects=True)


def _board(clinic, on_date):
    page = clinic["sign_in"]("boss").get(
        f"/appointments/?date={on_date.isoformat()}")
    assert page.status_code == 200
    return page.get_data(as_text=True)


# ------------------------------------------------------------ the fact ------
def test_an_invoice_records_which_appointment_it_was_raised_for(desk):
    from app.models import Invoice

    _collect(desk, desk["appt_id"])
    with desk["app"].app_context():
        invoice = Invoice.query.order_by(Invoice.id.desc()).first()
        assert invoice is not None
        assert invoice.appointment_id == desk["appt_id"]


def test_the_link_is_optional_because_money_arrives_without_an_appointment(desk):
    """A walk-in, a vaccine, a bill settled a week later. The column is
    nullable and always will be."""
    from app.models import Invoice

    assert Invoice.__table__.c.appointment_id.nullable

    desk["sign_in"]("boss").post(
        f"/finance/collect/{desk['ids']['child']}",
        data={"line_desc": ["كشف"], "line_service_id": [desk["ids"]["exam"]],
              "line_price": ["200"], "line_qty": ["1"],
              "line_no_commission": ["0"], "line_brand_id": [""],
              "line_dose_id": [""], "line_vs_id": [""],
              "line_dose_number": [""], "discount_id": "none",
              "amount": ["200"], "method": ["cash"]},
        follow_redirects=True)
    with desk["app"].app_context():
        assert Invoice.query.order_by(Invoice.id.desc()).first().appointment_id is None


# --------------------------------------------------------- the reported bug --
def test_the_saturday_board_knows_the_family_already_paid_on_thursday(desk):
    """The bug as reported, end to end."""
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    _collect(desk, desk["appt_id"])

    with desk["app"].app_context():
        appt = Appointment.query.get(desk["appt_id"])
        state = _payment_status([appt], desk["saturday"])[appt.id]
        assert state["state"] == "paid", (
            "the board still reads the Saturday row as unbilled, and will "
            "offer to collect money the family has already handed over")
        assert state["balance"] == 0


def test_and_the_row_stops_offering_to_collect_it_again(desk):
    """The badge is what reception reads; the button is what they press."""
    from app.i18n import t

    with desk["app"].test_request_context("/"):
        no_invoice = t("appointments.pay_none")
        paid = t("appointments.pay_paid")

    before = _board(desk, desk["saturday"])
    assert no_invoice in before          # nothing collected yet — fair enough

    _collect(desk, desk["appt_id"])
    after = _board(desk, desk["saturday"])
    assert paid in after
    assert f"/finance/checkout?appt_id={desk['appt_id']}" not in after


def test_a_part_payment_still_shows_what_is_left(desk):
    """The link must not flatten every linked invoice to "paid"."""
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    _collect(desk, desk["appt_id"], amount="200")
    with desk["app"].app_context():
        from app.models import Invoice, Payment

        invoice = Invoice.query.order_by(Invoice.id.desc()).first()
        # Take the payment back off and leave half of it.
        for payment in list(invoice.payments):
            desk["db"].session.delete(payment)
        desk["db"].session.flush()
        invoice.payments.append(Payment(amount=50, method="cash"))
        invoice.recalc_status()
        desk["db"].session.commit()

        appt = Appointment.query.get(desk["appt_id"])
        state = _payment_status([appt], desk["saturday"])[appt.id]
        assert state["state"] == "partial"
        assert state["balance"] == 150


def test_an_appointment_nobody_billed_still_reads_as_unbilled(desk):
    """The other half. A row that says "paid" for an appointment nobody
    collected for is the worse failure of the two, and the link must not
    create it: a second child of the same family, or a second appointment,
    borrows nothing from this one's invoice."""
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment

    _collect(desk, desk["appt_id"])

    with desk["app"].app_context():
        second = Appointment(patient_id=desk["ids"]["child"],
                             doctor_id=desk["ids"]["doctor"],
                             appt_date=desk["saturday"] + timedelta(days=7),
                             appt_time=__import__("datetime").time(16, 0),
                             status="scheduled", appt_type="consultation")
        desk["db"].session.add(second)
        desk["db"].session.commit()

        state = _payment_status([second], second.appt_date)[second.id]
        assert state["state"] == "none", (
            "next week's appointment is reading this week's invoice as its own")


def test_a_settled_row_does_not_borrow_last_months_debt(desk):
    """What the link is *for*, beyond the date.

    The family owe for a visit last month and have paid for Saturday. The
    Saturday row is about Saturday: it reads paid. Before the link there was
    nothing to tell the two bills apart, so the row took the worst state of
    everything the patient owed and showed "Collect" on a settled appointment.

    The old debt is not lost — it reaches the cashier through every row that
    has no invoice of its own, which is the test below.
    """
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment, Invoice, InvoiceItem
    from app.utils.clock import local_today

    _collect(desk, desk["appt_id"])
    with desk["app"].app_context():
        old_bill = Invoice(invoice_number="INV-OLD-9",
                           patient_id=desk["ids"]["child"],
                           doctor_id=desk["ids"]["doctor"],
                           invoice_date=local_today() - timedelta(days=30))
        desk["db"].session.add(old_bill)
        desk["db"].session.flush()
        old_bill.items.append(InvoiceItem(description="كشف الشهر اللي فات",
                                          unit_price=300, quantity=1))
        old_bill.recalc_status()
        desk["db"].session.commit()

        appt = Appointment.query.get(desk["appt_id"])
        state = _payment_status([appt], desk["saturday"])[appt.id]
        assert state["state"] == "paid", (
            "a settled appointment is showing last month's debt as its own")


def test_a_bill_already_open_today_claims_the_appointment_when_it_is_used(desk):
    """One invoice per day: a walk-in charge raised this morning, then the
    appointment collected onto the same bill. The bill takes the appointment
    it was actually used for, so the board can find it afterwards."""
    from app.models import Invoice

    # A walk-in charge first — no appointment on it.
    desk["sign_in"]("boss").post(
        f"/finance/collect/{desk['ids']['child']}",
        data={"line_desc": ["جلسة تنفس"],
              "line_service_id": [desk["ids"]["nebul"]],
              "line_price": ["150"], "line_qty": ["1"],
              "line_no_commission": ["0"], "line_brand_id": [""],
              "line_dose_id": [""], "line_vs_id": [""],
              "line_dose_number": [""], "discount_id": "none",
              "amount": ["150"], "method": ["cash"]},
        follow_redirects=True)
    with desk["app"].app_context():
        first = Invoice.query.order_by(Invoice.id.desc()).first()
        assert first.appointment_id is None

    _collect(desk, desk["appt_id"])
    with desk["app"].app_context():
        # Still one invoice for the day, and it now names the appointment.
        assert Invoice.query.count() == 1
        assert Invoice.query.first().appointment_id == desk["appt_id"]


def test_a_bill_already_raised_for_one_appointment_is_not_re_pointed(desk):
    """The other direction: a second appointment collected onto the same day's
    invoice does not quietly move the first one's money onto its own row."""
    from app.models import Appointment, Invoice

    _collect(desk, desk["appt_id"])
    with desk["app"].app_context():
        second = Appointment(patient_id=desk["ids"]["child"],
                             doctor_id=desk["ids"]["doctor"],
                             appt_date=desk["saturday"],
                             appt_time=__import__("datetime").time(16, 30),
                             status="scheduled", appt_type="consultation")
        desk["db"].session.add(second)
        desk["db"].session.commit()
        second_id = second.id

    _collect(desk, second_id, amount="100")
    with desk["app"].app_context():
        assert Invoice.query.first().appointment_id == desk["appt_id"]


# ------------------------------------------------- nothing else regressed ---
def test_an_invoice_raised_before_the_link_existed_still_shows_on_the_board(desk):
    """A clinic upgrading into this does not lose the badge on its history:
    the date rule stays for every invoice with no appointment on it."""
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment, Invoice

    _collect(desk, desk["appt_id"])
    with desk["app"].app_context():
        invoice = Invoice.query.order_by(Invoice.id.desc()).first()
        invoice.appointment_id = None                # as an old row would be
        invoice.invoice_date = desk["saturday"]      # collected on the day
        desk["db"].session.commit()

        appt = Appointment.query.get(desk["appt_id"])
        state = _payment_status([appt], desk["saturday"])[appt.id]
        assert state["state"] == "paid"


def test_an_outstanding_balance_from_another_day_still_reaches_the_cashier(desk):
    """The rule that was there for a reason: a lingering due shows up on the
    board so it is not silently forgotten."""
    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment, Invoice, InvoiceItem
    from app.utils.clock import local_today

    with desk["app"].app_context():
        old = Invoice(invoice_number="INV-OLD-1",
                      patient_id=desk["ids"]["child"],
                      doctor_id=desk["ids"]["doctor"],
                      invoice_date=local_today() - timedelta(days=30))
        desk["db"].session.add(old)
        desk["db"].session.flush()
        old.items.append(InvoiceItem(description="كشف قديم", unit_price=200,
                                     quantity=1))
        old.recalc_status()
        desk["db"].session.commit()

        appt = Appointment.query.get(desk["appt_id"])
        state = _payment_status([appt], desk["saturday"])[appt.id]
        assert state["state"] == "unpaid"
        assert state["balance"] == 200


def test_the_board_still_costs_one_query_for_the_payment_snapshot(desk):
    """It was one query for the whole board and it stays one: this added a
    branch to the same statement, not a second statement, and certainly not
    one per row."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from app.blueprints.appointments.routes import _payment_status
    from app.models import Appointment, Patient
    from app.utils.clock import local_today

    with desk["app"].app_context():
        appts = [Appointment.query.get(desk["appt_id"])]
        for i in range(12):
            child = Patient(patient_number=f"Q{i:03d}", full_name=f"طفل {i}",
                            gender="male", is_active=True,
                            date_of_birth=local_today() - timedelta(days=900))
            desk["db"].session.add(child)
            desk["db"].session.flush()
            row = Appointment(patient_id=child.id,
                              doctor_id=desk["ids"]["doctor"],
                              appt_date=desk["saturday"],
                              appt_time=__import__("datetime").time(9, i),
                              status="scheduled", appt_type="consultation")
            desk["db"].session.add(row)
            appts.append(row)
        desk["db"].session.commit()

        seen = []

        def record(conn, cursor, statement, params, context, many):
            if "FROM invoices" in statement:
                seen.append(statement)

        event.listen(Engine, "before_cursor_execute", record)
        try:
            _payment_status(appts, desk["saturday"])
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert len(seen) == 1, (
            f"{len(seen)} invoice queries for {len(appts)} appointments")
