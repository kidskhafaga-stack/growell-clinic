"""A service changed on a bill — priced like the till, by whoever may, on paper.

``MONEY_SAFETY_PLAN.md`` ف-٨. The owner: *«طريقة تحويل او تغيير الكشف الى
استشارة اوي اي خدمة تانيه وحساب الفرق والحته دي مش شغاله صح ولازم تكون
بصلحيات»*, and then *«عايز ادخله فى ويزر ويطبع ايصال بالارجاع او بدفع فرق
الفلوس … ويبقى متضمن رقم ايصال الخدمة الاصلية ورقم الارجاع»*.

What was measured on the program before the fix, each now a test:

* the doctor's own price was ignored (a 300 consultation turned into a 180
  review refunded 200, not 120);
* a covered child's insurer share was wiped — the family was charged the
  whole new service and the claim kept the old figure;
* the family's named discount fell off the corrected line;
* a second booking the same day — collected onto the first one's bill — read
  «nothing was charged»;
* a bill in a closed month was rewritten;
* the bill's journal entry kept the old total;
* anybody at the till could do it.
"""
import os
import sys
from datetime import time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """The clinic's 200 consultation (`exam`), and a 100 review."""
    from app.extensions import db
    from app.models import Service
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        exam = db.session.get(Service, clinic["ids"]["exam"])
        exam.visit_type = "new"
        review = Service(name="استشارة", category="consultation", price=100,
                         commission_type="percent", commission_value=40,
                         is_active=True, visit_type="followup")
        db.session.add(review)
        seed_accounts()
        from app.utils.accounting import ensure_seeded
        ensure_seeded()          # the chart, so the journal can be read
        db.session.commit()
        clinic["ids"]["review"] = review.id
    return clinic


def _bill(c, paid=None, unit_price=200, appt_type="new", on=None):
    """A booking and its bill: one consultation line, and what was paid."""
    from app.extensions import db
    from app.models import Appointment, Invoice, InvoiceItem, Payment, Service
    from app.utils.finance import generate_invoice_number

    ids = c["ids"]
    on = on or local_today()
    exam = db.session.get(Service, ids["exam"])
    appt = Appointment(patient_id=ids["child"], doctor_id=ids["doctor"],
                       appt_date=on, appt_time=time(15, 0),
                       appt_type=appt_type, status="scheduled")
    db.session.add(appt)
    db.session.flush()
    inv = Invoice(invoice_number=generate_invoice_number(),
                  patient_id=ids["child"], doctor_id=ids["doctor"],
                  appointment_id=appt.id, invoice_date=on)
    db.session.add(inv)
    db.session.flush()
    item = InvoiceItem(invoice_id=inv.id, service_id=exam.id,
                       description=exam.name, quantity=1,
                       unit_price=unit_price)
    db.session.add(item)
    if paid:
        db.session.add(Payment(invoice_id=inv.id, amount=paid, kind="payment",
                               method="cash"))
    db.session.flush()
    return appt, inv, item


def _review(c):
    from app.extensions import db
    from app.models import Service

    return db.session.get(Service, c["ids"]["review"])


# ------------------------------------------------- priced like the till ----
def test_the_doctors_own_prices_decide_the_difference(desk):
    from app.extensions import db
    from app.models import DoctorServiceCommission
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        ids = desk["ids"]
        for key, price in (("exam", 300), ("review", 180)):
            db.session.add(DoctorServiceCommission(
                doctor_id=ids["doctor"], service_id=ids[key],
                commission_type="percent", commission_value=40,
                price_override=price))
        appt, _, _ = _bill(desk, paid=300, unit_price=300)
        p = settle.propose_service_change(appt, _review(desk))
        assert (p.verdict, p.amount) == ("refund", 120.0)
        assert (p.before["price"], p.after["price"]) == (300, 180)


@pytest.fixture()
def covered(desk):
    """An insurer paying 80% of both services, and the child's card."""
    from app.extensions import db
    from app.models import (PatientCoverage, PayerContract, PayerEntity,
                            PayerServiceRate)

    with desk["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance",
                            is_active=True)
        db.session.add(payer)
        db.session.flush()
        for key in ("exam", "review"):
            db.session.add(PayerServiceRate(
                payer_id=payer.id, service_id=desk["ids"][key],
                coverage_type="percent", coverage_value=80))
        db.session.add(PayerContract(
            payer_id=payer.id, number="C-1",
            start_date=local_today() - timedelta(days=100),
            end_date=local_today() + timedelta(days=100), is_active=True))
        db.session.add(PatientCoverage(
            patient_id=desk["ids"]["child"], payer_id=payer.id,
            membership_number="M-1", is_active=True))
        db.session.commit()
    return desk


def test_a_covered_child_keeps_the_insurers_share(covered):
    """200 consultation at 80%: the family paid 40. As a 100 review the
    insurer pays 80 and the family 20 — 20 goes back, and the claim says 80."""
    from app.extensions import db
    from app.models import Patient
    from app.utils import billing
    from app.utils import service_settlement as settle

    with covered["app"].app_context():
        appt, inv, item = _bill(covered, paid=40)
        billing.apply_coverage(inv, db.session.get(Patient,
                                                   covered["ids"]["child"]))
        db.session.flush()
        assert (item.net, item.payer_amount) == (40, 160)
        p = settle.propose_service_change(appt, _review(covered))
        assert (p.verdict, p.amount) == ("refund", 20.0)
        assert (p.after["payer"], p.after["family"]) == (80, 20)
        settle.apply(p, service=_review(covered))
        db.session.flush()
        assert (item.net, item.payer_amount) == (20, 80)


def test_the_familys_named_discount_comes_with_it(desk):
    """A staff family's 10% (a named discount on the bill) paid 180 on the
    200 consultation; on the 100 review they owe 90 — 90 goes back."""
    from app.extensions import db
    from app.models import NamedDiscount
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        staff = NamedDiscount(name="موظفين", value=10, is_percent=True,
                              scope="all", is_active=True)
        db.session.add(staff)
        db.session.flush()
        appt, inv, item = _bill(desk, paid=180)
        inv.discount_id = staff.id
        item.discount_value = 20
        db.session.flush()
        p = settle.propose_service_change(appt, _review(desk))
        assert (p.verdict, p.amount) == ("refund", 90.0)


def test_a_second_booking_the_same_day_finds_its_line(desk):
    """One bill per family per day keeps the first booking's number; the
    second booking was billed all the same."""
    from app.extensions import db
    from app.models import Appointment, InvoiceItem, Service
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        _, inv, _ = _bill(desk, paid=400)
        exam = db.session.get(Service, desk["ids"]["exam"])
        db.session.add(InvoiceItem(invoice_id=inv.id, service_id=exam.id,
                                   description=exam.name, quantity=1,
                                   unit_price=200))
        later = Appointment(patient_id=desk["ids"]["child"],
                            doctor_id=desk["ids"]["doctor"],
                            appt_date=local_today(), appt_time=time(18, 0),
                            appt_type="new", status="scheduled")
        db.session.add(later)
        db.session.flush()
        p = settle.propose_service_change(later, _review(desk))
        assert p.verdict == "refund" and p.amount == 100.0


def test_asking_changes_nothing(desk):
    from app.extensions import db
    from app.models import Invoice

    with desk["app"].app_context():
        _, inv, item = _bill(desk, paid=200)
        db.session.commit()
        inv_id, item_id = inv.id, item.id
    page = desk["sign_in"]("boss").get(
        f"/finance/invoices/{inv_id}/change-service"
        f"?item_id={item_id}&service_id={desk['ids']['review']}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-verdict="refund"' in html and "data-svcfix-confirm" in html
    with desk["app"].app_context():
        assert db.session.get(Invoice, inv_id).total == 200


# ------------------------------------------------------ who, and when ----
def test_the_till_alone_is_not_enough(desk):
    """Reception collects; changing what a family was charged is a price
    decision. Without ``service_change``: no wizard, no button."""
    from app.extensions import db
    from app.models import Invoice

    with desk["app"].app_context():
        appt, inv, item = _bill(desk, paid=200)
        db.session.commit()
        inv_id, item_id, appt_id = inv.id, item.id, appt.id
    client = desk["sign_in"]("desk")
    url = (f"/finance/invoices/{inv_id}/change-service?item_id={item_id}"
           f"&service_id={desk['ids']['review']}")
    assert client.get(url).status_code == 403
    assert client.post(url, data={"reason": "x"}).status_code == 403
    client.post(f"/appointments/{appt_id}/change-service",
                data={"service_id": desk["ids"]["review"]})
    with desk["app"].app_context():
        assert db.session.get(Invoice, inv_id).total == 200


def test_a_receptionist_granted_it_files_a_refund_for_a_manager(desk):
    """Granted to one person, it works — and the refund waits for a manager
    like every refund; approving it settles the voucher."""
    from app.extensions import db
    from app.models import (Payment, RefundRequest, ServiceChange,
                            UserCapability)

    with desk["app"].app_context():
        db.session.add(UserCapability(user_id=desk["ids"]["desk"],
                                      capability="service_change"))
        _, inv, item = _bill(desk, paid=200)
        db.session.commit()
        inv_id, item_id = inv.id, item.id
    client = desk["sign_in"]("desk")
    resp = client.post(f"/finance/invoices/{inv_id}/change-service",
                       data={"item_id": item_id,
                             "service_id": desk["ids"]["review"],
                             "reason": "متابعة", "method": "cash"})
    assert resp.status_code == 302
    with desk["app"].app_context():
        change = ServiceChange.query.one()
        req = RefundRequest.query.one()
        assert (change.status, change.refund_request_id, req.amount) == \
            ("awaiting_approval", req.id, 100.0)
        assert change.number in req.reason
        assert Payment.query.filter_by(kind="refund").count() == 0
        req_id = req.id
    desk["sign_in"]("boss").post(f"/finance/refund-requests/{req_id}/decide",
                                 data={"decision": "approve"})
    with desk["app"].app_context():
        change = ServiceChange.query.one()
        assert change.status == "settled" and change.payment_id


def test_a_closed_month_is_not_rewritten(desk):
    from app.extensions import db
    from app.models import Invoice, ServiceChange
    from app.utils import periods
    from app.utils import service_settlement as settle

    with desk["app"].app_context():
        last_month = (local_today().replace(day=1) - timedelta(days=1))
        appt, inv, item = _bill(desk, paid=200, on=last_month)
        periods.close_period(periods.ensure_month(last_month.year,
                                                  last_month.month))
        db.session.commit()
        p = settle.propose_service_change(appt, _review(desk))
        assert p.blocked
        assert settle.apply(p, service=_review(desk)) is None
        inv_id, item_id = inv.id, item.id
    client = desk["sign_in"]("boss")
    page = client.get(f"/finance/invoices/{inv_id}/change-service?item_id="
                      f"{item_id}&service_id={desk['ids']['review']}")
    assert "data-svcfix-blocked" in page.get_data(as_text=True)
    client.post(f"/finance/invoices/{inv_id}/change-service",
                data={"item_id": item_id, "service_id": desk["ids"]["review"],
                      "reason": "x"})
    with desk["app"].app_context():
        assert db.session.get(Invoice, inv_id).total == 200
        assert ServiceChange.query.count() == 0


# ------------------------------------------------ the money and the paper ----
def _change(desk, service_key, **form):
    from app.extensions import db

    with desk["app"].app_context():
        _, inv, item = _bill(desk, paid=200)
        db.session.commit()
        inv_id, item_id = inv.id, item.id
    resp = desk["sign_in"]("boss").post(
        f"/finance/invoices/{inv_id}/change-service",
        data=dict({"item_id": item_id, "service_id": desk["ids"][service_key],
                   "reason": "متابعة مش كشف", "method": "cash"}, **form))
    return inv_id, resp


def test_an_admin_refund_is_given_back_and_printed_with_both_numbers(desk):
    from app.extensions import db
    from app.models import Invoice, JournalEntry, ServiceChange

    inv_id, resp = _change(desk, "review")
    assert "/service-changes/" in resp.headers["Location"]
    with desk["app"].app_context():
        change = ServiceChange.query.one()
        inv = db.session.get(Invoice, inv_id)
        assert change.number == "SC-000001"
        assert (change.status, change.difference) == ("settled", -100.0)
        assert change.payment.kind == "refund" and change.payment.amount == 100
        assert change.number in change.payment.notes
        assert (inv.total, inv.paid) == (100, 100)
        # The bill's journal entry follows the corrected bill.
        entry = JournalEntry.query.filter_by(source_type="invoice",
                                             source_id=inv_id).one()
        assert round(sum(line.debit for line in entry.lines), 2) == 100
        number, change_id = inv.invoice_number, change.id
    client = desk["sign_in"]("boss")
    voucher = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "SC-000001" in voucher and number in voucher
    assert 'data-voucher-kind="refund"' in voucher
    assert "100.00" in voucher
    # And on the A4 bill.
    bill = client.get(f"/finance/invoices/{inv_id}").get_data(as_text=True)
    assert 'data-service-change="SC-000001"' in bill
    assert f"/finance/service-changes/{change_id}/receipt" in bill


def test_a_dearer_service_collects_the_difference_and_says_so(desk):
    from app.extensions import db
    from app.models import Payment, Service, ServiceChange, Setting

    with desk["app"].app_context():
        longer = Service(name="زيارة ممتدة", category="consultation",
                         price=300, is_active=True)
        db.session.add(longer)
        # Cash goes in a drawer inside an open shift where the clinic asks
        # for one (the default); this clinic does not.
        Setting.set("require_shift_to_collect", "0")
        db.session.commit()
        desk["ids"]["long"] = longer.id
    inv_id, resp = _change(desk, "long", collect_now="1")
    with desk["app"].app_context():
        change = ServiceChange.query.one()
        pay = db.session.get(Payment, change.payment_id)
        assert (change.status, change.difference) == ("settled", 100.0)
        assert (pay.kind, pay.amount) == ("payment", 100.0)
    voucher = desk["sign_in"]("boss").get(resp.headers["Location"])
    assert 'data-voucher-kind="collect"' in voucher.get_data(as_text=True)


def test_a_difference_left_to_collect_is_owed_on_the_bill(desk):
    from app.extensions import db
    from app.models import Invoice, Service, ServiceChange

    with desk["app"].app_context():
        longer = Service(name="زيارة ممتدة", category="consultation",
                         price=300, is_active=True)
        db.session.add(longer)
        db.session.commit()
        desk["ids"]["long"] = longer.id
    inv_id, _ = _change(desk, "long")
    with desk["app"].app_context():
        change = ServiceChange.query.one()
        assert (change.status, change.payment_id) == ("owed", None)
        assert db.session.get(Invoice, inv_id).balance == 100


def test_cash_is_refused_with_no_shift_open_and_nothing_changes(desk):
    """The clinic's rule for cash at the till holds here too — refused before
    the bill is touched."""
    from app.extensions import db
    from app.models import Invoice, Service, ServiceChange

    with desk["app"].app_context():
        longer = Service(name="زيارة ممتدة", category="consultation",
                         price=300, is_active=True)
        db.session.add(longer)
        db.session.commit()
        desk["ids"]["long"] = longer.id
    inv_id, _ = _change(desk, "long", collect_now="1")
    with desk["app"].app_context():
        assert ServiceChange.query.count() == 0
        assert db.session.get(Invoice, inv_id).total == 200


def test_a_reason_is_required(desk):
    from app.models import ServiceChange

    _change(desk, "review", reason="")
    with desk["app"].app_context():
        assert ServiceChange.query.count() == 0


def test_any_line_of_any_bill_not_only_a_booking(desk):
    """The door is on the bill — the clinic's and a stay's alike: a bill with
    two lines and no booking, the second line changed, the first untouched."""
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, Service

    with desk["app"].app_context():
        _, inv, first = _bill(desk, paid=350)
        inv.appointment_id = None
        nebul = db.session.get(Service, desk["ids"]["nebul"])
        second = InvoiceItem(invoice_id=inv.id, service_id=nebul.id,
                             description=nebul.name, quantity=1,
                             unit_price=150)
        db.session.add(second)
        db.session.commit()
        inv_id, first_id, second_id = inv.id, first.id, second.id
    client = desk["sign_in"]("boss")
    bill = client.get(f"/finance/invoices/{inv_id}").get_data(as_text=True)
    assert f'data-change-service="{second_id}"' in bill
    client.post(f"/finance/invoices/{inv_id}/change-service",
                data={"item_id": second_id, "service_id": desk["ids"]["review"],
                      "reason": "x", "method": "cash"})
    with desk["app"].app_context():
        assert db.session.get(InvoiceItem, first_id).net == 200
        assert db.session.get(InvoiceItem, second_id).net == 100
        assert db.session.get(Invoice, inv_id).total == 300
