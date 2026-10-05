"""تخزين الأدوية — GAHAR `MMS.04` / `GSR.19`.

* **دليل ٥** — التشغيلة والصلاحية: اختيارية في الاستلام، والمتبقي من كل
  تشغيلة محسوب بالأقرب انتهاءً اللي كانت سليمة يومها، والصيدلي يقدر يختار
  التشغيلة على الرف — والمنتهية عمرها ما تتعرض ولا تتصرف؛
* **دليل ٤** — التفتيش الشهري لكل مكان، والمش متحقق محتاج اللي اتعمل؛
* **الحرارة** — قصاد مدى المستشفى، ومن غير مدى بتتقاس ومش بتتحكم؛
* **دليل ٣** — انقطاع الكهرباء: الأماكن وقرار الصيدلي لكل دوا قبل القفل؛
* ومخزن عمره ما كتب تشغيلة شغّال زي ما كان.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_box_that_left_the_shelf import counter  # noqa: E402,F401


@pytest.fixture()
def store(counter):
    from app.models import Setting, User

    with counter["app"].app_context():
        Setting.set("mod_enabled:inventory", "1")
        Setting.set("mod_enabled:beds", "1")
        nurse = User(username="nurse", full_name="الممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        counter["db"].session.add(nurse)
        counter["db"].session.commit()
    return counter


def _move(c, kind="in", qty=10, lot="", expiry="", who="chem"):
    return c["sign_in"](who).post(f"/inventory/store/{c['box']}/move", data={
        "kind": kind, "qty": str(qty), "lot_number": lot, "expiry_date": expiry,
        "unit_cost": "25"})


def _lots(c):
    from app.models import StoreItem
    from app.utils import med_storage

    with c["app"].app_context():
        item = c["db"].session.get(StoreItem, c["box"])
        return {r["lot"]: (r["left"], r["state"]) for r in med_storage.lots(item)}


def _age(c, lot, days):
    """Move a lot's receipt back in time, so it was on the shelf earlier."""
    from app.models import StockMovement

    with c["app"].app_context():
        for m in StockMovement.query.filter_by(lot_number=lot).all():
            m.created_at = m.created_at - timedelta(days=days)
        c["db"].session.commit()


# ------------------------------------------------------------- the lots --
def test_a_store_that_never_writes_a_lot_works_as_before(store):
    _move(store, qty=5)
    _move(store, kind="out", qty=2)
    assert _lots(store) == {}
    from app.models import StoreItem

    with store["app"].app_context():
        assert store["db"].session.get(StoreItem, store["box"]).current_stock == 3


def test_issues_come_off_the_earliest_good_lot(store):
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=10, lot="LATE", expiry=(today + timedelta(days=400)).isoformat())
    _move(store, qty=10, lot="SOON", expiry=(today + timedelta(days=30)).isoformat())
    _move(store, kind="out", qty=4)
    lots = _lots(store)
    assert lots["SOON"] == (6, "near") and lots["LATE"] == (10, "ok")
    # A lot named on the issue is the lot it came from.
    _move(store, kind="out", qty=3, lot="LATE")
    assert _lots(store)["LATE"] == (7, "ok")
    page = store["sign_in"]("chem").get(f"/inventory/store/{store['box']}").get_data(as_text=True)
    assert "data-item-lots" in page and 'data-lot-state="near"' in page


def test_an_expired_lot_is_not_counted_as_used_and_never_issued(store):
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=5, lot="OLD", expiry=(today - timedelta(days=3)).isoformat())
    _age(store, "OLD", 30)
    _move(store, qty=5, lot="NEW", expiry=(today + timedelta(days=300)).isoformat())
    _move(store, kind="out", qty=2)
    lots = _lots(store)
    # Today's issue could not have come from a lot that expired three days
    # ago — so the expired boxes are still on the shelf, and the list says so.
    assert lots["OLD"] == (5, "expired") and lots["NEW"] == (3, "ok")
    _move(store, kind="out", qty=1, lot="OLD")
    assert _lots(store)["OLD"] == (5, "expired"), "an expired lot is not issued"
    # It may be removed as waste, under its lot.
    _move(store, kind="waste", qty=5, lot="OLD")
    assert "OLD" not in _lots(store)
    _move(store, kind="out", qty=1, lot="NOPE")
    assert _lots(store)["NEW"] == (3, "ok"), "a lot the store does not hold"


def test_a_move_between_our_own_warehouses_is_not_an_issue(store):
    from app.models import StockMovement, Warehouse
    from app.utils.clock import local_today
    from app.utils.store_docs import open_document

    _move(store, qty=8, lot="A1", expiry=(local_today() + timedelta(days=200)).isoformat())
    with store["app"].app_context():
        main = Warehouse.default()
        fridge = Warehouse(name="تلاجة", kind="fridge")
        store["db"].session.add(fridge)
        store["db"].session.flush()
        doc = open_document("transfer")
        for qty, wh in ((-8, main.id), (8, fridge.id)):
            store["db"].session.add(StockMovement(item_id=store["box"], kind="out" if qty < 0 else "in",
                                                  qty=qty, warehouse_id=wh, document_id=doc.id))
        store["db"].session.commit()
    assert _lots(store)["A1"] == (8, "ok")


def test_the_pharmacist_may_pick_a_lot_on_the_shelf(store):
    from app.models import PrescriptionItem, StoreItem
    from app.utils import pharmacy
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=5, lot="P1", expiry=(today + timedelta(days=20)).isoformat())
    _move(store, qty=5, lot="P2", expiry=(today + timedelta(days=200)).isoformat())
    chem = store["sign_in"]("chem")
    chem.post(f"/pharmacy/line/{store['line']}/shelf",
              data={"store_item_id": str(store["box"]), "quantity": "1"})
    page = chem.get(f"/pharmacy/rx/{store['rx']}").get_data(as_text=True)
    assert "data-shelf-lot" in page and "P1" in page and "★" in page
    chem.post(f"/pharmacy/line/{store['line']}/shelf",
              data={"store_item_id": str(store["box"]), "quantity": "1", "lot_number": "P2"})
    with store["app"].app_context():
        line = store["db"].session.get(PrescriptionItem, store["line"])
        assert line.lot_number == "P2"

        class Bill:
            invoice_number = "INV-1"

        pharmacy.take_off_shelf([line], Bill())
        store["db"].session.commit()
        from app.models import StockMovement

        moved = store["db"].session.get(StockMovement, line.stock_movement_id)
        assert moved.lot_number == "P2" and moved.qty == -1
    assert _lots(store)["P2"] == (4, "ok") and _lots(store)["P1"] == (5, "near")
    # A lot that is not on the shelf is refused, and the line keeps its lot.
    chem.post(f"/pharmacy/line/{store['line']}/shelf",
              data={"store_item_id": str(store["box"]), "quantity": "1", "lot_number": "ZZ"})
    with store["app"].app_context():
        assert store["db"].session.get(PrescriptionItem, store["line"]).lot_number == "P2"
        assert store["db"].session.get(StoreItem, store["box"]) is not None


def test_the_expiry_list_holds_store_lots_and_vaccine_batches(store):
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=3, lot="EXP", expiry=(today - timedelta(days=1)).isoformat())
    _move(store, qty=3, lot="FINE", expiry=(today + timedelta(days=500)).isoformat())
    page = store["sign_in"]("chem").get("/med-storage/expiry").get_data(as_text=True)
    assert 'data-expiry-row="store-EXP"' in page and "store-FINE" not in page
    # The clinic fixture's vaccine batches: one expires within the window?
    assert "data-expiry-list" in page


# ----------------------------------------------------------- the places --
def _place(c, who="chem", **extra):
    data = {"name": "تلاجة الصيدلية", "kind": "fridge", "temp_min": "2",
            "temp_max": "8", "readings_per_day": "2", **extra}
    return c["sign_in"](who).post("/med-storage/areas", data=data)


def _area_id(c):
    from app.models import StorageArea

    with c["app"].app_context():
        return StorageArea.query.order_by(StorageArea.id.desc()).first().id


def test_a_place_is_the_pharmacy_s_to_set_and_its_range_the_hospital_s(store):
    from app.models import StorageArea

    _place(store, temp_min="8", temp_max="2")             # upside down
    assert _place(store, who="nurse").status_code == 403
    with store["app"].app_context():
        assert StorageArea.query.count() == 0
    _place(store)
    assert store["sign_in"]("desk").get("/med-storage/").status_code == 403
    page = store["sign_in"]("nurse").get("/med-storage/").get_data(as_text=True)
    assert "data-storage-places" in page and "data-new-place" not in page
    assert "data-inspection-due" in page, "never inspected"


def test_a_reading_out_of_the_hospital_s_range_needs_what_was_done(store):
    from app.models import TempReading

    _place(store)
    area = _area_id(store)
    nurse = store["sign_in"]("nurse")
    nurse.post(f"/med-storage/area/{area}/temp", data={"temp_c": "11"})
    with store["app"].app_context():
        assert TempReading.query.count() == 0
    nurse.post(f"/med-storage/area/{area}/temp",
               data={"temp_c": "11", "action": "نقلت التطعيمات للتلاجة التانية"})
    nurse.post(f"/med-storage/area/{area}/temp", data={"temp_c": "5"})
    with store["app"].app_context():
        rows = TempReading.query.order_by(TempReading.id).all()
        assert [r.out_of_range for r in rows] == [True, False]
        assert rows[0].temp_max == 8
    board = nurse.get("/med-storage/").get_data(as_text=True)
    assert "data-temp-out" in board and "data-temp-short" not in board
    nurse.post(f"/med-storage/area/{area}/temp", data={"temp_c": "99"})
    with store["app"].app_context():
        assert TempReading.query.count() == 2, "an impossible reading"


def test_a_place_with_no_range_is_measured_never_judged(store):
    from app.models import TempReading

    _place(store, temp_min="", temp_max="", readings_per_day="3")
    area = _area_id(store)
    store["sign_in"]("nurse").post(f"/med-storage/area/{area}/temp", data={"temp_c": "30"})
    with store["app"].app_context():
        assert TempReading.query.one().out_of_range is False
    board = store["sign_in"]("nurse").get("/med-storage/").get_data(as_text=True)
    assert "data-temp-short" in board, "1 of the hospital's 3 a day"


def test_the_monthly_inspection(store):
    from app.models import StorageInspection
    from app.models.med_storage import INSPECTION_ITEMS
    from app.utils import med_storage
    from app.utils.clock import local_today

    _place(store)
    area = _area_id(store)
    answers = {f"q_{k}": "yes" for k in INSPECTION_ITEMS}
    nurse = store["sign_in"]("nurse")
    nurse.post(f"/med-storage/area/{area}/inspect",
               data={**answers, "q_secured": ""})         # not every item
    nurse.post(f"/med-storage/area/{area}/inspect",
               data={**answers, "q_no_expired": "no"})   # a "no" with no action
    with store["app"].app_context():
        assert StorageInspection.query.count() == 0
    nurse.post(f"/med-storage/area/{area}/inspect",
               data={**answers, "q_no_expired": "no", "findings": "علبتين منتهيين",
                     "action": "اتشالوا واتسجلوا هالك"})
    with store["app"].app_context():
        row = StorageInspection.query.one()
        assert row.failed == ["no_expired"]
        a = row.area
        assert not med_storage.inspection_due(a, local_today())
        row.inspected_on = local_today() - timedelta(days=40)
        store["db"].session.commit()
        assert med_storage.inspection_due(a, local_today())


def test_an_outage_is_closed_only_with_the_pharmacist_s_decisions(store):
    from app.models import PowerOutage

    _place(store)
    area = _area_id(store)
    nurse = store["sign_in"]("nurse")
    start = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    nurse.post("/med-storage/outages", data={"started_at": start})   # no place
    nurse.post("/med-storage/outages", data={"started_at": start, "area_ids": [str(area)]})
    with store["app"].app_context():
        outage = PowerOutage.query.one()
        oid = outage.id
    board = store["sign_in"]("chem").get("/med-storage/").get_data(as_text=True)
    assert f'data-open-outage="{oid}"' in board
    chem = store["sign_in"]("chem")
    chem.post(f"/med-storage/outage/{oid}/close")
    assert nurse.post(f"/med-storage/outage/{oid}/decide",
                      data={"medicine": "إنسولين", "decision": "discard",
                            "reason": "فضل فوق ٨ درجات ساعتين"}).status_code == 403
    nurse.post(f"/med-storage/outage/{oid}/end", data={"highest_temp": "12"})
    chem.post(f"/med-storage/outage/{oid}/close")
    with store["app"].app_context():
        assert store["db"].session.get(PowerOutage, oid).closed_at is None, "nothing decided"
    chem.post(f"/med-storage/outage/{oid}/decide",
              data={"store_item_id": str(store["box"]), "decision": "use",
                    "reason": "التلاجة فضلت في المدى"})
    chem.post(f"/med-storage/outage/{oid}/close")
    with store["app"].app_context():
        row = store["db"].session.get(PowerOutage, oid)
        assert row.closed_at is not None and row.highest_temp == 12
        assert [d.decision for d in row.decisions] == ["use"]
