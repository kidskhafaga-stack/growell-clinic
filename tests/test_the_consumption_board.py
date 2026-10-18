"""لوحة الاستهلاك — استهلكنا أد إيه وبكام، في أي فترة، جنب الفترة اللي قبلها.

* **الاستهلاك** هو الصرف للاستخدام بس (مش التحويل بين المخازن)، والهالك
  لوحده، والقيمة هي تكلفة الحركة نفسها — والحركة اللي من غير تكلفة متقالة؛
* **حسب القسم** وحسب نوع الصنف، و**الأدوية** هي أصناف «دواء» بس؛
* **المعمل**: كل تحليل اتعمل في الفترة، اللي اتخصم عليه قدام سعره؛
* **الذكاء الاصطناعي** بالمكالمات والتوكنز، من غير فلوس من عند البرنامج؛
* كل جزء ورا الموديول بتاعه.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def shop(clinic):
    from app.models import (AiUsage, CostCentre, Investigation, Setting, StockMovement,
                            StoreDocument, StoreItem, VisitInvestigation)

    db = clinic["db"]
    now = datetime.utcnow()
    with clinic["app"].app_context():
        for m in ("inventory", "labs"):
            Setting.set(f"mod_enabled:{m}", "1")
        ward = CostCentre(key="ward_x", name_ar="الداخلي", name_en="Ward")
        lab_c = CostCentre(key="lab_x", name_ar="المعمل", name_en="Lab")
        amox = StoreItem(name="أموكسيسيلين", item_type="drug", unit="زجاجة", is_active=True)
        gauze = StoreItem(name="شاش", item_type="consumable", is_active=True)
        strip = StoreItem(name="شريط سكر", item_type="consumable", is_active=True)
        db.session.add_all([ward, lab_c, amox, gauze, strip])
        db.session.flush()

        def doc(kind, ref=None):
            d = StoreDocument(doc_number=f"D{kind}{StoreDocument.query.count() + 1}", kind=kind,
                              reference=ref)
            db.session.add(d)
            db.session.flush()
            return d

        issue = doc("issue")
        transfer = doc("transfer")
        moves = [
            (amox, -4, 25.0, ward, 2, issue, "out"),     # 100 now
            (gauze, -10, 2.0, ward, 3, issue, "out"),    # 20 now
            (gauze, -3, None, None, 4, None, "out"),     # unpriced, shared
            (gauze, -2, 2.0, None, 5, None, "waste"),    # waste 4
            (gauze, -50, 2.0, None, 5, transfer, "out"),  # a transfer: not use
            (amox, -2, 25.0, ward, 40, issue, "out"),    # 50 before (30-day preset)
        ]
        for item, qty, cost, centre, days, d, kind in moves:
            db.session.add(StockMovement(item_id=item.id, kind=kind, qty=qty, unit_cost=cost,
                                         cost_centre_id=centre.id if centre else None,
                                         document_id=d.id if d else None,
                                         created_at=now - timedelta(days=days)))
        test = Investigation(name_ar="سكر عشوائي", kind="lab")
        db.session.add(test)
        db.session.flush()
        for i in range(2):
            o = VisitInvestigation(visit_id=clinic["ids"]["visit"], patient_id=clinic["ids"]["child"], investigation_id=test.id, name="سكر عشوائي",
                                   consumed_at=now - timedelta(days=1))
            db.session.add(o)
            db.session.flush()
            d = doc("issue", f"LAB-{o.id}")
            db.session.add(StockMovement(item_id=strip.id, kind="out", qty=-1, unit_cost=7.5,
                                         cost_centre_id=lab_c.id, document_id=d.id,
                                         created_at=now - timedelta(days=1)))
        for feature, tokens, days in (("visit_summary", 1000, 1), ("lab_read", 400, 2),
                                      ("visit_summary", 600, 45)):
            db.session.add(AiUsage(feature=feature, provider="claude", model="m",
                                   prompt_tokens=tokens, completion_tokens=0,
                                   created_at=now - timedelta(days=days)))
        db.session.commit()
        clinic["ids"].update(ward_c=ward.id, test=test.id, amox=amox.id)
    return clinic


def test_the_store_counts_use_by_its_own_cost_beside_the_period_before(shop):
    from app.utils import consumption, med_board

    with shop["app"].app_context():
        w = med_board.window(preset="30")
        data = consumption.store(w)
        assert data["now"]["value"] == 135.0, "drug 100 + gauze 20 + lab strips 15"
        assert data["now"]["waste"] == 4.0 and data["now"]["unpriced"] == 1
        assert data["before"]["value"] == 50.0
        dept = {d["centre"].key if d["centre"] else None: d for d in data["departments"]}
        assert dept["ward_x"]["now"] == 120.0 and dept["ward_x"]["before"] == 50.0
        drugs = consumption.store(w, item_type="drug")
        assert drugs["now"]["value"] == 100.0 and [r["item"].name for r in drugs["top"]] == ["أموكسيسيلين"]
        assert consumption.change(100.0, 50.0) == 100
    page = shop["sign_in"]().get("/reports/consumption?part=store&preset=30").get_data(as_text=True)
    assert 'data-kpi="value"' in page and "data-cons-unpriced" in page
    assert f'data-cons-item="{shop["ids"]["amox"]}"' in page
    filtered = shop["sign_in"]().get(
        f"/reports/consumption?part=store&preset=30&centre={shop['ids']['ward_c']}").get_data(as_text=True)
    assert "شريط سكر" not in filtered


def test_each_lab_test_stands_beside_what_it_used(shop):
    from app.utils import consumption, med_board

    with shop["app"].app_context():
        data = consumption.lab(med_board.window(preset="30"))
        assert data["runs"] == 2 and data["now"]["value"] == 15.0
        row = data["tests"][0]
        assert row["runs"] == 2 and row["cost"] == 15.0 and row["each"] == 7.5
    page = shop["sign_in"]().get("/reports/consumption?part=lab").get_data(as_text=True)
    assert f'data-cons-test="{shop["ids"]["test"]}"' in page


def test_the_assistant_in_calls_and_tokens_and_no_money(shop):
    from app.utils import consumption, med_board

    with shop["app"].app_context():
        data = consumption.ai(med_board.window(preset="30"))
        assert data["now"] == {"calls": 2, "tokens": 1400} and data["before"]["tokens"] == 600
        feats = {f["feature"]: f for f in data["features"]}
        assert feats["visit_summary"]["tokens"] == 1000 and feats["visit_summary"]["before"] == 600
    page = shop["sign_in"]().get("/reports/consumption?part=ai").get_data(as_text=True)
    assert 'data-cons-feature="visit_summary"' in page and "data-cons-ai-money" in page


def test_each_part_behind_its_module_and_the_doors(shop):
    boss = shop["sign_in"]()
    hub = boss.get("/reports/").get_data(as_text=True)
    assert "/reports/consumption" in hub
    assert "data-to-consumption" in boss.get("/inventory/store/usage").get_data(as_text=True)
    board = boss.get("/reports/medical").get_data(as_text=True)
    assert "/reports/consumption" in board, "a tab beside the other boards"
    page = boss.get("/reports/consumption").get_data(as_text=True)
    for part in ("store", "drugs", "lab", "ai"):
        assert f'data-cons-part="{part}"' in page
    assert shop["sign_in"]("desk").get("/reports/consumption").status_code in (302, 403)
