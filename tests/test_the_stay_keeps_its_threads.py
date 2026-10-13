"""خيوط الإقامة — GAHAR ICD.06، ICD.08، ACT.11، ACT.14، PCC.05، PCC.14.

* **التقييم الطبي الأولي** بيتجمّع من الملف، والطبيب بيكتب الناقص بس،
  والحساسية والتاريخ المرضي بيروحوا لملف الطفل مش للإقامة؛ و٢٤ ساعة رقم
  المعيار نفسه.
* **فرز الاحتياجات**: الأربعة بمعايير المستشفى، والإيجابي محتاج تحويل،
  والخدمة بتكتب اللي لقته.
* **اجتماع الفريق، والإجازة المؤقتة، وأسئلة الأهل، والأمانات** — كل واحد
  بحاجته الوحيدة اللي بتخلّيه مفتوح، والأوقات أرقام المستشفى.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def _stamp(dt):
    from app.utils.clock import to_local

    return to_local(dt).strftime("%Y-%m-%dT%H:%M")


def test_initial_medical_assessment_reads_the_record_and_asks_the_rest(ward):
    from app.models import MedicalAssessment, Patient
    from app.models.admission import Admission
    from app.utils import medical_assessment as medass

    pid = _child(ward, "سلمى")
    stay = _admit(ward, pid)
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        row.reason = "حرارة وتشنج"
        ward["db"].session.get(Patient, pid).allergies = "بنسلين"
        ward["db"].session.commit()
        known = medass.assembled(row)
        assert known["complaint"] == ("admission", "حرارة وتشنج")
        assert known["allergies"][0] == "file"
        assert "family" in medass.missing(row, known)
        # Admitted a day ago, nothing written — past the standard's 24 hours.
        assert medass.clock(row)["state"] == "overdue"
    boss = ward["sign_in"]("boss")
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-medical-gap="family"' in page and 'data-medical-gap="allergies"' not in page
    assert "'medical-initial': 'overview'" in page and "data-medical-overdue" in page
    boss.post(f"/beds/admission/{stay}/medical-initial", data={})
    with ward["app"].app_context():
        assert MedicalAssessment.query.count() == 0
    boss.post(f"/beds/admission/{stay}/medical-initial",
              data={"family": "أخ عنده صرع", "past_history": "ربو", "exam": "واعي، رقبة لينة",
                    "allergies": "لا تكتب فوق الموجود"})
    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        child = ward["db"].session.get(Patient, pid)
        assert child.chronic_diseases == "ربو", "past history goes to the child's file"
        assert child.allergies == "بنسلين", "an allergy already on file is not overwritten"
        assert MedicalAssessment.query.one().family == "أخ عنده صرع"
        assert medass.clock(row)["state"] == "late"


def test_needs_screen_by_the_hospital_criteria_then_referral_then_the_service(ward):
    from app.models import NeedsScreen
    from app.models.admission import Admission
    from app.utils import needs_screen

    stay = _admit(ward, _child(ward, "يوسف"))
    boss = ward["sign_in"]("boss")
    boss.post("/beds/needs/criteria", data={"abuse": "كدمات بأشكال مختلفة الأعمار", "hours": "12"})
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "كدمات بأشكال مختلفة الأعمار" in page and "needs: 'care'" in page
    assert "data-needs-late" in page, "admitted a day ago, the hospital said 12 hours"
    boss.post(f"/beds/admission/{stay}/needs", data={})
    with ward["app"].app_context():
        assert NeedsScreen.query.count() == 0
    boss.post(f"/beds/admission/{stay}/needs",
              data={"functional": "negative", "psychosocial": "negative", "discharge": "negative",
                    "abuse": "positive", "abuse_note": "كدمات على الضهر"})
    with ward["app"].app_context():
        row = NeedsScreen.query.filter_by(kind="abuse").one()
        state = needs_screen.for_stay(ward["db"].session.get(Admission, stay))
        assert not state["late"] and [r.id for r in state["to_refer"]] == [row.id]
        rid = row.id
    boss.post(f"/beds/needs/{rid}/seen", data={"seen_note": "اتشاف"})
    with ward["app"].app_context():
        assert ward["db"].session.get(NeedsScreen, rid).seen_at is None, "not referred yet"
    boss.post(f"/beds/needs/{rid}/refer", data={"referred_to": "لجنة حماية الطفل"})
    boss.post(f"/beds/needs/{rid}/seen", data={"seen_note": "اتقيّم والأهل اتكلموا مع الأخصائية"})
    with ward["app"].app_context():
        row = ward["db"].session.get(NeedsScreen, rid)
        assert row.referred_to == "لجنة حماية الطفل" and row.seen_at is not None
    # The criteria are an administrator's to write.
    ward["sign_in"]("doc").post("/beds/needs/criteria", data={"abuse": "غيره"})
    with ward["app"].app_context():
        assert needs_screen.criteria()["abuse"] == "كدمات بأشكال مختلفة الأعمار"


def test_mdt_leave_questions_and_belongings_on_the_stay(ward):
    from app.models import Belonging, FamilyQuestion, MdtMeeting, StayLeave

    stay = _admit(ward, _child(ward, "نور"))
    boss = ward["sign_in"]("boss")
    with ward["app"].app_context():
        doctor = ward["ids"]["doctor"]

    boss.post(f"/beds/admission/{stay}/mdt", data={"reason": "ورم", "attendees": "أورام، جراحة"})
    boss.post(f"/beds/admission/{stay}/mdt",
              data={"reason": "ورم بالبطن", "attendees": "أورام، جراحة، أشعة", "findings": "كتلة ٥ سم",
                    "decision": "عينة ثم كيماوي", "responsibilities": "الجراحة: العينة",
                    "family_present": "yes"})
    with ward["app"].app_context():
        m = MdtMeeting.query.one()
        assert m.decision == "عينة ثم كيماوي" and m.family_present is True

    now = datetime.utcnow()
    boss.post(f"/beds/admission/{stay}/leave", data={"reason": "مناسبة عائلية",
                                                    "back_by": _stamp(now + timedelta(hours=6))})
    with ward["app"].app_context():
        assert StayLeave.query.count() == 0, "a leave needs the doctor who ordered it"
    boss.post(f"/beds/admission/{stay}/leave",
              data={"reason": "مناسبة عائلية", "ordered_by": doctor,
                    "out_at": _stamp(now - timedelta(hours=8)), "back_by": _stamp(now - timedelta(hours=2)),
                    "instructions": "الدوا الساعة ٦"})
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-leave-late" in page
    boss.post(f"/beds/admission/{stay}/leave", data={"reason": "تاني", "ordered_by": doctor,
                                                    "back_by": _stamp(now + timedelta(hours=3))})
    with ward["app"].app_context():
        assert StayLeave.query.count() == 1, "one open leave at a time"
        lid = StayLeave.query.one().id
    boss.post(f"/beds/leave/{lid}/back", data={"return_note": "رجع كويس"})
    with ward["app"].app_context():
        assert ward["db"].session.get(StayLeave, lid).returned_at is not None

    boss.post(f"/beds/admission/{stay}/question", data={"question": "الأشعة طلعت إيه؟", "asked_by": "الأم"})
    with ward["app"].app_context():
        q = FamilyQuestion.query.one()
        assert q.is_open and q.for_whom == "doctor"
        qid = q.id
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-q-open" in page and "data-q-late" not in page, "no time set, nothing is late"
    boss.post("/beds/question-hours", data={"hours": "1", "admission_id": stay})
    with ward["app"].app_context():
        q = ward["db"].session.get(FamilyQuestion, qid)
        q.asked_at = datetime.utcnow() - timedelta(hours=3)
        ward["db"].session.commit()
    assert "data-q-late" in boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    ward["sign_in"]("doc").post(f"/beds/question/{qid}/answer", data={"answer": "سليمة"})
    with ward["app"].app_context():
        assert ward["db"].session.get(FamilyQuestion, qid).answer == "سليمة"

    boss.post(f"/beds/admission/{stay}/belongings", data={"items": "موبايل وسلسلة"})
    boss.post(f"/beds/admission/{stay}/belongings",
              data={"items": "موبايل وسلسلة", "kept_where": "خزنة التمريض", "family_told": "1"})
    with ward["app"].app_context():
        b = Belonging.query.one()
        assert b.family_told and b.returned_at is None
        bid = b.id
    assert "موبايل وسلسلة" in boss.get("/beds/lost-found").get_data(as_text=True)
    boss.post(f"/beds/belongings/{bid}/returned", data={"returned_to": "الأب"})
    with ward["app"].app_context():
        assert ward["db"].session.get(Belonging, bid).returned_to == "الأب"
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    for anchor in ("mdt: 'treatment'", "leave: 'overview'", "'family-questions': 'overview'",
                   "belongings: 'overview'"):
        assert anchor in page


def test_lost_and_found_waits_the_hospitals_days(ward):
    from app.models import LostItem

    boss = ward["sign_in"]("boss")
    assert "data-to-lost-found" in boss.get("/beds/").get_data(as_text=True)
    boss.post("/beds/lost-found", data={"found_where": "صالة الانتظار", "description": "نضارة",
                                        "kept_where": "الأمن"})
    with ward["app"].app_context():
        rid = LostItem.query.one().id
    boss.post(f"/beds/lost/{rid}/closed", data={"closed_note": "اتبرّع بيها"})
    with ward["app"].app_context():
        assert ward["db"].session.get(LostItem, rid).closed_at is None, "no waiting time written"
    boss.post("/beds/lost-found", data={"what": "days", "days": "30"})
    boss.post(f"/beds/lost/{rid}/closed", data={"closed_note": "اتبرّع بيها"})
    with ward["app"].app_context():
        assert ward["db"].session.get(LostItem, rid).closed_at is None, "thirty days have not passed"
        ward["db"].session.get(LostItem, rid).found_at = datetime.utcnow() - timedelta(days=31)
        ward["db"].session.commit()
    assert "data-lost-past" in boss.get("/beds/lost-found").get_data(as_text=True)
    boss.post(f"/beds/lost/{rid}/closed", data={"closed_note": "اتسلّمت للإدارة"})
    with ward["app"].app_context():
        assert ward["db"].session.get(LostItem, rid).closed_at is not None
