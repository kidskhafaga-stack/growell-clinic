"""سحب تشغيلة — GAHAR MMS.08.

* السحب بيوقف التشغيلة: ما تتختارش على الرف وما تتصرفش من المخزن؛
* بيبيّن مين أخدها من الصيدلية، والصرف اللي ما كتبش تشغيلة بيتعدّ؛
* ما يتقفلش قبل الخطوات التلاتة (اتفصلت، المرضى، اتعدمت)؛
* والجرس بيرن للصيدلية، وفيه باب من تخزين الأدوية.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_medicines_kept_well_and_shown_to_be import _lots, _move, store  # noqa: E402,F401
from tests.test_the_box_that_left_the_shelf import counter  # noqa: E402,F401


def test_a_recalled_lot_stops_and_shows_who_had_it(store):
    from app.models import DrugRecall, PrescriptionItem
    from app.utils import pharmacy
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=5, lot="R1", expiry=(today + timedelta(days=300)).isoformat())
    chem = store["sign_in"]("chem")
    chem.post(f"/pharmacy/line/{store['line']}/shelf",
              data={"store_item_id": str(store["box"]), "quantity": "1", "lot_number": "R1"})
    with store["app"].app_context():
        line = store["db"].session.get(PrescriptionItem, store["line"])

        class Bill:
            invoice_number = "INV-1"

        pharmacy.take_off_shelf([line], Bill())
        store["db"].session.commit()
    _move(store, kind="out", qty=1)  # an issue with no lot written

    boss = store["sign_in"]("boss")
    boss.post("/med-storage/recalls/open", data={"item_id": store["box"], "lot_number": "R1"})
    with store["app"].app_context():
        assert DrugRecall.query.count() == 0, "no source, not opened"
    boss.post("/med-storage/recalls/open", data={"item_id": store["box"], "lot_number": "R1",
                                                 "notice_from": "هيئة الدواء", "notice_ref": "C-77"})
    with store["app"].app_context():
        rid = DrugRecall.query.one().id
    page = boss.get(f"/med-storage/recall/{rid}").get_data(as_text=True)
    assert "data-recall-patient" in page and "data-recall-unlotted" in page

    before = _lots(store)["R1"][0]
    _move(store, kind="out", qty=1, lot="R1")
    assert _lots(store)["R1"][0] == before, "a recalled lot is not issued"
    _move(store, kind="waste", qty=1, lot="R1")
    assert _lots(store)["R1"][0] == before - 1, "but it may be removed"

    boss.post(f"/med-storage/recall/{rid}/act", data={"what": "close"})
    for step, note in (("separated", "رف الحجز"), ("patients", "الأهل اتبلّغوا"), ("disposed", "رجعت للمورّد")):
        boss.post(f"/med-storage/recall/{rid}/act", data={"what": step, "note": note})
    boss.post(f"/med-storage/recall/{rid}/act", data={"what": "close"})
    with store["app"].app_context():
        assert not store["db"].session.get(DrugRecall, rid).is_open
    assert "data-to-recalls" in boss.get("/med-storage/").get_data(as_text=True)


def test_the_shelf_refuses_a_recalled_lot(store):
    from app.models import PrescriptionItem
    from app.utils.clock import local_today

    today = local_today()
    _move(store, qty=5, lot="R2", expiry=(today + timedelta(days=300)).isoformat())
    store["sign_in"]("boss").post("/med-storage/recalls/open", data={
        "item_id": store["box"], "lot_number": "R2", "notice_from": "الشركة"})
    store["sign_in"]("chem").post(f"/pharmacy/line/{store['line']}/shelf", data={
        "store_item_id": str(store["box"]), "quantity": "1", "lot_number": "R2"})
    with store["app"].app_context():
        assert store["db"].session.get(PrescriptionItem, store["line"]).lot_number is None
