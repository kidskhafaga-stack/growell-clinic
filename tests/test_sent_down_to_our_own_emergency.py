"""«حوّل للطوارئ» → «طوارئ المستشفى عندنا».

* موجود بس لو المستشفى عندها طوارئ — والعيادة لوحدها زي ما هي بالظبط؛
* بيفتح حضور في الطوارئ بالسبب ومين بعته، ويظهر على شاشة الطوارئ على طول؛
* مش ورقة إحالة لمستشفى تانية — فمش مستني رد؛
* طفل موجود في الطوارئ أصلاً ما بيتفتحلوش حضور تاني؛
* الإلغاء بيشيل الحضور لو محدّش في الطوارئ لمسه، وبعد كده لأ.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _er_on(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        Setting.set("mod_enabled:emergency", "1" if on else "0")
        c["db"].session.commit()


def _send(c, **form):
    data = {"kind": "in_house", "referral_note": "ضيق تنفس شديد", **form}
    return c["sign_in"]("doc").post(f"/visits/{c['ids']['visit']}/refer", data=data)


def test_offered_only_where_the_hospital_has_an_emergency_department(clinic):
    from app.models import EmergencyVisit

    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'value="in_house"' not in page and 'value="referral"' in page
    _er_on(clinic)
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'value="in_house"' in page
    _er_on(clinic, on=False)
    _send(clinic)                                       # asked anyway: an ordinary referral
    with clinic["app"].app_context():
        assert EmergencyVisit.query.count() == 0


def test_the_child_arrives_on_the_department_s_list_with_the_reason(clinic):
    from app.models import EmergencyVisit, Referral, Visit

    _er_on(clinic)
    _send(clinic)
    with clinic["app"].app_context():
        row = EmergencyVisit.query.one()
        assert row.from_visit_id == clinic["ids"]["visit"] and row.arrival == "referred"
        assert row.sent_reason == "ضيق تنفس شديد" and row.visit_id is None
        assert Referral.query.count() == 0, "not a paper to another hospital"
        assert clinic["db"].session.get(Visit, clinic["ids"]["visit"]).is_referred
        rid = row.id
    boss = clinic["sign_in"]("boss")
    board = boss.get("/emergency/register").get_data(as_text=True)
    assert f'data-open-row="{rid}"' in board and "data-from-clinic" in board
    page = boss.get(f"/emergency/attendance/{rid}").get_data(as_text=True)
    assert "data-from-clinic" in page and "ضيق تنفس شديد" in page
    record = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-er-inhouse" in record


def test_a_child_already_in_the_department_is_not_opened_twice(clinic):
    from app.models import EmergencyVisit, Patient
    from app.utils import emergency as er

    _er_on(clinic)
    with clinic["app"].app_context():
        er.arrive(clinic["db"].session.get(Patient, clinic["ids"]["child"]))
        clinic["db"].session.commit()
    _send(clinic)
    with clinic["app"].app_context():
        row = EmergencyVisit.query.one()
        assert row.from_visit_id == clinic["ids"]["visit"] and row.arrival == "walk_in"
    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/refer", data={"undo": "1"})
    with clinic["app"].app_context():
        row = EmergencyVisit.query.one()
        assert row.from_visit_id is None, "the attendance they were in stays"


def test_undo_only_while_the_department_has_not_started(clinic):
    from app.models import EmergencyVisit, Visit
    from app.utils import emergency as er

    _er_on(clinic)
    _send(clinic)
    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/refer", data={"undo": "1"})
    with clinic["app"].app_context():
        assert EmergencyVisit.query.count() == 0
        assert not clinic["db"].session.get(Visit, clinic["ids"]["visit"]).is_referred
    _send(clinic)
    with clinic["app"].app_context():
        er.triage(EmergencyVisit.query.one(), level="أحمر", urgent=True)
        clinic["db"].session.commit()
    clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/refer", data={"undo": "1"})
    with clinic["app"].app_context():
        assert EmergencyVisit.query.count() == 1
        assert clinic["db"].session.get(Visit, clinic["ids"]["visit"]).is_referred
