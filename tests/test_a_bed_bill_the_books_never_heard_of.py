"""A stay's bill, run through the same door as everybody else's.

Reported in one sentence: *"والجزء المحاسبي والمالي ماظبط؟ للمديولات دي اللي
عملناها؟"* — and it was not. Pricing an invoice in this program means four
things: the clinic's cash price list, the payer's tariff and cover split, the
named discounts, and a line in the ledger. All four lived as private helpers
inside ``blueprints/finance/routes.py``, which was fine while the cashier's
screen was the only thing that ever raised an invoice.

Then the wards started raising them, from outside that file, and missed all
four at once:

* a child with an insurance card was billed the **cash rate** for eleven
  nights, and nothing became claimable from the payer — on the single thing
  insurance most reliably pays for;
* the contract tariff and the cash price list never touched a bed line;
* the doctor's share of a night was **zero**, whatever the price list said;
* the hospital's largest revenue line reached the revenue report (it reads
  invoices) and never reached the profit-and-loss (it reads the journal), so
  the two disagreed by the biggest number in the building;
* and the cashier could not find the bill. The till looks for "today's
  invoice for this patient", which is right for an outpatient and wrong for a
  stay: the nights are charged on the ward on Tuesday, the family pays at the
  desk on Thursday, and the date rule opened a **second** invoice and left the
  ward's one hanging. The same failure as the appointment paid on Thursday for
  a Saturday booking, and for the same reason — the desk was guessing from a
  date because nothing recorded what the bill was for.

So the parts of that door which are not about a screen moved to
``utils/billing``, and this file is what holds them there. The move itself was
meant to change nothing, and there is a test below that says so in the one
place a "tidy up" would have done real damage: the vaccine line that carries
no invoice commission on purpose.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital(clinic):
    """A ward with a priced night, and a chart of accounts to post into."""
    from app.models import Service, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        for module in ("observations", "beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")

        night = Service(name="ليلة داخلي", category="other", price=500,
                        commission_type="percent", commission_value=10)
        clinic["db"].session.add(night)
        clinic["db"].session.flush()

        unit = Unit(name="الداخلي", kind="ward", rate_service_id=night.id)
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        for order, name in enumerate(("د١", "د٢")):
            clinic["db"].session.add(
                Bed(space_id=space.id, name=name, sort_order=order))
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
        clinic["night"] = night.id
    return clinic


def _child(clinic, name):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"B{name}", full_name=name,
                        gender="male", is_active=True,
                        date_of_birth=local_today() - timedelta(days=900))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, bed_name="د١", days_ago=3):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(clinic["beds"][bed_name]),
                          when=datetime.utcnow() - timedelta(days=days_ago))
        clinic["db"].session.commit()
        return row.id


def _post(clinic, admission_id):
    """Charge the stay the way a screen does — commit first, journal after.

    ``charge`` and not ``post``: the ledger posting is best-effort and rolls
    the session back when it fails, so calling it before the commit discards
    the very invoice it was journalling. A whole suite run found that; see
    ``bed_billing.charge``.
    """
    from app.models.admission import Admission
    from app.utils import bed_billing

    with clinic["app"].app_context():
        return bed_billing.charge(
            clinic["db"].session.get(Admission, admission_id))


def _bill(clinic, admission_id):
    """A snapshot of the stay's invoice, read inside a context.

    Read as plain values rather than handed back as a model, because the
    fixture opens its own session per call and an ``Invoice`` returned across
    that boundary is detached — its ``items`` blow up on the first assertion.
    """
    from app.models.invoice import Invoice

    with clinic["app"].app_context():
        row = Invoice.query.filter_by(admission_id=admission_id).one()
        return {
            "id": row.id, "number": row.invoice_number,
            "payer_id": row.payer_id, "coverage_card": row.coverage_card,
            "subtotal": row.subtotal, "discount_total": row.discount_total,
            "total": row.total,
            "prices": [i.unit_price for i in row.items],
            "commissions": [i.commission_amount for i in row.items],
            "lines": len(row.items),
        }


# ------------------------------------------------------- the doctor's share --
def test_the_doctor_is_paid_their_share_of_a_night(hospital):
    """A night is a chargeable service like any other. Left off at first, so a
    clinic that had set a commission on "a night on the ward" was paying
    nothing on the one service its inpatients buy most of."""
    child = _child(hospital, "نسبة")
    admission = _admit(hospital, child)
    _post(hospital, admission)

    bill = _bill(hospital, admission)
    assert bill["lines"] == 3
    assert bill["commissions"] == [50, 50, 50]


# ------------------------------------------------------------- the payer -----
def test_a_covered_child_is_not_billed_the_cash_rate_for_eleven_nights(
        hospital):
    """**The test this file exists for.**

    A stay is the single thing insurance most reliably pays for, and the bed
    bill was raised outside the door that knows about insurance at all.
    """
    from app.models.payer import (PatientCoverage, PayerEntity,
                                  PayerServiceRate)
    from app.utils.clock import local_today

    child = _child(hospital, "تأمين")

    with hospital["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", is_active=True)
        hospital["db"].session.add(payer)
        hospital["db"].session.flush()
        # The payer takes 80% of a night.
        hospital["db"].session.add(PayerServiceRate(
            payer_id=payer.id, service_id=hospital["night"],
            coverage_type="percent", coverage_value=80))
        hospital["db"].session.add(PatientCoverage(
            patient_id=child, payer_id=payer.id, membership_number="M-1",
            is_active=True, expiry_date=local_today() + timedelta(days=365)))
        hospital["db"].session.commit()
        payer_id = payer.id

    admission = _admit(hospital, child)
    _post(hospital, admission)

    bill = _bill(hospital, admission)
    # The payer is stamped on the bill, so the share is claimable at all.
    assert bill["payer_id"] == payer_id
    assert bill["coverage_card"] == "M-1"
    # And the family pays a fifth of it, not all of it.
    assert bill["subtotal"] == 1500
    assert bill["discount_total"] == 1200
    assert bill["total"] == 300


def test_a_payers_contract_tariff_reaches_the_night(hospital):
    """A negotiated price for a night is a price, and it has to be the one
    billed — otherwise the claim goes out at a number the payer never
    agreed to."""
    from app.models.payer import (PatientCoverage, PayerContract,
                                  PayerContractRate, PayerEntity)
    from app.utils.clock import local_today

    child = _child(hospital, "تعاقد")

    with hospital["app"].app_context():
        payer = PayerEntity(name="جهة متعاقدة", is_active=True)
        hospital["db"].session.add(payer)
        hospital["db"].session.flush()
        contract = PayerContract(payer_id=payer.id, number="٢٠٢٦",
                                 start_date=local_today() - timedelta(days=30),
                                 end_date=local_today() + timedelta(days=300),
                                 is_active=True)
        hospital["db"].session.add(contract)
        hospital["db"].session.flush()
        hospital["db"].session.add(PayerContractRate(
            contract_id=contract.id, service_id=hospital["night"],
            special_price=300, coverage_type="percent", coverage_value=0))
        hospital["db"].session.add(PatientCoverage(
            patient_id=child, payer_id=payer.id, membership_number="M-2",
            is_active=True, expiry_date=local_today() + timedelta(days=365)))
        hospital["db"].session.commit()

    admission = _admit(hospital, child)
    _post(hospital, admission)

    assert _bill(hospital, admission)["prices"] == [300, 300, 300]


def test_a_clinics_cash_price_reaches_the_night(hospital):
    """No card, no payer — and still not the list price, if the clinic keeps a
    cash tariff. It is what the walk-in pays, and a bed night is no more
    exempt from it than an X-ray."""
    from app.models.payer import (PayerContract, PayerContractRate,
                                  PayerEntity)
    from app.utils.clock import local_today
    from app.utils.pricing import set_cash_payer

    child = _child(hospital, "كاش")

    with hospital["app"].app_context():
        cash = PayerEntity(name="التسعيرة النقدية", is_active=True)
        hospital["db"].session.add(cash)
        hospital["db"].session.flush()
        contract = PayerContract(payer_id=cash.id, number="نقدي",
                                 start_date=local_today() - timedelta(days=30),
                                 is_active=True)
        hospital["db"].session.add(contract)
        hospital["db"].session.flush()
        hospital["db"].session.add(PayerContractRate(
            contract_id=contract.id, service_id=hospital["night"],
            special_price=450, coverage_type="percent", coverage_value=0))
        set_cash_payer(cash.id)
        hospital["db"].session.commit()

    admission = _admit(hospital, child)
    _post(hospital, admission)

    assert _bill(hospital, admission)["prices"] == [450, 450, 450]


# ------------------------------------------------------------ the ledger -----
def test_the_nights_reach_the_journal(hospital):
    """The revenue report reads invoices and the profit-and-loss reads the
    journal. Posted from the ward and never journalled, the two disagreed by
    the largest number in the hospital."""
    from app.models import JournalEntry

    child = _child(hospital, "دفتر")
    admission = _admit(hospital, child)
    _post(hospital, admission)

    bill = _bill(hospital, admission)
    with hospital["app"].app_context():
        entry = JournalEntry.query.filter_by(source_type="invoice",
                                             source_id=bill["id"]).one()
        moved = {(line.account.code, line.debit, line.credit)
                 for line in entry.lines}
        # Debit patients' receivables, credit service revenue.
        assert ("1030", 1500.0, 0.0) in moved
        assert ("4010", 0.0, 1500.0) in moved


def test_a_second_posting_refreshes_the_entry_rather_than_doubling_it(
        hospital):
    """A stay grows: three nights on Tuesday, two more on Thursday. The ledger
    has to mirror the bill, not add it up twice."""
    from app.models import JournalEntry
    from app.utils.clock import local_today

    child = _child(hospital, "مرتين_دفتر")
    admission = _admit(hospital, child, days_ago=4)

    from app.models.admission import Admission
    from app.utils import bed_billing

    with hospital["app"].app_context():
        stay = hospital["db"].session.get(Admission, admission)
        bed_billing.charge(stay, upto=local_today() - timedelta(days=3))
        bed_billing.charge(hospital["db"].session.get(Admission, admission))

    bill = _bill(hospital, admission)
    with hospital["app"].app_context():
        entries = JournalEntry.query.filter_by(source_type="invoice",
                                               source_id=bill["id"]).all()
        assert len(entries) == 1
        debit = sum(line.debit for line in entries[0].lines)
        assert debit == bill["total"]


def test_a_bookkeeping_failure_never_loses_the_bill(hospital, monkeypatch):
    """The invoice and the nights on it are the facts. A journal entry that
    could not be written is a report to fix on Monday, not a charge to refuse
    now — which is why the posting is best-effort.

    **Made to actually fail**, not merely left unseeded. The first version of
    this test deleted the chart of accounts, and with no accounts
    ``post_entry`` returns quietly and never raises — so a version that let
    the exception through passed it. Found by breaking the ``except`` and
    watching nothing fail.
    """
    from app.utils import accounting as acct

    def explode(*args, **kwargs):
        raise RuntimeError("the ledger is having a bad day")

    monkeypatch.setattr(acct, "post_invoice", explode)

    child = _child(hospital, "دفتر_واقع")
    admission = _admit(hospital, child)
    result = _post(hospital, admission)

    assert result["periods"] == 3
    assert _bill(hospital, admission)["lines"] == 3


def test_a_ledger_failure_does_not_roll_the_bill_away(hospital, monkeypatch):
    """**Found by a suite run, not by a mutation.**

    ``post_to_ledger`` rolls the session back when the journal refuses — which
    is right, and lethal if it runs before the bill is committed: the rollback
    discards the invoice it was trying to post, and the family goes home owing
    nothing because the chart of accounts was in a bad way. The till has
    always committed first; ``charge`` is where the wards do.
    """
    from app.models.invoice import Invoice
    from app.utils import accounting as acct

    def explode(*args, **kwargs):
        raise RuntimeError("the ledger is having a bad day")

    monkeypatch.setattr(acct, "post_invoice", explode)

    child = _child(hospital, "دفتر_وقع")
    admission = _admit(hospital, child)
    _post(hospital, admission)

    with hospital["app"].app_context():
        # The bill survived the rollback, because it was already committed.
        bill = Invoice.query.filter_by(admission_id=admission).one()
        assert len(bill.items) == 3
        assert bill.total == 1500


def test_the_button_on_the_stay_screen_journals_it_too(hospital):
    """Through the route, because that is what a person presses.

    The utility can be right and the screen still call the wrong one — and it
    did: a mutation that pointed the button back at the raw ``post`` passed
    every test in this file, because none of them went through the address.
    """
    from app.models import JournalEntry
    from app.models.invoice import Invoice

    child = _child(hospital, "زرار")
    admission = _admit(hospital, child)

    hospital["sign_in"]("boss").post(f"/beds/admission/{admission}/nights",
                                     data={}, follow_redirects=True)

    with hospital["app"].app_context():
        bill = Invoice.query.filter_by(admission_id=admission).one()
        assert len(bill.items) == 3
        assert JournalEntry.query.filter_by(source_type="invoice",
                                            source_id=bill.id).count() == 1


def test_a_discharge_journals_the_nights_it_charges(hospital):
    """The other door onto the same act, and the one that runs unattended at
    the end of a stay."""
    from app.models import JournalEntry
    from app.models.invoice import Invoice

    child = _child(hospital, "خروج_دفتر")
    admission = _admit(hospital, child)

    hospital["sign_in"]("boss").post(
        f"/beds/admission/{admission}/discharge",
        data={"outcome": "home"}, follow_redirects=True)

    with hospital["app"].app_context():
        bill = Invoice.query.filter_by(admission_id=admission).one()
        assert JournalEntry.query.filter_by(source_type="invoice",
                                            source_id=bill.id).count() == 1


# ------------------------------------------------- the cashier finds it ------
def test_the_till_finds_a_stay_bill_raised_on_another_day(hospital):
    """The failure reported for appointments, happening again for stays: the
    desk matched by date, so a family paying on Thursday for nights charged on
    Tuesday opened a second invoice and left the first one hanging.

    Asked of **the till's own lookup** and not of the helper underneath it.
    The first version of this test called ``billing.stay_invoice`` directly,
    so tearing the hook out of ``_todays_invoice`` — which is the whole fix —
    changed nothing and the test still passed.
    """
    from app.blueprints.finance.routes import _todays_invoice
    from app.models.invoice import Invoice
    from app.utils.clock import local_today

    child = _child(hospital, "بكرة")
    admission = _admit(hospital, child)
    _post(hospital, admission)

    with hospital["app"].app_context():
        # The ward charged the nights yesterday; the family is at the desk now.
        bill = Invoice.query.filter_by(admission_id=admission).one()
        bill.invoice_date = local_today() - timedelta(days=1)
        hospital["db"].session.commit()

        found = _todays_invoice(child)
        assert found is not None and found.id == bill.id


def test_a_settled_stay_does_not_come_back_at_the_next_visit(hospital):
    """Only what is still owed is offered. A stay paid in full at discharge
    must not reopen when the child returns in March for a sore throat."""
    from app.models.invoice import Invoice, Payment
    from app.utils import billing

    child = _child(hospital, "اتسدد")
    admission = _admit(hospital, child)
    _post(hospital, admission)

    with hospital["app"].app_context():
        bill = Invoice.query.filter_by(admission_id=admission).one()
        hospital["db"].session.add(Payment(invoice_id=bill.id, kind="payment",
                                           amount=bill.total, method="cash"))
        hospital["db"].session.commit()

        assert billing.stay_invoice(child) is None


def test_a_patient_with_no_stay_is_untouched(hospital):
    """The outpatient rule is unchanged for everybody who has no stay: this
    is an extra door, not a replacement for the one that works."""
    from app.utils import billing

    child = _child(hospital, "خارجي")
    with hospital["app"].app_context():
        assert billing.stay_invoice(child) is None


# --------------------------------------------- the move changed nothing ------
def test_the_vaccine_line_still_carries_no_invoice_commission(hospital):
    """**The one place a tidy-up would have cost money.**

    A vaccine product line deliberately carries no commission on the invoice:
    the doctor's share of a vaccine is the brand's ``doctor_fee``, tracked on
    the dose. A "recompute the commission on every line" while moving this
    code would have paid it twice, silently, on every vaccine sold.
    """
    from app.models.invoice import Invoice, InvoiceItem
    from app.models.service import Service
    from app.utils import billing
    from app.utils.finance import generate_invoice_number

    child = _child(hospital, "تطعيم")
    with hospital["app"].app_context():
        product = Service(name="لقاح", category="vaccination_fee", price=900,
                          commission_type="percent", commission_value=20)
        hospital["db"].session.add(product)
        hospital["db"].session.flush()
        bill = Invoice(invoice_number=generate_invoice_number(),
                       patient_id=child)
        hospital["db"].session.add(bill)
        hospital["db"].session.flush()
        line = InvoiceItem(invoice_id=bill.id, service_id=product.id,
                           description="لقاح", unit_price=900, quantity=1,
                           commission_amount=0)
        hospital["db"].session.add(line)
        hospital["db"].session.flush()

        from app.models import Patient
        billing.apply_coverage(bill, hospital["db"].session.get(Patient, child))
        hospital["db"].session.commit()

        assert line.commission_amount == 0


def test_nothing_in_the_pricing_door_needs_a_screen(hospital):
    """It is called from a ward round with nobody standing at a till, and a
    ``flash`` outside a request context is a crash rather than a message. The
    warnings are a callback the screen passes in."""
    import inspect

    from app.utils import billing

    source = inspect.getsource(billing)
    assert "flash(" not in source, "the pricing door reaches for the screen"
    assert "warn" in inspect.signature(billing.apply_coverage).parameters


def test_the_finance_screen_still_warns_about_an_expired_card(hospital):
    """The wrapper kept the half that needs a person: the warning still
    reaches the cashier through the callback."""
    import inspect

    from app.blueprints.finance import routes

    source = inspect.getsource(routes._apply_coverage)
    assert "billing.apply_coverage" in source
    assert "flash" in source and "warn=" in source
