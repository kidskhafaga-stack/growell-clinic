"""What the family carries on a contract: a fixed share, a deductible, and
where the payer stops.

Asked as *«حسب كل عقد ايه الى داخل على العقد وايه الى المريض بيحاسب
عنده»*. The rules said what share of each line the payer covers; an
agreement says more, and the program now holds it:

* a fixed sum the family pays on each bill, per department;
* a yearly deductible — the first so much of what would be covered;
* the most the payer pays per bill, per year, and per night's bed (a ward
  bed is covered, a private room is the difference);
* each line says why the family pays what it pays.

**And a bug found on the way, measured before it was fixed.** A stay's bill
is covered again each night it is charged, and every pass zeroed the payer's
figure on the lines it had covered before — so two nights covered at 270
each were claimed as **270**. Cover the program wrote is recomputed now, and
a discount somebody typed is still left alone.

Every figure is the hospital's own; a contract with none bills as before.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402
from tests.test_a_contract_that_knows_the_departments import (  # noqa: E402,F401
    _rule, _stay, insured)


def _contract(c, **figures):
    from app.models import PayerContract

    with c["app"].app_context():
        row = c["db"].session.get(PayerContract, c["ids"]["contract"])
        for k, v in figures.items():
            setattr(row, k, v)
        c["db"].session.commit()


def _term(c, setting="any", **figures):
    from app.models import PayerContractTerm

    with c["app"].app_context():
        c["db"].session.add(PayerContractTerm(contract_id=c["ids"]["contract"],
                                              setting=setting, **figures))
        c["db"].session.commit()


def _bill(c, lines, admission_id=None, number="INV-1"):
    """``lines``: [(service_key or None, price, manual_discount)]. Returns the
    invoice id."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    with c["app"].app_context():
        db = c["db"]
        inv = Invoice(patient_id=c["ids"]["child"], invoice_number=number,
                      invoice_date=local_today(), status="unpaid",
                      admission_id=admission_id)
        db.session.add(inv)
        db.session.flush()
        for key, price, manual in lines:
            svc = db.session.get(Service, c["ids"][key]) if key else None
            db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id if svc else None,
                                       description=svc.name if svc else "شاش",
                                       quantity=1, unit_price=price, discount_value=manual))
        db.session.flush()
        db.session.refresh(inv)
        billing.apply_coverage(inv, db.session.get(Patient, c["ids"]["child"]))
        db.session.commit()
        return inv.id


def _cover_again(c, invoice_id, add=None):
    """Add a line (``(service_key, price)``) and cover the bill again — what
    the ward does every night."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    with c["app"].app_context():
        db = c["db"]
        inv = db.session.get(Invoice, invoice_id)
        if add:
            svc = db.session.get(Service, c["ids"][add[0]])
            db.session.add(InvoiceItem(invoice_id=inv.id, service_id=svc.id,
                                       description=svc.name, quantity=1, unit_price=add[1]))
            db.session.flush()
            db.session.refresh(inv)
        billing.apply_coverage(inv, db.session.get(Patient, c["ids"]["child"]))
        db.session.commit()


def _read(c, invoice_id):
    from app.models import Invoice

    with c["app"].app_context():
        inv = c["db"].session.get(Invoice, invoice_id)
        return {"payer": inv.payer_total, "family": inv.total,
                "lines": [(i.payer_amount, i.cover_note) for i in inv.items]}


# --------------------------------------------- the bug, measured first --
def test_a_stay_covered_night_by_night_claims_every_night(insured):
    stay = _stay(insured, "ward")
    _rule(insured, setting="inpatient", scope="all", coverage_type="percent", coverage_value=90)
    inv = _bill(insured, [("film", 300, 0)], admission_id=stay)
    _cover_again(insured, inv, add=("film", 300))
    _cover_again(insured, inv, add=("film", 300))
    got = _read(insured, inv)
    assert got["payer"] == 810.0, "the earlier nights fell off the claim"
    assert got["family"] == 90.0


def test_a_typed_discount_survives_the_next_night(insured):
    stay = _stay(insured, "ward")
    inv = _bill(insured, [("cbc", 100, 30)], admission_id=stay)
    _cover_again(insured, inv, add=("exam", 200))
    from app.models import Invoice

    with insured["app"].app_context():
        items = insured["db"].session.get(Invoice, inv).items
        assert [(i.discount_value, i.payer_amount) for i in items] == [(30, 0.0), (200.0, 200.0)]
    assert _read(insured, inv)["payer"] == 200.0


# --------------------------------------------- a contract with no terms --
def test_no_terms_bills_as_before_and_says_why(insured):
    got = _read(insured, _bill(insured, [("exam", 200, 0), ("cbc", 100, 0)]))
    assert got["payer"] == 200.0
    assert got["lines"] == [(200.0, None), (0.0, "not_covered")]


# ----------------------------------------------------------- per bill --
def test_a_fixed_share_on_each_bill_in_its_department(insured):
    stay = _stay(insured, "ward")
    _term(insured, "outpatient", copay_amount=50)
    clinic = _read(insured, _bill(insured, [("exam", 200, 0)], number="INV-O"))
    assert clinic["payer"] == 150.0 and clinic["family"] == 50.0
    assert clinic["lines"] == [(150.0, "copay")]
    ward = _read(insured, _bill(insured, [("exam", 200, 0)], admission_id=stay, number="INV-W"))
    assert ward["payer"] == 200.0, "the clinic's share reached the ward"


def test_the_ceiling_per_bill_cuts_the_later_charges(insured):
    _rule(insured, setting="any", scope="all", coverage_type="percent", coverage_value=100)
    _term(insured, ceiling_case=250)
    got = _read(insured, _bill(insured, [("exam", 200, 0), ("film", 300, 0)]))
    assert got["payer"] == 250.0 and got["family"] == 250.0
    assert got["lines"] == [(200.0, None), (50.0, "over_ceiling")]


def test_the_room_over_the_nightly_ceiling_is_the_familys(insured):
    from app.models import BedCharge, Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    stay = _stay(insured, "ward")
    _rule(insured, setting="inpatient", scope="all", coverage_type="percent", coverage_value=100)
    _term(insured, "inpatient", night_ceiling=400)
    with insured["app"].app_context():
        db = insured["db"]
        room = Service(name="غرفة خاصة", category="accommodation", price=700, is_active=True)
        db.session.add(room)
        inv = Invoice(patient_id=insured["ids"]["child"], invoice_number="S-1",
                      invoice_date=local_today(), status="unpaid", admission_id=stay)
        db.session.add(inv)
        db.session.flush()
        night = InvoiceItem(invoice_id=inv.id, service_id=room.id, description="ليلة",
                            quantity=1, unit_price=700)
        lab = InvoiceItem(invoice_id=inv.id, service_id=insured["ids"]["cbc"],
                          description="صورة دم", quantity=1, unit_price=100)
        db.session.add_all([night, lab])
        db.session.flush()
        db.session.add(BedCharge(admission_id=stay, patient_id=insured["ids"]["child"],
                                 on_date=local_today(), quantity=1, basis="night",
                                 service_id=room.id, unit_price=700, invoice_item_id=night.id))
        db.session.flush()
        db.session.refresh(inv)
        billing.apply_coverage(inv, db.session.get(Patient, insured["ids"]["child"]))
        db.session.commit()
        inv_id = inv.id
    got = _read(insured, inv_id)
    assert got["lines"] == [(400.0, "room_ceiling"), (100.0, None)]
    assert got["family"] == 300.0


# ----------------------------------------------------------- per year --
def test_the_deductible_is_carried_once_across_the_year(insured):
    _contract(insured, deductible_year=300)
    first = _bill(insured, [("exam", 200, 0)], number="INV-1")
    second = _bill(insured, [("exam", 200, 0)], number="INV-2")
    third = _bill(insured, [("exam", 200, 0)], number="INV-3")
    assert [_read(insured, i)["payer"] for i in (first, second, third)] == [0.0, 100.0, 200.0]
    # Covered again — the first bill does not take the deductible twice, and
    # the others do not move.
    _cover_again(insured, first)
    _cover_again(insured, third)
    assert [_read(insured, i)["payer"] for i in (first, second, third)] == [0.0, 100.0, 200.0]


def test_the_yearly_ceiling(insured):
    _contract(insured, ceiling_year=300)
    paid = [_read(insured, _bill(insured, [("exam", 200, 0)], number=f"INV-{n}"))["payer"]
            for n in range(3)]
    assert paid == [200.0, 100.0, 0.0]


def test_the_claim_is_what_the_payer_owes_after_the_terms(insured):
    from app.models import Claim

    _term(insured, copay_amount=50)
    _bill(insured, [("exam", 200, 0)])
    boss = insured["sign_in"]("boss")
    day = local_today().isoformat()
    boss.post("/finance/claims/create", data={"payer_id": insured["ids"]["payer"],
                                              "date_from": day, "date_to": day})
    with insured["app"].app_context():
        assert Claim.query.one().total_amount == 150.0


# --------------------------------------------------- the contract screen --
def test_the_terms_are_set_on_the_contract_screen(insured):
    from app.models import PayerContract

    boss = insured["sign_in"]("boss")
    url = f"/finance/contract/{insured['ids']['contract']}"
    assert "data-contract-terms" in boss.get(url + "/rates").get_data(as_text=True)
    boss.post(url + "/terms", data={"setting": "nicu", "copay_amount": "100",
                                    "ceiling_case": "", "night_ceiling": "450"})
    boss.post(url + "/terms", data={"setting": "icu", "copay_amount": "-5"})
    boss.post(url + "/year", data={"deductible_year": "500", "ceiling_year": "20000"})
    with insured["app"].app_context():
        c = insured["db"].session.get(PayerContract, insured["ids"]["contract"])
        assert [(t.setting, t.copay_amount, t.ceiling_case, t.night_ceiling)
                for t in c.terms] == [("nicu", 100.0, None, 450.0)]
        assert (c.deductible_year, c.ceiling_year) == (500.0, 20000.0)
        term_id = c.terms[0].id
    # Every box empty takes the department's row away.
    boss.post(url + "/terms", data={"setting": "nicu"})
    with insured["app"].app_context():
        assert insured["db"].session.get(PayerContract, insured["ids"]["contract"]).terms == []
    assert term_id


def test_a_renewal_keeps_the_terms(insured):
    from app.models import PayerContract

    _term(insured, "inpatient", copay_amount=100, night_ceiling=400)
    _contract(insured, deductible_year=500)
    with insured["app"].app_context():
        clone = insured["db"].session.get(PayerContract, insured["ids"]["contract"]).copy_to("C-2")
        assert [(t.setting, t.copay_amount, t.night_ceiling) for t in clone.terms] == [
            ("inpatient", 100, 400)]
        assert clone.deductible_year == 500


def test_the_bill_says_why(insured):
    _term(insured, copay_amount=50)
    inv = _bill(insured, [("exam", 200, 0), ("cbc", 100, 0)])
    page = insured["sign_in"]("boss").get(f"/finance/invoices/{inv}").get_data(as_text=True)
    assert 'data-cover-note="copay"' in page and 'data-cover-note="not_covered"' in page
