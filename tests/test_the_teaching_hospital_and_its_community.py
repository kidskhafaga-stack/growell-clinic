"""المستشفى التعليمي ومجتمعه — GAHAR `ATH` و`CAI`.

* **التعليم موديول اختياري**: العيادة اللي ما بتعلّمش ما بتشوفش الشاشة ولا
  موافقة التعليم والبحث ولا لجانهم؛
* **المتدرّب بمشرفه وحدود شغله**، ومحدّش يشرف على نفسه أو يقيّم نفسه،
  والتوجيه بند بند، والدورة اللي خلصت من غير تقييم بتبان؛
* **ما فيش طفل في بحث** من غير بروتوكول موافق عليه وساري، ومن غير موافقة
  البحث الموقّعة في ملف الطفل بعد موافقة اللجنة؛ والانسحاب من غير سبب؛
  ومشكلة السلامة بإمتى الأهل اتبلّغوا واللي اتعمل؛
* **المجتمع**: تقييم الاحتياجات بالخمسة ومع شريك، والجاي بعد سنتين، والرضا
  ما يزيدش عن اللي اتسألوا، والإعلان المش مطابق ما يتنشرش.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def school(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:teaching", "1")
        clinic["db"].session.commit()
    return clinic


def test_a_clinic_that_teaches_nobody_sees_nothing_new(clinic):
    from app.utils import consent as cs
    from app.utils import governance as gov

    boss = clinic["sign_in"]()
    assert boss.get("/teaching/").status_code in (302, 403, 404)
    with clinic["app"].app_context():
        assert "research" not in cs.kinds_offered() and "teaching" not in cs.kinds_offered()
        assert "education" not in [r["key"] for r in gov.committees()]
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert 'value="photography"' in page and 'value="research"' not in page


def test_a_trainee_has_a_supervisor_and_nobody_marks_their_own_work(school):
    from app.models import Trainee, TraineeAssessment
    from app.utils import teaching as teach

    boss, today = school["sign_in"](), local_today()
    doctor = school["ids"]["doctor"]
    form = {"kind": "resident", "user_id": str(doctor), "scope": "يكتب الأوامر بإمضاء المشرف",
            "starts_on": today.isoformat()}
    boss.post("/teaching/trainee", data=form)
    with school["app"].app_context():
        assert Trainee.query.count() == 0, "no supervisor"
    boss.post("/teaching/trainee", data={**form, "supervisor_id": str(doctor)})
    with school["app"].app_context():
        assert Trainee.query.count() == 0, "their own supervisor"
        boss_id = __import__("app.models", fromlist=["User"]).User.query.filter_by(username="boss").one().id
    res = boss.post("/teaching/trainee", data={**form, "supervisor_id": str(boss_id)})
    with school["app"].app_context():
        tr = Trainee.query.one()
        assert f"/teaching/trainee/{tr.id}" in res.headers["Location"]
        assert len(teach.orientation_missing(tr)) == 7
        tid = tr.id
    boss.post(f"/teaching/trainee/{tid}/orient", data={"items": ["policies", "supervision"], "on": today.isoformat()})
    boss.post(f"/teaching/trainee/{tid}/rotation", data={"department": "الحضّانة", "supervisor_id": str(boss_id),
                                                         "starts_on": (today - timedelta(days=40)).isoformat(),
                                                         "ends_on": (today - timedelta(days=10)).isoformat()})
    with school["app"].app_context():
        tr = Trainee.query.one()
        assert len(teach.orientation_missing(tr)) == 5
        assert len(teach.trainees_board()["unevaluated"]) == 1
    doc = school["sign_in"]("doc")
    doc.post(f"/teaching/trainee/{tid}/assess", data={"tool": "mini_cex", "on": today.isoformat(), "result": "مرضي"})
    boss.post(f"/teaching/trainee/{tid}/assess", data={"tool": "mini_cex", "on": today.isoformat(), "result": "مرضي"})
    with school["app"].app_context():
        rows = TraineeAssessment.query.all()
        assert [r.assessor_id for r in rows] == [boss_id], "the trainee did not assess themselves"
    page = boss.get(f"/teaching/trainee/{tid}").get_data(as_text=True)
    assert 'data-rotation-unevaluated' in page and 'data-orientation-gap="didactic"' in page


def test_no_child_in_a_study_without_approval_and_signed_consent(school):
    from app.models import Patient, ResearchParticipant, ResearchProtocol
    from app.utils import consent as cs

    boss, today = school["sign_in"](), local_today()
    pid = school["ids"]["child"]
    boss.post("/teaching/research", data={"title": "فيتامين د في الرضّع", "investigator_id": str(school["ids"]["doctor"]),
                                          "eligibility": "رضّع من ٢ لـ ٦ شهور"})
    with school["app"].app_context():
        prid = ResearchProtocol.query.one().id
    page = boss.get(f"/teaching/protocol/{prid}").get_data(as_text=True)
    assert "data-enrol-closed" in page
    doc = school["sign_in"]("doc")
    assert doc.post(f"/teaching/protocol/{prid}/decide", data={"state": "approved"}).status_code == 403
    boss.post(f"/teaching/protocol/{prid}/decide", data={"state": "approved", "approved_on": today.isoformat()})
    with school["app"].app_context():
        assert ResearchProtocol.query.one().state == "submitted", "an approval needs its number"
    boss.post(f"/teaching/protocol/{prid}/decide", data={"state": "approved", "rec_reference": "REC-2026-14",
                                                        "approved_on": today.isoformat()})
    boss.post(f"/teaching/protocol/{prid}/enroll", data={"patient_id": pid, "enrolled_on": today.isoformat()})
    with school["app"].app_context():
        assert ResearchParticipant.query.count() == 0, "no research consent"
        assert "research" in cs.kinds_offered()
        child = school["db"].session.get(Patient, pid)
        general = cs.record(child, "general", "الأم")
        school["db"].session.commit()
        gid = general.id
    boss.post(f"/teaching/protocol/{prid}/enroll", data={"patient_id": pid, "consent_id": gid,
                                                        "enrolled_on": today.isoformat()})
    with school["app"].app_context():
        assert ResearchParticipant.query.count() == 0, "a general consent is not a research consent"
        rc = cs.record(school["db"].session.get(Patient, pid), "research", "الأم")
        school["db"].session.commit()
        rid = rc.id
        assert "لجنة أخلاقيات البحث" in rc.statement
    page = boss.get(f"/teaching/protocol/{prid}?patient_id={pid}").get_data(as_text=True)
    assert "data-enroll" in page
    boss.post(f"/teaching/protocol/{prid}/enroll", data={"patient_id": pid, "consent_id": rid,
                                                        "enrolled_on": today.isoformat()})
    with school["app"].app_context():
        part = ResearchParticipant.query.one()
        assert part.consent_id == rid
        partid = part.id
    boss.post(f"/teaching/participant/{partid}/safety", data={"on": today.isoformat(), "what": "طفح جلدي",
                                                             "action": "إيقاف الجرعة"})
    boss.post(f"/teaching/participant/{partid}/safety", data={"on": today.isoformat(), "what": "طفح جلدي",
                                                             "action": "إيقاف الجرعة",
                                                             "family_told_on": today.isoformat()})
    boss.post(f"/teaching/participant/{partid}/withdraw", data={"withdrawn_on": today.isoformat()})
    with school["app"].app_context():
        part = ResearchParticipant.query.one()
        assert len(part.events) == 1 and part.withdrawn_on == today and part.withdrawn_note is None


def test_a_lapsed_approval_closes_enrolment_and_is_said(school):
    from app.models import ResearchProtocol
    from app.utils import teaching as teach

    boss, today = school["sign_in"](), local_today()
    boss.post("/teaching/research", data={"title": "دراسة", "investigator_id": str(school["ids"]["doctor"]),
                                          "eligibility": "كل الأطفال"})
    with school["app"].app_context():
        p = ResearchProtocol.query.one()
        p.state, p.rec_reference = "approved", "REC-1"
        p.approved_on, p.valid_until = today - timedelta(days=400), today - timedelta(days=1)
        school["db"].session.commit()
        assert not teach.open_for_enrolment(p)


def test_a_learner_s_concern_stays_open_until_acted_on(school):
    from app.models import TeachingConcern

    boss, today = school["sign_in"](), local_today().isoformat()
    boss.post("/teaching/concerns", data={"kind": "safety", "raised_on": today, "concern": "دوا اتدّى من غير مراجعة"})
    with school["app"].app_context():
        cid = TeachingConcern.query.one().id
    boss.post(f"/teaching/concern/{cid}", data={"closed_on": today})
    with school["app"].app_context():
        assert TeachingConcern.query.one().closed_on is None
    boss.post(f"/teaching/concern/{cid}", data={"action": "تدريب على مراجعة الأوامر", "closed_on": today})
    with school["app"].app_context():
        assert TeachingConcern.query.one().closed_on is not None
    assert "data-concerns-open=\"0\"" in boss.get("/teaching/").get_data(as_text=True)


def test_the_community_needs_every_two_years_and_honest_ads(clinic):
    from app.models import Advertisement, CommunityActivity, CommunityPartner, NeedsAssessment
    from app.utils import community as cm
    from app.utils.preparedness import add_months

    boss, today = clinic["sign_in"](), local_today().isoformat()
    assert boss.get("/quality/community").status_code == 200
    assert clinic["sign_in"]("doc").get("/quality/community").status_code == 403
    boss.post("/quality/community/partner", data={"name": "مديرية الصحة", "kind": "health_authority",
                                                  "channel": "اجتماع شهري"})
    with clinic["app"].app_context():
        assert cm.next_assessment()["overdue"]
        partner = CommunityPartner.query.one().id
    form = {"done_on": today, "partners": [str(partner)], "population": "أطفال الحي", "sources": "استبيان وتعداد",
            "services_plan": "عيادة تطعيمات مسائية", "need_access": "المواعيد الصبح بس", "need_hazards": "مصرف مكشوف",
            "need_unmet": "متابعة سكر الأطفال", "need_education": "الرضاعة", "need_expectations": "مواعيد مسائية"}
    boss.post("/quality/community/assessment", data={**form, "need_hazards": ""})
    with clinic["app"].app_context():
        assert NeedsAssessment.query.count() == 0, "all five needs"
    boss.post("/quality/community/assessment", data=form)
    with clinic["app"].app_context():
        nxt = cm.next_assessment()
        assert not nxt["overdue"] and nxt["due"] == add_months(local_today(), 24)
        assert len(cm.board()["unshared"]) == 1
    boss.post("/quality/community/activity", data={"held_on": today, "kind": "initiative", "title": "يوم تطعيم",
                                                   "initiative": "مبادرة الرعاية الوطنية", "need": "التطعيمات",
                                                   "surveyed": "10", "satisfied": "12"})
    with clinic["app"].app_context():
        assert CommunityActivity.query.count() == 0, "more satisfied than asked"
    boss.post("/quality/community/activity", data={"held_on": today, "kind": "initiative", "title": "يوم تطعيم",
                                                   "initiative": "مبادرة الرعاية الوطنية", "need": "التطعيمات",
                                                   "surveyed": "10", "satisfied": "8"})
    with clinic["app"].app_context():
        assert cm.activities_board()["rate"] == 80
    ad = {"title": "أحسن دكاترة في مصر", "channel": "فيسبوك", "content": "…", "reviewed_by": "مدير الجودة",
          "reviewed_on": today, "compliant": "no", "published_on": today, "action": "اتعدّل النص"}
    boss.post("/quality/community/ad", data=ad)
    with clinic["app"].app_context():
        assert Advertisement.query.count() == 0, "a non-compliant ad is not published"
    boss.post("/quality/community/ad", data={**ad, "published_on": ""})
    with clinic["app"].app_context():
        assert Advertisement.query.one().compliant is False
