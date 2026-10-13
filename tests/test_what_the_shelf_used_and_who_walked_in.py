"""استهلاك المخزون ونفاده (GAHAR `OGM.11` دليل ٣)، والزوار والمقاولين
(`EFS.09` ج، د).

* **الاستهلاك** هو اللي اتصرف للاستخدام بس — مش التحويل بين المخازن ولا
  المرتجع للمورّد — والهالك لوحده؛ **النفاد** من الحركات نفسها: الرصيد نزل
  لصفر، وبيخلص لما الصنف يرجع؛ والصنف اللي عمره ما اتخزّن ما «خلصش»؛
* **الزائر** ببطاقة ولمين جاي، والمندوب والمقاول بشركتهم، والمكان المحظور
  بإذن مكتوب، والبطاقة ما تتدّاش لاتنين جوه، والخروج بيقفلها.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _move(db, item, qty, days_ago, kind=None):
    from app.models import StockMovement

    kind = kind or ("in" if qty > 0 else "out")
    db.session.add(StockMovement(item_id=item.id, kind=kind, qty=qty,
                                 created_at=datetime.utcnow() - timedelta(days=days_ago)))


def test_use_is_what_was_issued_and_a_stock_out_is_read_from_the_movements(clinic):
    from app.models import StoreItem
    from app.utils import stock_watch

    db = clinic["db"]
    with clinic["app"].app_context():
        gauze = StoreItem(name="شاش", opening_stock=10, reorder_level=5, is_active=True,
                          created_at=datetime.utcnow() - timedelta(days=60))
        never = StoreItem(name="صنف جديد", opening_stock=0, reorder_level=0, is_active=True)
        db.session.add_all([gauze, never])
        db.session.flush()
        _move(db, gauze, -6, 40)
        _move(db, gauze, -4, 30)          # ran out
        _move(db, gauze, 20, 20)          # back
        _move(db, gauze, -5, 5)
        _move(db, gauze, -2, 3, kind="waste")
        db.session.commit()
        data = stock_watch.report(90)
        rows = {r["item"].name: r for r in data["rows"]}
        g = rows["شاش"]
        assert g["used"] == 15 and g["wasted"] == 2 and g["per_month"] == 5.0
        assert g["stock"] == 13 and g["cover_days"] == 78
        assert len(g["stockouts"]) == 1 and g["stockouts"][0]["days"] == 10 and not g["out_now"]
        n = rows["صنف جديد"]
        assert n["stockouts"] == [] and n["out_now"], "never stocked is not a stock-out"
    boss = clinic["sign_in"]()
    page = boss.get("/inventory/store/usage").get_data(as_text=True)
    assert 'data-item-stockouts="1"' in page
    assert "data-to-stock-usage" in boss.get("/quality/contracts").get_data(as_text=True)
    assert clinic["sign_in"]("doc").get("/inventory/store/usage").status_code in (302, 403)


def test_visitors_carry_a_badge_and_a_restricted_area_needs_its_permission(clinic):
    from app.models import RestrictedArea, VisitorPass

    boss = clinic["sign_in"]()
    assert boss.get("/facility/visitors").status_code == 200
    assert clinic["sign_in"]("doc").get("/facility/visitors").status_code == 403
    boss.post("/facility/restricted-area", data={"name": "الحضّانة", "rule": "الأم والطاقم بس"})
    with clinic["app"].app_context():
        area = RestrictedArea.query.one().id
    form = {"kind": "contractor", "name": "مهندس التكييف", "visiting": "صيانة التكييف", "badge_no": "C-7"}
    boss.post("/facility/visitors", data=form)
    with clinic["app"].app_context():
        assert VisitorPass.query.count() == 0, "a contractor without the company"
    boss.post("/facility/visitors", data={**form, "company": "شركة التبريد", "area_id": str(area)})
    with clinic["app"].app_context():
        assert VisitorPass.query.count() == 0, "a restricted area without permission"
    boss.post("/facility/visitors", data={**form, "company": "شركة التبريد", "area_id": str(area),
                                          "permitted_by": "رئيسة تمريض الحضّانة"})
    boss.post("/facility/visitors", data={"kind": "visitor", "name": "جد", "visiting": "حفيده", "badge_no": "C-7"})
    with clinic["app"].app_context():
        assert VisitorPass.query.count() == 1, "one badge, one person inside"
        pid = VisitorPass.query.one().id
        row = VisitorPass.query.one()
        row.in_at = row.in_at - timedelta(days=2)
        clinic["db"].session.commit()
    page = boss.get("/facility/visitors").get_data(as_text=True)
    assert 'data-overnight="1"' in page
    boss.post(f"/facility/visitor/{pid}/out")
    with clinic["app"].app_context():
        assert VisitorPass.query.one().out_at is not None
    assert 'data-inside="0"' in boss.get("/facility/visitors").get_data(as_text=True)
