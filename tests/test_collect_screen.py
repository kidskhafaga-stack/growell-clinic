"""Collecting money with a family standing at the desk.

Item 12, the rest of it. Four complaints about the collection screen, and they
turned out to be three symptoms of one thing plus a gate that fired too late.

Reception's **"collect now"** opened `finance.invoice_new` — the invoice
*builder*. That screen has a patient dropdown to choose from, a doctor dropdown,
blank lines, and **no payment section at all**: you saved an invoice, opened it,
and paid from a third screen. Which accounts for three of the four:

* *"the patient's and doctor's names should show after 'collect'"* — on the
  builder the patient is a `<select>`, not a heading;
* *"it shouldn't be chosen from scratch with the patient standing there"* —
  that is what a builder is;
* *"the multi-payment screen should be the one that shows"* — the builder has
  no payment on it, and the checkout screen already had split payment.

So there is nothing new to design: **the checkout screen already existed**, it
was just unreachable unless the patient happened to have an appointment. It
takes a patient now as well.

And the fourth: *"the 'open the shift' message should be clear."* It fired on
**submit** — the cashier filled in the whole form with a family at the desk,
pressed collect, and got the form thrown away and a redirect. A refusal that
arrives after the work is a refusal that costs the work. It is said on arrival
now, with the button to fix it.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def owing(clinic):
    """A patient with an unbilled procedure — somebody reception owes a bill."""
    from app.models import Service, VisitService

    with clinic["app"].app_context():
        svc = clinic["db"].session.get(Service, clinic["ids"]["nebul"])
        clinic["db"].session.add(VisitService(
            visit_id=clinic["ids"]["visit"], service_id=svc.id,
            name=svc.name, quantity=1))
        clinic["db"].session.commit()
    return clinic


@pytest.fixture()
def desk(clinic):
    return clinic["sign_in"]("desk")


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ============================== one screen, reachable both ways =============
def test_a_patient_can_be_collected_from_without_an_appointment(owing, desk):
    """The checkout already existed and was already right. It was unreachable
    unless the patient happened to have an appointment booked."""
    reply = desk.get(f"/finance/collect/{owing['ids']['child']}")
    assert reply.status_code == 200


def test_the_names_are_words_at_the_top_not_a_dropdown(owing, desk):
    """On the builder the patient was a `<select>` you had to pick from, with
    the family in front of you."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    head = body[:body.index("</h1>") + 400] if "</h1>" in body else body
    assert "طفل" in head
    assert 'name="patient_id"' not in body, "still asking who this is for"


def test_the_bill_arrives_filled_in(owing, desk):
    """Nothing to choose from scratch: what is owed is already on the screen."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert "جلسة تنفس" in body


def test_the_payment_section_is_on_the_same_screen(owing, desk):
    """The builder had none — you saved, reopened, and paid from a third
    screen. Three screens with a family waiting."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert 'name="amount"' in body and 'name="method"' in body
    with owing["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.add_method") in body, "no way to split the payment"


def test_reception_is_sent_to_the_checkout_not_the_builder(owing):
    body = _read("app", "templates", "finance", "cashier.html")
    assert "finance.collect" in body
    assert "finance.invoice_new" not in body


def test_the_appointment_door_still_works(owing, desk, clinic):
    """Two ways in, one screen. Breaking the older door to open a new one
    would be trading one complaint for another."""
    from app.models import Appointment

    with clinic["app"].app_context():
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=date.today(), appt_time=time(10, 0),
                           appt_type="new", status="scheduled")
        clinic["db"].session.add(appt)
        clinic["db"].session.commit()
        appt_id = appt.id

    assert desk.get(f"/finance/checkout/{appt_id}").status_code == 200


def test_each_door_posts_back_to_itself(owing, desk):
    """A form that posts to the other door would lose the patient on a
    validation bounce."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert f"/finance/collect/{owing['ids']['child']}" in body


# ==================================================== the money still works =
def test_collecting_from_a_patient_takes_the_money(owing, desk, clinic):
    from app.models import Invoice

    with clinic["app"].app_context():
        from app.models import CashierShift
        clinic["db"].session.add(CashierShift(
            opened_by=clinic["ids"]["desk"], opening_float=0, status="open"))
        clinic["db"].session.commit()

    desk.post(f"/finance/collect/{owing['ids']['child']}", data={
        "line_desc": "جلسة تنفس", "line_service_id": str(clinic["ids"]["nebul"]),
        "line_price": "150", "line_qty": "1", "line_no_commission": "0",
        "line_brand_id": "", "line_dose_id": "", "line_vs_id": "",
        "line_dose_number": "",
        "amount": "150", "method": "cash", "discount_id": "none",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        invoice = Invoice.query.filter_by(
            patient_id=clinic["ids"]["child"]).order_by(Invoice.id.desc()).first()
        assert invoice is not None
        assert invoice.total == 150
        assert invoice.paid == 150


def test_the_vaccine_picker_is_on_the_screen_reception_uses(owing, desk):
    """It went onto the invoice builder first — the screen this change exists
    to keep them off."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert "addVaccine()" in body
    assert "vaccineId" in body


# ================================================ the gate, said in time ====
def test_the_shift_warning_shows_on_arrival(owing, desk):
    """It fired on submit: the whole form filled in with a family at the desk,
    then thrown away with a redirect. A refusal that arrives after the work is
    a refusal that costs the work."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    with owing["app"].test_request_context("/"):
        from app.i18n import t
        assert t("shifts.gate_blocked") in body


def test_the_warning_carries_the_way_to_fix_it(owing, desk):
    """Telling somebody what is wrong without telling them where to go is the
    same message in a nicer font."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert "#shift" in body
    assert "shift" in _read("app", "templates", "finance", "cashier.html")


def test_no_warning_once_a_shift_is_open(owing, desk, clinic):
    """A banner that is always there is furniture."""
    from app.models import CashierShift

    with clinic["app"].app_context():
        clinic["db"].session.add(CashierShift(
            opened_by=clinic["ids"]["desk"], opening_float=0, status="open"))
        clinic["db"].session.commit()

    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("shifts.gate_blocked") not in body


def test_the_gate_still_refuses_cash_at_the_last_moment(owing, desk, clinic):
    """The warning is a courtesy, not the rule. Somebody who ignores it — or
    whose shift closed in another tab while they typed — must still not put
    cash in a drawer that belongs to no shift."""
    from app.models import Invoice

    desk.post(f"/finance/collect/{owing['ids']['child']}", data={
        "line_desc": "جلسة تنفس", "line_service_id": str(clinic["ids"]["nebul"]),
        "line_price": "150", "line_qty": "1", "line_no_commission": "0",
        "line_brand_id": "", "line_dose_id": "", "line_vs_id": "",
        "line_dose_number": "",
        "amount": "150", "method": "cash", "discount_id": "none",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        paid = [i for i in Invoice.query.all() if i.paid > 0]
        assert not paid, "cash was taken with no open shift"


def test_a_card_payment_is_not_held_up_by_the_cash_drawer(owing, desk, clinic):
    """Refusing an InstaPay payment because the cash drawer is shut is
    refusing money for no reason — it never touches the drawer."""
    from app.models import Invoice

    desk.post(f"/finance/collect/{owing['ids']['child']}", data={
        "line_desc": "جلسة تنفس", "line_service_id": str(clinic["ids"]["nebul"]),
        "line_price": "150", "line_qty": "1", "line_no_commission": "0",
        "line_brand_id": "", "line_dose_id": "", "line_vs_id": "",
        "line_dose_number": "",
        "amount": "150", "method": "instapay", "discount_id": "none",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        invoice = Invoice.query.filter_by(
            patient_id=clinic["ids"]["child"]).order_by(Invoice.id.desc()).first()
        assert invoice is not None and invoice.paid == 150
