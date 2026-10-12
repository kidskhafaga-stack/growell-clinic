"""عربات الطوارئ — GAHAR MMS.05.

* قايمة واحدة للمستشفى، والفحص عليها برقم القفل، والناقص لازم يتكتب؛
* الاستخدام بيفضل مفتوح لحد ما العربة تتعوّض وتتقفل برقم جديد؛
* مدة التعويض بتاعة المستشفى: من غيرها الانتظار بيبان ومش بيتحكم، ومعاها المتأخر بيرن.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def carts(clinic):
    from app.models import Setting
    from app.models.med_storage import StorageArea

    with clinic["app"].app_context():
        for m in ("pharmacy", "beds"):
            Setting.set(f"mod_enabled:{m}", "1")
        cart = StorageArea(name="عربة الطوارئ — الباطنة", kind="cart")
        clinic["db"].session.add(cart)
        clinic["db"].session.commit()
        clinic.update(cart=cart.id)
    return clinic


def test_checked_against_the_one_list_used_and_restocked(carts):
    from app.models import CartCheck, CartUse, User
    from app.utils import notifications

    boss = carts["sign_in"]("boss")
    boss.post(f"/med-storage/carts/{carts['cart']}/check", data={"complete": "1", "seal": "A1"})
    with carts["app"].app_context():
        assert CartCheck.query.count() == 0, "no list, nothing to check against"
    boss.post("/med-storage/carts/setup", data={"what": "item", "drawer": "١", "name": "Adrenaline 1 mg/ml", "quantity": "٤"})
    boss.post(f"/med-storage/carts/{carts['cart']}/check", data={"complete": "0", "seal": "A1"})
    boss.post(f"/med-storage/carts/{carts['cart']}/check", data={"complete": "0", "seal": "A1", "missing": "أمبول أدرينالين"})
    with carts["app"].app_context():
        assert [c.complete for c in CartCheck.query.all()] == [False]
    boss.post(f"/med-storage/carts/{carts['cart']}/use", data={"what": "أدرينالين ×٢ — إنعاش"})
    page = boss.get("/med-storage/carts").get_data(as_text=True)
    assert "data-cart-use" in page and "data-late" not in page, "no hospital hours, never judged"
    with carts["app"].app_context():
        u = CartUse.query.one()
        u.used_at = datetime.utcnow() - timedelta(hours=5)
        carts["db"].session.commit()
        uid = u.id
    boss.post("/med-storage/carts/setup", data={"what": "hours", "hours": "2"})
    with carts["app"].app_context():
        notifications.invalidate()
        me = User.query.filter_by(username="boss").first()
        assert any(i["key"] == "carts_late" for i in notifications.get_notifications(me))
    boss.post(f"/med-storage/carts/use/{uid}/restock", data={"seal_after": " "})
    boss.post(f"/med-storage/carts/use/{uid}/restock", data={"seal_after": "A2"})
    with carts["app"].app_context():
        assert carts["db"].session.get(CartUse, uid).seal_after == "A2"
    assert "data-to-carts" in boss.get("/med-storage/").get_data(as_text=True)
