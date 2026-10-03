"""Prior approvals: the line carries the payer's number, or its bill waits.

Asked as *«ولو هو تعاقد لازم موافقات على حجات معينة لان دي بتتبعت مع
المطالبات»*. What is held here:

* a rule that asks for an approval flags a covered line that has none — the
  cover stays, nothing is quietly moved onto the family — and its bill waits
  out of the claim;
* recording the payer's answer links it to every line waiting for it, the
  line shows the number, and the bill is claimable again;
* an approval for a stay covers what that stay needs; one past its date, or
  refused, covers nothing;
* a rule that asks for nothing flags nothing.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def insured(clinic):
    from app.models import (PatientCoverage, PayerContract, PayerContractRule,
                            PayerEntity, Service)

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance", is_active=True)
        db.session.add(payer)
        db.session.flush()
        contract = PayerContract(payer_id=payer.id, number="C-1", is_active=True)
        db.session.add(contract)
        db.session.flush()
        mri = Service(name="رنين مغناطيسي", category="radiology", price=2000, is_active=True)
        db.session.add(mri)
        db.session.flush()
        db.session.add(PayerContractRule(contract_id=contract.id, setting="any",
                                         scope="category", category="radiology",
                                         coverage_type="percent", coverage_value=80,
                                         needs_approval=True))
        db.session.add(PayerContractRule(contract_id=contract.id, setting="any",
                                         scope="service", service_id=clinic["ids"]["exam"],
                                         coverage_type="percent", coverage_value=100))
        db.session.add(PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                                       membership_number="M-1", is_active=True))
        db.session.commit()
        clinic["ids"].update(payer=payer.id, mri=mri.id)
    return clinic


def _bill(c, key, price, number="INV-1", admission_id=None):
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = c["db"]
    with c["app"].app_context():
        svc = db.session.get(Service, c["ids"][key])
        inv = Invoice(patient_id=c["ids"]["child"], invoice_number=number,
                      invoice_date=local_today(), status="unpaid", admission_id=admission_id)
        db.session.add(inv)
        db.session.flush()
        item = InvoiceItem(invoice_id=inv.id, service_id=svc.id, description=svc.name,
                           quantity=1, unit_price=price, discount_value=0)
        db.session.add(item)
        db.session.flush()
        billing.apply_coverage(inv, db.session.get(Patient, c["ids"]["child"]))
        db.session.commit()
        return inv.id, item.id


def _item(c, item_id):
    from app.models import InvoiceItem

    with c["app"].app_context():
        it = c["db"].session.get(InvoiceItem, item_id)
        return {"needed": it.approval_needed, "approval": it.approval_id,
                "payer": it.payer_amount}


def _claimable(c):
    from app.blueprints.finance.routes import _claimable_invoices

    with c["app"].app_context():
        return [i.id for i in _claimable_invoices(c["ids"]["payer"], local_today(), local_today())]


def test_a_line_that_needs_approval_is_flagged_and_its_bill_waits(insured):
    inv, item = _bill(insured, "mri", 2000)
    assert _item(insured, item) == {"needed": True, "approval": None, "payer": 1600.0}
    assert inv not in _claimable(insured), "sent to the payer without its approval"
    page = insured["sign_in"]("boss").get(f"/finance/invoices/{inv}").get_data(as_text=True)
    assert f'data-approval-missing="{item}"' in page


def test_a_rule_that_asks_for_nothing_flags_nothing(insured):
    inv, item = _bill(insured, "exam", 200)
    assert _item(insured, item)["needed"] is None
    assert inv in _claimable(insured)


def test_recording_the_answer_links_it_and_the_bill_is_claimable(insured):
    from app.models import InsuranceApproval

    inv, item = _bill(insured, "mri", 2000)
    boss = insured["sign_in"]("boss")
    page = boss.get(f"/finance/approvals?item={item}").get_data(as_text=True)
    assert "data-prefilled" in page and f'data-waiting-line="{item}"' in page
    boss.post("/finance/approvals", data={"patient_id": insured["ids"]["child"],
                                          "payer_id": insured["ids"]["payer"],
                                          "service_id": insured["ids"]["mri"],
                                          "estimate": "2000"})
    with insured["app"].app_context():
        approval = InsuranceApproval.query.one()
        assert approval.status == "requested"
        aid = approval.id
    # Refused without a number on an approval: nothing changes.
    boss.post(f"/finance/approvals/{aid}/decide", data={"decision": "approved",
                                                        "approval_number": ""})
    assert _item(insured, item)["needed"] is True
    boss.post(f"/finance/approvals/{aid}/decide",
              data={"decision": "approved", "approval_number": "AP-777",
                    "approved_amount": "1600",
                    "valid_until": (local_today() + timedelta(days=30)).isoformat()})
    assert _item(insured, item) == {"needed": False, "approval": aid, "payer": 1600.0}
    assert inv in _claimable(insured)


def test_a_later_bill_finds_the_approval_on_file(insured):
    from app.models import InsuranceApproval

    with insured["app"].app_context():
        db = insured["db"]
        db.session.add(InsuranceApproval(patient_id=insured["ids"]["child"],
                                         payer_id=insured["ids"]["payer"],
                                         service_id=insured["ids"]["mri"],
                                         status="approved", approval_number="AP-1"))
        db.session.commit()
    _, item = _bill(insured, "mri", 2000)
    assert _item(insured, item)["needed"] is False


def test_an_expired_or_refused_approval_covers_nothing(insured):
    from app.models import InsuranceApproval

    with insured["app"].app_context():
        db = insured["db"]
        db.session.add(InsuranceApproval(patient_id=insured["ids"]["child"],
                                         payer_id=insured["ids"]["payer"],
                                         service_id=insured["ids"]["mri"],
                                         status="approved", approval_number="OLD",
                                         valid_until=local_today() - timedelta(days=1)))
        db.session.add(InsuranceApproval(patient_id=insured["ids"]["child"],
                                         payer_id=insured["ids"]["payer"],
                                         service_id=insured["ids"]["mri"],
                                         status="rejected"))
        db.session.commit()
    _, item = _bill(insured, "mri", 2000)
    assert _item(insured, item)["needed"] is True


def test_an_approval_for_the_stay_covers_what_the_stay_needs(insured):
    from app.models import InsuranceApproval, Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward

    with insured["app"].app_context():
        db = insured["db"]
        Setting.set("mod_enabled:beds", "1")
        unit = Unit(name="الداخلي", kind="ward")
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير", kind="bed")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, insured["ids"]["child"]), bed)
        db.session.flush()
        db.session.add(InsuranceApproval(patient_id=insured["ids"]["child"],
                                         payer_id=insured["ids"]["payer"],
                                         admission_id=stay.id, status="approved",
                                         approval_number="ADM-5"))
        db.session.commit()
        stay_id = stay.id
    _, inside = _bill(insured, "mri", 2000, number="INV-S", admission_id=stay_id)
    _, outside = _bill(insured, "mri", 2000, number="INV-O")
    assert _item(insured, inside)["needed"] is False
    assert _item(insured, outside)["needed"] is True


def test_the_contract_screen_sets_a_rule_that_needs_approval(insured):
    from app.models import PayerContract, PayerContractRule

    with insured["app"].app_context():
        cid = PayerContract.query.one().id
    insured["sign_in"]("boss").post(f"/finance/contract/{cid}/rules",
                                    data={"setting": "icu", "scope": "all",
                                          "coverage_type": "percent", "coverage_value": "90",
                                          "needs_approval": "1"})
    with insured["app"].app_context():
        row = PayerContractRule.query.filter_by(setting="icu").one()
        assert row.needs_approval is True
