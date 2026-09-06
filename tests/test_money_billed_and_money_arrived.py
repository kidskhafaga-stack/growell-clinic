"""Earned is not collected, and on contract work they are months apart.

**The program watched one of the two doors money comes through.** A family
pays at the desk and it lands as a ``Payment`` on the invoice. A payer pays a
claim, and that lands on the ``Claim`` and **never touches the invoice at
all** — so a fully covered visit read as settled the moment it was raised,
because the family owed nothing, while the 200 billed to the insurer had not
been asked for yet.

Survivable while the only question was "does this family still owe us
something". Not survivable the moment a doctor is settled on what was
collected, which is how contract work is paid almost everywhere:
*"التعاقد غالباً لما يتم التحصيل من الجهة"*.

**Nothing that existed moved.** ``earned`` still means everything billed, and
``balance`` is still earned minus paid, because a clinic updating must not
find the figure it settles on has changed under it. What is new sits beside
them: how much of that has actually come in, and **who the rest is owed by** —
chasing a family and chasing an insurer are two jobs done by two people, and
one "outstanding" number is no use to either.

**And the split is proportional in both directions**, the rule the refunds
already keep: money arrives against a bill and against a claim, never against
a line, so a line is collected for in proportion — and a claim paid short is
short across every invoice in it, because the payer said the batch was worth
less without saying which row they struck out.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def covered(clinic):
    """An insurer covering the whole consultation, and a child on its books."""
    from app.models import PatientCoverage, PayerEntity, PayerServiceRate

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance",
                            is_active=True)
        db.session.add(payer)
        db.session.flush()
        db.session.add(PayerServiceRate(
            payer_id=payer.id, service_id=clinic["ids"]["exam"],
            coverage_type="percent", coverage_value=100))
        db.session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=payer.id,
            membership_number="M-1", is_active=True))
        db.session.commit()
        clinic["payer"] = payer.id
    return clinic


def _insured_bill(covered, number="INV-C"):
    """A covered consultation: 200 to the insurer, nothing to the family."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = covered["db"]
    with covered["app"].app_context():
        service = db.session.get(Service, covered["ids"]["exam"])
        invoice = Invoice(patient_id=covered["ids"]["child"],
                          doctor_id=covered["ids"]["doctor"],
                          invoice_number=number, invoice_date=local_today(),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=service.name, quantity=1, unit_price=service.price,
            discount_value=0))
        db.session.flush()
        billing.apply_coverage(
            invoice, db.session.get(Patient, covered["ids"]["child"]))
        invoice.recalc_status()
        db.session.commit()
        return invoice.id


def _cash_bill(clinic, paid=0.0, number="INV-K"):
    """A plain 200 consultation with no payer, part-paid or not."""
    from app.models import Invoice, InvoiceItem, Payment, Service

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number=number, invoice_date=local_today(),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description=service.name, quantity=1,
                           unit_price=service.price, discount_value=0)
        db.session.add(item)
        db.session.flush()
        item.commission_amount = service.doctor_share(item.net, None)
        if paid:
            db.session.add(Payment(invoice_id=invoice.id, amount=paid,
                                   method="cash"))
        invoice.recalc_status()
        db.session.commit()
        return invoice.id


def _claim(covered, invoice_id, status="submitted", paid_amount=None,
           total=None):
    """Put the invoice on a claim and drive it to ``status``."""
    from app.models import Invoice
    from app.models.payer import Claim, ClaimItem

    db = covered["db"]
    with covered["app"].app_context():
        invoice = db.session.get(Invoice, invoice_id)
        amount = total if total is not None else invoice.discount_total
        claim = Claim(claim_number=f"CLM-{invoice_id}",
                      payer_id=covered["payer"], date_from=local_today(),
                      date_to=local_today(), status=status,
                      total_amount=amount, paid_amount=paid_amount)
        db.session.add(claim)
        db.session.flush()
        db.session.add(ClaimItem(claim_id=claim.id, invoice_id=invoice_id,
                                 amount=amount))
        db.session.commit()
        return claim.id


def _split(fx):
    from app.utils.collected import split_for_doctor

    with fx["app"].app_context():
        return split_for_doctor(fx["ids"]["doctor"])


def _account(fx):
    from app.utils import doctor_work

    with fx["app"].app_context():
        return doctor_work.account(fx["ids"]["doctor"])


# ------------------------------------------------------------- the whole gap

def test_a_covered_visit_is_not_collected_the_moment_it_is_raised(covered):
    """The bug in one line: the family owes nothing, so the old reading called
    it settled — while the insurer had not even been asked yet."""
    _insured_bill(covered)
    split = _split(covered)
    assert split["collected"] == 0.0
    assert split["from_payer"] == 80.0
    assert split["from_family"] == 0.0


def test_submitting_a_claim_is_not_being_paid_for_it(covered):
    """Sent is not received. A claim can sit submitted for ninety days, and
    that is the whole reason this distinction exists."""
    invoice_id = _insured_bill(covered)
    _claim(covered, invoice_id, status="submitted")
    assert _split(covered)["from_payer"] == 80.0


def test_a_paid_claim_moves_the_share_to_collected(covered):
    invoice_id = _insured_bill(covered)
    _claim(covered, invoice_id, status="paid", paid_amount=200)
    split = _split(covered)
    assert split["collected"] == 80.0
    assert split["from_payer"] == 0.0


def test_a_claim_paid_short_is_short_across_the_line(covered):
    """The payer said the batch was worth half without saying which row they
    struck out, so the shortfall lands proportionally rather than on a row
    somebody picks."""
    invoice_id = _insured_bill(covered)
    _claim(covered, invoice_id, status="paid", paid_amount=100)   # of 200
    split = _split(covered)
    assert split["collected"] == 40.0
    assert split["from_payer"] == 40.0


def test_a_rejected_claim_leaves_the_money_outstanding(covered):
    """Rejected is not paid, and the share must not quietly settle because a
    claim exists."""
    invoice_id = _insured_bill(covered)
    _claim(covered, invoice_id, status="rejected", paid_amount=200)
    assert _split(covered)["from_payer"] == 80.0


# ------------------------------------------------------------ the cash clinic

def test_cash_collected_at_the_desk_is_collected(clinic):
    _cash_bill(clinic, paid=200)
    split = _split(clinic)
    assert split["collected"] == 80.0
    assert split["from_family"] == 0.0
    assert split["from_payer"] == 0.0


def test_a_bill_the_family_has_not_settled_is_owed_by_the_family(clinic):
    _cash_bill(clinic, paid=0)
    split = _split(clinic)
    assert split["collected"] == 0.0
    assert split["from_family"] == 80.0


def test_half_paid_is_half_collected(clinic):
    """Proportional: money is handed over against a bill, not against a row on
    it, so there is no honest way to say which half was settled."""
    _cash_bill(clinic, paid=100)
    split = _split(clinic)
    assert split["collected"] == 40.0
    assert split["from_family"] == 40.0


def test_a_bill_that_asked_for_nothing_is_not_waiting_for_ever(clinic):
    """A staff child, a free follow-up. There was nothing to collect, and
    parking the share in "waiting" would leave a row nobody could ever clear.
    """
    from app.models import Invoice, InvoiceItem, Service

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-FREE",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=service.id, description="كشف",
            quantity=1, unit_price=0, discount_value=0, commission_amount=0))
        db.session.commit()
    split = _split(clinic)
    assert split == {"collected": 0.0, "from_family": 0.0, "from_payer": 0.0}


def test_a_plain_discount_is_not_a_payer_waiting_to_pay(clinic):
    """Found by breaking it. Cover is stored as a line discount, so anything
    reading the discount without checking there is a payer turns **every
    discount the clinic ever gave** into money an insurer supposedly owes —
    and a doctor is shown a receivable against a company that was never
    billed and does not exist.
    """
    from app.models import Invoice, InvoiceItem, Payment, Service
    from app.utils.collected import payer_billed

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-DISC",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description="كشف", quantity=1, unit_price=200,
                           discount_value=50)
        db.session.add(item)
        db.session.flush()
        item.commission_amount = service.doctor_share(item.net, None)
        db.session.add(Payment(invoice_id=invoice.id, amount=150,
                               method="cash"))
        invoice.recalc_status()
        db.session.commit()
        assert payer_billed(invoice) == 0.0

    split = _split(clinic)
    assert split["from_payer"] == 0.0
    assert split["collected"] == 60.0        # 40% of the 150 charged


def test_paying_over_the_odds_does_not_collect_more_than_was_earned(clinic):
    """A family hands over 300 against a 200 bill — a deposit, or change not
    yet given. Without a cap the doctor's share reads as 120 of an 80 earning,
    and the three parts stop adding up to what was earned."""
    _cash_bill(clinic, paid=300)
    split = _split(clinic)
    assert split["collected"] == 80.0
    assert split["from_family"] == 0.0


def test_a_share_stored_on_a_bill_that_asks_for_nothing_is_not_waiting(clinic):
    """The guard, tested where it actually bites: a share recorded against a
    bill with nothing to collect. Left uncapped it sits in "waiting" for ever
    with nobody able to clear it, because no payment will ever arrive."""
    from app.models import Invoice, InvoiceItem

    db = clinic["db"]
    with clinic["app"].app_context():
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-ZERO",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=clinic["ids"]["exam"],
            description="كشف", quantity=1, unit_price=0, discount_value=0,
            commission_amount=50))
        db.session.commit()
    split = _split(clinic)
    assert split["collected"] == 50.0
    assert split["from_family"] == 0.0


def test_how_settled_a_bill_is_answers_zero_to_one_and_nothing_else(clinic):
    """Asked of the helper itself, because the caller happens to rescue it.

    Found by breaking it: ``split_for_doctor`` has a fallback for a bill
    nobody owes anything on, and that fallback quietly produced the right
    total even when the fraction underneath was 0 or 1.5. The fraction is a
    public answer with its own meaning — "how much of this bill has come in" —
    and the next thing to read it will not have the fallback.
    """
    from app.models import Invoice, InvoiceItem, Payment, Service
    from app.utils.collected import settled_fraction

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])

        def bill(number, price, paid):
            invoice = Invoice(patient_id=clinic["ids"]["child"],
                              doctor_id=clinic["ids"]["doctor"],
                              invoice_number=number,
                              invoice_date=local_today(), status="unpaid")
            db.session.add(invoice)
            db.session.flush()
            db.session.add(InvoiceItem(
                invoice_id=invoice.id, service_id=service.id,
                description="كشف", quantity=1, unit_price=price,
                discount_value=0, commission_amount=0))
            if paid:
                db.session.add(Payment(invoice_id=invoice.id, amount=paid,
                                       method="cash"))
            db.session.flush()
            return invoice

        # Nothing was asked for, so nothing is outstanding — 1.0 and not 0.0,
        # or the share sits in "waiting" with no payment that could ever clear
        # it.
        assert settled_fraction(bill("F-0", 0, 0)) == 1.0
        # And more money than the bill asked for is still a settled bill, not
        # a bill and a half: uncapped, a deposit would show a doctor more than
        # they earned.
        assert settled_fraction(bill("F-1", 200, 300)) == 1.0
        assert settled_fraction(bill("F-2", 200, 100)) == 0.5
        assert settled_fraction(bill("F-3", 200, 0)) == 0.0
        assert settled_fraction(None) == 0.0


def test_one_doctors_collection_is_not_another_doctors(clinic):
    """Two doctors on one day, one bill paid and the other not. Without the
    filter each of them is shown the other's money as well as their own —
    the same failure the rota had, in the other half of the money."""
    from app.models import Invoice, InvoiceItem, Payment, Service, User
    from app.utils.collected import split_for_doctor

    db = clinic["db"]
    with clinic["app"].app_context():
        other = User(username="doc2", full_name="د. تاني", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()
        service = db.session.get(Service, clinic["ids"]["exam"])
        for number, doctor_id, paid in (("INV-A", clinic["ids"]["doctor"], 200),
                                        ("INV-B", other.id, 0)):
            invoice = Invoice(patient_id=clinic["ids"]["child"],
                              doctor_id=doctor_id, invoice_number=number,
                              invoice_date=local_today(), status="unpaid")
            db.session.add(invoice)
            db.session.flush()
            item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                               description="كشف", quantity=1, unit_price=200,
                               discount_value=0)
            db.session.add(item)
            db.session.flush()
            item.commission_amount = service.doctor_share(item.net, None)
            if paid:
                db.session.add(Payment(invoice_id=invoice.id, amount=paid,
                                       method="cash"))
            invoice.recalc_status()
        db.session.commit()
        other_id = other.id

        mine = split_for_doctor(clinic["ids"]["doctor"])
        theirs = split_for_doctor(other_id)

    assert mine == {"collected": 80.0, "from_family": 0.0, "from_payer": 0.0}
    assert theirs == {"collected": 0.0, "from_family": 80.0, "from_payer": 0.0}


# --------------------------------------------------------- the two together

def test_the_two_kinds_of_debt_are_kept_apart(covered):
    """One unpaid cash bill and one unclaimed covered visit. Reception chases
    one and the claims desk chases the other; a single "outstanding" figure
    would send both of them to the wrong person."""
    _cash_bill(covered, paid=0, number="INV-K1")
    _insured_bill(covered, number="INV-C1")
    split = _split(covered)
    assert split["from_family"] == 80.0
    assert split["from_payer"] == 80.0
    assert split["collected"] == 0.0


# ------------------------------------------------------ nothing old moved

def test_earned_still_means_everything_billed(covered):
    """The promise to a clinic mid-update: the figure they settle on has not
    changed, whatever the new columns say."""
    _insured_bill(covered)
    assert _account(covered)["earned"] == 80.0


def test_the_balance_is_still_earned_minus_paid(covered):
    _insured_bill(covered)
    account = _account(covered)
    assert account["balance"] == round(account["earned"] - account["paid"], 2)


def test_the_three_parts_add_back_up_to_what_was_earned(clinic):
    """Otherwise the screen shows a doctor money that belongs to nobody."""
    _cash_bill(clinic, paid=100)
    account = _account(clinic)
    assert round(account["collected"] + account["from_family"]
                 + account["from_payer"], 2) == account["earned"]


def test_a_shift_is_collected_because_nobody_owes_it_to_us(clinic):
    """Cover and duty are owed by the clinic itself with no third party in
    between. There is nobody to wait for, so they belong on the collected
    side — otherwise a resident's night would sit in "due from families" for
    ever, and the three parts would stop adding up."""
    from datetime import time

    from app.models import Setting
    from app.models.duty import DutySlot
    from app.utils import duty

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("mod_enabled:duty", "1")
        night = DutySlot(name="ليلي", start_time=time(22, 0),
                         end_time=time(8, 0), rate=700)
        db.session.add(night)
        db.session.commit()
        from app.models import User

        row = duty.assign(db.session.get(User, clinic["ids"]["doctor"]), night)
        duty.confirm(row)
        db.session.commit()

    account = _account(clinic)
    assert account["earned"] == 700.0
    assert account["collected"] == 700.0
    assert account["from_family"] == 0.0


# ----------------------------------------------------------------- the door

def test_the_screen_shows_it(covered):
    """A figure nothing displays is a figure nobody has. This project has
    shipped that eight times."""
    _insured_bill(covered)
    page = covered["sign_in"]("boss").get(
        "/finance/doctor-payouts").get_data(as_text=True)
    # The note under the boxes rather than the column heading: the heading is
    # in the table as well, so asserting on it passed with the summary hidden.
    assert "الفلوس وصلت فعلاً" in page
    assert "مستني من الجهة" in page


def test_a_cash_clinic_sees_the_screen_it_saw_yesterday(clinic):
    """Nothing outstanding from anybody means the three new boxes are absent
    rather than showing three zeroes — the update promise, on screen."""
    _cash_bill(clinic, paid=200)
    page = clinic["sign_in"]("boss").get(
        "/finance/doctor-payouts").get_data(as_text=True)
    assert "مستني من الجهة" not in page
