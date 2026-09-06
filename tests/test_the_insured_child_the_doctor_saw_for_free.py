"""A covered consultation, and the share it used to pay the doctor: nothing.

**Measured before it was written, not reasoned about.** A 200 consultation at
40%, a card covering 100% of it:

    before cover:  price 200 · doctor 80
    after cover:   price 200 · doctor  0     ← what was stored
    claimed from the insurer: 200 · doctor's share of the bill: 0

The doctor saw the child, the clinic claimed the whole 200, and the person who
did the work earned nothing for it.

**The cause is a shortcut in how cover is stored.** The payer's part is
written onto the line as a *discount*, which is how the claimable amount is
worked out and is perfectly fine as far as the money goes. It is not a
discount in any other sense — an insurer paying for a consultation does not
make the consultation cheaper, it changes who hands the money over. But
everything downstream reads a discount as a lower price, so the commission was
recomputed on what was left for the family: on a fully covered service, zero.

A real discount **should** reduce the doctor's share, and still does. Cover
should not, and now does not.

**Nothing an existing clinic has already billed moves.** Cover is applied when
an invoice is raised — at the till, or when a stay is posted — and never to an
invoice that already exists, so every stored figure reads exactly as it did.
A clinic with no payers at all never reaches this code.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def insured(clinic):
    """An insurer covering the whole consultation, and a child holding a card.

    100% on purpose: a partial cover leaves a residual, and a commission read
    off the residual is merely *wrong* — at 100% it is zero, which is the
    version somebody notices.
    """
    from app.models import PatientCoverage, PayerEntity, PayerServiceRate, Service

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance",
                            is_active=True)
        db.session.add(payer)
        db.session.flush()
        db.session.add(PayerServiceRate(
            payer_id=payer.id, service_id=clinic["ids"]["exam"],
            coverage_type="percent", coverage_value=100))
        # Half of the other service, so the partial case is a real row too.
        db.session.add(PayerServiceRate(
            payer_id=payer.id, service_id=clinic["ids"]["nebul"],
            coverage_type="percent", coverage_value=50))
        db.session.add(PatientCoverage(
            patient_id=clinic["ids"]["child"], payer_id=payer.id,
            membership_number="M-1", is_active=True))
        db.session.commit()
        clinic["payer"] = payer.id
        clinic["doctor"] = clinic["ids"]["doctor"]
    return clinic


def _bill(insured, service_key="exam", price=None):
    """Raise an invoice for the child and run it through the pricing door."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = insured["db"]
    with insured["app"].app_context():
        service = db.session.get(Service, insured["ids"][service_key])
        invoice = Invoice(patient_id=insured["ids"]["child"],
                          doctor_id=insured["doctor"],
                          invoice_number=f"INV-{service_key}",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description=service.name, quantity=1,
                           unit_price=price if price is not None else service.price,
                           discount_value=0)
        db.session.add(item)
        db.session.flush()
        billing.apply_coverage(
            invoice, db.session.get(Patient, insured["ids"]["child"]))
        db.session.flush()
        return {"gross": item.gross, "net": item.net,
                "commission": item.commission_amount,
                "claimable": invoice.discount_total,
                "total": invoice.total,
                "share_total": invoice.doctor_share_total}


# ------------------------------------------------------------- the whole bug

def test_a_fully_covered_consultation_still_pays_the_doctor(insured):
    """80, not 0. The one number this whole file exists for."""
    assert _bill(insured)["commission"] == 80.0


def test_the_claim_is_unchanged_by_it(insured):
    """The insurer is still billed 200 and the family still owes nothing —
    the fix moves the doctor's share, not anybody's money."""
    row = _bill(insured)
    assert row["claimable"] == 200.0
    assert row["total"] == 0.0


def test_the_share_is_read_off_the_price_not_the_residual(insured):
    """Half covered: the doctor's share is 40% of 150, not 40% of the 75 the
    family is left with."""
    row = _bill(insured, "nebul")          # 150 at 50% commission, 50% covered
    assert row["gross"] == 150.0
    assert row["net"] == 75.0
    assert row["commission"] == 75.0       # 50% of 150, not 50% of 75


def test_the_invoices_own_total_share_follows(insured):
    """The figure every statement and payout reads."""
    assert _bill(insured)["share_total"] == 80.0


# ------------------------------------------ what must NOT have changed with it

def test_a_real_discount_still_costs_the_doctor(insured):
    """The distinction the fix rests on. A clinic that knocks money off a bill
    *has* sold the service for less, and the doctor's share goes down with it.
    Cover is not that."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = insured["db"]
    with insured["app"].app_context():
        service = db.session.get(Service, insured["ids"]["exam"])
        invoice = Invoice(patient_id=insured["ids"]["child"],
                          doctor_id=insured["doctor"], invoice_number="INV-D",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        # Priced by hand at half — a line carrying its own discount, which
        # cover is not allowed to touch.
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description=service.name, quantity=1,
                           unit_price=200, discount_value=100)
        db.session.add(item)
        db.session.flush()
        item.commission_amount = service.doctor_share(item.net, None)
        billing.apply_coverage(
            invoice, db.session.get(Patient, insured["ids"]["child"]))
        db.session.flush()
        # 40% of the 100 actually charged, and cover left the line alone.
        assert item.commission_amount == 40.0
        assert item.discount_value == 100


def test_a_clinic_with_no_payer_is_untouched(clinic):
    """The single-doctor cash clinic never reaches this code at all — the
    thing that has to stay true on the morning somebody updates."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = clinic["db"]
    with clinic["app"].app_context():
        service = db.session.get(Service, clinic["ids"]["exam"])
        invoice = Invoice(patient_id=clinic["ids"]["child"],
                          doctor_id=clinic["ids"]["doctor"],
                          invoice_number="INV-CASH",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description=service.name, quantity=1,
                           unit_price=200, discount_value=0)
        db.session.add(item)
        db.session.flush()
        item.commission_amount = service.doctor_share(item.net, None)
        billing.apply_coverage(
            invoice, db.session.get(Patient, clinic["ids"]["child"]))
        db.session.flush()
        assert item.commission_amount == 80.0
        assert invoice.payer_id is None


def test_an_invoice_already_written_is_never_repriced(insured):
    """The upgrade promise, tested rather than asserted in a note.

    Cover is applied when a bill is raised and at no other moment, so a
    clinic's history keeps whatever it was billed at. If some screen ever
    starts repricing old invoices, this fails and somebody reads why.
    """
    from app.models import Invoice, InvoiceItem, Patient
    from app.utils import billing

    db = insured["db"]
    with insured["app"].app_context():
        invoice = Invoice(patient_id=insured["ids"]["child"],
                          doctor_id=insured["doctor"], invoice_number="INV-OLD",
                          invoice_date=local_today(), status="paid")
        db.session.add(invoice)
        db.session.flush()
        # An old line: cover already taken off as a discount, and the share
        # stored the way the old code left it.
        item = InvoiceItem(invoice_id=invoice.id,
                           service_id=insured["ids"]["exam"],
                           description="كشف", quantity=1, unit_price=200,
                           discount_value=200, commission_amount=0)
        db.session.add(item)
        db.session.commit()

        billing.apply_coverage(
            invoice, db.session.get(Patient, insured["ids"]["child"]))
        db.session.flush()
        # Untouched: the line already carries a discount, so it is skipped.
        assert item.commission_amount == 0
        assert item.discount_value == 200


def test_the_lines_own_doctor_still_wins(insured):
    """A covered line belonging to a visiting doctor is priced at *their*
    rate. Cover and the surgeon's share are two fixes to the same sentence and
    they have to hold together."""
    from app.models import (Invoice, InvoiceItem, Patient, Service, User)
    from app.utils import billing

    db = insured["db"]
    with insured["app"].app_context():
        visiting = User(username="vis2", full_name="د. زائر", role="doctor",
                        is_active=True)
        visiting.set_password("secret")
        db.session.add(visiting)
        db.session.flush()

        service = db.session.get(Service, insured["ids"]["exam"])
        from app.models.service import DoctorServiceCommission

        db.session.add(DoctorServiceCommission(
            doctor_id=visiting.id, service_id=service.id,
            commission_type="percent", commission_value=60))
        invoice = Invoice(patient_id=insured["ids"]["child"],
                          doctor_id=insured["doctor"], invoice_number="INV-V",
                          invoice_date=local_today(), status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        item = InvoiceItem(invoice_id=invoice.id, service_id=service.id,
                           description="كشف", quantity=1, unit_price=200,
                           discount_value=0, doctor_id=visiting.id)
        db.session.add(item)
        db.session.flush()
        billing.apply_coverage(
            invoice, db.session.get(Patient, insured["ids"]["child"]))
        db.session.flush()
        assert item.commission_amount == 120.0   # 60% of 200, their own rate
