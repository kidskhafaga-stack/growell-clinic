"""دفتر المخدرات — GAHAR MMS.09 دليل ٤.

* الوارد بمصدره، والمنصرف لطفل في سرير، والرصيد بعد كل سطر محسوب مش متكتب؛
* ما ينفعش يصرف أكتر من رصيد الدفتر؛
* الهالك والجرد محتاجين شاهد تاني غير اللي بيكتب، والهالك محتاج سبب؛
* الجرد اللي فيه فرق محتاج اللي اتعمل، وبيبان على واجهة الدفتر؛
* النقل بيطلع من صفحة ويدخل صفحة؛ وفيه باب من تخزين الأدوية والصيدلية.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def book(clinic):
    from app.models import Bed, ControlledItem, Patient, Setting, Space, Unit
    from app.models.med_storage import StorageArea
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        for m in ("pharmacy", "beds"):
            Setting.set(f"mod_enabled:{m}", "1")
        u = Unit(name="الباطنة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        sp = Space(unit_id=u.id, name="عنبر", kind="bay")
        db.session.add(sp)
        db.session.flush()
        bed = Bed(space_id=sp.id, name="1", kind="bed")
        ward, pharm = StorageArea(name="دولاب الباطنة", kind="ward"), StorageArea(name="الصيدلية", kind="pharmacy")
        item = ControlledItem(name="Morphine 10 mg/ml amp", unit="amp")
        db.session.add_all([bed, ward, pharm, item])
        db.session.flush()
        stay = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                          when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(ward=ward.id, pharm=pharm.id, item=item.id, stay=stay.id)
    return clinic


def _lines(b, area):
    from app.models import ControlledEntry

    with b["app"].app_context():
        return [(e.kind, e.qty, e.balance) for e in
                ControlledEntry.query.filter_by(item_id=b["item"], area_id=area).order_by(ControlledEntry.id)]


def test_in_out_and_never_more_than_the_book(book):
    boss = book["sign_in"]("boss")
    url = f"/med-storage/controlled/{book['item']}/{book['ward']}/record"
    boss.post(url, data={"kind": "received", "qty": "5"})
    assert _lines(book, book["ward"]) == [], "received with no source is refused"
    boss.post(url, data={"kind": "received", "qty": "5", "source": "الصيدلية — إذن ١"})
    boss.post(url, data={"kind": "given", "qty": "1"})
    assert len(_lines(book, book["ward"])) == 1, "given needs the child"
    boss.post(url, data={"kind": "given", "qty": "1", "admission_id": book["stay"]})
    boss.post(url, data={"kind": "given", "qty": "9", "admission_id": book["stay"]})
    assert _lines(book, book["ward"]) == [("received", 5, 5), ("given", 1, 4)]
    page = boss.get(f"/med-storage/controlled/{book['item']}/{book['ward']}").get_data(as_text=True)
    assert 'data-ctrl-book>4<' in page and "طفل" in page


def test_waste_and_count_need_another_person(book):
    with book["app"].app_context():
        from app.models import User
        doc = User.query.filter_by(username="doc").first().id
        me = User.query.filter_by(username="boss").first().id
    boss = book["sign_in"]("boss")
    url = f"/med-storage/controlled/{book['item']}/{book['ward']}/record"
    boss.post(url, data={"kind": "received", "qty": "3", "source": "الصيدلية"})
    boss.post(url, data={"kind": "wasted", "qty": "1", "note": "اتكسر", "witness_id": me})
    boss.post(url, data={"kind": "wasted", "qty": "1", "witness_id": doc})
    assert len(_lines(book, book["ward"])) == 1, "self-witness and no reason are refused"
    boss.post(url, data={"kind": "wasted", "qty": "1", "note": "اتكسر الأمبول", "witness_id": doc})
    boss.post(url, data={"kind": "count", "counted": "1", "witness_id": doc})
    assert len(_lines(book, book["ward"])) == 2, "a differing count needs what was done"
    boss.post(url, data={"kind": "count", "counted": "1", "witness_id": doc, "note": "اتبلّغ المشرف"})
    assert _lines(book, book["ward"])[-1] == ("count", -1, 1)
    front = boss.get("/med-storage/controlled").get_data(as_text=True)
    assert "data-ctrl-diff" in front


def test_a_transfer_leaves_one_page_and_enters_another_and_the_doors(book):
    boss = book["sign_in"]("boss")
    boss.post(f"/med-storage/controlled/{book['item']}/{book['pharm']}/record",
              data={"kind": "received", "qty": "10", "source": "المورّد — فاتورة ٧"})
    boss.post(f"/med-storage/controlled/{book['item']}/{book['pharm']}/record",
              data={"kind": "transfer", "qty": "4", "other_area_id": book["ward"]})
    assert _lines(book, book["pharm"])[-1] == ("transfer_out", 4, 6)
    assert _lines(book, book["ward"]) == [("transfer_in", 4, 4)]
    assert "data-to-controlled" in boss.get("/med-storage/").get_data(as_text=True)
    assert "data-to-controlled" in boss.get("/pharmacy/").get_data(as_text=True)
    assert boss.post("/med-storage/controlled/items", data={"name": "Fentanyl 50 mcg/ml", "unit": "amp"}).status_code == 302
    assert book["sign_in"]("desk").get("/med-storage/controlled").status_code == 403
