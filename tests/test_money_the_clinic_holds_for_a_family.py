"""Money the clinic holds for a family: the patient's own account.

Asked as *«حساب دفعات مقدّمة منفصل، كمّل عليه»* and *«ويبقى في حساب دائن
للمرضى لان ده المفروض موجود فى الاسنان»*. It was not there: the dental
deposit's own code said *"money taken beyond what is owed is a credit this
program has nowhere to keep"*. What is held here:

* money taken on account is in the drawer and the till, and in the ledger as
  a liability (2030) — the clinic owes it to the family;
* a bill paid from the account is an ordinary payment of method «credit»:
  the bill reads paid, the ledger moves 2030 to the patients' account, and
  the drawer does not count the money a second time;
* never more than the account holds, nor more than the bill owes — refused,
  and nothing written;
* handing a balance back takes it out of the drawer, and is a manager's
  where refunds need approval;
* a hospital's stay shows the deposit against what the stay has come to, and
  says when it no longer covers it;
* a clinic with no wards and no dentistry sees the screens it had — unless it
  turns the account on, or a family already holds a balance.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """A clinic with the account on, the chart seeded and a shift open."""
    from app.models import CashierShift, Setting
    from app.utils import accounting

    with clinic["app"].app_context():
        db = clinic["db"]
        accounting.ensure_seeded()
        Setting.set("patient_credit_mode", "on")
        shift = CashierShift(status="open", opening_float=100,
                             opened_by=clinic["ids"]["admin"])
        db.session.add(shift)
        db.session.commit()
        clinic["ids"]["shift"] = shift.id
    return clinic


def _bill(c, amount=300, admission_id=None, number="INV-1"):
    from app.models import Invoice, InvoiceItem

    with c["app"].app_context():
        db = c["db"]
        inv = Invoice(patient_id=c["ids"]["child"], invoice_number=number,
                      invoice_date=local_today(), status="unpaid",
                      admission_id=admission_id)
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="إقامة",
                                   quantity=1, unit_price=amount))
        db.session.commit()
        return inv.id


def _held(c):
    from app.utils import patient_credit

    with c["app"].app_context():
        return patient_credit.balance(c["ids"]["child"])


def _expected(c):
    from app.models import CashierShift

    with c["app"].app_context():
        return c["db"].session.get(CashierShift, c["ids"]["shift"]).expected_cash


def _ledger(c, source_type):
    """[(code, debit, credit)] of the entries posted for ``source_type``."""
    from app.models import JournalEntry

    with c["app"].app_context():
        out = []
        for entry in JournalEntry.query.filter_by(source_type=source_type).all():
            out += [(ln.account.code, ln.debit, ln.credit) for ln in entry.lines]
        return sorted(out)


def _take(client, c, amount="500", method="cash", **extra):
    return client.post(f"/finance/patient/{c['ids']['child']}/account/take",
                       data=dict(amount=amount, method=method, **extra))


# ------------------------------------------------------------ money in --
def test_money_taken_on_account_is_in_the_drawer_and_owed_to_the_family(desk):
    boss = desk["sign_in"]("boss")
    _take(boss, desk, "500")
    assert _held(desk) == 500.0
    assert _expected(desk) == 600.0, "the deposit is in the drawer"
    assert _ledger(desk, "patient_credit") == [("1010", 500.0, 0.0), ("2030", 0.0, 500.0)]
    page = boss.get(f"/finance/patient/{desk['ids']['child']}/account").get_data(as_text=True)
    assert 'data-credit-line="in"' in page


def test_a_card_deposit_is_not_counted_as_cash(desk):
    _take(desk["sign_in"]("boss"), desk, "500", method="card")
    assert _held(desk) == 500.0 and _expected(desk) == 100.0


# ------------------------------------------------------- used on a bill --
def test_a_bill_paid_from_the_account(desk):
    from app.models import Invoice

    boss = desk["sign_in"]("boss")
    _take(boss, desk, "500")
    inv = _bill(desk, 300)
    page = boss.get(f"/finance/invoices/{inv}").get_data(as_text=True)
    assert "data-from-credit" in page
    boss.post(f"/finance/invoices/{inv}/from-credit", data={"next": "invoice"})
    with desk["app"].app_context():
        row = desk["db"].session.get(Invoice, inv)
        assert row.status == "paid" and row.paid == 300.0
        assert [(p.method, p.shift_id) for p in row.payments] == [("credit", None)]
    assert _held(desk) == 200.0
    assert _expected(desk) == 600.0, "the drawer counted that money twice"
    assert _ledger(desk, "payment") == [("1030", 0.0, 300.0), ("2030", 300.0, 0.0)]


@pytest.mark.parametrize("amount,why", [("600", "over_held"), ("400", "over_owed")])
def test_never_more_than_held_nor_more_than_owed(desk, amount, why):
    from app.models import Invoice, PatientCredit

    boss = desk["sign_in"]("boss")
    _take(boss, desk, "500")
    inv = _bill(desk, 300 if why == "over_owed" else 1000)
    boss.post(f"/finance/invoices/{inv}/from-credit", data={"amount": amount})
    with desk["app"].app_context():
        assert desk["db"].session.get(Invoice, inv).paid == 0.0
        assert PatientCredit.query.filter_by(kind="applied").count() == 0
    assert _held(desk) == 500.0


# ------------------------------------------------------------ handed back --
def test_handing_back_leaves_the_drawer(desk):
    boss = desk["sign_in"]("boss")
    _take(boss, desk, "500")
    boss.post(f"/finance/patient/{desk['ids']['child']}/account/give-back",
              data={"amount": "500", "method": "cash"})
    assert _held(desk) == 0.0 and _expected(desk) == 100.0
    assert ("2030", 500.0, 0.0) in _ledger(desk, "patient_credit")
    boss.post(f"/finance/patient/{desk['ids']['child']}/account/give-back",
              data={"amount": "1", "method": "cash"})
    assert _held(desk) == 0.0, "handed back more than was held"


def test_handing_back_is_a_managers_where_refunds_need_approval(desk):
    _take(desk["sign_in"]("boss"), desk, "500")
    desk["sign_in"]("desk").post(
        f"/finance/patient/{desk['ids']['child']}/account/give-back",
        data={"amount": "500", "method": "cash"})
    assert _held(desk) == 500.0


def test_the_till_statement_shows_the_deposit(desk):
    from app.models import CashAccount, PatientCredit
    from app.utils import treasury

    with desk["app"].app_context():
        treasury.seed_accounts()
        desk["db"].session.commit()
    _take(desk["sign_in"]("boss"), desk, "250")
    with desk["app"].app_context():
        row = PatientCredit.query.one()
        assert row.account_id is not None
        rows = treasury.movements(desk["db"].session.get(CashAccount, row.account_id))
        assert ("credit_in", 250.0) in [(r["kind"], r["amount"]) for r in rows]


# ------------------------------------------------------------- the stay --
def _stay(c):
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward

    with c["app"].app_context():
        db = c["db"]
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
        stay = ward.admit(db.session.get(Patient, c["ids"]["child"]), bed)
        db.session.commit()
        return stay.id


def test_a_stay_shows_its_deposit_and_asks_for_more_when_it_runs_short(desk):
    from app.models import PatientCredit

    stay = _stay(desk)
    boss = desk["sign_in"]("boss")
    answer = _take(boss, desk, "1000", admission_id=str(stay), next=f"admission:{stay}")
    assert answer.headers["Location"].endswith(f"/beds/admission/{stay}")
    with desk["app"].app_context():
        assert PatientCredit.query.one().admission_id == stay
    _bill(desk, 1500, admission_id=stay)
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-stay-deposit" in page and "data-deposit-short" in page
    assert "data-deposit-apply" in page


def test_a_nurse_does_not_see_the_money_on_the_stay(desk):
    stay = _stay(desk)
    page = desk["sign_in"]("doc").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-stay-deposit" not in page


# ---------------------------------------- a clinic that has none of this --
def test_a_plain_clinic_sees_the_screens_it_had(clinic):
    from app.models import Setting
    from app.utils import patient_credit

    boss = clinic["sign_in"]("boss")
    with clinic["app"].app_context():
        assert patient_credit.enabled() is False
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-profile-credit" not in page
    inv = _bill(clinic, 200)
    assert "data-credit-link" not in boss.get(f"/finance/invoices/{inv}").get_data(as_text=True)

    with clinic["app"].app_context():
        Setting.set("patient_credit_mode", "on")
        clinic["db"].session.commit()
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-profile-credit" in page


def test_a_balance_is_never_hidden_by_the_switch(desk):
    from app.models import Setting

    boss = desk["sign_in"]("boss")
    _take(boss, desk, "50")
    with desk["app"].app_context():
        Setting.set("patient_credit_mode", "off")
        desk["db"].session.commit()
    page = boss.get(f"/patients/{desk['ids']['child']}").get_data(as_text=True)
    assert "data-profile-credit" in page
    account = boss.get(f"/finance/patient/{desk['ids']['child']}/account").get_data(as_text=True)
    assert "data-credit-off" in account


def test_on_by_itself_for_a_hospital_and_a_dental_clinic(clinic):
    from app.models import Setting
    from app.utils import patient_credit

    for module in ("beds", "dentistry"):
        with clinic["app"].app_context():
            Setting.set("mod_enabled:beds", "0")
            Setting.set("mod_enabled:dentistry", "0")
            Setting.set(f"mod_enabled:{module}", "1")
            clinic["db"].session.commit()
            assert patient_credit.enabled() is True, module


# --------------------------------------------------------------- dental --
def test_the_dental_plan_offers_the_account_and_pays_from_it(desk):
    from app.models import Setting, TreatmentPlan
    from app.utils import dental_money

    with desk["app"].app_context():
        db = desk["db"]
        Setting.set("mod_enabled:dentistry", "1")
        plan = TreatmentPlan(patient_id=desk["ids"]["child"])
        db.session.add(plan)
        db.session.flush()
        from app.models import TreatmentPlanItem
        db.session.add(TreatmentPlanItem(plan_id=plan.id, description="حشو",
                                         price=400))
        db.session.flush()
        dental_money.accept(plan)
        db.session.commit()
        plan_id, invoice_id = plan.id, plan.invoice_id
    boss = desk["sign_in"]("boss")
    # A parent hands over more than the plan's bill: told where the rest goes.
    answer = boss.post(f"/dentistry/plan/{plan_id}/deposit",
                       data={"amount": "1000", "method": "cash"}, follow_redirects=True)
    assert "حساب المريض الدائن" in answer.get_data(as_text=True)
    _take(boss, desk, "1000")
    page = boss.get(f"/dentistry/plan/{plan_id}").get_data(as_text=True)
    assert "data-dental-credit" in page and "data-dental-from-credit" in page
    boss.post(f"/finance/invoices/{invoice_id}/from-credit")
    from app.models import Invoice

    with desk["app"].app_context():
        assert desk["db"].session.get(Invoice, invoice_id).balance == 0
    assert _held(desk) == 600.0
