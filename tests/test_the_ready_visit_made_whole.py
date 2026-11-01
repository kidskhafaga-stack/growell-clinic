"""الكشف الجاهز كامل (DOCTOR_EASE_PLAN.md ب-١، الجزء اللي كان «لسه»).

صاحب العيادة اختار يكمّله: الكشف الجاهز يشيل كمان **التحاليل، وتعليمات
الأهل، وميعاد المتابعة بعد كام يوم، وقالب لوح التخصص**.

* بيتحفظ من الكشف نفسه «ومعاه التحاليل والمتابعة وتعليمات الأهل» — من اللي
  في الزيارة: التحاليل اللي من القايمة، والمتابعة بالأيام من تاريخ الكشف؛
* بيتعدّل من «الكشوف الجاهزة»؛
* في الكشف بيتعرض بعلامات صح، و**مفيش حاجة بتتطلب إلا مع «حفظ»**: التحليل
  اللي مطلوب في الزيارة خلاص ما بيتطلبش تاني، والمتابعة وتعليمات الأهل
  بيتكتبوا بس لو فاضيين — عمره ما بيكتب فوق كلام الدكتور؛
* اللي اتشالت علامته ما بيتطلبش.
"""
import html
import json
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import desk  # noqa: E402,F401


def _tests(desk):
    from app.models import Investigation

    with desk["app"].app_context():
        rows = [Investigation(name_ar="صورة دم كاملة", name_en="CBC", kind="lab", is_active=True),
                Investigation(name_ar="CRP", kind="lab", is_active=True),
                Investigation(name_ar="قديم متوقف", kind="lab", is_active=False)]
        desk["db"].session.add_all(rows)
        desk["db"].session.commit()
        return [r.id for r in rows]


def _cfg(page):
    raw = re.search(r'<script type="application/json" id="visitCfg">(.*?)</script>', page, re.S)
    return json.loads(html.unescape(raw.group(1)))


def _template(desk, **rest):
    from app.models import User
    from app.utils import visit_templates

    with desk["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        row = visit_templates.save(boss, "التهاب حلق", "ألم في الزور", "", "", rest=rest)
        desk["db"].session.commit()
        return row.id


def test_saved_from_the_visit_with_its_tests_follow_up_and_words(desk):
    from app.models import Visit, VisitInvestigation, VisitTemplate

    cbc, crp, _ = _tests(desk)
    db = desk["db"]
    with desk["app"].app_context():
        v = db.session.get(Visit, desk["ids"]["visit"])
        v.followup_due = v.visit_date + timedelta(days=3)
        v.followup_instructions = "سوائل كتير، ولو الحرارة فوق ٣٩ ارجعوا"
        db.session.add(VisitInvestigation(visit_id=v.id, patient_id=v.patient_id,
                                          investigation_id=cbc, kind="lab", name="صورة دم كاملة"))
        db.session.add(VisitInvestigation(visit_id=v.id, patient_id=v.patient_id,
                                          kind="lab", name="مكتوب بإيد"))
        db.session.commit()
    boss = desk["sign_in"]("boss")
    r = boss.post("/visits/visit-templates", content_type="application/json", data=json.dumps({
        "name": "التهاب حلق", "cc": "ألم في الزور", "with_rest": True,
        "visit_id": desk["ids"]["visit"]}))
    t = r.get_json()["template"]
    assert [x["id"] for x in t["tests"]] == [cbc], "the catalogue's tests, not a typed name"
    assert (t["days"], t["family"]) == (3, "سوائل كتير، ولو الحرارة فوق ٣٩ ارجعوا")
    # Without the box ticked, only the three boxes are kept.
    boss.post("/visits/visit-templates", content_type="application/json", data=json.dumps({
        "name": "بس الكلام", "cc": "كحة", "with_rest": False, "visit_id": desk["ids"]["visit"]}))
    with desk["app"].app_context():
        bare = VisitTemplate.query.filter_by(name="بس الكلام").one()
        assert (bare.tests, bare.followup_days, bare.family_instructions) == (None, None, None)


def test_offered_on_the_visit_and_added_only_with_save(desk):
    from app.models import Visit, VisitInvestigation

    cbc, crp, stopped = _tests(desk)
    tid = _template(desk, tests=[cbc, crp, stopped], days=5, family="اشرب سوايل")
    page = desk["sign_in"]("boss").get(desk["url"]).get_data(as_text=True)
    offered = next(x for x in _cfg(page)["visitTpls"] if x["id"] == tid)
    assert [x["id"] for x in offered["tests"]] == [cbc, crp], "a stopped test is not offered"
    assert (offered["days"], offered["family"]) == (5, "اشرب سوايل")
    assert "data-vt-rest-box" in page
    with desk["app"].app_context():
        assert VisitInvestigation.query.filter_by(visit_id=desk["ids"]["visit"]).count() == 0, \
            "nothing ordered by showing it"

    # The doctor keeps CBC ticked and unticks CRP, and saves.
    r = desk["sign_in"]("boss").post(desk["url"], data={
        "chief_complaint": "ألم في الزور", "visit_templates_used": str(tid),
        "vt_test": [str(cbc)], "vt_days": "5", "vt_family": "اشرب سوايل"}, follow_redirects=True)
    assert r.status_code == 200
    with desk["app"].app_context():
        v = desk["db"].session.get(Visit, desk["ids"]["visit"])
        ordered = VisitInvestigation.query.filter_by(visit_id=v.id).all()
        assert [x.investigation_id for x in ordered] == [cbc]
        assert ordered[0].ordered_by is not None and ordered[0].name == "صورة دم كاملة"
        assert v.followup_due == v.visit_date + timedelta(days=5)
        assert v.followup_instructions == "اشرب سوايل"

    # Saved again: the test is not ordered twice, and what is there stays.
    desk["sign_in"]("boss").post(desk["url"], data={
        "chief_complaint": "ألم في الزور", "vt_test": [str(cbc)], "vt_days": "10",
        "vt_family": "كلام تاني"})
    with desk["app"].app_context():
        v = desk["db"].session.get(Visit, desk["ids"]["visit"])
        assert VisitInvestigation.query.filter_by(visit_id=v.id).count() == 1
        assert v.followup_due == v.visit_date + timedelta(days=5)
        assert v.followup_instructions == "اشرب سوايل", "never over the doctor's words"


def test_a_plain_save_touches_nothing(desk):
    from app.models import Visit, VisitInvestigation

    desk["sign_in"]("boss").post(desk["url"], data={"chief_complaint": "متابعة"})
    with desk["app"].app_context():
        v = desk["db"].session.get(Visit, desk["ids"]["visit"])
        assert v.followup_due is None and v.followup_instructions is None
        assert VisitInvestigation.query.filter_by(visit_id=v.id).count() == 0


def test_edited_on_the_ready_visits_screen(desk):
    from app.models import PanelTemplate, User, VisitTemplate

    cbc, crp, _ = _tests(desk)
    tid = _template(desk)
    with desk["app"].app_context():
        boss = User.query.filter_by(username="boss").one()
        other = User.query.filter_by(username="doc").one()
        mine = PanelTemplate(doctor_id=boss.id, panel_key="cardiology", name="قلب سليم", values="{}")
        private = PanelTemplate(doctor_id=other.id, panel_key="cardiology", name="بتاعه", values="{}")
        desk["db"].session.add_all([mine, private])
        desk["db"].session.commit()
        mine_id, private_id = mine.id, private.id
    boss = desk["sign_in"]("boss")
    page = boss.get("/visits/visit-templates/mine").get_data(as_text=True)
    for mark in ("data-vt-tests", "data-vt-family", "data-vt-days", "data-vt-panel"):
        assert mark in page
    boss.post("/visits/visit-templates/mine", data={
        "id": tid, "action": "save", "name": "التهاب حلق", "cc": "ألم في الزور",
        "tests": [str(crp), "999"], "family": "غرغرة بمية وملح", "days": "400",
        "panel_tpl": str(private_id)})
    with desk["app"].app_context():
        row = desk["db"].session.get(VisitTemplate, tid)
        assert row.test_ids == [crp] and row.family_instructions == "غرغرة بمية وملح"
        assert row.followup_days is None, "more than a year is not a follow-up"
        assert row.panel_template_id is None, "another doctor's private template"
    boss.post("/visits/visit-templates/mine", data={
        "id": tid, "action": "save", "name": "التهاب حلق", "cc": "ألم في الزور",
        "days": "7", "panel_tpl": str(mine_id)})
    with desk["app"].app_context():
        row = desk["db"].session.get(VisitTemplate, tid)
        assert (row.followup_days, row.panel_template_id, row.test_ids) == (7, mine_id, [])


def test_a_template_of_only_the_rest_is_a_template(desk):
    """Tests and a follow-up with no words in the boxes still make a ready
    visit — «متابعة تحاليل الأنيميا» is exactly that."""
    from app.models import VisitTemplate

    cbc, _, _ = _tests(desk)
    tid = _template(desk, tests=[cbc], days=30)
    with desk["app"].app_context():
        row = desk["db"].session.get(VisitTemplate, tid)
        assert row.test_ids == [cbc] and row.followup_days == 30
