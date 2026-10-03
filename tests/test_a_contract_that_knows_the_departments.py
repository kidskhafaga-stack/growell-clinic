"""A contract that knows the departments, and a claim that claims the cover.

Asked as *«نظام التأمين ده شغال على كل الاقسام الطوارئ والداخلى والحضانة
وحسب كل عقد ايه الى داخل على العقد وايه الى المريض بيحاسب عنده … عايز اظبط
نظام العقود وسراينها علشان تناسب المستشفيات مش العيادات بس»*.

**And a bug found on the way, measured before it was fixed.** The claim was
the invoice's discount total, and cover is stored as a discount — so a
cashier's own discount on another line went to the insurer as well: a 200
consultation covered in full and a 30 courtesy discount on the gauze were
claimed as **230**. Cover is now kept per line (`InvoiceItem.payer_amount`)
and the claim reads that, and only that.

What is held here:

* the claim is the cover, never a cashier's discount; an invoice billed
  before the figure existed reads as it did;
* a contract with no department rules bills exactly as before;
* a rule for one department and one service beats the price list, which
  beats the rules by category and by «everything else»;
* the department is read off the bill: a stay's bed, the emergency, or the
  outpatient clinic;
* «not covered» in a department means the family pays all of it there;
* a renewed contract keeps its rules.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def insured(clinic):
    from app.models import (PatientCoverage, PayerContract, PayerContractRate,
                            PayerEntity, Service)

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة تأمين", entity_type="insurance", is_active=True)
        db.session.add(payer)
        db.session.flush()
        contract = PayerContract(payer_id=payer.id, number="C-1", is_active=True)
        db.session.add(contract)
        db.session.flush()
        # The price list: the consultation 100% covered, in every department.
        db.session.add(PayerContractRate(contract_id=contract.id,
                                         service_id=clinic["ids"]["exam"],
                                         coverage_type="percent", coverage_value=100))
        cbc = Service(name="صورة دم", category="lab", price=100, is_active=True)
        film = Service(name="أشعة صدر", category="radiology", price=300, is_active=True)
        db.session.add_all([cbc, film])
        db.session.add(PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                                       membership_number="M-1", is_active=True))
        db.session.commit()
        clinic["ids"].update(payer=payer.id, contract=contract.id, cbc=cbc.id, film=film.id)
    return clinic


def _rule(c, **kw):
    from app.models import PayerContractRule

    with c["app"].app_context():
        c["db"].session.add(PayerContractRule(contract_id=c["ids"]["contract"], **kw))
        c["db"].session.commit()


def _bill(c, lines, admission_id=None, visit_id=None, number="INV-1"):
    """``lines`` is [(service_key or None, price, manual_discount)]. Returns
    {service_key: payer_amount} and the invoice id."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = c["db"]
    with c["app"].app_context():
        inv = Invoice(patient_id=c["ids"]["child"], doctor_id=c["ids"]["doctor"],
                      invoice_number=number, invoice_date=local_today(), status="unpaid",
                      admission_id=admission_id, visit_id=visit_id)
        db.session.add(inv)
        db.session.flush()
        items = {}
        for key, price, manual in lines:
            svc = db.session.get(Service, c["ids"][key]) if key else None
            item = InvoiceItem(invoice_id=inv.id, service_id=svc.id if svc else None,
                               description=svc.name if svc else "شاش", quantity=1,
                               unit_price=price, discount_value=manual)
            db.session.add(item)
            items[key or "free"] = item
        db.session.flush()
        billing.apply_coverage(inv, db.session.get(Patient, c["ids"]["child"]))
        db.session.commit()
        return {k: i.payer_amount for k, i in items.items()}, inv.id


def _payer_total(c, invoice_id):
    from app.models import Invoice

    with c["app"].app_context():
        return c["db"].session.get(Invoice, invoice_id).payer_total


def _stay(c, unit_kind):
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward

    with c["app"].app_context():
        db = c["db"]
        Setting.set("mod_enabled:beds", "1")
        unit = Unit(name=unit_kind, kind=unit_kind)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير", kind="bed")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, c["ids"]["child"]), bed)
        db.session.commit()
        return stay.id


# ------------------------------------------------- the claim is the cover --
def test_a_cashiers_discount_is_not_claimed_from_the_insurer(insured):
    _, inv = _bill(insured, [("exam", 200, 0), (None, 100, 30)])
    assert _payer_total(insured, inv) == 200.0
    boss = insured["sign_in"]("boss")
    day = local_today().isoformat()
    boss.post("/finance/claims/create", data={"payer_id": insured["ids"]["payer"],
                                              "date_from": day, "date_to": day})
    from app.models import Claim

    with insured["app"].app_context():
        assert Claim.query.one().total_amount == 200.0, "the courtesy discount was claimed"


def test_an_invoice_billed_before_the_figure_existed_reads_as_it_did(insured):
    from app.models import Invoice, InvoiceItem

    with insured["app"].app_context():
        db = insured["db"]
        inv = Invoice(patient_id=insured["ids"]["child"], invoice_number="OLD-1",
                      invoice_date=local_today(), status="unpaid",
                      payer_id=insured["ids"]["payer"])
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, service_id=insured["ids"]["exam"],
                                   description="كشف", quantity=1, unit_price=200,
                                   discount_value=200))
        db.session.commit()
        assert inv.payer_total == 200.0


# --------------------------------------------------- the departments --
def test_no_rules_bills_exactly_as_before(insured):
    paid, _ = _bill(insured, [("exam", 200, 0), ("cbc", 100, 0)])
    assert paid == {"exam": 200.0, "cbc": 0.0}


def test_a_category_rule_covers_every_lab_test_in_a_department(insured):
    stay = _stay(insured, "ward")
    _rule(insured, setting="inpatient", scope="category", category="lab",
          coverage_type="percent", coverage_value=80)
    inpatient, _ = _bill(insured, [("cbc", 100, 0)], admission_id=stay, number="INV-W")
    outpatient, _ = _bill(insured, [("cbc", 100, 0)], number="INV-O")
    assert inpatient == {"cbc": 80.0}
    assert outpatient == {"cbc": 0.0}, "the ward's rule reached the clinic"


def test_everything_else_in_the_nicu(insured):
    stay = _stay(insured, "nicu")
    _rule(insured, setting="nicu", scope="all", coverage_type="percent", coverage_value=90)
    paid, _ = _bill(insured, [("film", 300, 0)], admission_id=stay)
    assert paid == {"film": 270.0}


def test_the_most_specific_rule_decides(insured):
    stay = _stay(insured, "ward")
    # The price list covers the consultation 100% everywhere; the ward's own
    # rule for the consultation says 50%, and wins there.
    _rule(insured, setting="inpatient", scope="service", service_id=insured["ids"]["exam"],
          coverage_type="percent", coverage_value=50)
    _rule(insured, setting="inpatient", scope="all", coverage_type="percent", coverage_value=10)
    ward_bill, _ = _bill(insured, [("exam", 200, 0), ("film", 300, 0)],
                         admission_id=stay, number="INV-W")
    clinic_bill, _ = _bill(insured, [("exam", 200, 0)], number="INV-O")
    assert ward_bill == {"exam": 100.0, "film": 30.0}
    assert clinic_bill == {"exam": 200.0}


def test_not_covered_in_the_emergency_means_the_family_pays(insured):
    from app.models import Patient
    from app.utils import emergency as util

    with insured["app"].app_context():
        db = insured["db"]
        attendance = util.arrive(db.session.get(Patient, insured["ids"]["child"]))
        db.session.flush()
        from app.models import User
        from app.utils import emergency_orders as eo
        visit = eo.encounter(attendance, db.session.get(User, insured["ids"]["doctor"]))
        db.session.commit()
        visit_id = visit.id
    _rule(insured, setting="any", scope="category", category="radiology",
          coverage_type="percent", coverage_value=100)
    _rule(insured, setting="emergency", scope="category", category="radiology", excluded=True)
    er, _ = _bill(insured, [("film", 300, 0)], visit_id=visit_id, number="INV-E")
    clinic, _ = _bill(insured, [("film", 300, 0)], number="INV-O")
    assert er == {"film": 0.0} and clinic == {"film": 300.0}


def test_a_renewed_contract_keeps_its_rules(insured):
    from app.models import PayerContract

    _rule(insured, setting="nicu", scope="all", coverage_type="percent", coverage_value=90)
    with insured["app"].app_context():
        c = insured["db"].session.get(PayerContract, insured["ids"]["contract"])
        clone = c.copy_to(number="C-2")
        assert [(r.setting, r.scope, r.coverage_value) for r in clone.rules] == [("nicu", "all", 90)]


def test_rules_are_set_on_the_contract_screen(insured):
    boss = insured["sign_in"]("boss")
    page = boss.get(f"/finance/contract/{insured['ids']['contract']}/rates").get_data(as_text=True)
    assert "data-contract-rules" in page
    boss.post(f"/finance/contract/{insured['ids']['contract']}/rules",
              data={"setting": "icu", "scope": "category", "category": "lab",
                    "coverage_type": "percent", "coverage_value": "85"})
    boss.post(f"/finance/contract/{insured['ids']['contract']}/rules",
              data={"setting": "icu", "scope": "category", "category": "lab",
                    "coverage_type": "percent", "coverage_value": "95"})
    boss.post(f"/finance/contract/{insured['ids']['contract']}/rules",
              data={"setting": "icu", "scope": "all", "coverage_type": "percent",
                    "coverage_value": "150"})
    from app.models import PayerContractRule

    with insured["app"].app_context():
        rows = PayerContractRule.query.all()
        assert [(r.setting, r.category, r.coverage_value) for r in rows] == [("icu", "lab", 95.0)]
