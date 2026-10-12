"""الاشتباه التنفسي عند أول نقطة دخول — GAHAR IPC.07.

* الفرز بيعلّم «أعراض تنفسية» و«اتدّى ماسك»، وبيظهر على الطفل في لوحة القسم؛
* المكان المخصص للتنفسي بيتعلّم في الأسرّة، وعدد أسرّته الفاضية بيتقال.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ed(clinic):
    from app.models import Bed, Patient, Setting, Space, Unit
    from app.utils import emergency as er

    with clinic["app"].app_context():
        db = clinic["db"]
        for m in ("emergency", "beds"):
            Setting.set(f"mod_enabled:{m}", "1")
        u = Unit(name="الطوارئ", kind="emergency", sort_order=0)
        db.session.add(u)
        db.session.flush()
        sp = Space(unit_id=u.id, name="تنفسي", kind="partition")
        db.session.add(sp)
        db.session.flush()
        db.session.add(Bed(space_id=sp.id, name="1", kind="trolley"))
        visit = er.arrive(db.session.get(Patient, clinic["ids"]["child"]))
        db.session.commit()
        clinic.update(ev=visit.id, space=sp.id)
    return clinic


def test_flagged_at_triage_and_shown_with_the_area(ed):
    from app.models import EmergencyVisit

    boss = ed["sign_in"]("boss")
    boss.post(f"/beds/space/{ed['space']}/respiratory")
    boss.post(f"/emergency/triage/{ed['ev']}", data={"level": "3", "resp": "1", "mask": "1"})
    with ed["app"].app_context():
        row = ed["db"].session.get(EmergencyVisit, ed["ev"])
        assert row.resp_symptoms is True and row.resp_mask is True
    page = boss.get("/emergency/register").get_data(as_text=True)
    assert "data-resp-flag" in page and "data-resp-free" in page


def test_no_symptoms_means_no_mask_question(ed):
    from app.models import EmergencyVisit

    ed["sign_in"]("boss").post(f"/emergency/triage/{ed['ev']}", data={"level": "4", "mask": "1"})
    with ed["app"].app_context():
        row = ed["db"].session.get(EmergencyVisit, ed["ev"])
        assert row.resp_symptoms is False and row.resp_mask is None
