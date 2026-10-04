"""The last three pieces of the hospital insurance plan.

* **The approval letter** — the payer's paper, scanned or photographed,
  kept with its answer and opened from the approvals list and the bill.
* **While a line waits for its approval**, per contract: the bill waits and
  the family is not asked (as before), or the family pays the line now and
  is refunded to its own account when the approval arrives — never an
  urgent emergency child.
* **A suggested deposit** per department, the hospital's figure for a cash
  patient and the contract's for a member, read on the stay.
"""
import os
import sys
from datetime import datetime, timedelta
from io import BytesIO

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_an_approval_that_travels_with_the_claim import (  # noqa: E402,F401
    _bill, insured)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _approval(c):
    from app.models import InsuranceApproval

    with c["app"].app_context():
        row = InsuranceApproval(patient_id=c["ids"]["child"], payer_id=c["ids"]["payer"],
                                service_id=c["ids"]["mri"], status="requested")
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _decide(c, approval_id, **extra):
    data = dict(decision="approved", approval_number="AP-77", **extra)
    return c["sign_in"]("boss").post(f"/finance/approvals/{approval_id}/decide", data=data,
                                     content_type="multipart/form-data")


def _policy(c, policy):
    from app.models import PayerContract

    with c["app"].app_context():
        row = PayerContract.query.one()
        row.approval_policy = policy
        c["db"].session.commit()


# ------------------------------------------------------------ the letter --
def test_the_letter_is_kept_with_the_answer(insured):
    from app.models import InsuranceApproval

    inv, _item = _bill(insured, "mri", 2000)
    approval = _approval(insured)
    _decide(insured, approval, letter=(BytesIO(PNG), "letter.png"))
    with insured["app"].app_context():
        row = insured["db"].session.get(InsuranceApproval, approval)
        assert row.letter_file and row.letter_file.endswith(".png")
    boss = insured["sign_in"]("boss")
    assert "data-approval-letter" in boss.get("/finance/approvals").get_data(as_text=True)
    assert "uploads/patient_docs/" in boss.get(f"/finance/invoices/{inv}").get_data(as_text=True)


def test_a_file_that_is_not_a_letter_is_refused(insured):
    from app.models import InsuranceApproval

    approval = _approval(insured)
    _decide(insured, approval, letter=(BytesIO(b"<html>"), "x.png"))
    with insured["app"].app_context():
        row = insured["db"].session.get(InsuranceApproval, approval)
        assert row.letter_file is None and row.status == "requested"


# ------------------------------------------------- waiting for approval --
def test_by_default_the_bill_waits_and_the_family_is_not_asked(insured):
    from app.models import Invoice

    inv, _item = _bill(insured, "mri", 2000)
    with insured["app"].app_context():
        row = insured["db"].session.get(Invoice, inv)
        assert row.total == 400.0 and row.waiting_approval


def test_collect_now_and_refund_to_the_account_on_approval(insured):
    from app.models import Invoice, Payment
    from app.utils import patient_credit

    _policy(insured, "collect")
    inv, item = _bill(insured, "mri", 2000)
    with insured["app"].app_context():
        db = insured["db"]
        row = db.session.get(Invoice, inv)
        assert row.total == 2000.0, "the family was not asked while it waits"
        assert [i.cover_note for i in row.items] == ["awaiting_approval"]
        row.payments.append(Payment(amount=2000, method="card"))
        row.recalc_status()
        db.session.commit()
    approval = _approval(insured)
    _decide(insured, approval)
    with insured["app"].app_context():
        db = insured["db"]
        row = db.session.get(Invoice, inv)
        assert row.total == 400.0 and row.payer_total == 1600.0
        assert row.balance == 0 and row.status == "paid"
        assert patient_credit.balance(insured["ids"]["child"]) == 1600.0
        assert [(p.method, p.kind, p.amount) for p in row.payments][-1] == ("credit", "refund", 1600.0)


def test_an_urgent_emergency_child_never_pays_while_it_waits(insured):
    from app.models import Invoice, Patient, Setting, User
    from app.utils import billing
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo
    from app.models import InvoiceItem, Service
    from app.utils.clock import local_today

    _policy(insured, "collect")
    with insured["app"].app_context():
        db = insured["db"]
        Setting.set("mod_enabled:emergency", "1")
        child = db.session.get(Patient, insured["ids"]["child"])
        attendance = util.arrive(child, at=datetime.utcnow() - timedelta(minutes=5))
        db.session.flush()
        util.triage(attendance, level="أحمر", urgent=True)
        visit = eo.encounter(attendance, db.session.get(User, insured["ids"]["doctor"]))
        db.session.flush()
        inv = Invoice(patient_id=child.id, invoice_number="ER-1", invoice_date=local_today(),
                      status="unpaid", visit_id=visit.id)
        db.session.add(inv)
        db.session.flush()
        mri = db.session.get(Service, insured["ids"]["mri"])
        db.session.add(InvoiceItem(invoice_id=inv.id, service_id=mri.id, description=mri.name,
                                   quantity=1, unit_price=2000))
        db.session.flush()
        db.session.refresh(inv)
        billing.apply_coverage(inv, child)
        db.session.commit()
        assert inv.total == 400.0, "an urgent emergency child was asked to pay ahead"


# -------------------------------------------------------- the deposit --
def _stay(c, kind="nicu"):
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward

    with c["app"].app_context():
        db = c["db"]
        Setting.set("mod_enabled:beds", "1")
        unit = Unit(name="الحضانة", kind=kind)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="حضانة 1", kind="incubator")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, c["ids"]["child"]), bed)
        db.session.commit()
        return stay.id


def test_the_suggested_deposit_the_department_s_and_the_contract_s(insured):
    from app.models import Admission, PatientCoverage, PayerContract, PayerContractTerm, Setting
    from app.utils import patient_credit

    stay = _stay(insured)
    with insured["app"].app_context():
        db = insured["db"]
        Setting.set("deposit_suggest:nicu", "5000")
        # A cash patient first: the member's card put aside.
        PatientCoverage.query.update({PatientCoverage.is_active: False})
        db.session.commit()
        assert patient_credit.suggested_deposit(db.session.get(Admission, stay)) == (5000.0, "department")
    page = insured["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-deposit-suggested" in page and 'value="5000.0"' in page
    with insured["app"].app_context():
        db = insured["db"]
        PatientCoverage.query.update({PatientCoverage.is_active: True})
        contract = PayerContract.query.one()
        db.session.add(PayerContractTerm(contract_id=contract.id, setting="nicu",
                                         deposit_amount=1500))
        db.session.commit()
        assert patient_credit.suggested_deposit(db.session.get(Admission, stay)) == (1500.0, "contract")


def test_the_contract_screen_sets_the_policy_and_the_deposit(insured):
    from app.models import PayerContract

    with insured["app"].app_context():
        cid = PayerContract.query.one().id
    boss = insured["sign_in"]("boss")
    page = boss.get(f"/finance/contract/{cid}/rates").get_data(as_text=True)
    assert "data-approval-policy" in page
    boss.post(f"/finance/contract/{cid}/year", data={"approval_policy": "collect"})
    boss.post(f"/finance/contract/{cid}/terms", data={"setting": "icu", "deposit_amount": "3000"})
    with insured["app"].app_context():
        row = insured["db"].session.get(PayerContract, cid)
        assert row.approval_policy == "collect"
        assert [(t.setting, t.deposit_amount) for t in row.terms] == [("icu", 3000.0)]
