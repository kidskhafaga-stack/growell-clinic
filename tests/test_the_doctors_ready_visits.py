"""الكشف الجاهز لكل شكوى (DOCTOR_EASE_PLAN.md ب-١).

* الدكتور بيحفظ الشكوى والفحص والخطة من شاشة الكشف من غير ما يسيبها، ومعاها
  روشتة جاهزة لو حب؛ الكشف الجاهز من غير اسم أو فاضي ما بيتحفظش؛
* بتاعه بيظهر له، والمشترك بيظهر لكل الأطباء، والخاص بتاع غيره لأ؛ وحفظ الكشف
  بيعدّ استخدامه؛
* الروشتة المربوطة بتتفتح جاهزة في شاشة الروشتة؛ والروشتة اللي مش من حقه
  ما بتتربطش؛
* «الكشوف الجاهزة»: التعديل والمشاركة والمسح لصاحبه بس.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _page, _save, desk)


def _post(client, **body):
    return client.post("/visits/visit-templates", data=json.dumps(body),
                       content_type="application/json")


def _offered(page):
    """The ready visits the visit screen offers, read from its config."""
    import html
    import re

    raw = re.search(r'<script type="application/json" id="visitCfg">(.*?)</script>', page, re.S)
    return [v["name"] for v in json.loads(html.unescape(raw.group(1)))["visitTpls"]]


def _preset(desk, owner="boss", shared=False, name="روشتة حلق"):
    from app.models import RxPreset, User

    with desk["app"].app_context():
        user = User.query.filter_by(username=owner).one()
        row = RxPreset(name=name, doctor_id=user.id, is_shared=shared)
        desk["db"].session.add(row)
        desk["db"].session.commit()
        return row.id


def test_a_ready_visit_is_saved_from_the_visit_screen(desk):
    from app.models import VisitTemplate

    mine = _preset(desk)
    private = _preset(desk, owner="doc", name="بتاعة غيري")
    boss = desk["sign_in"]("boss")
    r = _post(boss, name="التهاب حلق", cc="سخونية وألم في الزور", exam="لوز ملتهبة",
              plan="سوائل ومتابعة بعد ٣ أيام", preset=mine)
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] and body["template"]["preset"] == mine
    # Saved again under the same name, it replaces — and a prescription the
    # doctor may not use is not linked.
    _post(boss, name="التهاب حلق", cc="ألم في الزور", preset=private)
    with desk["app"].app_context():
        row = VisitTemplate.query.one()
        assert row.chief_complaint == "ألم في الزور" and row.clinical_exam is None
        assert row.rx_preset_id is None
    assert _post(boss, name="", cc="x").status_code == 400
    assert _post(boss, name="فاضي", cc="  ").status_code == 400


def test_own_and_shared_are_offered_and_a_use_is_counted(desk):
    from app.models import User, VisitTemplate

    db = desk["db"]
    with desk["app"].app_context():
        other = User.query.filter_by(username="doc").one()
        db.session.add_all([
            VisitTemplate(doctor_id=other.id, name="نزلة برد مشتركة", chief_complaint="رشح",
                          is_shared=True),
            VisitTemplate(doctor_id=other.id, name="خاص بيه", chief_complaint="كحة")])
        db.session.commit()
        shared_id = VisitTemplate.query.filter_by(name="نزلة برد مشتركة").one().id
    boss = desk["sign_in"]("boss")
    _post(boss, name="نزلة معوية", cc="إسهال وترجيع", plan="محلول جفاف")
    page = _page(desk)
    assert _offered(page) == ["نزلة معوية", "نزلة برد مشتركة"]
    assert "data-visit-tpls" in page and "data-vt-used" in page and "data-to-visit-tpls" in page
    _save(desk, visit_templates_used=f"{shared_id},999999,abc")
    with desk["app"].app_context():
        assert db.session.get(VisitTemplate, shared_id).use_count == 1


def test_the_linked_prescription_opens_ready(desk):
    mine = _preset(desk)
    theirs = _preset(desk, owner="doc", name="خاصة")
    boss = desk["sign_in"]("boss")
    pid = desk["ids"]["child"]
    page = boss.get(f"/prescriptions/new?patient_id={pid}&preset={mine}").get_data(as_text=True)
    assert f'data-auto-preset="{mine}"' in page and f"applyPreset({mine})" in page
    page = boss.get(f"/prescriptions/new?patient_id={pid}&preset={theirs}").get_data(as_text=True)
    assert 'data-auto-preset=""' in page and f"applyPreset({theirs})" not in page.split("x-init")[1][:400]


def test_the_ready_visits_screen_is_the_owners(desk):
    from app.models import User, VisitTemplate

    db = desk["db"]
    rx = _preset(desk)
    boss = desk["sign_in"]("boss")
    _post(boss, name="قديم", cc="سخونية")
    with desk["app"].app_context():
        tid = VisitTemplate.query.one().id
        other = User.query.filter_by(username="doc").one()
        theirs = VisitTemplate(doctor_id=other.id, name="بتاعه", plan="x", is_shared=True)
        db.session.add(theirs)
        db.session.commit()
        theirs_id = theirs.id
    page = boss.get("/visits/visit-templates/mine").get_data(as_text=True)
    assert f'data-vt-row="{tid}"' in page and f'data-vt-row="{theirs_id}"' not in page
    assert "data-to-visit-tpls" in boss.get("/visits/phrases").get_data(as_text=True)
    boss.post("/visits/visit-templates/mine", data={
        "id": tid, "action": "save", "name": "جديد", "cc": "سخونية", "exam": "زور أحمر",
        "plan": "", "preset": rx, "shared": "1"})
    with desk["app"].app_context():
        row = db.session.get(VisitTemplate, tid)
        assert (row.name, row.clinical_exam, row.rx_preset_id, row.is_shared) == (
            "جديد", "زور أحمر", rx, True)
    # Emptied out, it is refused and left as it was.
    boss.post("/visits/visit-templates/mine", data={"id": tid, "action": "save", "name": "جديد"})
    with desk["app"].app_context():
        assert db.session.get(VisitTemplate, tid).clinical_exam == "زور أحمر"
    assert boss.post("/visits/visit-templates/mine",
                     data={"id": theirs_id, "action": "delete"}).status_code == 404
    boss.post("/visits/visit-templates/mine", data={"id": tid, "action": "delete"})
    with desk["app"].app_context():
        assert db.session.get(VisitTemplate, tid) is None
