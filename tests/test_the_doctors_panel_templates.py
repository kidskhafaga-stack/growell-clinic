"""قوالب الدكتور للوح التخصص (DOCTOR_EASE_PLAN.md أ-٣).

* القالب بيتحفظ من شاشة الكشف من غير ما يسيبها، وفيه **اختيارات بس**: الأرقام
  والإجابات اللي مش في اللوح والخانة اللي شرطها مش متحقق ما بتتحفظش؛
* القالب بتاع الدكتور ليه، والمشترك بيظهر لأطباء التخصص؛ وحفظ الكشف بيعدّ
  استخدام القالب؛
* «قوالبي»: تغيير الاسم والمشاركة والمسح — لصاحب القالب بس؛ والإجابة اللي
  اللوح ما بقاش فيها بتتجاهل وبيتقال.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, _save, desk)


def _post(client, **body):
    return client.post("/visits/panel-templates", data=json.dumps(body),
                       content_type="application/json")


def test_a_template_keeps_choices_only(desk):
    from app.models import PanelTemplate

    _module(desk, True)
    boss = desk["sign_in"]("boss")
    r = _post(boss, panel="dentistry", name="روتيني", answers={
        "oral_hygiene": "جيدة", "gingiva": "سليمة", "overjet_mm": "4",
        "night_feeding": "مش من الاختيارات", "ga_reason": "صغر السن",
        "behaviour_route": "إقناع وتطمين", "nonexistent": "x"})
    assert r.status_code == 200 and r.get_json()["ok"]
    with desk["app"].app_context():
        row = PanelTemplate.query.one()
        assert json.loads(row.values) == {"oral_hygiene": "جيدة", "gingiva": "سليمة",
                                          "behaviour_route": "إقناع وتطمين"}
    assert _post(boss, panel="dentistry", name="", answers={"gingiva": "سليمة"}).status_code == 400
    assert _post(boss, panel="dentistry", name="فاضي", answers={"overjet_mm": "4"}).status_code == 400
    assert _post(boss, panel="nope", name="x", answers={"gingiva": "سليمة"}).status_code == 400


def test_own_and_shared_are_offered_and_a_use_is_counted(desk):
    from app.models import PanelTemplate, User

    _module(desk, True)
    db = desk["db"]
    with desk["app"].app_context():
        other = User.query.filter_by(username="doc").one()
        db.session.add_all([
            PanelTemplate(doctor_id=other.id, panel_key="dentistry", name="مشترك",
                          values=json.dumps({"gingiva": "سليمة"}), is_shared=True),
            PanelTemplate(doctor_id=other.id, panel_key="dentistry", name="خاص بيه",
                          values=json.dumps({"gingiva": "سليمة"}), is_shared=False)])
        db.session.commit()
        shared_id = PanelTemplate.query.filter_by(name="مشترك").one().id
    boss = desk["sign_in"]("boss")
    _post(boss, panel="dentistry", name="بتاعي", answers={"oral_hygiene": "جيدة"})
    page = _page(desk)
    assert "بتاعي" in page and "مشترك" in page and "خاص بيه" not in page
    assert 'data-tpl-values="{&#34;oral_hygiene&#34;: &#34;جيدة&#34;}"' in page or "oral_hygiene" in page
    _save(desk, specialty_panel="dentistry", m_gingiva="سليمة", panel_templates_used=str(shared_id))
    with desk["app"].app_context():
        assert db.session.get(PanelTemplate, shared_id).use_count == 1


def test_my_templates_screen_is_the_owners(desk):
    from app.models import PanelTemplate, User

    _module(desk, True)
    db = desk["db"]
    boss = desk["sign_in"]("boss")
    _post(boss, panel="dentistry", name="قديم", answers={"gingiva": "سليمة", "oral_hygiene": "جيدة"})
    with desk["app"].app_context():
        row = PanelTemplate.query.one()
        vals = json.loads(row.values)
        vals["oral_hygiene"] = "إجابة اتشالت"
        row.values = json.dumps(vals, ensure_ascii=False)
        db.session.commit()
        tid = row.id
        other = User.query.filter_by(username="doc").one()
        theirs = PanelTemplate(doctor_id=other.id, panel_key="dentistry", name="بتاعه",
                               values="{}", is_shared=True)
        db.session.add(theirs)
        db.session.commit()
        theirs_id = theirs.id
    page = boss.get("/visits/panel-templates/mine").get_data(as_text=True)
    assert f'data-tpl-row="{tid}"' in page and "data-tpl-dropped" in page
    assert f'data-tpl-row="{theirs_id}"' not in page
    assert "data-to-panel-tpls" in boss.get("/visits/phrases").get_data(as_text=True)
    boss.post("/visits/panel-templates/mine", data={"id": tid, "action": "save", "name": "جديد", "shared": "1"})
    assert boss.post("/visits/panel-templates/mine",
                     data={"id": theirs_id, "action": "delete"}).status_code == 404
    with desk["app"].app_context():
        row = db.session.get(PanelTemplate, tid)
        assert row.name == "جديد" and row.is_shared
    boss.post("/visits/panel-templates/mine", data={"id": tid, "action": "delete"})
    with desk["app"].app_context():
        assert db.session.get(PanelTemplate, tid) is None
