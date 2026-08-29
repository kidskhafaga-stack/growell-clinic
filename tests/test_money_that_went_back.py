"""Refunds: what they close, who must agree, and whose share moves with them.

Written after a clinic looked at one invoice carrying seven movements —
collect, refund, collect, refund, collect — and asked *"أنا خلاص عملت
استرداد، ينفع يبقى فيه تحصيل تاني في ساعته؟"*

**A full refund closes the invoice.** It could not before, and the reason is
worth stating plainly: a fully refunded invoice has ``paid == 0``, so
``recalc_status`` called it **unpaid**. Back in the "who still owes" list,
offering a Collect button, with the money already handed across the counter.
The service was cancelled; charging for it again is a new decision and belongs
on a new invoice, or the patient's statement becomes a column of numbers
nobody can read back into events.

**A full refund waits for a manager; a small partial one does not.** Handing
back fifty pounds of a vaccine difference should not stop the queue while
somebody is found; handing back the whole visit should not be one person's
decision. The line is a figure the clinic sets, and setting it to zero
restores exactly the behaviour that was there before.

**The doctor's share follows the money.** This half had no implementation at
all: ``commission_amount`` is a snapshot written when the line was billed, and
nothing ever subtracted from it — so a clinic that refunded a visit still owed
the doctor their cut of money it no longer had.

**And the doctor is told, and may object.** Asked for in those words, with the
rule attached: *"هو مش هيوقف عملية، بس الطبيب في ساعتها ممكن يعارض ويظهر
للاستقبال."* The objection stops nothing — the money went back before the row
existed — it puts the disagreement in front of the desk that made it.
"""
import os
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def billed(clinic):
    """A 200 exam, fully paid, with the doctor on 40% of it."""
    from app.extensions import db
    from app.models import (Invoice, InvoiceItem, Payment, Service, Setting,
                            User)
    from app.utils.accounting import ensure_seeded
    from app.utils.clock import local_today
    from app.utils.treasury import seed_accounts

    with clinic["app"].app_context():
        ensure_seeded()
        seed_accounts()
        Setting.set("refund_approval_required", "1")
        Setting.set("refund_no_approval_under", "100")
        doctor = db.session.get(User, clinic["ids"]["doctor"])
        exam = Service.query.filter_by(name="كشف").first()
        invoice = Invoice(invoice_number="INV-R1",
                          patient_id=clinic["ids"]["child"],
                          doctor_id=doctor.id, invoice_date=local_today())
        db.session.add(invoice)
        db.session.flush()
        line = InvoiceItem(invoice_id=invoice.id, service_id=exam.id,
                           description=exam.name, quantity=1,
                           unit_price=exam.price, discount_value=0)
        db.session.add(line)
        db.session.flush()
        line.commission_amount = exam.doctor_share(line.net, doctor)
        invoice.payments.append(Payment(amount=exam.price, method="cash",
                                        received_by=doctor.id))
        invoice.recalc_status()
        db.session.commit()
        clinic["invoice"] = invoice.id
        clinic["total"] = exam.price          # 200
        clinic["share"] = line.commission_amount   # 80
    return clinic


def _refund(billed, amount, who="boss", **form):
    data = {"amount": str(amount), "method": "cash"}
    data.update(form)
    return billed["sign_in"](who).post(
        f"/finance/invoices/{billed['invoice']}/refund", data=data,
        follow_redirects=True)


def _state(billed):
    """The invoice's own answers, read inside a session.

    Returned as plain values rather than the object: handing a detached model
    back across the context boundary is how a test starts failing on a lazy
    load instead of on the thing it is about.
    """
    from app.models import Invoice

    with billed["app"].app_context():
        invoice = billed["db"].session.get(Invoice, billed["invoice"])
        return {"status": invoice.status, "refunded": invoice.refunded,
                "paid": invoice.paid, "refunded_at": invoice.refunded_at}


# ------------------------------------------- a full refund closes the invoice

def test_refunding_everything_closes_the_invoice(billed):
    """The report. It used to read "unpaid" and offer to collect again."""
    _refund(billed, billed["total"])

    invoice = _state(billed)
    assert invoice["status"] == "refunded", \
        f"a fully refunded invoice reads as {invoice['status']!r}"
    assert invoice["refunded_at"] is not None


def test_a_closed_invoice_is_not_the_days_invoice_any_more(billed):
    """The one-invoice-a-day rule appends today's charges to today's invoice.
    Left alone it would quietly reopen the closed one, which is the same bug
    wearing the other screen."""
    from app.models import Appointment, Invoice
    from app.utils.clock import local_today

    _refund(billed, billed["total"])

    from app.extensions import db

    with billed["app"].app_context():
        appt = Appointment(patient_id=billed["ids"]["child"],
                           doctor_id=billed["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(13, 0),
                           appt_type="consultation", status="scheduled")
        db.session.add(appt)
        db.session.commit()
        appt_id = appt.id
        before = Invoice.query.count()

    billed["sign_in"]("boss").post(
        f"/finance/checkout/{appt_id}",
        data={"line_desc": "كشف", "line_price": "200", "line_qty": "1",
              "pay_amount": "200", "pay_method": "cash"},
        follow_redirects=True)

    with billed["app"].app_context():
        assert Invoice.query.count() == before + 1, \
            "the new charge went onto the refunded invoice"
    assert _state(billed)["status"] == "refunded", \
        "the closed invoice was reopened by the next collection"


def test_a_partial_refund_leaves_it_open(billed):
    """Half the money back is not a cancelled visit."""
    _refund(billed, 50)

    invoice = _state(billed)
    assert invoice["status"] == "partial"
    assert invoice["refunded_at"] is None


def test_two_partials_that_finish_it_close_it_too(billed):
    """Full means nothing collected is left, whether that took one refund or
    three. Keyed off the amount alone, the second half of a split refund would
    leave the invoice open with nothing on it."""
    _refund(billed, 120)
    _refund(billed, 80)

    assert _state(billed)["status"] == "refunded"


# --------------------------------------------------- who has to say yes

def test_a_small_partial_refund_does_not_wait(billed):
    """*"رجّعت ٥٠ جنيه فرق تطعيم"* should not stop the queue."""
    from app.models import RefundRequest

    _refund(billed, 50, who="desk")

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 0, "a small refund was queued"
    assert _state(billed)["refunded"] == 50


def test_a_full_refund_always_waits(billed):
    """Handing back the whole visit is not one person's decision."""
    from app.models import RefundRequest

    _refund(billed, billed["total"], who="desk")

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 1
    assert _state(billed)["refunded"] == 0, "money left before approval"


def test_a_full_refund_waits_even_below_the_threshold(billed):
    """The rule the plain case cannot see. With the threshold at 500, a
    partial refund of 200 goes straight through — so if "full" did not have a
    branch of its own, refunding the *whole* 200 would go straight through
    too, and the invoice would close on one person's say-so.

    Caught by mutation testing: deleting the full-refund branch left every
    other test passing, because the fixture's total happened to sit above the
    threshold anyway.
    """
    from app.extensions import db
    from app.models import RefundRequest, Setting

    with billed["app"].app_context():
        Setting.set("refund_no_approval_under", "500")
        db.session.commit()

    _refund(billed, billed["total"], who="desk")      # the whole 200

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 1, \
            "a full refund went through unapproved because it was a small one"
    assert _state(billed)["refunded"] == 0


def test_a_partial_below_that_same_threshold_does_not_wait(billed):
    """The other half of the pair, so the test above is measuring the *scope*
    and not simply a high threshold."""
    from app.extensions import db
    from app.models import RefundRequest, Setting

    with billed["app"].app_context():
        Setting.set("refund_no_approval_under", "500")
        db.session.commit()

    _refund(billed, 150, who="desk")

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 0
    assert _state(billed)["refunded"] == 150


def test_a_large_partial_refund_waits(billed):
    from app.models import RefundRequest

    _refund(billed, 150, who="desk")

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 1


def test_zero_threshold_makes_everything_wait(billed):
    """The setting that restores the behaviour a clinic had before."""
    from app.extensions import db
    from app.models import RefundRequest, Setting

    with billed["app"].app_context():
        Setting.set("refund_no_approval_under", "0")
        db.session.commit()

    _refund(billed, 5, who="desk")

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 1


def test_an_admin_never_waits(billed):
    from app.models import RefundRequest

    _refund(billed, billed["total"])

    with billed["app"].app_context():
        assert RefundRequest.query.count() == 0
    assert _state(billed)["refunded"] == billed["total"]


# ----------------------------------------- the doctor's share follows it

def test_a_refund_takes_the_doctors_share_with_it(billed):
    """The half that had no implementation at all: the clinic still owed the
    doctor their cut of money it had handed back."""
    from app.utils import doctor_work

    with billed["app"].app_context():
        before = doctor_work.earned_ever(billed["ids"]["doctor"])

    _refund(billed, 100)                       # half the invoice

    with billed["app"].app_context():
        after = doctor_work.earned_ever(billed["ids"]["doctor"])

    assert before == billed["share"]           # 80
    assert after == round(billed["share"] / 2, 2), \
        f"the doctor kept their whole share of refunded money: {after}"


def test_refunding_everything_takes_the_whole_share(billed):
    from app.utils import doctor_work

    _refund(billed, billed["total"])

    with billed["app"].app_context():
        assert doctor_work.earned_ever(billed["ids"]["doctor"]) == 0


def test_the_share_is_split_in_proportion_not_guessed(billed):
    """An invoice can carry several lines at different rates, and a refund is
    rarely against one of them. Proportional is the only split that holds."""
    from app.utils import refunds

    from app.models import Invoice

    with billed["app"].app_context():
        invoice = billed["db"].session.get(Invoice, billed["invoice"])
        assert refunds.doctor_share_of(invoice, 50) == round(
            billed["share"] * 50 / billed["total"], 2)


def test_an_invoice_with_no_doctor_divides_by_nothing_safely(billed):
    from app.extensions import db
    from app.models import Invoice
    from app.utils import refunds

    with billed["app"].app_context():
        invoice = db.session.get(Invoice, billed["invoice"])
        invoice.doctor_id = None
        db.session.commit()
        assert refunds.doctor_share_of(invoice, 100) >= 0


# --------------------------------------------- the doctor is told, and answers

def test_the_doctor_gets_a_notice(billed):
    from app.models import RefundNotice

    _refund(billed, 100, notes="اتحول لاستشارة")

    with billed["app"].app_context():
        notice = RefundNotice.query.one()
        assert notice.doctor_id == billed["ids"]["doctor"]
        assert notice.amount == 100
        assert notice.doctor_amount == round(billed["share"] / 2, 2)
        assert notice.scope == "partial"
        assert notice.reason == "اتحول لاستشارة"


def test_a_full_refund_says_so_on_the_notice(billed):
    from app.models import RefundNotice

    _refund(billed, billed["total"])

    with billed["app"].app_context():
        assert RefundNotice.query.one().scope == "full"


def test_the_doctor_sees_it_on_their_own_screen(billed):
    _refund(billed, 100)

    page = billed["sign_in"]("doc").get("/my-clinic").get_data(as_text=True)

    assert "refunds.notices_title" not in page, \
        "the strings are keys, not translations"
    assert "INV-R1" in page


def test_the_doctor_can_object_and_it_changes_no_money(billed):
    """*"هو مش هيوقف عملية"* — the objection is a record, not a lever."""
    from app.models import RefundNotice

    _refund(billed, 100)

    before = _state(billed)["refunded"]
    with billed["app"].app_context():
        notice_id = RefundNotice.query.one().id

    billed["sign_in"]("doc").post(f"/my-clinic/refund/{notice_id}/object",
                                  data={"note": "الحالة اتشافت فعلاً"},
                                  follow_redirects=True)

    with billed["app"].app_context():
        notice = RefundNotice.query.one()
        assert notice.objected is True
        assert notice.objection_note == "الحالة اتشافت فعلاً"
    assert _state(billed)["refunded"] == before, "the objection moved money"


def test_a_doctor_cannot_object_to_somebody_elses_refund(billed):
    from app.models import RefundNotice

    _refund(billed, 100)

    with billed["app"].app_context():
        notice_id = RefundNotice.query.one().id

    answer = billed["sign_in"]("acct").post(
        f"/my-clinic/refund/{notice_id}/object", data={"note": "لأ"})

    assert answer.status_code in (302, 403)
    with billed["app"].app_context():
        assert RefundNotice.query.one().objected is False


def test_reception_sees_the_objection(billed):
    """It stops nothing, so the only thing that makes it worth recording is
    that somebody reads it."""
    from app.models import RefundNotice

    _refund(billed, 100)
    with billed["app"].app_context():
        notice_id = RefundNotice.query.one().id
    billed["sign_in"]("doc").post(f"/my-clinic/refund/{notice_id}/object",
                                  data={"note": "الحالة اتشافت فعلاً"},
                                  follow_redirects=True)

    page = billed["sign_in"]("boss").get(
        "/finance/refund-requests").get_data(as_text=True)

    assert "refunds.objections_title" not in page
    assert "الحالة اتشافت فعلاً" in page


def test_an_invoice_with_no_doctor_notifies_nobody(billed):
    """A dressing done by the nurse is still a refund; it simply has nobody to
    tell, and a notice with no doctor on it would sit in a feed for ever."""
    from app.extensions import db
    from app.models import Invoice, RefundNotice

    with billed["app"].app_context():
        invoice = db.session.get(Invoice, billed["invoice"])
        invoice.doctor_id = None
        db.session.commit()

    _refund(billed, 100)

    with billed["app"].app_context():
        assert RefundNotice.query.count() == 0


# ------------------------------------------------------- the approved path

def test_an_approved_request_does_all_of_it_too(billed):
    """Both ways money goes back run through one helper, or the rules drift:
    the manager's approval used to append a Payment and nothing else."""
    from app.models import RefundNotice, RefundRequest

    _refund(billed, billed["total"], who="desk")

    with billed["app"].app_context():
        req_id = RefundRequest.query.one().id

    billed["sign_in"]("boss").post(
        f"/finance/refund-requests/{req_id}/decide",
        data={"decision": "approve"}, follow_redirects=True)

    with billed["app"].app_context():
        assert RefundNotice.query.count() == 1, \
            "an approved refund told the doctor nothing"
    assert _state(billed)["status"] == "refunded", \
        "an approved full refund did not close the invoice"
