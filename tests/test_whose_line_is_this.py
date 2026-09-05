"""A bill several doctors worked on, and whose money each line is.

**The bug this closes was live and it was money.** An invoice belonged to one
doctor, because for as long as an invoice was one outpatient visit that was
true. A hospital stay is not one visit: the bill carries the ward's nightly
charge, an operation done by a surgeon who never admitted the child, and a
round by a consultant who came in for an hour. Every screen that asked "what
has this doctor earned" asked the *invoice*, so the surgeon's work was paid at
the admitting doctor's rate, appeared on the admitting doctor's statement, and
was missing from the surgeon's own screen — all three at once, and all three
looking perfectly plausible.

``InvoiceItem.doctor_id`` was added when the operations module landed, and it
recorded the truth faithfully. **Nothing read it.** That is the shape this
codebase keeps producing: a fact stored correctly with no door in front of it.

**One question, one owner.** ``InvoiceItem.earner_id`` decides whose a line is
— the line's own doctor, falling back to the invoice's. ``earned_by`` is the
same rule as SQL for the queries that must not load rows. Two readings of one
question is how a doctor's statement and the doctor's own screen come to
disagree about their pay, and a doctor who finds two numbers stops believing
either.

**And the refund had to move with it.** Crediting the earning to the surgeon
while debiting the refund from the admitting doctor is worse than the bug it
replaces: before, at least the two sides named the same person. So a refund on
a shared bill writes a notice per doctor whose share actually moved.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def shared(clinic):
    """One paid bill: the admitting doctor's exam, a visiting doctor's session.

    200 at 40% to the doctor on the invoice; 150 at 50% to somebody who is not
    on the invoice at all. The two rates differ on purpose — reading the share
    off the wrong doctor produces a *plausible* number, and a fixture where
    both rates matched would pass whichever doctor the code asked.
    """
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, Service, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        mine = User.query.filter_by(username="doc").first()
        visiting = User(username="vis", full_name="د. زائر", role="doctor",
                        is_active=True)
        visiting.set_password("secret")
        db.session.add(visiting)
        db.session.flush()

        exam = Service.query.filter_by(name="كشف").first()
        nebul = Service.query.filter_by(name="جلسة تنفس").first()

        invoice = Invoice(patient_id=clinic["ids"]["child"], doctor_id=mine.id,
                          invoice_number="INV-SHARED",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.flush()

        ours = InvoiceItem(invoice_id=invoice.id, service_id=exam.id,
                           description=exam.name, quantity=1,
                           unit_price=exam.price, discount_value=0)
        theirs = InvoiceItem(invoice_id=invoice.id, service_id=nebul.id,
                             description=nebul.name, quantity=1,
                             unit_price=nebul.price, discount_value=0,
                             doctor_id=visiting.id)
        db.session.add_all([ours, theirs])
        db.session.flush()
        ours.commission_amount = exam.doctor_share(ours.net, mine)
        theirs.commission_amount = nebul.doctor_share(theirs.net, visiting)
        db.session.commit()

        clinic["mine"] = mine.id
        clinic["visiting"] = visiting.id
        clinic["invoice"] = invoice.id
        clinic["ours_share"] = 80.0            # 200 @ 40%
        clinic["theirs_share"] = 75.0          # 150 @ 50%
    return clinic


def _earned(shared, doctor_id):
    from app.utils import doctor_work

    with shared["app"].app_context():
        return doctor_work.earned_ever(doctor_id)


def _window(shared, doctor_id):
    from app.utils import doctor_work
    from app.utils.clock import local_today

    with shared["app"].app_context():
        today = local_today()
        return doctor_work.by_service(doctor_id, today, today)


# ---------------------------------------------------------- whose line it is

def test_a_line_with_no_doctor_belongs_to_the_invoices_doctor(shared):
    """The old meaning, kept: null is not "nobody", it is "the bill's doctor".

    Every line written before the column existed is null, so if null meant
    unowned, every clinic's history would empty itself on upgrade.
    """
    from app.extensions import db
    from app.models import Invoice

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        plain = [i for i in invoice.items if i.doctor_id is None]
        assert plain and all(i.earner_id == shared["mine"] for i in plain)


def test_a_line_naming_a_doctor_belongs_to_them(shared):
    from app.extensions import db
    from app.models import Invoice

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        named = [i for i in invoice.items if i.doctor_id is not None]
        assert named and all(i.earner_id == shared["visiting"] for i in named)


def test_a_line_on_no_invoice_answers_none_rather_than_breaking(shared):
    """An unattached line is a half-built thing, not a crash."""
    from app.models import InvoiceItem

    with shared["app"].app_context():
        assert InvoiceItem(description="x").earner_id is None


# -------------------------------------------------------------- the earnings

def test_the_visiting_doctor_is_paid_their_own_rate(shared):
    """75, not 60 — 50% of their session, not the invoice doctor's 40%."""
    assert _earned(shared, shared["visiting"]) == shared["theirs_share"]


def test_the_invoices_doctor_is_not_paid_for_work_they_did_not_do(shared):
    assert _earned(shared, shared["mine"]) == shared["ours_share"]


def test_the_two_shares_do_not_overlap(shared):
    """Together they are the bill's whole commission, counted once.

    The failure this guards is not "a wrong number" but the same money
    appearing on two statements, which is how a clinic pays 155 twice.
    """
    from app.extensions import db
    from app.models import Invoice

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        assert (_earned(shared, shared["mine"])
                + _earned(shared, shared["visiting"])
                == invoice.doctor_share_total)


def test_the_visiting_doctors_work_shows_on_their_own_screen(shared):
    """It is on the screen at all — before, their row simply was not there."""
    rows, share, invoices = _window(shared, shared["visiting"])
    assert share == shared["theirs_share"]
    assert [r["label"] for r in rows] == ["جلسة تنفس"]
    assert len(invoices) == 1


def test_the_other_doctors_line_is_not_on_it(shared):
    rows, _, _ = _window(shared, shared["mine"])
    assert [r["label"] for r in rows] == ["كشف"]


def test_the_window_and_the_all_time_balance_agree(shared):
    """Two calculations of one doctor's pay, and they must never differ."""
    for who in ("mine", "visiting"):
        _, share, _ = _window(shared, shared[who])
        assert share == _earned(shared, shared[who])


# ------------------------------------------------------------- the statement

def _statement(shared, doctor_id):
    return shared["sign_in"]("boss").get(
        f"/finance/statements?doctor_id={doctor_id}")


def test_the_statement_lists_a_bill_that_is_not_the_doctors_own(shared):
    """The visiting doctor's statement has to reach an invoice with somebody
    else's name on it, or their work is unbillable to them."""
    page = _statement(shared, shared["visiting"]).get_data(as_text=True)
    assert "INV-SHARED" in page


def test_the_statement_shows_their_part_not_the_whole_bill(shared):
    """75 on the row, not the bill's 155 and not the other doctor's 80."""
    page = _statement(shared, shared["visiting"]).get_data(as_text=True)
    assert ">75.0<" in page
    assert ">155.0<" not in page


def test_the_statements_total_is_their_own(shared):
    page = _statement(shared, shared["mine"]).get_data(as_text=True)
    assert ">80.0<" in page


def test_what_was_collected_is_split_the_same_way_it_is_earned(shared):
    """Money is paid against a bill, never against a line, so the split is
    proportional — the same rule the refund side uses, read forwards."""
    from app.extensions import db
    from app.models import Invoice, Payment

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        db.session.add(Payment(invoice_id=invoice.id, amount=350,
                               method="cash"))
        db.session.commit()
        # 200 of a 350 bill is the exam's; 150 is the session's.
        assert invoice.collected_for(shared["mine"]) == 200.0
        assert invoice.collected_for(shared["visiting"]) == 150.0


def test_a_bill_that_came_to_nothing_is_not_divided_by_zero(shared):
    from app.extensions import db
    from app.models import Invoice
    from app.utils.clock import local_today

    with shared["app"].app_context():
        empty = Invoice(patient_id=shared["ids"]["child"],
                        doctor_id=shared["mine"], invoice_number="INV-0",
                        invoice_date=local_today(), status="paid")
        db.session.add(empty)
        db.session.commit()
        assert empty.collected_for(shared["mine"]) == 0.0


# ---------------------------------------------------------------- the refund

def _refund(shared, part=1.0):
    """Pay the bill in full, then refund ``part`` of it through the till.

    Through the route a desk actually posts to, not the helper behind it: the
    refund reads the open cashier shift off the request, so calling the helper
    from a bare app context tests a path no cashier can reach.
    """
    from app.extensions import db
    from app.models import Invoice, Payment, RefundNotice

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        total = invoice.total
        db.session.add(Payment(invoice_id=invoice.id, amount=total,
                               method="cash"))
        invoice.recalc_status()
        db.session.commit()

    shared["sign_in"]("boss").post(
        f"/finance/invoices/{shared['invoice']}/refund",
        data={"amount": str(round(total * part, 2)), "method": "cash",
              "reason": "خطأ"},
        follow_redirects=True)

    with shared["app"].app_context():
        return {n.doctor_id: n.doctor_amount
                for n in RefundNotice.query.filter_by(
                    invoice_id=shared["invoice"]).all()}


def test_a_refund_on_a_shared_bill_reaches_both_doctors(shared):
    """One notice each. Before, the surgeon's money came out of the admitting
    doctor's account and the surgeon never heard about it."""
    notices = _refund(shared)
    assert set(notices) == {shared["mine"], shared["visiting"]}


def test_each_doctor_gives_back_their_own_share(shared):
    notices = _refund(shared)
    assert notices[shared["mine"]] == shared["ours_share"]
    assert notices[shared["visiting"]] == shared["theirs_share"]


def test_a_part_refund_takes_a_part_of_each(shared):
    """Half the money back, half of each doctor's share with it."""
    notices = _refund(shared, part=0.5)
    assert notices[shared["mine"]] == 40.0
    assert notices[shared["visiting"]] == 37.5


def test_nobody_is_told_about_a_refund_that_moved_none_of_their_money(shared):
    """A line with no commission on it — the nurse's dressing — has no share
    to move, and a notice saying "0" is a message that wastes somebody's
    attention every time it arrives."""
    from app.extensions import db
    from app.models import Invoice, InvoiceItem, User

    with shared["app"].app_context():
        nurse = User(username="nur", full_name="ممرضة", role="nurse",
                     is_active=True)
        nurse.set_password("secret")
        db.session.add(nurse)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=shared["invoice"], description="غيار",
            quantity=1, unit_price=5, discount_value=0,
            commission_amount=0, doctor_id=nurse.id))
        db.session.commit()
        nurse_id = nurse.id

    assert nurse_id not in _refund(shared)


def test_a_bill_with_nobody_on_it_produces_no_notices(clinic):
    from app.extensions import db
    from app.models import Invoice, InvoiceItem
    from app.utils import refunds
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          invoice_number="INV-NONE",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, description="غيار",
                                   quantity=1, unit_price=50,
                                   discount_value=0, commission_amount=0))
        db.session.commit()
        assert refunds.notify_doctor(invoice, None, 50, scope="full") == []


def test_the_clinics_own_books_still_see_the_whole_commission(shared):
    """``doctor_share_of`` with no doctor named is the bill's whole cut, which
    is what the ledger posts. Narrowing that by accident would have quietly
    understated every refund the accounts ever saw."""
    from app.extensions import db
    from app.models import Invoice
    from app.utils import refunds

    with shared["app"].app_context():
        invoice = db.session.get(Invoice, shared["invoice"])
        assert refunds.doctor_share_of(invoice, invoice.total) == 155.0
