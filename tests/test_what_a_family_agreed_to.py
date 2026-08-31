"""A dental plan, and the money it commits a family to.

A paediatric visit is one event: the child is seen, a bill is raised, it is
paid. Dentistry is not shaped like that. A plan is agreed on one day — four
fillings, a crown, two extractions — and carried out over weeks, with the
family paying part before anything starts and the rest as the work goes.

**The plan raises one invoice for the agreed total, at acceptance.** Not one
per completed item, and that is a choice worth arguing for. A family agreeing
to a course of treatment agrees to a *figure*; that figure is what they budget
against, what the statement should show, and what a deposit is a deposit
against. Billing item by item would mean nobody could answer "what does this
cost?" until the last visit, and the balance a receptionist reads would climb
every few days without anything new being agreed.

It also means everything the money side already does works here unchanged:
part-payments, the running balance, the printed statement, the aging report.
The audit before this was written found exactly one thing wrong in that
machinery; building a second, parallel way to owe this clinic money would have
been the way to reintroduce it.

**And none of it happens when the module is off** — stated in the money, not
only on the screens, because the promise was made about the money: *"لو مش
متعلّم يتعامل مع العيادة ولا يقبل دفعة مقدمة."*
"""
import pytest


@pytest.fixture
def dental(clinic):
    """A clinic that has said it is a dental clinic."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        clinic["db"].session.commit()
    return clinic


@pytest.fixture
def boss(dental):
    return dental["sign_in"]("boss")


def _plan(clinic, items=(("55", "حشو", 300), ("16", "تلبيسة", 700))):
    """A draft with lines on it, through the screens a doctor uses."""
    boss = clinic["sign_in"]("boss")
    boss.post(f"/dentistry/patient/{clinic['ids']['child']}/plans/new",
              data={"title": "خطة"}, follow_redirects=True)
    from app.models import TreatmentPlan

    with clinic["app"].app_context():
        plan_id = TreatmentPlan.query.order_by(TreatmentPlan.id.desc()).first().id
    for tooth, what, price in items:
        boss.post(f"/dentistry/plan/{plan_id}/item",
                  data={"tooth": tooth, "description": what, "price": str(price)},
                  follow_redirects=True)
    return plan_id


def _state(clinic, plan_id):
    from app.models import TreatmentPlan

    with clinic["app"].app_context():
        plan = clinic["db"].session.get(TreatmentPlan, plan_id)
        return {"status": plan.status, "total": plan.total,
                "items": len(plan.live_items),
                "invoice": plan.invoice_id,
                "balance": plan.invoice.balance if plan.invoice else None,
                "paid": plan.invoice.paid if plan.invoice else None,
                "lines": [i.description for i in plan.invoice.items]
                if plan.invoice else []}


# ------------------------------------------------------- a draft is free ----
def test_a_draft_commits_nobody(dental, boss):
    """It can be written, priced and thrown away with nothing in the books."""
    plan_id = _plan(dental)
    state = _state(dental, plan_id)
    assert state["status"] == "draft"
    assert state["total"] == 1000.0
    assert state["invoice"] is None


def test_a_draft_puts_nothing_on_the_family_account(dental, boss):
    """The number every screen reads. A plan being discussed is not a debt."""
    from app.models import Invoice

    _plan(dental)
    with dental["app"].app_context():
        invoices = Invoice.query.filter_by(
            patient_id=dental["ids"]["child"]).all()
        assert invoices == []


# ------------------------------------------------- accepting is the money ---
def test_accepting_raises_one_invoice_for_the_agreed_total(dental, boss):
    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    state = _state(dental, plan_id)
    assert state["status"] == "accepted"
    assert state["invoice"] is not None
    assert state["balance"] == 1000.0


def test_the_invoice_reads_back_as_the_plan(dental, boss):
    """One lump nobody can check is not a bill. Each line says which tooth,
    so a parent can hold the statement against their child's mouth."""
    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    lines = _state(dental, plan_id)["lines"]
    assert len(lines) == 2
    assert any("55" in line for line in lines)


def test_accepting_twice_does_not_bill_the_child_twice(dental, boss):
    """The button is on a screen with a family in front of it."""
    from app.models import Invoice

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    with dental["app"].app_context():
        assert Invoice.query.filter_by(
            patient_id=dental["ids"]["child"]).count() == 1


def test_an_empty_plan_raises_nothing(dental, boss):
    """A bill for nothing is a bill somebody has to go and cancel."""
    from app.models import Invoice, TreatmentPlan

    boss.post(f"/dentistry/patient/{dental['ids']['child']}/plans/new",
              data={"title": "فاضية"}, follow_redirects=True)
    with dental["app"].app_context():
        plan_id = TreatmentPlan.query.order_by(
            TreatmentPlan.id.desc()).first().id
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    with dental["app"].app_context():
        assert Invoice.query.count() == 0
        assert clinic_status(dental, plan_id) == "draft"


def clinic_status(clinic, plan_id):
    from app.models import TreatmentPlan

    with clinic["app"].app_context():
        return clinic["db"].session.get(TreatmentPlan, plan_id).status


def test_an_accepted_plan_cannot_be_edited(dental, boss):
    """The plan is what the family agreed to. Changing it underneath them is
    changing what they agreed to."""
    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    boss.post(f"/dentistry/plan/{plan_id}/item",
              data={"tooth": "11", "description": "زيادة", "price": "500"},
              follow_redirects=True)
    state = _state(dental, plan_id)
    assert state["items"] == 2
    assert state["balance"] == 1000.0


# ------------------------------------------------------------- the money ----
def test_a_deposit_is_a_payment_on_that_invoice(dental, boss):
    """Not a new kind of money. The program already knows how to hold a
    part-paid bill, print it and age it."""
    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    boss.post(f"/dentistry/plan/{plan_id}/deposit",
              data={"amount": "400", "method": "cash"}, follow_redirects=True)
    state = _state(dental, plan_id)
    assert state["paid"] == 400.0
    assert state["balance"] == 600.0


def test_the_family_account_shows_it(dental, boss):
    """The running balance a receptionist reads when the child walks in —
    which is the whole reason the plan bills as one figure."""
    from app.models import Invoice

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    boss.post(f"/dentistry/plan/{plan_id}/deposit",
              data={"amount": "400"}, follow_redirects=True)
    with dental["app"].app_context():
        owed = sum(i.balance for i in Invoice.query.filter_by(
            patient_id=dental["ids"]["child"]).all())
    assert round(owed, 2) == 600.0


def test_more_than_the_bill_is_refused(dental, boss):
    """Money taken beyond what is owed is a credit this program has nowhere
    to keep, so it is refused at the door rather than stored somewhere it
    would later be wrong."""
    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    boss.post(f"/dentistry/plan/{plan_id}/deposit",
              data={"amount": "5000"}, follow_redirects=True)
    assert _state(dental, plan_id)["paid"] == 0.0


def test_a_deposit_before_acceptance_is_refused(dental, boss):
    """There is no bill yet. A payment with nothing to pay against is money
    the program cannot explain later."""
    from app.models import Payment

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/deposit",
              data={"amount": "400"}, follow_redirects=True)
    with dental["app"].app_context():
        assert Payment.query.count() == 0


def test_carrying_out_an_item_does_not_bill_again(dental, boss):
    """The plan already billed. Charging on completion too is how a family
    pays twice for one crown."""
    from app.models import TreatmentPlan

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    with dental["app"].app_context():
        item_id = clinic_first_item(dental, plan_id)
    boss.post(f"/dentistry/plan/item/{item_id}/done", follow_redirects=True)
    assert _state(dental, plan_id)["balance"] == 1000.0


def clinic_first_item(clinic, plan_id):
    from app.models import TreatmentPlan

    plan = clinic["db"].session.get(TreatmentPlan, plan_id)
    return plan.live_items[0].id


def test_a_plan_whose_work_is_finished_says_so(dental, boss):
    """So the list of open plans is the list of work outstanding, rather than
    a list somebody has to remember to tidy."""
    from app.models import TreatmentPlan

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    with dental["app"].app_context():
        plan = dental["db"].session.get(TreatmentPlan, plan_id)
        ids = [i.id for i in plan.live_items]
    for item_id in ids:
        boss.post(f"/dentistry/plan/item/{item_id}/done", follow_redirects=True)
    assert _state(dental, plan_id)["status"] == "done"


# ------------------------------------------ the clinic's asking figure ------
def test_the_minimum_is_shown_and_not_enforced(dental, boss):
    """A parent who can pay half today and the rest on Sunday is a normal
    afternoon. A program that refuses their money is one the desk works
    around — so the figure is advice, and a smaller payment goes through."""
    from app.models import Setting

    with dental["app"].app_context():
        Setting.set("dental_deposit_percent", "50")
        dental["db"].session.commit()

    plan_id = _plan(dental)
    boss.post(f"/dentistry/plan/{plan_id}/accept", follow_redirects=True)
    page = boss.get(f"/dentistry/plan/{plan_id}").get_data(as_text=True)
    assert "500" in page

    boss.post(f"/dentistry/plan/{plan_id}/deposit",
              data={"amount": "100"}, follow_redirects=True)
    assert _state(dental, plan_id)["paid"] == 100.0


def test_no_minimum_by_default(dental):
    """Inventing one would be making a commercial policy for the clinic."""
    from app.utils.dental_money import minimum_deposit

    with dental["app"].app_context():
        assert minimum_deposit(1000) == 0.0


# ------------------------------------------------- and none of it when off --
def test_none_of_this_exists_when_the_module_is_off(clinic):
    """The screens. Every address, not only the ones somebody would browse."""
    boss = clinic["sign_in"]("boss")
    assert boss.get(
        f"/dentistry/patient/{clinic['ids']['child']}/plans").status_code == 404
    assert boss.post(
        f"/dentistry/patient/{clinic['ids']['child']}/plans/new",
        data={"title": "x"}).status_code == 404


def test_the_money_refuses_even_when_called_directly(clinic):
    """Stated in the money rather than only on the screens.

    The gate on the routes is the way in; this is the rule itself, so a
    future caller that is not a screen — an import, a scheduled job, an API —
    cannot walk past it.
    """
    from app.models import TreatmentPlan
    from app.utils import dental_money

    with clinic["app"].app_context():
        plan = TreatmentPlan(patient_id=clinic["ids"]["child"])
        clinic["db"].session.add(plan)
        clinic["db"].session.commit()

        with pytest.raises(dental_money.DentalMoneyError):
            dental_money.accept(plan)
        with pytest.raises(dental_money.DentalMoneyError):
            dental_money.take_deposit(plan, 100)
