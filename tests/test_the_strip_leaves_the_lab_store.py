"""What a test uses leaves the lab's store when it is run.

Asked as *«غالباً بيبقى بيخصم برده مستهلكات وليه مخزن شرايط التحاليل»* and
*«علشان التحليل يتسعّر سعر وتكلفة وكل حاجه»*. What is held here:

* with no lab store chosen, a result takes **nothing** — a running clinic
  sees exactly what it saw before;
* with one, the result takes each consumable once, from that store, under
  the lab's cost centre;
* a result cleared and typed again is the same run and takes nothing more;
* a test with no consumables takes nothing;
* the cost of a run is typed and kept, and the screen warns when the price
  service would take its own consumables at billing as well.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def lab(clinic):
    from app.models import Investigation, Setting, StoreItem, VisitInvestigation, Warehouse

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        store = Warehouse(name="مخزن المعمل", kind="sub", is_active=True)
        strip = StoreItem(name="شريط سكر", unit="شريط", purchase_price=4, is_active=True)
        lancet = StoreItem(name="لانسيت", unit="قطعة", purchase_price=1, is_active=True)
        sugar = Investigation(name_ar="سكر عشوائي", kind="lab", is_active=True)
        db.session.add_all([store, strip, lancet, sugar])
        db.session.flush()
        order = VisitInvestigation(visit_id=clinic["ids"]["visit"],
                                   patient_id=clinic["ids"]["child"],
                                   investigation_id=sugar.id, kind="lab",
                                   name="سكر عشوائي", status="requested")
        db.session.add(order)
        db.session.commit()
        clinic["ids"].update(store=store.id, strip=strip.id, lancet=lancet.id,
                             sugar=sugar.id, order=order.id)
    return clinic


def _out(lab):
    from app.models import StockMovement

    with lab["app"].app_context():
        return sorted((m.item_id, m.qty, m.warehouse_id)
                      for m in StockMovement.query.filter_by(kind="out").all())


def _list(lab, boss):
    boss.post(f"/labs/tests/{lab['ids']['sugar']}/money",
              data={"cost": "6.5", "item_id": [str(lab["ids"]["strip"]), str(lab["ids"]["lancet"]), ""],
                    "qty": ["1", "2", "1"]})


def _result(lab, boss, value="95"):
    boss.post(f"/labs/order/{lab['ids']['order']}/result",
              data={"result_value": value, "result_unit": "mg/dL"})


def test_no_store_chosen_takes_nothing(lab):
    boss = lab["sign_in"]("boss")
    _list(lab, boss)
    _result(lab, boss)
    assert _out(lab) == []


def test_the_run_takes_each_consumable_once_from_the_lab_store(lab):
    from app.models import Investigation, StockMovement, VisitInvestigation
    from app.utils import cost_centres

    boss = lab["sign_in"]("boss")
    boss.post("/labs/store", data={"warehouse_id": str(lab["ids"]["store"])})
    _list(lab, boss)
    with lab["app"].app_context():
        row = lab["db"].session.get(Investigation, lab["ids"]["sugar"])
        assert row.cost == 6.5 and len(row.lab_consumables) == 2
    _result(lab, boss)
    assert _out(lab) == sorted([(lab["ids"]["strip"], -1, lab["ids"]["store"]),
                                (lab["ids"]["lancet"], -2, lab["ids"]["store"])])
    with lab["app"].app_context():
        assert lab["db"].session.get(VisitInvestigation, lab["ids"]["order"]).consumed_at
        centre = cost_centres.centre_id("lab")
        assert {m.cost_centre_id for m in StockMovement.query.all()} == {centre}

    # Cleared and typed again: the same run.
    _result(lab, boss, value="")
    _result(lab, boss, value="101")
    assert len(_out(lab)) == 2


def test_a_test_with_no_consumables_takes_nothing(lab):
    boss = lab["sign_in"]("boss")
    boss.post("/labs/store", data={"warehouse_id": str(lab["ids"]["store"])})
    _result(lab, boss)
    assert _out(lab) == []


def test_the_screen_warns_when_the_price_service_would_take_them_too(lab):
    from app.models import Investigation, ServiceConsumable

    with lab["app"].app_context():
        db = lab["db"]
        test = db.session.get(Investigation, lab["ids"]["sugar"])
        test.service_id = lab["ids"]["exam"]
        db.session.add(ServiceConsumable(service_id=lab["ids"]["exam"],
                                         store_item_id=lab["ids"]["strip"], quantity=1))
        db.session.commit()
    boss = lab["sign_in"]("boss")
    page = boss.get(f"/labs/tests/{lab['ids']['sugar']}/ranges").get_data(as_text=True)
    assert "data-double-taken" not in page, "warned with nothing listed on the test"
    _list(lab, boss)
    page = boss.get(f"/labs/tests/{lab['ids']['sugar']}/ranges").get_data(as_text=True)
    assert "data-double-taken" in page and "data-money" in page


def test_only_the_admin_sets_the_store_and_the_figures(lab):
    from app.models import Investigation
    from app.utils import lab_stock

    desk = lab["sign_in"]("desk")
    desk.post("/labs/store", data={"warehouse_id": str(lab["ids"]["store"])})
    _list(lab, desk)
    with lab["app"].app_context():
        assert lab_stock.store() is None
        assert lab["db"].session.get(Investigation, lab["ids"]["sugar"]).cost is None
