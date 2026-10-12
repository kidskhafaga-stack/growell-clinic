"""احتياطات العزل على الإقامة وعلى الباب — GAHAR IPC.12.

* الاحتياطات بتتسجّل جنب السرير (ومبدئية قبل أي نتيجة)، و«المعتادة بس»
  بتنهيها؛
* قرار مكافحة العدوى على ميكروب منذر بيبقى احتياطات الإقامة؛
* بتظهر في رأس الإقامة وفي كارت التسليم، ولافتة الباب من غير اسم الطفل؛
* غرفة العزل الهوائي بتتعلّم على مكان العزل بس.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def stay(clinic):
    from app.models import Bed, Patient, Setting, Space, Unit
    from app.utils import beds

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:beds", "1")
        u = Unit(name="الباطنة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        bay = Space(unit_id=u.id, name="عنبر", kind="bay")
        iso = Space(unit_id=u.id, name="عزل", kind="room", is_isolation=True)
        db.session.add_all([bay, iso])
        db.session.flush()
        bed = Bed(space_id=bay.id, name="1", kind="bed")
        db.session.add(bed)
        db.session.flush()
        row = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                         when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(stay=row.id, bay=bay.id, iso=iso.id)
    return clinic


def test_set_at_the_bedside_shown_and_ended(stay):
    from app.models import Admission

    doc = stay["sign_in"]("doc")
    doc.post(f"/beds/admission/{stay['stay']}/precautions",
             data={"precautions": ["standard", "droplet"], "empiric": "1", "note": "Cough"})
    with stay["app"].app_context():
        a = stay["db"].session.get(Admission, stay["stay"])
        assert a.precautions == "droplet" and a.precautions_empiric is True
    page = stay["sign_in"]("boss").get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert "data-stay-prec" in page and "data-isolation-sign" in page
    sign = stay["sign_in"]("boss").get(f"/beds/admission/{stay['stay']}/isolation-sign").get_data(as_text=True)
    assert 'data-sign-kind="droplet"' in sign and "طفل" not in sign.split("<body>")[1], "no name on the door"
    doc.post(f"/beds/admission/{stay['stay']}/precautions", data={"precautions": ["standard"]})
    with stay["app"].app_context():
        a = stay["db"].session.get(Admission, stay["stay"])
        assert a.precaution_list == [] and a.precautions_empiric is None
    assert stay["sign_in"]("boss").get(f"/beds/admission/{stay['stay']}/isolation-sign").status_code == 404


def test_the_handover_card_carries_them(stay):
    from app.models import Admission
    from app.utils import handover

    stay["sign_in"]("doc").post(f"/beds/admission/{stay['stay']}/precautions",
                                data={"precautions": ["contact"]})
    with stay["app"].app_context():
        a = stay["db"].session.get(Admission, stay["stay"])
        assert handover.cards([a])[a.id]["precautions"] == ["contact"]


def test_aiir_is_marked_only_on_an_isolation_space(stay):
    from app.models import Space

    boss = stay["sign_in"]("boss")
    boss.post(f"/beds/space/{stay['bay']}/aiir")
    boss.post(f"/beds/space/{stay['iso']}/aiir")
    with stay["app"].app_context():
        assert not stay["db"].session.get(Space, stay["bay"]).is_aiir
        assert stay["db"].session.get(Space, stay["iso"]).is_aiir
    assert stay["sign_in"]("doc").post(f"/beds/space/{stay['iso']}/aiir").status_code == 403
