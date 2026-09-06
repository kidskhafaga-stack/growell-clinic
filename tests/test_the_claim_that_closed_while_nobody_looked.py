"""A payer agreement is a price list and two dates. We only held the list.

The two dates are the ones a claims desk argues about: **by when must the
claim be sent**, and **by when must the money come**. Both live in the paper
agreement and neither lived in this program, so it could not say either of the
two sentences that make a claims desk a job rather than a filing cabinet —
*"this one closes on Thursday"* and *"this payer is sixty days late"*.

Asked for in these words: *"لازم الاتفاق يبقى موجود بعقد واضح بيتحصل امتى
وتتقفل المطالبات امتى"*.

**The filing window is the sharp one.** It runs from the date of service, and
past it an otherwise payable claim is refused — most agreements also forbid
billing it to the family, so it converts straight into a write-off. Windows
run from about 90 days to a year depending on the payer, which is exactly why
**the program never guesses one**. An invented number would either raise
alarms about claims that are fine or stay silent about claims that are already
dead, and the second is the expensive one.

**No term typed, no deadline shown**, and that is the whole of the upgrade
promise here: a clinic that has never opened a contract sees the screens it
saw yesterday, and a clinic with no payers at all never reaches any of it.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def insurer(clinic):
    """A payer on contract, with a 90-day window and 30-day payment terms."""
    from app.models import (PatientCoverage, PayerContract, PayerEntity,
                            PayerServiceRate)

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance",
                            is_active=True)
        db.session.add(payer)
        db.session.flush()
        db.session.add(PayerServiceRate(
            payer_id=payer.id, service_id=clinic["ids"]["exam"],
            coverage_type="percent", coverage_value=100))
        db.session.add(PayerContract(
            payer_id=payer.id, number="C-1",
            start_date=local_today() - timedelta(days=400),
            end_date=local_today() + timedelta(days=400),
            is_active=True, filing_days=90, payment_days=30))
        db.session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=payer.id,
            membership_number="M-1", is_active=True))
        db.session.commit()
        clinic["payer"] = payer.id
    return clinic


def _covered_bill(fx, days_ago=0, number=None):
    """A covered consultation raised ``days_ago`` days back."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = fx["db"]
    with fx["app"].app_context():
        service = db.session.get(Service, fx["ids"]["exam"])
        invoice = Invoice(patient_id=fx["ids"]["child"],
                          doctor_id=fx["ids"]["doctor"],
                          invoice_number=number or f"INV-{days_ago}",
                          invoice_date=local_today() - timedelta(days=days_ago),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=service.id,
            description=service.name, quantity=1, unit_price=service.price,
            discount_value=0))
        db.session.flush()
        billing.apply_coverage(invoice,
                               db.session.get(Patient, fx["ids"]["child"]))
        invoice.recalc_status()
        db.session.commit()
        return invoice.id


def _sent_claim(fx, invoice_id, days_ago, status="submitted"):
    from app.models import Invoice
    from app.models.payer import Claim, ClaimItem

    db = fx["db"]
    with fx["app"].app_context():
        invoice = db.session.get(Invoice, invoice_id)
        claim = Claim(claim_number=f"CLM-{invoice_id}",
                      payer_id=fx["payer"], date_from=invoice.invoice_date,
                      date_to=invoice.invoice_date, status=status,
                      total_amount=invoice.discount_total,
                      submitted_at=datetime.utcnow() - timedelta(days=days_ago))
        db.session.add(claim)
        db.session.flush()
        db.session.add(ClaimItem(claim_id=claim.id, invoice_id=invoice_id,
                                 amount=invoice.discount_total))
        db.session.commit()
        return claim.id


# ------------------------------------------------------------- the two dates

def test_the_window_is_counted_from_the_date_of_service(insurer):
    from app.models import Invoice
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    with insurer["app"].app_context():
        invoice = insurer["db"].session.get(Invoice, invoice_id)
        assert claim_clock.filing_due(invoice) == \
            invoice.invoice_date + timedelta(days=90)
        assert claim_clock.days_to_file(invoice) == 80


def test_a_window_that_has_closed_reads_negative_rather_than_vanishing(insurer):
    """The most important row on the screen: nobody can send it any more, and
    somebody has to decide to write it off rather than find it at the audit."""
    from app.models import Invoice
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=100)
    with insurer["app"].app_context():
        invoice = insurer["db"].session.get(Invoice, invoice_id)
        assert claim_clock.days_to_file(invoice) == -10


def test_the_money_is_due_counted_from_submission_not_from_the_visit(insurer):
    """The payer's clock starts when the claim reaches them — it is also the
    only date they would accept being held to."""
    from app.models.payer import Claim
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=60)
    claim_id = _sent_claim(insurer, invoice_id, days_ago=45)
    with insurer["app"].app_context():
        claim = insurer["db"].session.get(Claim, claim_id)
        assert claim_clock.payment_due(claim) == \
            claim.submitted_at.date() + timedelta(days=30)
        assert claim_clock.days_overdue(claim) == 15


def test_a_claim_still_inside_its_terms_is_not_overdue(insurer):
    from app.models.payer import Claim
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    claim_id = _sent_claim(insurer, invoice_id, days_ago=5)
    with insurer["app"].app_context():
        claim = insurer["db"].session.get(Claim, claim_id)
        assert claim_clock.days_overdue(claim) == 0


# ------------------------------------------------- the program never guesses

def test_no_term_means_no_deadline_at_all(clinic):
    """The upgrade promise. A payer with no contract terms produces no dates,
    no warnings and no rows — not a default window somebody has to discover
    and switch off."""
    from app.models import (Invoice, InvoiceItem, PatientCoverage, PayerEntity,
                            PayerServiceRate, Service)
    from app.utils import billing, claim_clock
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="نادي", entity_type="club", is_active=True)
        db.session.add(payer)
        db.session.flush()
        db.session.add(PayerServiceRate(
            payer_id=payer.id, service_id=clinic["ids"]["exam"],
            coverage_type="percent", coverage_value=100))
        db.session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=payer.id,
            membership_number="M-9", is_active=True))
        db.session.commit()

        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-NT", invoice_date=local_today(),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=invoice.id, service_id=service.id, description="كشف",
            quantity=1, unit_price=service.price, discount_value=0))
        db.session.flush()
        billing.apply_coverage(
            invoice, db.session.get(Patient, clinic["ids"]["child"]))
        db.session.commit()

        assert claim_clock.filing_due(invoice) is None
        assert claim_clock.days_to_file(invoice) is None
        assert claim_clock.closing_soon() == []


def test_an_invoice_with_no_payer_has_no_window(clinic):
    """A cash bill is nobody's claim. This is the line a single-doctor clinic
    never crosses."""
    from app.models import Invoice
    from app.utils import claim_clock

    db = clinic["db"]
    with clinic["app"].app_context():
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          invoice_number="INV-CASH",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.commit()
        assert claim_clock.filing_due(invoice) is None


def test_the_terms_are_read_off_the_contract_in_force(insurer):
    """A renewal may change them, and a claim raised in March is judged by
    March's agreement — not by whatever is signed today."""
    from app.models import Invoice, PayerContract
    from app.utils import claim_clock

    db = insurer["db"]
    with insurer["app"].app_context():
        # Yesterday's agreement stops, and a new one starts today with a
        # tighter window.
        old = PayerContract.query.filter_by(payer_id=insurer["payer"]).first()
        old.end_date = local_today() - timedelta(days=1)
        db.session.add(PayerContract(
            payer_id=insurer["payer"], number="C-2",
            start_date=local_today(), end_date=local_today() + timedelta(days=90),
            is_active=True, filing_days=30, payment_days=15))
        db.session.commit()

    old_bill = _covered_bill(insurer, days_ago=10, number="INV-OLD")
    new_bill = _covered_bill(insurer, days_ago=0, number="INV-NEW")
    with insurer["app"].app_context():
        assert claim_clock.days_to_file(
            db.session.get(Invoice, old_bill)) == 80          # 90-day terms
        assert claim_clock.days_to_file(
            db.session.get(Invoice, new_bill)) == 30          # 30-day terms


# ------------------------------------------------------------- what is listed

def test_a_bill_already_on_a_claim_is_not_still_closing(insurer):
    """It has been sent. Leaving it on the list would bury the ones that have
    not, which is the list's whole job."""
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=85)
    with insurer["app"].app_context():
        assert len(claim_clock.closing_soon()) == 1
    _sent_claim(insurer, invoice_id, days_ago=1)
    with insurer["app"].app_context():
        assert claim_clock.closing_soon() == []


def test_a_rejected_claim_puts_its_bill_back_on_the_list(insurer):
    """A rejection releases the invoice — and it is then racing the same
    window it was always racing, with less of it left."""
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=85)
    _sent_claim(insurer, invoice_id, days_ago=1, status="rejected")
    with insurer["app"].app_context():
        assert len(claim_clock.closing_soon()) == 1


def test_a_bill_past_its_window_stays_on_the_list(insurer):
    """The list has to keep the dead ones, not tidy them away.

    Found by breaking it: the deadline arithmetic was tested and the *list*
    was not, so a filter that dropped everything already past the window
    passed every test — and the rows somebody has to write off would have
    disappeared silently, which is the exact failure the list exists to
    prevent.
    """
    from app.utils import claim_clock

    _covered_bill(insurer, days_ago=100)          # window closed ten days ago
    with insurer["app"].app_context():
        rows = claim_clock.closing_soon()
    assert len(rows) == 1
    assert rows[0]["days"] == -10


def test_the_deadest_one_is_first(insurer):
    """Sorted by how little time is left, so the row that needs a decision
    today is not below the one that needs it next week."""
    from app.utils import claim_clock

    _covered_bill(insurer, days_ago=100, number="INV-DEAD")   # -10
    _covered_bill(insurer, days_ago=85, number="INV-SOON")    # +5
    with insurer["app"].app_context():
        rows = claim_clock.closing_soon()
    assert [r["days"] for r in rows] == [-10, 5]


def test_a_bill_with_time_left_is_not_shouted_about(insurer):
    """Ninety days out is not news. A list that shows everything shows
    nothing."""
    from app.utils import claim_clock

    _covered_bill(insurer, days_ago=1)
    with insurer["app"].app_context():
        assert claim_clock.closing_soon() == []


def test_a_draft_claim_is_not_money_out(insurer):
    """It is still on our own desk. Counting it as outstanding would let the
    clinic blame the payer for its own paperwork."""
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    _sent_claim(insurer, invoice_id, days_ago=5, status="draft")
    with insurer["app"].app_context():
        assert claim_clock.outstanding() == []


def test_an_approved_claim_is_still_money_out(insurer):
    """Approved is the payer saying "yes, we owe this" — money agreed and not
    sent is exactly the money worth chasing."""
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    _sent_claim(insurer, invoice_id, days_ago=5, status="approved")
    with insurer["app"].app_context():
        assert len(claim_clock.outstanding()) == 1


def test_a_paid_claim_is_not_money_out(insurer):
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    _sent_claim(insurer, invoice_id, days_ago=5, status="paid")
    with insurer["app"].app_context():
        assert claim_clock.outstanding() == []


# ------------------------------------------------------------------ the aging

def test_the_money_is_aged_from_the_day_it_was_sent(insurer):
    from app.utils import claim_clock

    for days, number in ((10, "A"), (45, "B"), (75, "C"), (200, "D")):
        invoice_id = _covered_bill(insurer, days_ago=days + 5, number=f"I-{number}")
        _sent_claim(insurer, invoice_id, days_ago=days)

    with insurer["app"].app_context():
        buckets = claim_clock.aging()
    assert [(b["low"], b["count"]) for b in buckets] == [
        (0, 1), (31, 1), (61, 1), (91, 1)]


def test_every_bucket_is_drawn_even_when_empty(insurer):
    """A table that grows and loses rows is one nobody reads the shape of."""
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=10)
    _sent_claim(insurer, invoice_id, days_ago=5)
    with insurer["app"].app_context():
        buckets = claim_clock.aging()
    assert len(buckets) == 4
    assert [b["count"] for b in buckets] == [1, 0, 0, 0]


def test_the_amount_is_what_the_payer_agreed_when_they_have_agreed(insurer):
    """An approved claim is worth what was approved, not what was asked. The
    difference is the part already lost, and showing the larger figure tells
    the clinic it is owed money nobody is going to send."""
    from app.models.payer import Claim
    from app.utils import claim_clock

    invoice_id = _covered_bill(insurer, days_ago=20)
    claim_id = _sent_claim(insurer, invoice_id, days_ago=10, status="approved")
    with insurer["app"].app_context():
        claim = insurer["db"].session.get(Claim, claim_id)
        claim.approved_amount = 150            # of 200
        insurer["db"].session.commit()
        assert claim_clock.outstanding()[0]["amount"] == 150.0


# ----------------------------------------------------------------- the screens

def test_the_claims_screen_shows_what_is_about_to_close(insurer):
    _covered_bill(insurer, days_ago=85)
    page = insurer["sign_in"]("boss").get(
        "/finance/claims").get_data(as_text=True)
    assert "مطالبات بتقفل قريب" in page


def test_the_claims_screen_shows_the_money_out(insurer):
    invoice_id = _covered_bill(insurer, days_ago=60)
    _sent_claim(insurer, invoice_id, days_ago=45)
    page = insurer["sign_in"]("boss").get(
        "/finance/claims").get_data(as_text=True)
    assert "على الجهات" in page


def test_a_clinic_with_no_terms_sees_neither_block(clinic):
    """The screen it saw yesterday, on the morning somebody updates."""
    page = clinic["sign_in"]("boss").get(
        "/finance/claims").get_data(as_text=True)
    assert "مطالبات بتقفل قريب" not in page
    assert "على الجهات" not in page


def test_the_terms_are_typed_on_the_contract(insurer):
    """A term with no screen is a term nobody sets — and this route had no
    screen posting to it at all before now."""
    from app.models import PayerContract

    db = insurer["db"]
    with insurer["app"].app_context():
        contract = PayerContract.query.filter_by(
            payer_id=insurer["payer"]).first()
        contract_id = contract.id

    insurer["sign_in"]("boss").post(
        f"/finance/contract/{contract_id}/edit",
        data={"terms": "1", "filing_days": "120", "payment_days": "60",
              "cycle_day": "25"}, follow_redirects=True)

    with insurer["app"].app_context():
        contract = db.session.get(PayerContract, contract_id)
        assert (contract.filing_days, contract.payment_days,
                contract.cycle_day) == (120, 60, 25)


def test_saving_the_terms_does_not_wipe_the_period(insurer):
    """The bug this shape produces: one form posts three fields, the route
    overwrites eight, and the contract's dates disappear — showing up a month
    later on somebody's bill rather than now."""
    from app.models import PayerContract

    db = insurer["db"]
    with insurer["app"].app_context():
        contract = PayerContract.query.filter_by(
            payer_id=insurer["payer"]).first()
        contract_id, start, end = contract.id, contract.start_date, contract.end_date

    insurer["sign_in"]("boss").post(
        f"/finance/contract/{contract_id}/edit",
        data={"terms": "1", "filing_days": "120"}, follow_redirects=True)

    with insurer["app"].app_context():
        contract = db.session.get(PayerContract, contract_id)
        assert (contract.start_date, contract.end_date) == (start, end)
        assert contract.number == "C-1"
        assert contract.is_active is True


def test_a_term_can_be_cleared_back_to_nothing_agreed(insurer):
    """A clinic that typed 90 by mistake must be able to get back to no
    deadline, not be stuck with a wrong one."""
    from app.models import PayerContract

    db = insurer["db"]
    with insurer["app"].app_context():
        contract_id = PayerContract.query.filter_by(
            payer_id=insurer["payer"]).first().id

    insurer["sign_in"]("boss").post(
        f"/finance/contract/{contract_id}/edit",
        data={"terms": "1", "filing_days": "", "payment_days": ""},
        follow_redirects=True)

    with insurer["app"].app_context():
        contract = db.session.get(PayerContract, contract_id)
        assert contract.filing_days is None
        assert contract.payment_days is None


def test_a_renewal_carries_the_terms_over(insurer):
    """Dropping them on renewal would switch the deadlines off on the one day
    nobody is looking at them."""
    from app.models import PayerContract

    db = insurer["db"]
    with insurer["app"].app_context():
        contract = PayerContract.query.filter_by(
            payer_id=insurer["payer"]).first()
        clone = contract.copy_to(number="C-2", start_date=date(2027, 1, 1),
                                 end_date=date(2027, 12, 31))
        assert clone.filing_days == 90
        assert clone.payment_days == 30
