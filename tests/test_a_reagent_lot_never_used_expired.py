"""Reagent lots received, inspected, opened and finished — GAHAR DAS.12.

Step five of the laboratory plan:

* a lot is received with its lot number and expiry, and inspected: accepted,
  or rejected with why; a lot already expired on arrival can only be
  rejected;
* an expired lot is never opened, and stays listed in red — on the lab's
  own list and on the rack — until somebody takes it off the shelf;
* a lot within the warning window says it is expiring;
* what the lab's store holds at or under its reorder level is shown, read
  from the store;
* none of this touches the store's own counts.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401


def _lot(c, **extra):
    data = {"name": "شرائط سكر", "lot_number": "L-100",
            "expiry_date": (date.today() + timedelta(days=200)).isoformat(),
            "decision": "accepted", **extra}
    return c["sign_in"]("boss").post("/labs/reagents", data=data)


def _rows(c):
    from app.models import ReagentLot

    with c["app"].app_context():
        return [(r.lot_number, r.decision, r.inspection_note) for r in
                ReagentLot.query.order_by(ReagentLot.id).all()]


def test_received_and_inspected_accepted_or_rejected_with_why(lab):
    _lot(lab)
    _lot(lab, lot_number="L-101", decision="rejected")
    _lot(lab, lot_number="L-101", decision="rejected", inspection_note="العبوة مكسورة")
    assert _rows(lab) == [("L-100", "accepted", None), ("L-101", "rejected", "العبوة مكسورة")]
    page = lab["sign_in"]("boss").get("/labs/reagents").get_data(as_text=True)
    assert 'data-lot-state="in_stock"' in page and "data-rejected-lots" in page


def test_a_lot_expired_on_arrival_can_only_be_rejected(lab):
    old = (date.today() - timedelta(days=1)).isoformat()
    _lot(lab, expiry_date=old)
    assert _rows(lab) == []
    _lot(lab, expiry_date=old, decision="rejected", inspection_note="منتهي")
    assert _rows(lab) == [("L-100", "rejected", "منتهي")]


def test_an_expired_lot_is_never_opened_and_stays_red_until_taken_off(lab):
    from app.models import ReagentLot
    from app.utils import lab_reagents

    _lot(lab)
    with lab["app"].app_context():
        lot = ReagentLot.query.one()
        lot.expiry_date = date.today() - timedelta(days=2)
        lab["db"].session.commit()
        lot_id = lot.id
        assert lab_reagents.expired_on_shelf() == 1
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/reagents/{lot_id}/open")
    with lab["app"].app_context():
        assert lab["db"].session.get(ReagentLot, lot_id).opened_at is None
    assert "data-expired-lots" in boss.get("/labs/").get_data(as_text=True)
    assert 'data-lot-state="expired"' in boss.get("/labs/reagents").get_data(as_text=True)
    boss.post(f"/labs/reagents/{lot_id}/finish")
    with lab["app"].app_context():
        assert lab_reagents.expired_on_shelf() == 0
    assert "data-expired-lots" not in boss.get("/labs/").get_data(as_text=True)


def test_open_and_finish_and_expiring_soon(lab):
    from app.models import ReagentLot
    from app.utils import lab_reagents

    _lot(lab, expiry_date=(date.today() + timedelta(days=10)).isoformat())
    boss = lab["sign_in"]("boss")
    with lab["app"].app_context():
        lot_id = ReagentLot.query.one().id
    boss.post(f"/labs/reagents/{lot_id}/open")
    with lab["app"].app_context():
        lot = lab["db"].session.get(ReagentLot, lot_id)
        assert lot.opened_by == lab["ids"]["admin"] and lab_reagents.state(lot) == "near"
    boss.post(f"/labs/reagents/{lot_id}/finish")
    with lab["app"].app_context():
        assert lab_reagents.state(lab["db"].session.get(ReagentLot, lot_id)) == "finished"


def test_running_low_is_read_from_the_lab_store(lab):
    from app.models import Setting, StoreItem, Warehouse

    with lab["app"].app_context():
        db = lab["db"]
        store = Warehouse(name="مخزن المعمل", kind="sub", is_active=True)
        db.session.add(store)
        db.session.flush()
        item = StoreItem(name="كاشف CRP", unit="علبة", reorder_level=5, opening_stock=0)
        db.session.add(item)
        db.session.flush()
        Setting.set("lab_store_warehouse_id", str(store.id))
        db.session.commit()
        item_id = item.id
    page = lab["sign_in"]("boss").get("/labs/reagents").get_data(as_text=True)
    assert f'data-low-item="{item_id}"' in page
