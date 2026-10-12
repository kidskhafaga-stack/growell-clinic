"""لبن الأم المسحوب — GAHAR IPC.20 (h).

* الكيس بيتسجّل على إقامة الطفل بملصق فيه اسمه وتاريخ ميلاده والانتهاء؛
* مدد الحفظ بتاعة المستشفى: لحد ما تتكتب، الانتهاء بيتكتب على الكيس،
  ومن غيره الكيس ما يتسجّلش؛
* الإدّا من صفحة الطفل: كيس طفل تاني أو كيس خلصت مدته بيترفض؛
* فك التجميد بيقصّر الانتهاء، والاستبعاد محتاج سبب؛ وفيه باب للوحة.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _local(delta):
    from app.utils.clock import local_now

    return (local_now() + delta).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture()
def nursery(clinic):
    from app.models import Bed, Patient, Setting, Space, Unit
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        u = Unit(name="الحضانة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        bay = Space(unit_id=u.id, name="عنبر", kind="bay")
        db.session.add(bay)
        db.session.flush()
        b1, b2 = Bed(space_id=bay.id, name="1", kind="bed"), Bed(space_id=bay.id, name="2", kind="bed")
        db.session.add_all([b1, b2])
        twin = Patient(patient_number="P-TWIN", full_name="رضيع تاني", gender="female", date_of_birth=date(2026, 9, 1),
                       is_active=True)
        db.session.add(twin)
        db.session.flush()
        one = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), b1,
                         when=datetime.utcnow() - timedelta(days=1))
        two = beds.admit(twin, b2, when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(one=one.id, two=two.id)
    return clinic


def _bags(n):
    from app.models import MilkBag

    with n["app"].app_context():
        return [(b.id, b.patient_id, b.status, b.storage, b.expires_at)
                for b in MilkBag.query.order_by(MilkBag.id)]


def test_no_hours_means_the_expiry_is_written(nursery):
    doc = nursery["sign_in"]("doc")
    doc.post(f"/beds/admission/{nursery['one']}/milk",
             data={"expressed_at": _local(timedelta(hours=-1)), "storage": "fridge"})
    assert _bags(nursery) == [], "no keeping time and no expiry — nothing invented"
    r = doc.post(f"/beds/admission/{nursery['one']}/milk",
                 data={"expressed_at": _local(timedelta(hours=-1)), "storage": "fridge",
                       "expires_at": _local(timedelta(hours=20)), "volume_ml": "30"})
    [(bag, _, status, storage, _)] = _bags(nursery)
    assert status == "stored" and storage == "fridge"
    assert r.headers["Location"].endswith(f"/beds/milk/{bag}/label")
    label = doc.get(f"/beds/milk/{bag}/label").get_data(as_text=True)
    assert "EBM%06d" % bag in label and "2025-01-01" in label
    page = doc.get(f"/beds/admission/{nursery['one']}").get_data(as_text=True)
    assert 'id="milk"' in page and f'data-milk-bag="{bag}"' in page and "data-milk-no-hours" in page


def test_another_babys_bag_and_an_expired_one_are_refused(nursery):
    from app.models import MilkBag, Setting

    boss = nursery["sign_in"]("boss")
    boss.post("/beds/milk/hours", data={"fridge": "48", "freezer": "", "thawed": ""})
    with nursery["app"].app_context():
        assert Setting.get("ebm_fridge_hours") == "48"
    doc = nursery["sign_in"]("doc")
    doc.post(f"/beds/admission/{nursery['one']}/milk",
             data={"expressed_at": _local(timedelta(hours=-2)), "storage": "fridge"})
    [(bag, _, _, _, expires)] = _bags(nursery)
    with nursery["app"].app_context():
        row = nursery["db"].session.get(MilkBag, bag)
        assert abs((expires - row.expressed_at) - timedelta(hours=48)) < timedelta(seconds=1)
    doc.post(f"/beds/admission/{nursery['two']}/milk/give", data={"code": "EBM%06d" % bag})
    assert _bags(nursery)[0][2] == "stored", "the other baby's page cannot give it"
    with nursery["app"].app_context():
        nursery["db"].session.get(MilkBag, bag).expires_at = datetime.utcnow() - timedelta(minutes=1)
        nursery["db"].session.commit()
    doc.post(f"/beds/admission/{nursery['one']}/milk/give", data={"code": "EBM%06d" % bag})
    assert _bags(nursery)[0][2] == "stored", "expired is not given"
    with nursery["app"].app_context():
        nursery["db"].session.get(MilkBag, bag).expires_at = datetime.utcnow() + timedelta(hours=5)
        nursery["db"].session.commit()
    doc.post(f"/beds/admission/{nursery['one']}/milk/give",
             data={"code": "ebm%06d" % bag, "second_check": "Nurse B"})
    with nursery["app"].app_context():
        row = nursery["db"].session.get(MilkBag, bag)
        assert row.status == "given" and row.second_check == "Nurse B"


def test_thaw_shortens_and_discard_needs_a_reason_and_the_board_has_a_door(nursery):
    from app.models import Setting

    with nursery["app"].app_context():
        Setting.set("ebm_freezer_hours", "2000")
        nursery["db"].session.commit()
    doc = nursery["sign_in"]("doc")
    doc.post(f"/beds/admission/{nursery['one']}/milk",
             data={"expressed_at": _local(timedelta(hours=-1)), "storage": "freezer"})
    [(bag, _, _, _, frozen_until)] = _bags(nursery)
    doc.post(f"/beds/milk/{bag}/thaw")
    assert _bags(nursery)[0][3] == "freezer", "no thawed keeping time — not thawed"
    with nursery["app"].app_context():
        Setting.set("ebm_thawed_hours", "24")
        nursery["db"].session.commit()
    doc.post(f"/beds/milk/{bag}/thaw")
    [(_, _, _, storage, until)] = _bags(nursery)
    assert storage == "thawed" and until < frozen_until
    doc.post(f"/beds/milk/{bag}/discard", data={"reason": " "})
    assert _bags(nursery)[0][2] == "stored"
    doc.post(f"/beds/milk/{bag}/discard", data={"reason": "اتلوّث"})
    assert _bags(nursery)[0][2] == "discarded"
    index = doc.get("/beds/").get_data(as_text=True)
    assert "data-to-milk" in index
    assert doc.get("/beds/milk").status_code == 200
    assert doc.post("/beds/milk/hours", data={"fridge": "1"}).status_code == 403
