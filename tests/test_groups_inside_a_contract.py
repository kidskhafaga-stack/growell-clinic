"""Groups inside a contract — «نقدي 10%» and «تعاقد 25%» on the services the
clinic chooses (CONTRACTS_PLAN.md ع-٦).

Asked as *«محتاجين مجموعة جوه التعاقد علشان فى تعاقد نقدي 10% تعاقد 25% مثلاُ
على بعض الخدمات وانا محتاج اجمعه تحت مجموعات داخل التعاقد ومحتاجها تبقى
مرنة»*, and decided: a group is the contract's own (copied on renewal, or from
another contract by hand), and pays the payer's share, the family's discount on
its own share, or both.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def contract(clinic):
    """A company on contract, the child its member, and a third service, an
    ECG, in another category. No rules yet."""
    from app.models import (PatientCoverage, PayerContract, PayerEntity,
                            Service)

    db = clinic["db"]
    with clinic["app"].app_context():
        payer = PayerEntity(name="شركة البترول", entity_type="company", is_active=True)
        db.session.add(payer)
        db.session.flush()
        c = PayerContract(payer_id=payer.id, number="K-1",
                          start_date=local_today() - timedelta(days=100),
                          end_date=local_today() + timedelta(days=200), is_active=True)
        db.session.add(c)
        ecg = Service(name="رسم قلب", category="radiology", price=300, is_active=True,
                      commission_type="percent", commission_value=50)
        db.session.add(ecg)
        db.session.add(PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                                       membership_number="M-9", is_active=True,
                                       expiry_date=local_today() + timedelta(days=300)))
        db.session.commit()
        clinic["ids"].update({"payer": payer.id, "contract": c.id, "ecg": ecg.id})
    return clinic


def _group(fx, name, services, payer_pct=0, family_pct=0, setting="any"):
    from app.models import PayerContract, PayerContractGroup, PayerContractRule, Service

    db = fx["db"]
    with fx["app"].app_context():
        c = db.session.get(PayerContract, fx["ids"]["contract"])
        g = PayerContractGroup(name=name, services=[db.session.get(Service, fx["ids"][s])
                                                    for s in services])
        c.groups.append(g)
        db.session.flush()
        c.rules.append(PayerContractRule(setting=setting, scope="group", group_id=g.id,
                                         coverage_type="percent", coverage_value=payer_pct,
                                         family_discount=family_pct or None))
        db.session.commit()
        return g.id


def _rule(fx, scope, value, **kw):
    from app.models import PayerContract, PayerContractRule

    db = fx["db"]
    with fx["app"].app_context():
        c = db.session.get(PayerContract, fx["ids"]["contract"])
        c.rules.append(PayerContractRule(setting="any", scope=scope, coverage_type="percent",
                                         coverage_value=value, **kw))
        db.session.commit()


def _bill(fx, *services, discount=None, twice=False):
    """A bill for the child with one line per service; the figures of each line
    as ``{service: (net, payer_amount, group_discount, group_id, commission)}``."""
    from app.models import Invoice, InvoiceItem, Patient, Service
    from app.utils import billing

    db = fx["db"]
    with fx["app"].app_context():
        n = Invoice.query.count() + 1
        invoice = Invoice(patient_id=fx["ids"]["child"], doctor_id=fx["ids"]["doctor"],
                          invoice_number=f"INV-G{n}", invoice_date=local_today(),
                          status="unpaid")
        db.session.add(invoice)
        db.session.flush()
        for key in services:
            svc = db.session.get(Service, fx["ids"][key])
            db.session.add(InvoiceItem(invoice_id=invoice.id, service_id=svc.id,
                                       description=svc.name, quantity=1,
                                       unit_price=svc.price,
                                       discount_value=(discount or {}).get(key, 0)))
        db.session.flush()
        patient = db.session.get(Patient, fx["ids"]["child"])
        for _ in range(2 if twice else 1):
            billing.apply_coverage(invoice, patient)
        invoice.recalc_status()
        db.session.commit()
        out = {}
        for item in invoice.items:
            key = next(k for k in services if fx["ids"][k] == item.service_id)
            out[key] = (item.net, item.payer_amount, item.group_discount,
                        item.contract_group_id, item.commission_amount)
        return out


# ---------------------------------------------------------- the billing ---
def test_a_contract_with_no_groups_bills_as_it_did(contract):
    _rule(contract, "category", 50, category="consultation")
    line = _bill(contract, "exam")["exam"]
    assert line[:4] == (100, 100, None, None)


def test_contract_25_the_payer_covers_its_share(contract):
    gid = _group(contract, "تعاقد ٢٥", ["exam", "ecg"], payer_pct=25)
    lines = _bill(contract, "exam", "ecg", "nebul")
    assert lines["exam"][:4] == (150, 50, None, gid)
    assert lines["ecg"][:4] == (225, 75, None, gid)
    assert lines["nebul"][1] == 0 and lines["nebul"][3] is None   # not in the group
    # The doctor's share is on the price: cover is not a cheaper consultation.
    assert lines["exam"][4] == 80


def test_cash_10_the_family_pays_less_and_the_payer_nothing(contract):
    gid = _group(contract, "نقدي ١٠", ["exam"], family_pct=10)
    line = _bill(contract, "exam")["exam"]
    assert line[:4] == (180, 0, 20, gid)
    # A discount in every sense: the share comes off the discounted price.
    assert line[4] == 72


def test_both_the_payer_covers_and_the_family_gets_its_discount(contract):
    _group(contract, "الاتنين", ["exam"], payer_pct=25, family_pct=10)
    net, payer, family, _gid, commission = _bill(contract, "exam")["exam"]
    assert payer == 50                   # the claim reads this alone
    assert family == 15                  # 10% of the family's 150
    assert net == 135
    assert commission == round((200 - 15) * 0.4, 2)


def test_a_service_rule_beats_its_group_and_a_group_beats_the_category(contract):
    _rule(contract, "category", 80, category="consultation")
    _group(contract, "مجموعة", ["exam", "nebul"], payer_pct=25)
    _rule(contract, "service", 100, service_id=contract["ids"]["nebul"])
    lines = _bill(contract, "exam", "nebul")
    assert lines["exam"][1] == 50        # the group, not the category's 80%
    assert lines["nebul"][1] == 150      # its own rule, not the group's


def test_billed_again_the_figures_stay_and_a_typed_discount_is_kept(contract):
    _group(contract, "الاتنين", ["exam", "nebul"], payer_pct=25, family_pct=10)
    again = _bill(contract, "exam", twice=True)["exam"]
    assert again[:3] == (135, 50, 15)
    # A cashier's own discount on a line is the cashier's, and stays.
    typed = _bill(contract, "nebul", discount={"nebul": 30})["nebul"]
    assert typed[0] == 120 and typed[2] is None


def test_the_family_discount_survives_the_contracts_copay(contract):
    from app.models import PayerContract, PayerContractTerm

    _group(contract, "الاتنين", ["exam"], payer_pct=50, family_pct=10)
    with contract["app"].app_context():
        c = contract["db"].session.get(PayerContract, contract["ids"]["contract"])
        c.terms.append(PayerContractTerm(setting="any", copay_amount=20))
        contract["db"].session.commit()
    net, payer, family, _gid, _c = _bill(contract, "exam")["exam"]
    assert family == 10                  # 10% of the family's 100, before the copay
    assert payer == 80                   # 100 less the copay of 20
    assert net == 110


# ------------------------------------------------------------ the screen --
def test_the_screen_makes_a_group_and_refuses_a_service_in_two(contract):
    from app.models import PayerContract

    boss = contract["sign_in"]()
    cid = contract["ids"]["contract"]
    page = boss.get(f"/finance/contract/{cid}/rates").get_data(as_text=True)
    assert "data-contract-groups" in page and "data-no-groups" in page
    got = boss.post(f"/finance/contract/{cid}/groups", data={
        "name": "نقدي ١٠", "service_ids": [contract["ids"]["exam"]],
        "coverage_type": "percent", "coverage_value": "0", "family_discount": "10"})
    assert got.status_code == 302
    # A whole category at once.
    boss.post(f"/finance/contract/{cid}/groups", data={
        "name": "الأشعة", "category": "radiology",
        "coverage_type": "percent", "coverage_value": "25", "family_discount": "0"})
    # The exam is in a group already: refused, and said where.
    clash = boss.post(f"/finance/contract/{cid}/groups", data={
        "name": "تاني", "service_ids": [contract["ids"]["exam"]],
        "coverage_type": "percent", "coverage_value": "30"}, follow_redirects=True)
    assert "نقدي ١٠" in clash.get_data(as_text=True)
    # Nothing at all for either side is not a group.
    boss.post(f"/finance/contract/{cid}/groups", data={
        "name": "فاضية", "service_ids": [contract["ids"]["nebul"]],
        "coverage_value": "0", "family_discount": "0"})
    with contract["app"].app_context():
        c = contract["db"].session.get(PayerContract, cid)
        assert sorted(g.name for g in c.groups) == ["الأشعة", "نقدي ١٠"]
        rays = next(g for g in c.groups if g.name == "الأشعة")
        assert [s.id for s in rays.services] == [contract["ids"]["ecg"]]
        cash = next(r for r in c.rules if r.group and r.group.name == "نقدي ١٠")
        assert (cash.coverage_value, cash.family_discount) == (0, 10)
    page = boss.get(f"/finance/contract/{cid}/rates").get_data(as_text=True)
    assert page.count("data-group=") == 2 and 'value="group"' in page


def test_services_in_and_out_and_a_group_deleted_with_its_rules(contract):
    from app.models import PayerContract, PayerContractRule

    gid = _group(contract, "مجموعة", ["exam"], payer_pct=25)
    boss = contract["sign_in"]()
    boss.post(f"/finance/contract/group/{gid}/services",
              data={"service_ids": [contract["ids"]["nebul"]]})
    boss.post(f"/finance/contract/group/{gid}/services",
              data={"remove_id": contract["ids"]["exam"]})
    with contract["app"].app_context():
        c = contract["db"].session.get(PayerContract, contract["ids"]["contract"])
        assert [s.id for s in c.groups[0].services] == [contract["ids"]["nebul"]]
    boss.post(f"/finance/contract/group/{gid}/delete")
    with contract["app"].app_context():
        c = contract["db"].session.get(PayerContract, contract["ids"]["contract"])
        assert c.groups == []
        assert PayerContractRule.query.filter_by(group_id=gid).count() == 0


def test_a_bill_line_names_its_group(contract):
    from app.models import Invoice

    _group(contract, "نقدي ١٠", ["exam"], family_pct=10)
    _bill(contract, "exam")
    with contract["app"].app_context():
        invoice_id = Invoice.query.first().id
    page = contract["sign_in"]().get(f"/finance/invoices/{invoice_id}").get_data(as_text=True)
    assert "data-line-group" in page and "نقدي ١٠" in page


# --------------------------------------------- renewal, and copying by hand --
def test_a_renewal_carries_the_groups_and_their_rules(contract):
    from app.models import PayerContract

    _group(contract, "الاتنين", ["exam", "ecg"], payer_pct=25, family_pct=10)
    with contract["app"].app_context():
        db = contract["db"]
        old = db.session.get(PayerContract, contract["ids"]["contract"])
        new = old.copy_to(number="K-2")
        db.session.add(new)
        db.session.commit()
        assert [g.name for g in new.groups] == ["الاتنين"]
        assert new.groups[0].id != old.groups[0].id
        assert sorted(s.id for s in new.groups[0].services) == sorted(
            [contract["ids"]["exam"], contract["ids"]["ecg"]])
        rule = new.rules[0]
        assert rule.group_id == new.groups[0].id
        assert (rule.coverage_value, rule.family_discount) == (25, 10)


def test_groups_copied_from_another_contract_skip_what_is_here(contract):
    from app.models import PayerContract, PayerEntity

    _group(contract, "الاتنين", ["exam"], payer_pct=25, family_pct=10)
    _group(contract, "الأشعة", ["ecg"], payer_pct=50)
    with contract["app"].app_context():
        db = contract["db"]
        other_payer = PayerEntity(name="نادي", entity_type="club", is_active=True)
        db.session.add(other_payer)
        db.session.flush()
        target = PayerContract(payer_id=other_payer.id, number="N-1", is_active=True)
        db.session.add(target)
        db.session.commit()
        target_id = target.id
    _target = {"ids": dict(contract["ids"], contract=target_id), **{k: contract[k] for k in ("app", "db")}}
    _group(_target, "الأشعة", ["ecg"], payer_pct=10)        # same name already here
    boss = contract["sign_in"]()
    got = boss.post(f"/finance/contract/{target_id}/groups/copy",
                    data={"from_id": contract["ids"]["contract"]}, follow_redirects=True)
    assert "الأشعة" in got.get_data(as_text=True)          # said, not guessed
    with contract["app"].app_context():
        t = contract["db"].session.get(PayerContract, target_id)
        assert sorted(g.name for g in t.groups) == ["الأشعة", "الاتنين"]
        both = next(g for g in t.groups if g.name == "الاتنين")
        rule = next(r for r in t.rules if r.group_id == both.id)
        assert (rule.coverage_value, rule.family_discount) == (25, 10)
        kept = next(r for r in t.rules if r.group and r.group.name == "الأشعة")
        assert kept.coverage_value == 10                     # this contract's own


def test_covered_again_after_the_group_changes_the_line_follows_it(contract):
    """A stay's bill is covered again every night: the line's discount is
    known to be the contract's (cover and family discount together), so a
    changed figure reaches it — it is not mistaken for a cashier's."""
    from app.models import Invoice, Patient, PayerContractRule
    from app.utils import billing

    gid = _group(contract, "الاتنين", ["exam"], payer_pct=25, family_pct=10)
    _bill(contract, "exam")
    with contract["app"].app_context():
        db = contract["db"]
        rule = PayerContractRule.query.filter_by(group_id=gid).one()
        rule.coverage_value = 50
        invoice = Invoice.query.one()
        billing.apply_coverage(invoice, db.session.get(Patient, contract["ids"]["child"]))
        item = invoice.items[0]
        assert (item.payer_amount, item.group_discount, item.net) == (100, 10, 90)
