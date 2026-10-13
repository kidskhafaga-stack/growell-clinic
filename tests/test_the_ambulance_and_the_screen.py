"""الإسعاف والكشف عن بُعد — GAHAR ICD.02 وACT.16، موديولين اختياريين.

* **الإسعاف**: المكالمة والأربع لحظات بالترتيب، والطفل اللي وصل ما بيتقفلش
  من غير التقييم والرعاية والتسليم، وزمن الاستجابة قصاد أهداف المستشفى بس،
  والجاهزية بالناقص وإجرائه، وورقة الإسعاف من حضور الطوارئ.
* **الكشف عن بُعد**: الفرز، وما بيبدأش من غير الهوية والمكانين، والبداية
  بتفتح زيارة عادية على قناتها، والتقييم الدوري بالأرقام.
* **والاتنين مقفولين** لحد ما المستشفى تفتحهم.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def on(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        for m in ("ambulance", "telemedicine", "emergency"):
            Setting.set(f"mod_enabled:{m}", "1")
        clinic["db"].session.commit()
    return clinic


def test_both_are_off_until_switched_on(clinic):
    boss = clinic["sign_in"]("boss")
    assert boss.get("/ambulance/").status_code in (302, 403, 404)
    assert boss.get("/telemedicine/").status_code in (302, 403, 404)


def test_an_ambulance_run_in_order_and_complete(on):
    from app.models import AmbulanceCall, AmbulanceReadiness, AmbulanceVehicle
    from app.utils import ambulance as amb

    boss = on["sign_in"]("boss")
    boss.post("/ambulance/fleet", data={"what": "vehicle", "name": "إسعاف ١", "provider": "contracted"})
    with on["app"].app_context():
        assert AmbulanceVehicle.query.count() == 0, "a contracted vehicle names its contractor"
    boss.post("/ambulance/fleet", data={"what": "vehicle", "name": "إسعاف ١", "plate": "أ ب ١٢٣"})
    with on["app"].app_context():
        vid = AmbulanceVehicle.query.one().id
    boss.post("/ambulance/fleet", data={"kind": "check", "vehicle_id": vid, "ok": "no", "missing": "أسطوانة أكسجين"})
    boss.post("/ambulance/fleet", data={"kind": "check", "vehicle_id": vid, "ok": "no", "missing": "أسطوانة أكسجين",
                                        "action": "اتبدّلت"})
    with on["app"].app_context():
        assert AmbulanceReadiness.query.count() == 1
    boss.post("/ambulance/", data={"location": "شارع النيل", "complaint": "تشنج", "caller": "الأم"})
    with on["app"].app_context():
        call = AmbulanceCall.query.one()
        cid = call.id
        call.received_at = datetime.utcnow() - timedelta(minutes=40)
        on["db"].session.commit()
    boss.post(f"/ambulance/call/{cid}/at_scene_at", data={})
    with on["app"].app_context():
        assert on["db"].session.get(AmbulanceCall, cid).at_scene_at is None, "in order"
    boss.post(f"/ambulance/call/{cid}/dispatched_at", data={})
    with on["app"].app_context():
        assert on["db"].session.get(AmbulanceCall, cid).dispatched_at is None, "which vehicle"
    for step, extra in (("dispatched_at", {"vehicle_id": vid, "crew": "مسعف وسواق"}), ("at_scene_at", {}),
                        ("left_scene_at", {}), ("arrived_at", {})):
        boss.post(f"/ambulance/call/{cid}/{step}", data=extra)
    boss.post(f"/ambulance/call/{cid}/close", data={"outcome": "brought"})
    with on["app"].app_context():
        assert on["db"].session.get(AmbulanceCall, cid).is_open, "brought, with nothing written"
    boss.post(f"/ambulance/call/{cid}/record", data={"patient_id": on["ids"]["child"],
                                                     "assessment": "واعي، حرارة ٣٩", "care": "باراسيتامول شرجي",
                                                     "handed_to": "تمريض الطوارئ"})
    boss.post(f"/ambulance/call/{cid}/close", data={"outcome": "brought"})
    with on["app"].app_context():
        call = on["db"].session.get(AmbulanceCall, cid)
        assert not call.is_open and call.minutes("dispatched_at") >= 39
        assert amb.over_target(call) == [], "no target written, nothing is late"
    boss.post("/ambulance/fleet", data={"what": "targets", "dispatched_at": "5"})
    with on["app"].app_context():
        assert amb.over_target(on["db"].session.get(AmbulanceCall, cid)) == ["dispatched_at"]
    page = boss.get("/ambulance/report").get_data(as_text=True)
    assert 'data-amb-count>1<' in page


def test_the_ed_attendance_shows_the_ambulance_sheet(on):
    from app.models import AmbulanceCall, EmergencyVisit

    with on["app"].app_context():
        now = datetime.utcnow()
        ev = EmergencyVisit(patient_id=on["ids"]["child"], arrived_at=now, arrival="ambulance")
        on["db"].session.add(ev)
        on["db"].session.add(AmbulanceCall(received_at=now - timedelta(minutes=30), location="المعادي",
                                           complaint="ضيق نفس", patient_id=on["ids"]["child"],
                                           arrived_at=now - timedelta(minutes=2)))
        on["db"].session.commit()
        evid = ev.id
    page = on["sign_in"]("boss").get(f"/emergency/attendance/{evid}").get_data(as_text=True)
    assert "data-ambulance-run" in page


def test_a_remote_encounter_checks_identity_and_opens_a_visit(on):
    from app.models import TeleEncounter, Visit
    from app.utils import telemedicine as tele

    boss = on["sign_in"]("boss")
    boss.post("/telemedicine/programme", data={"criteria": "متابعة مزمن مستقر", "platforms": "زووم\nواتساب فيديو",
                                               "director": "د. المشرف"})
    boss.post("/telemedicine/", data={"patient_id": on["ids"]["child"], "reason": "متابعة ربو", "modality": "video",
                                      "eligible": "no"})
    with on["app"].app_context():
        assert TeleEncounter.query.count() == 0, "not eligible says what the family was told"
    boss.post("/telemedicine/", data={"patient_id": on["ids"]["child"], "reason": "متابعة ربو", "modality": "video",
                                      "eligible": "yes", "doctor_id": on["ids"]["doctor"]})
    with on["app"].app_context():
        eid = TeleEncounter.query.one().id
        visits_before = Visit.query.count()
    boss.post(f"/telemedicine/{eid}/start", data={"patient_location": "البيت", "doctor_location": "العيادة"})
    with on["app"].app_context():
        assert on["db"].session.get(TeleEncounter, eid).started_at is None, "identity first"
    boss.post(f"/telemedicine/{eid}/start", data={"identity_how": "الاسم ورقم الملف", "patient_location": "البيت",
                                                  "doctor_location": "العيادة", "platform": "زووم"})
    with on["app"].app_context():
        enc = on["db"].session.get(TeleEncounter, eid)
        visit = on["db"].session.get(Visit, enc.visit_id)
        assert visit.channel == "tele" and visit.doctor_id == on["ids"]["doctor"]
        assert Visit.query.count() == visits_before + 1
    page = boss.get(f"/telemedicine/{eid}").get_data(as_text=True)
    assert "data-tele-visit" in page
    assert "data-tele-visit" in boss.get(f"/visits/{enc.visit_id}").get_data(as_text=True)
    boss.post(f"/telemedicine/{eid}/end", data={"outcome": "in_person"})
    with on["app"].app_context():
        from datetime import date
        stats = tele.evaluation(date.today() - timedelta(days=1), date.today())
        assert stats["done"] == 1 and stats["came_in"] == 1
    boss.post("/telemedicine/programme", data={"what": "review", "period_from": "2026-01-01",
                                               "period_to": "2026-03-31", "text": "نص الحالات احتاجت تيجي — راجعنا المعايير"})
    assert "راجعنا المعايير" in boss.get("/telemedicine/programme").get_data(as_text=True)
