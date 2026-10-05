"""A tube kept after its result, found again, and thrown away — GAHAR DAS.20
(ج)(هـ)(و), evidence 5 and 6.

* **where** is the laboratory's list of places, or typed;
* **how long** is the laboratory's figure — per test, else its general one —
  and with neither the tube is never called due;
* **found** by its code or by the child, from one search box;
* **thrown away** by somebody, and before its day only with a reason;
* one tube with three tests on it is one tube on the shelf.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _resulted(c, **kw):
    from app.utils import labs

    order = _order(c, **kw)
    with c["app"].app_context():
        labs.collect(_row(c, order))
        c["db"].session.commit()
        code = _row(c, order).sample_code
    c["sign_in"]("boss").post(f"/labs/order/{order}/result",
                              data={"result_text": "سلبي"})
    return order, code


def _kept(c, code):
    from app.utils import lab_storage

    return lab_storage.current(code)


def test_a_resulted_tube_is_put_away_where_the_lab_says(lab):
    order, code = _resulted(lab)
    boss = lab["sign_in"]("boss")
    page = boss.get("/labs/storage").get_data(as_text=True)
    assert f'data-waiting-tube="{code}"' in page
    assert "data-storage-box" in boss.get(f"/labs/order/{order}").get_data(as_text=True)

    boss.post("/labs/storage/places", data={"name": "ثلاجة ١ — رف ٢"})
    with lab["app"].app_context():
        from app.utils import lab_storage

        (place,) = lab_storage.places()
        key = place.key
    boss.post("/labs/storage/store", data={"code": code, "place_key": key})
    with lab["app"].app_context():
        row = _kept(lab, code)
        assert row.place_key == key and row.stored_by == lab["ids"]["admin"]
        assert row.keep_until is None, "no figure written, no day invented"
    assert f'data-waiting-tube="{code}"' not in boss.get("/labs/storage").get_data(as_text=True)
    assert "data-kept" in boss.get(f"/labs/order/{order}").get_data(as_text=True)


def test_a_tube_still_on_the_bench_is_not_stored(lab):
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        labs.collect(_row(lab, order))
        lab["db"].session.commit()
        code = _row(lab, order).sample_code
    lab["sign_in"]("boss").post("/labs/storage/store",
                                data={"code": code, "place_text": "رف"})
    with lab["app"].app_context():
        assert _kept(lab, code) is None


def test_how_long_is_the_lab_s_figure_per_test_then_general(lab):
    from app.models import Investigation
    from app.utils.clock import local_today

    boss = lab["sign_in"]("boss")
    boss.post("/labs/storage/keep-days", data={"days": "3"})
    _, general = _resulted(lab)
    boss.post("/labs/storage/store", data={"code": general, "place_text": "رف ١"})
    with lab["app"].app_context():
        assert _kept(lab, general).keep_until == local_today() + timedelta(days=3)
    boss.post(f"/labs/tests/{lab['urine']}/details", data={"keep_days": "7"})
    with lab["app"].app_context():
        assert lab["db"].session.get(Investigation, lab["urine"]).keep_days == 7
    _, own = _resulted(lab, name="تحليل بول", test="urine")
    boss.post("/labs/storage/store", data={"code": own, "place_text": "رف ٢"})
    with lab["app"].app_context():
        assert _kept(lab, own).keep_until == local_today() + timedelta(days=7)


def test_found_by_the_code_or_by_the_child(lab):
    _, code = _resulted(lab)
    boss = lab["sign_in"]("boss")
    boss.post("/labs/storage/store", data={"code": code, "place_text": "ثلاجة ٣"})
    with lab["app"].app_context():
        from app.models import Patient

        row = _kept(lab, code)
        child = lab["db"].session.get(Patient, row.patient_id)
        name, number = child.full_name, child.patient_number
    for q in (code, name, number):
        page = boss.get("/labs/storage", query_string={"q": q}).get_data(as_text=True)
        assert f'data-found-row="{row.id}"' in page and "ثلاجة ٣" in page, q


def test_thrown_away_on_its_day_freely_and_before_it_only_with_a_reason(lab):
    from app.utils.clock import local_today

    boss = lab["sign_in"]("boss")
    boss.post("/labs/storage/keep-days", data={"days": "2"})
    _, code = _resulted(lab)
    boss.post("/labs/storage/store", data={"code": code, "place_text": "رف"})
    with lab["app"].app_context():
        store_id = _kept(lab, code).id
    boss.post("/labs/storage/dispose", data={"store_id": str(store_id)})
    with lab["app"].app_context():
        assert _kept(lab, code).disposed_at is None, "early and no reason"
        row = _kept(lab, code)
        row.keep_until = local_today() - timedelta(days=1)
        lab["db"].session.commit()
    assert f'data-due-row="{store_id}"' in boss.get("/labs/storage").get_data(as_text=True)
    boss.post("/labs/storage/dispose", data={"store_id": str(store_id)})
    with lab["app"].app_context():
        row = _kept(lab, code)
        assert row.disposed_at is not None and row.disposed_by == lab["ids"]["admin"]
    # Thrown away is not put back on a shelf.
    boss.post("/labs/storage/store", data={"code": code, "place_text": "رف"})
    with lab["app"].app_context():
        assert _kept(lab, code).disposed_at is not None

    _, other = _resulted(lab)
    boss.post("/labs/storage/store", data={"code": other, "place_text": "رف"})
    with lab["app"].app_context():
        other_id = _kept(lab, other).id
    boss.post("/labs/storage/dispose",
              data={"store_id": str(other_id), "note": "العينة اتكسرت"})
    with lab["app"].app_context():
        assert _kept(lab, other).disposed_note == "العينة اتكسرت"


def test_one_tube_with_several_tests_is_one_tube_on_the_shelf(lab):
    from app.models import SpecimenStore
    from app.utils import labs

    first = _order(lab)
    second = _order(lab, name="تحليل بول", test="urine")
    with lab["app"].app_context():
        labs.collect(_row(lab, first))
        lab["db"].session.commit()
        code = _row(lab, first).sample_code
        _row(lab, second).sample_code = code
        labs.collect(_row(lab, second))
        lab["db"].session.commit()
    boss = lab["sign_in"]("boss")
    for order in (first, second):
        boss.post(f"/labs/order/{order}/result", data={"result_text": "سلبي"})
    page = boss.get("/labs/storage").get_data(as_text=True)
    assert page.count(f'data-waiting-tube="{code}"') == 1
    boss.post("/labs/storage/store", data={"code": code, "place_text": "رف"})
    with lab["app"].app_context():
        assert SpecimenStore.query.count() == 1


def test_only_the_lists_maker_writes_the_places_and_the_figure(lab):
    from app.utils import lab_storage

    doc = lab["sign_in"]("doc")
    doc.post("/labs/storage/places", data={"name": "ثلاجة"})
    doc.post("/labs/storage/keep-days", data={"days": "5"})
    with lab["app"].app_context():
        assert lab_storage.places() == [] and lab_storage.default_days() is None
    boss = lab["sign_in"]("boss")
    assert "data-to-storage" in boss.get("/labs/").get_data(as_text=True)
    assert "data-storage-settings" in boss.get("/labs/storage").get_data(as_text=True)
    assert "data-keep-days" in boss.get(f"/labs/tests/{lab['urine']}/ranges").get_data(as_text=True)
