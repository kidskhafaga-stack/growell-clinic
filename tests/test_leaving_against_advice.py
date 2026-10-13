"""الخروج ضد النصيحة — DAMA من الإقامة، وLAMA من الطوارئ.

* نوع خروج لوحده، مش الخروج العادي ولا التحويل ولا الوفاة، و«مشي قبل ما
  حد يشوفه» حاجة تالتة؛
* الاختيار من شاشة الإقامة أو الطوارئ بيفتح الاستمارة، والاستمارة هي اللي
  بتقفل — مربوطة بالحالة؛
* الطبيب اللي شرح لازم يكون طبيب، وتقييمه، والتوقيع أو رفضه بشاهد،
  والمتابعة، والخطر الجسيم أو شبهة الإساءة لازم تتصعّد — التوقيع مش إعفاء؛
* سياسة المستشفى: «تسجيل» بيقفل والناقص بيفضل باين، و«إلزام» ما بيقفلش؛
* الكتابة للطاقم الإكلينيكي بس، وكل حركة في سجل التدقيق، والتقرير بالفترة.
"""
import base64
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401

PNG = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d"
    "4944415478da63f8ffff3f0005fe02fea7d6a5e20000000049454e44ae426082")).decode()


def _full(doctor, **over):
    form = {"refused": "استكمال المضاد الوريدي", "condition": "التهاب رئوي بيتحسّن",
            "consequences": "رجوع الحرارة وصعوبة تنفس", "alternatives": "مضاد بالفم ومتابعة بكرة",
            "explained_by": doctor, "doctor_assessment": "مستقر، الأب صاحب القرار وله الحق فيه",
            "serious_risk": "no", "safeguarding": "no", "followup_plan": "أموكسيسيلين وميعاد بعد ٤٨ ساعة",
            "guardian_name": "الأب", "guardian_relation": "father", "signature_refused": "yes",
            "witness_name": "ممرضة الوردية"}
    form.update(over)
    return form


def test_by_default_the_tap_closes_and_the_form_follows(ward):
    """The family is never held at the door: the one tap closes the stay as
    it always has, the form opens next, and what is missing shows."""
    from app.models import ActivityLog
    from app.models.admission import Admission
    from app.utils import refusal as no

    stay = _admit(ward, _child(ward, "سلمى"))
    doc = ward["sign_in"]("doc")
    res = doc.post(f"/beds/admission/{stay}/discharge", data={"outcome": "self_discharge"})
    assert f"/beds/against-advice/stay/{stay}" in res.headers["Location"]
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        assert not row.is_open and row.outcome == "self_discharge"
        assert stay in [x["row"].id for x in no.undocumented() if x["what"] == "discharge"]
        log = ActivityLog.query.filter_by(action="discharge.against_advice", entity_id=stay).one()
        assert "one-tap" in log.detail
    page = doc.get(f"/beds/against-advice/stay/{stay}").get_data(as_text=True)
    assert "data-ama-closed" in page and "data-ama-missing" in page and "data-ama-close>" not in page


def test_under_require_dama_opens_its_form_and_the_form_closes_the_stay(ward):
    from app.models import ActivityLog, Refusal
    from app.models.admission import Admission
    from app.utils import refusal as no

    stay = _admit(ward, _child(ward, "حسن"))
    ward["sign_in"]("boss").post("/beds/against-advice/policy", data={"policy": "require"})
    doc = ward["sign_in"]("doc")
    res = doc.post(f"/beds/admission/{stay}/discharge", data={"outcome": "self_discharge"})
    assert f"/beds/against-advice/stay/{stay}" in res.headers["Location"]
    with ward["app"].app_context():
        assert ward["db"].session.get(Admission, stay).is_open, "not closed by one tap"
    ward["sign_in"]("boss").post("/beds/against-advice/policy", data={"policy": "record"})
    page = doc.get(f"/beds/against-advice/stay/{stay}").get_data(as_text=True)
    assert "data-ama-form" in page and "data-ama-duty" in page
    doc.post(f"/beds/against-advice/stay/{stay}", data={"refused": "المضاد الوريدي", "close": "1"})
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        assert row.outcome == "self_discharge" and not row.is_open
        ref = Refusal.query.filter_by(admission_id=stay).one()
        assert ref.kind == "discharge" and ref.explained_by_id == ward["ids"]["doctor"]
        assert stay not in [x["row"].id for x in no.undocumented() if x["what"] == "discharge"]
        assert ActivityLog.query.filter_by(action="discharge.against_advice", entity_id=stay).count() == 1
    page = doc.get(f"/beds/against-advice/stay/{stay}").get_data(as_text=True)
    for gap in ("consequences", "signature", "risk", "doctor_assessment"):
        assert f'data-ama-gap="{gap}"' in page


def test_the_hospital_can_require_the_whole_form_and_escalation(ward):
    from app.models.admission import Admission
    from app.utils import against_advice as ama

    stay = _admit(ward, _child(ward, "منة"))
    boss, doc = ward["sign_in"]("boss"), ward["sign_in"]("doc")
    boss.post("/beds/against-advice/policy", data={"policy": "require"})
    with ward["app"].app_context():
        assert ama.policy() == "require"
    doctor = ward["ids"]["doctor"]
    doc.post(f"/beds/against-advice/stay/{stay}", data={"refused": "المضاد", "close": "1"})
    with ward["app"].app_context():
        assert ward["db"].session.get(Admission, stay).is_open, "incomplete under require"
    doc.post(f"/beds/against-advice/stay/{stay}", data=dict(_full(doctor, serious_risk="yes"), close="1"))
    with ward["app"].app_context():
        assert ward["db"].session.get(Admission, stay).is_open, "a serious danger needs the escalation"
    doc.post(f"/beds/against-advice/stay/{stay}",
             data=dict(_full(doctor, serious_risk="yes", escalated_to="الأخصائي المناوب ولجنة حماية الطفل"),
                       close="1"))
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        assert not row.is_open and row.outcome == "self_discharge"
        ref = ama.refusal_for("stay", row)
        assert ref.escalated and ama.missing(ref) == []


def test_a_nurse_may_record_but_the_explaining_doctor_is_a_doctor(ward):
    from app.models import User
    from app.utils import against_advice as ama

    with ward["app"].app_context():
        nurse = User(username="nurse1", full_name="ممرضة", role="nursing", is_active=True)
        nurse.set_password("secret")
        ward["db"].session.add(nurse)
        ward["db"].session.commit()
        nid = nurse.id
    stay = _admit(ward, _child(ward, "ريم"))
    ward["sign_in"]("nurse1").post(f"/beds/against-advice/stay/{stay}",
                                   data=_full(nid))
    with ward["app"].app_context():
        from app.models.admission import Admission

        ref = ama.refusal_for("stay", ward["db"].session.get(Admission, stay))
        assert ref is not None and ref.explained_by_id is None
        assert "doctor" in ama.missing(ref)


def test_the_desk_cannot_write_it(ward):
    stay = _admit(ward, _child(ward, "سما"))
    desk = ward["sign_in"]("desk")
    assert desk.post(f"/beds/against-advice/stay/{stay}", data={"refused": "x", "close": "1"}).status_code == 403
    with ward["app"].app_context():
        pid = __import__("app.models.admission", fromlist=["Admission"]).Admission.query.get(stay).patient_id
    assert desk.post(f"/patients/{pid}/refusal", data={"kind": "discharge"}).status_code == 403
    assert ward["sign_in"]("acct").get(f"/beds/against-advice/stay/{stay}").status_code == 403


def test_lama_from_the_emergency_chairs_and_left_unseen_apart(ward):
    from app.models import EmergencyVisit, Setting
    from app.utils import against_advice as ama

    with ward["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        pid = _child(ward, "عمرو")
        a = EmergencyVisit(patient_id=pid, arrived_at=datetime.utcnow() - timedelta(hours=2))
        b = EmergencyVisit(patient_id=pid, arrived_at=datetime.utcnow() - timedelta(hours=1))
        ward["db"].session.add_all([a, b])
        ward["db"].session.commit()
        aid, bid = a.id, b.id
    doc = ward["sign_in"]("doc")
    ward["sign_in"]("boss").post("/beds/against-advice/policy", data={"policy": "require"})
    res = doc.post(f"/emergency/depart/{aid}", data={"disposition": "self_discharge"})
    assert f"/beds/against-advice/er/{aid}" in res.headers["Location"]
    with ward["app"].app_context():
        assert ward["db"].session.get(EmergencyVisit, aid).departed_at is None
    doc.post(f"/beds/against-advice/er/{aid}", data=dict(_full(ward["ids"]["doctor"]), close="1"))
    doc.post(f"/emergency/depart/{bid}", data={"disposition": "left_unseen"})
    with ward["app"].app_context():
        assert ward["db"].session.get(EmergencyVisit, aid).disposition == "self_discharge"
        assert ward["db"].session.get(EmergencyVisit, bid).disposition == "left_unseen"
        data = ama.report(local_today() - timedelta(days=1), local_today())
        assert data["lama"] == 1 and data["complete"] == 1 and [u.id for u in data["unseen"]] == [bid]
        assert ama.refusal_for("er", ward["db"].session.get(EmergencyVisit, aid)).kind == "emergency"


def test_the_watch_screen_form_belongs_to_the_stay_and_the_report_counts_it(ward):
    from app.models import Refusal
    from app.models.admission import Admission
    from app.utils import beds as place
    from app.utils import refusal as no

    stay = _admit(ward, _child(ward, "لمى"))
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        place.discharge(row, "self_discharge")
        ward["db"].session.commit()
        pid = row.patient_id
        assert stay in [x["row"].id for x in no.undocumented() if x["what"] == "discharge"]
    boss = ward["sign_in"]("boss")
    page = boss.get("/beds/watch").get_data(as_text=True)
    assert "data-ama-full" in page
    boss.post(f"/patients/{pid}/refusal", data={"kind": "discharge", "admission_id": stay,
                                              "refused": "الحجز", "consequences": "تدهور"})
    with ward["app"].app_context():
        assert Refusal.query.one().admission_id == stay
        assert stay not in [x["row"].id for x in no.undocumented() if x["what"] == "discharge"]
    report = boss.get("/beds/against-advice/report").get_data(as_text=True)
    assert "data-ama-dama>1<" in report and "data-to-against-advice" in boss.get("/beds/").get_data(as_text=True)


def test_the_guardians_signature_is_attached_as_evidence(ward):
    from app.models import Refusal

    stay = _admit(ward, _child(ward, "يارا"))
    doc = ward["sign_in"]("doc")
    doc.post(f"/beds/against-advice/stay/{stay}", data=_full(ward["ids"]["doctor"], signature_refused="no"))
    with ward["app"].app_context():
        rid = Refusal.query.one().id
    doc.post(f"/beds/against-advice/form/{rid}/signature", data={"drawn": "data:image/png;base64," + PNG})
    with ward["app"].app_context():
        ref = ward["db"].session.get(Refusal, rid)
        assert ref.signature_kind == "drawn" and ref.has_signature
