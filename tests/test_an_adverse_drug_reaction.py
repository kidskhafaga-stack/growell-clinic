"""العرض الجانبي للدوا — GAHAR MMS.16 دليل ٣–٥.

* بيتكتب على إقامة الطفل باللي حصل واللي اتعمل والشدة، ومن غيرهم ما يتحفظش؛
* إضافته لسطر الحساسية قرار الشخص (علامة)، مش البرنامج؛
* الجرس بيرن للصيدلية لحد ما رقم البلاغ يتكتب؛ والطبيب اتبلّغ بيتسجّل.
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
        for m in ("beds", "pharmacy"):
            Setting.set(f"mod_enabled:{m}", "1")
        u = Unit(name="الباطنة", kind="ward", sort_order=0)
        db.session.add(u)
        db.session.flush()
        sp = Space(unit_id=u.id, name="عنبر", kind="bay")
        db.session.add(sp)
        db.session.flush()
        bed = Bed(space_id=sp.id, name="1", kind="bed")
        db.session.add(bed)
        db.session.flush()
        row = beds.admit(db.session.get(Patient, clinic["ids"]["child"]), bed,
                         when=datetime.utcnow() - timedelta(days=1))
        db.session.commit()
        clinic.update(stay=row.id)
    return clinic


def test_recorded_with_its_action_and_allergy_only_when_ticked(stay):
    from app.models import AdverseReaction, Patient

    doc = stay["sign_in"]("doc")
    url = f"/beds/admission/{stay['stay']}/adr"
    doc.post(url, data={"drug_name": "Ceftriaxone", "what_happened": "طفح", "severity": "mild"})
    with stay["app"].app_context():
        assert AdverseReaction.query.count() == 0, "no action, not saved"
    doc.post(url, data={"drug_name": "Ceftriaxone", "what_happened": "طفح جلدي بعد الجرعة",
                        "severity": "moderate", "action_taken": "اتوقف"})
    with stay["app"].app_context():
        assert AdverseReaction.query.count() == 1
        assert not (stay["db"].session.get(Patient, stay["ids"]["child"]).allergies or "")
    doc.post(url, data={"drug_name": "Vancomycin", "what_happened": "احمرار", "severity": "mild",
                        "action_taken": "إبطاء التسريب", "add_allergy": "1", "prescriber_told": "د. أحمد"})
    with stay["app"].app_context():
        assert "Vancomycin" in stay["db"].session.get(Patient, stay["ids"]["child"]).allergies
    page = doc.get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert 'id="adr"' in page and "data-adr-unreported" in page and "adr: 'treatment'" in page


def test_the_bell_rings_until_the_report_number(stay):
    from app.models import AdverseReaction, User
    from app.utils import notifications

    stay["sign_in"]("doc").post(f"/beds/admission/{stay['stay']}/adr",
                                data={"drug_name": "Amoxicillin", "what_happened": "قيء",
                                      "severity": "mild", "action_taken": "متابعة"})
    with stay["app"].app_context():
        boss = User.query.filter_by(username="boss").first()
        notifications.invalidate()
        assert any(i["key"] == "adr_unreported" for i in notifications.get_notifications(boss))
        rid = AdverseReaction.query.one().id
    boss_c = stay["sign_in"]("boss")
    assert "data-to-adr" in boss_c.get("/pharmacy/").get_data(as_text=True)
    boss_c.post(f"/pharmacy/adr/{rid}/reported", data={"report_ref": " "})
    boss_c.post(f"/pharmacy/adr/{rid}/told", data={"prescriber_told": "د. أحمد", "back": "board"})
    boss_c.post(f"/pharmacy/adr/{rid}/reported", data={"report_ref": "EPVC-2026-114"})
    with stay["app"].app_context():
        row = stay["db"].session.get(AdverseReaction, rid)
        assert row.report_ref == "EPVC-2026-114" and row.prescriber_told == "د. أحمد"
        notifications.invalidate()
        boss = User.query.filter_by(username="boss").first()
        assert not any(i["key"] == "adr_unreported" for i in notifications.get_notifications(boss))
