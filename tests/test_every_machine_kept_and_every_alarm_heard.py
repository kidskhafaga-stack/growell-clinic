"""الأجهزة الطبية — GAHAR `EFS.10` / `GSR.27` و`CSS.02` / `GSR.08`.

* **الجرد** منفصل عن قايمة أجهزة الفحوصات، ويتربط بيها لو هو نفس الجهاز؛
* **الصيانة الوقائية والمعايرة** بموعد الشركة اللي المستشفى كتبته — ومن
  غيره محدّش بيقول إنها متأخرة؛
* **العطل** بيطلّع الجهاز من الخدمة لحد إصلاح، والحادثة لازم إجراء وبلاغ؛
* **الإنذار الحرج**: الإعدادات المتفق عليها، والاختبار، وأحداث الإنذار
  بالإجراء — ولجهاز عليه إنذار بس؛
* **التدريب**: مين واتدرب إمتى ولحد إمتى؛
* اللي بيبلّغ عن عطل أي حد واقف جنب الجهاز، واللي بيدير الجرد المسؤول.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import User

    with clinic["app"].app_context():
        nurse = User(username="nurse", full_name="الممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)
        clinic["db"].session.commit()
        clinic["ids"]["nurse"] = nurse.id
    return clinic


def _new(c, who="boss", **extra):
    from app.utils.clock import local_today

    data = {"name": "جهاز تنفس صناعي", "category": "تنفس", "location": "العناية",
            "serial_number": "VX-100", "company": "شركة الصيانة",
            "company_contact": "0100", "installed_on": (local_today() - timedelta(days=200)).isoformat(),
            "ppm_every_days": "180", "is_critical": "1", "backup": "الجهاز التاني في الطوارئ",
            "has_critical_alarm": "1", "alarm_settings": "ضغط أعلى من 35 — الصوت عالي",
            "alarm_test_every_days": "30", **extra}
    return c["sign_in"](who).post("/equipment/new", data=data)


def _row(c):
    from app.models import Equipment

    with c["app"].app_context():
        row = Equipment.query.order_by(Equipment.id.desc()).first()
        return row.id if row else None


def _event(c, eid, who="boss", **form):
    return c["sign_in"](who).post(f"/equipment/{eid}/event", data=form)


def test_the_register_is_the_store_s_to_keep(ward):
    from app.models import Equipment

    assert _new(ward, who="nurse").status_code == 403
    _new(ward, alarm_settings="")                      # alarm with no settings
    with ward["app"].app_context():
        assert Equipment.query.count() == 0
    _new(ward)
    eid = _row(ward)
    board = ward["sign_in"]("nurse").get("/equipment/").get_data(as_text=True)
    assert f'data-equipment="{eid}"' in board and "data-new-equipment" not in board
    assert ward["sign_in"]("desk").get("/equipment/").status_code == 403
    page = ward["sign_in"]("boss").get(f"/equipment/{eid}").get_data(as_text=True)
    assert "data-alarm-settings" in page and "ضغط أعلى من 35" in page


def test_overdue_is_the_manufacturer_s_interval_or_nothing(ward):
    from app.models import Equipment
    from app.utils import equipment as eq

    _new(ward, calibration_every_days="")
    eid = _row(ward)
    with ward["app"].app_context():
        row = ward["db"].session.get(Equipment, eid)
        assert eq.due(row, "ppm")["state"] == "overdue"      # 200 days since install, every 180
        assert eq.due(row, "calibration")["state"] == "quiet", "no interval, nothing judged"
    _event(ward, eid, kind="ppm", result="pass", details="صيانة كاملة", done_by="م. سامي")
    with ward["app"].app_context():
        row = ward["db"].session.get(Equipment, eid)
        state = eq.due(row, "ppm")
        assert state["state"] == "ok" and state["on"] > row.installed_on + timedelta(days=180)
    board = ward["sign_in"]().get("/equipment/").get_data(as_text=True)
    assert 'data-overdue="ppm"' not in board


def test_a_malfunction_takes_it_out_of_service_until_a_repair(ward):
    from app.models import Equipment

    _new(ward)
    eid = _row(ward)
    _event(ward, eid, who="nurse", kind="malfunction", details="الشاشة مطفية")   # no action
    with ward["app"].app_context():
        assert ward["db"].session.get(Equipment, eid).status == "in_service"
    _event(ward, eid, who="nurse", kind="malfunction", details="الشاشة مطفية",
           action="اتنقل الطفل على الجهاز البديل")
    with ward["app"].app_context():
        assert ward["db"].session.get(Equipment, eid).status == "out_of_service"
    page = ward["sign_in"]("nurse").get(f"/equipment/{eid}").get_data(as_text=True)
    assert "data-broken" in page
    # A nurse reports; the repair is the equipment manager's.
    _event(ward, eid, who="nurse", kind="repair", details="اتغيرت الشاشة")
    with ward["app"].app_context():
        assert ward["db"].session.get(Equipment, eid).status == "out_of_service"
    _event(ward, eid, kind="repair", details="اتغيرت الشاشة", done_by="الشركة")
    with ward["app"].app_context():
        assert ward["db"].session.get(Equipment, eid).status == "in_service"
    # A repair with nothing broken is refused.
    _event(ward, eid, kind="repair", details="ولا حاجة")
    with ward["app"].app_context():
        assert len(ward["db"].session.get(Equipment, eid).events) == 2


def test_an_incident_is_reported_with_its_action(ward):
    from app.models import EquipmentEvent
    from app.utils.clock import local_today

    _new(ward)
    eid = _row(ward)
    _event(ward, eid, who="nurse", kind="incident", details="المضخة ادّت جرعة زيادة",
           action="اتوقفت واتبلّغ الطبيب")                 # nobody reported to
    with ward["app"].app_context():
        assert EquipmentEvent.query.count() == 0
    _event(ward, eid, who="nurse", kind="incident", details="المضخة ادّت جرعة زيادة",
           action="اتوقفت واتبلّغ الطبيب", reported_to="إدارة الجودة")
    page = ward["sign_in"]("nurse").get("/equipment/incidents").get_data(as_text=True)
    assert "data-incident=" in page and "إدارة الجودة" in page


def test_the_critical_alarm_its_test_and_its_events(ward):
    from app.models import Equipment, EquipmentEvent
    from app.utils import equipment as eq

    _new(ward)
    eid = _row(ward)
    _event(ward, eid, kind="alarm_test", details="اتختبر الإنذار")          # no result
    _event(ward, eid, kind="alarm_test", result="pass", details="اتختبر الإنذار وصوته مسموع")
    _event(ward, eid, who="nurse", kind="alarm_event", details="الإنذار ضرب",
           action="اتشفط الأنبوب والقراية رجعت")
    with ward["app"].app_context():
        kinds = [e.kind for e in EquipmentEvent.query.order_by(EquipmentEvent.id)]
        assert kinds == ["alarm_test", "alarm_event"]
        row = ward["db"].session.get(Equipment, eid)
        assert eq.due(row, "alarm_test")["state"] == "ok"
    # No alarm on record, no alarm events.
    _new(ward, name="ميزان", has_critical_alarm="", alarm_settings="", ppm_every_days="")
    other = _row(ward)
    _event(ward, other, kind="alarm_test", result="pass", details="x")
    with ward["app"].app_context():
        assert not ward["db"].session.get(Equipment, other).events


def test_who_is_trained_and_until_when(ward):
    from app.models import Equipment
    from app.utils import equipment as eq
    from app.utils.clock import local_today

    _new(ward)
    eid = _row(ward)
    today = local_today()
    boss = ward["sign_in"]()
    boss.post(f"/equipment/{eid}/train", data={"user_id": str(ward["ids"]["nurse"]),
              "trained_on": today.isoformat(), "valid_until": today.isoformat()})  # until = on
    assert ward["sign_in"]("nurse").post(f"/equipment/{eid}/train", data={
        "user_id": str(ward["ids"]["nurse"]), "trained_on": today.isoformat()}).status_code == 403
    boss.post(f"/equipment/{eid}/train", data={"user_id": str(ward["ids"]["nurse"]),
              "trained_on": (today - timedelta(days=400)).isoformat(),
              "valid_until": (today - timedelta(days=35)).isoformat(), "trainer": "الشركة"})
    with ward["app"].app_context():
        row = ward["db"].session.get(Equipment, eid)
        assert len(row.trainings) == 1 and eq.trained_now(row) == {}
    boss.post(f"/equipment/{eid}/train", data={"user_id": str(ward["ids"]["nurse"]),
              "trained_on": today.isoformat(), "trainer": "م. سامي"})
    with ward["app"].app_context():
        row = ward["db"].session.get(Equipment, eid)
        assert list(eq.trained_now(row)) == [ward["ids"]["nurse"]]


def test_retired_equipment_leaves_the_board_and_takes_no_events(ward):
    from app.models import Equipment

    _new(ward)
    eid = _row(ward)
    boss = ward["sign_in"]()
    boss.post(f"/equipment/{eid}/retire", data={"reason": ""})
    boss.post(f"/equipment/{eid}/retire", data={"reason": "اتغيّر بجهاز أحدث"})
    with ward["app"].app_context():
        assert ward["db"].session.get(Equipment, eid).status == "retired"
    assert f'data-equipment="{eid}"' not in boss.get("/equipment/").get_data(as_text=True)
    assert f'data-equipment="{eid}"' in boss.get("/equipment/?retired=1").get_data(as_text=True)
    _event(ward, eid, kind="malfunction", details="x", action="y")
    with ward["app"].app_context():
        assert not ward["db"].session.get(Equipment, eid).events
