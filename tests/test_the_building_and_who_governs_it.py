"""البيئة والمنشأة والحوكمة — GAHAR `EFS` و`OGM`.

* **الجولات:** كل ملاحظة بخطورتها وإجرائها ومسؤولها، وربع من غير جولة بيئة
  بيتقال، والملاحظة بتتقفل بكلمة عن اللي اتعمل، وتقرير الربع للمجلس؛
* **المواد الخطرة:** من غير صحيفة بيانات سلامة أو من غير ملصق بتظهر،
  والنفايات بالفئة والوزن، والحشرات؛
* **الإنشاءات:** كل بند في التقييم بإجرائه، وما فيش «شغّال» من غير تصريح،
  والمقاول المش ملتزم محتاج إجراء؛
* **الطوارئ:** تجربة الكوارث وخطف الطفل بالسيناريو واللي اتشاف والاجتماع
  بعدها، ونص سنة من غير تجربة بيتقال، والتدريب على كل خطة لوحده؛
* **الخطط:** المراجعة بعد ١٢ شهر من الاعتماد (المعيار: «سنوياً»)، والنسخة
  الجديدة بتحل محل القديمة والقديمة بتفضل تاريخ؛ وتفتيش الجهات الخارجية؛
* **اللجان:** كل لجنة مطلوبة ظاهرة حتى لو مش موجودة، والمتأخرة بس قصاد
  الميعاد اللي هي كاتباه، والتقرير الربعي للمجلس ورده؛
* **الأخلاقيات** والقفل محتاج القرار ومين اتبلّغ؛ **التعاقدات والموردين**
  بالتقييم السنوي؛ **صحة العاملين** للإدارة ومكافحة العدوى بس، والنتيجة
  الإيجابية محتاجة الإجراء وإبلاغ الموظف.
"""
import base64
import io
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.clock import local_today  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")


def _boss(c):
    return c["sign_in"]()


def test_every_screen_has_its_door_and_its_lock(clinic):
    boss, doc = _boss(clinic), clinic["sign_in"]("doc")
    index = boss.get("/facility/").get_data(as_text=True)
    for tab in ("rounds", "hazmat", "construction", "preparedness", "plans"):
        assert f'data-facility-tab="{tab}"' in index
        assert boss.get(f"/facility/{tab}").status_code == 200
        assert doc.get(f"/facility/{tab}").status_code == 403
    committee = boss.get("/quality/committee").get_data(as_text=True)
    assert "data-to-committees" in committee and "data-to-staff-health" in committee
    for path in ("/quality/committees", "/quality/ethics", "/quality/contracts", "/quality/staff-health"):
        assert boss.get(path).status_code == 200
        assert doc.get(path).status_code == 403


def test_a_round_writes_its_actions_and_closes_them_in_words(clinic):
    from app.models import RoundFinding, SafetyRound
    from app.utils import safety_program as sp

    boss, today = _boss(clinic), local_today()
    form = {"focus": "environment", "held_on": today.isoformat(), "areas": "الدور الأول والكافيتريا",
            "team": [str(clinic["ids"]["doctor"])], "f_area": ["المطبخ"], "f_finding": ["تسريب جنب لوحة الكهربا"],
            "f_risk": ["high"], "f_action": [""], "f_owner": ["الصيانة"], "f_due": [""]}
    boss.post("/facility/rounds", data=form)
    with clinic["app"].app_context():
        assert SafetyRound.query.count() == 0, "a finding without its action"
        q = (today.month - 1) // 3 + 1
        assert q in sp.rounds_board()["missing_quarters"]
    boss.post("/facility/rounds", data={**form, "f_action": ["فصل الدايرة وإصلاح السقف"]})
    with clinic["app"].app_context():
        board = sp.rounds_board()
        assert q not in board["missing_quarters"] and len(board["open"]) == 1
        fid = RoundFinding.query.one().id
    report = boss.get(f"/facility/rounds/quarter?q={sp.quarter_of(today)}").get_data(as_text=True)
    assert f'data-quarter-finding="{fid}"' in report
    boss.post(f"/facility/finding/{fid}/close", data={})
    with clinic["app"].app_context():
        assert RoundFinding.query.one().closed_at is None
    boss.post(f"/facility/finding/{fid}/close", data={"note": "اتصلّح السقف واتغيّرت اللوحة"})
    with clinic["app"].app_context():
        assert RoundFinding.query.one().closed_note == "اتصلّح السقف واتغيّرت اللوحة"


def test_hazardous_materials_without_their_sheet_are_listed(clinic):
    from app.models import HazardousMaterial, WasteHandover

    boss, today = _boss(clinic), local_today().isoformat()
    boss.post("/facility/hazmat", data={"name": "فورمالين", "hazard": "carcinogenic", "location": "المعمل",
                                        "responsible": "مشرف المعمل"})
    page = boss.get("/facility/hazmat").get_data(as_text=True)
    assert 'data-no-sds="1"' in page and 'data-unlabelled="1"' in page
    with clinic["app"].app_context():
        mid = HazardousMaterial.query.one().id
    boss.post(f"/facility/hazmat/{mid}", data={"name": "فورمالين", "hazard": "carcinogenic",
                                              "location": "المعمل", "responsible": "مشرف المعمل",
                                              "labelled": "1", "sds": (io.BytesIO(PNG), "sds.png")},
              content_type="multipart/form-data")
    with clinic["app"].app_context():
        row = HazardousMaterial.query.one()
        assert row.sds_file and row.labelled and row.sds_reviewed_on == local_today()
    boss.post("/facility/waste", data={"handed_on": today, "category": "sharps", "weight_kg": "3.5"})
    boss.post("/facility/waste", data={"handed_on": today, "category": "sharps", "weight_kg": "3.5",
                                       "carrier": "شركة النقل المرخّصة"})
    with clinic["app"].app_context():
        assert WasteHandover.query.count() == 1
    assert 'data-waste-row="sharps"' in boss.get("/facility/hazmat").get_data(as_text=True)


def test_construction_weighs_every_item_and_waits_for_its_permit(clinic):
    from app.models import ConstructionCheck, ConstructionProject

    boss = _boss(clinic)
    form = {"title": "تجديد العناية", "area": "الدور التاني", "departments": "مكافحة العدوى، السلامة، العناية"}
    for item in ("noise", "vibration", "icra", "air", "fire", "hazmat", "waste"):
        form[f"risk_{item}"] = "medium"
        form[f"measure_{item}"] = "حاجز وساعات شغل محددة"
    boss.post("/facility/construction", data={**form, "measure_icra": ""})
    with clinic["app"].app_context():
        assert ConstructionProject.query.count() == 0, "a risk without its measure"
    boss.post("/facility/construction", data=form)
    with clinic["app"].app_context():
        pid = ConstructionProject.query.one().id
    assert 'data-no-permit="1"' in boss.get("/facility/construction").get_data(as_text=True)
    boss.post(f"/facility/construction/{pid}/state", data={"state": "underway"})
    with clinic["app"].app_context():
        assert ConstructionProject.query.one().state == "planned"
    boss.post(f"/facility/construction/{pid}/permit", data={"permit_by": "مدير الهندسة",
                                                            "permit_on": local_today().isoformat()})
    boss.post(f"/facility/construction/{pid}/state", data={"state": "underway"})
    boss.post(f"/facility/construction/{pid}/check", data={"checked_on": local_today().isoformat(),
                                                           "compliant": "no", "note": "الحاجز مفتوح"})
    with clinic["app"].app_context():
        assert ConstructionProject.query.one().state == "underway" and ConstructionCheck.query.count() == 0


def test_the_disaster_and_abduction_drills_twice_a_year(clinic):
    from app.models import FireDrill
    from app.utils import facility_safety as fs

    boss, today = _boss(clinic), local_today()
    form = {"kind": "abduction", "held_at": f"{today.isoformat()}T11:00", "shift": "morning",
            "areas": "الحضّانة", "others": "4", "evaluation": "المخارج اتقفلت في ٣ دقايق",
            "corrective_action": "تدريب الأمن على البوابة الخلفية"}
    boss.post("/facility/drill", data=form)
    with clinic["app"].app_context():
        assert FireDrill.query.count() == 0, "without its scenario"
        half = 1 if today.month <= 6 else 2
        assert half in fs.half_years("abduction")["missing_halves"]
    res = boss.post("/facility/drill", data={**form, "scenario": "سيدة خدت طفل من الحضّانة",
                                             "observations": "الكود اتعلن بعد دقيقة", "debrief": "اتعمل"})
    assert "/facility/preparedness" in res.headers["Location"]
    with clinic["app"].app_context():
        data = fs.half_years("abduction")
        assert half not in data["missing_halves"] and len(data["untold"]) == 1
        assert fs.year_of_drills()["drills"] == [], "an abduction drill is not a fire drill"
        did = FireDrill.query.one().id
    boss.post(f"/facility/drill/{did}/told", data={"committee_told_on": today.isoformat()})
    with clinic["app"].app_context():
        assert fs.half_years("abduction")["untold"] == []


def test_training_is_counted_per_plan(clinic):
    from app.utils import facility_safety as fs

    with clinic["app"].app_context():
        fire_before = len(fs.untrained_this_year(topic="fire"))
        hazmat_before = len(fs.untrained_this_year(topic="hazmat"))
    _boss(clinic).post("/facility/training", data={"topic": "hazmat", "user_ids": [str(clinic["ids"]["doctor"])],
                                                   "trained_on": local_today().isoformat()})
    with clinic["app"].app_context():
        assert len(fs.untrained_this_year(topic="hazmat")) == hazmat_before - 1
        assert len(fs.untrained_this_year(topic="fire")) == fire_before


def test_a_plan_is_due_a_year_after_approval_and_keeps_its_history(clinic):
    from app.models import ExternalInspection, HospitalPlan
    from app.utils import preparedness as prep

    boss = _boss(clinic)
    old = local_today() - timedelta(days=400)
    boss.post("/facility/plans", data={"kind": "fire", "title": "خطة الحريق", "approved_by": "مجلس الإدارة",
                                       "approved_on": old.isoformat()})
    with clinic["app"].app_context():
        board = prep.plans_board()
        assert [r["plan"].title for r in board["overdue"]] == ["خطة الحريق"] and "hazmat" in board["missing"]
        first = HospitalPlan.query.one()
        assert prep.due_on(first) == prep.add_months(old, 12)
        fid = first.id
    boss.post(f"/facility/plans/{fid}/replace", data={"kind": "fire", "title": "خطة الحريق ٢",
                                                      "approved_by": "مجلس الإدارة",
                                                      "approved_on": local_today().isoformat()})
    with clinic["app"].app_context():
        board = prep.plans_board()
        assert board["overdue"] == [] and [r["plan"].title for r in board["rows"]] == ["خطة الحريق ٢"]
        assert [p.id for p in prep.history(board["rows"][0]["plan"])] == [fid]
    boss.post("/facility/inspection", data={"authority": "الدفاع المدني", "visited_on": local_today().isoformat(),
                                            "observations": "طفاية ناقصة", "corrective_plan": "توريد طفايتين",
                                            "due_on": (local_today() - timedelta(days=1)).isoformat()})
    with clinic["app"].app_context():
        assert len(prep.inspections_board()["overdue"]) == 1
        iid = ExternalInspection.query.one().id
    boss.post(f"/facility/inspection/{iid}/close", data={"closed_on": local_today().isoformat(),
                                                         "note": "اتوردوا"})
    with clinic["app"].app_context():
        assert prep.inspections_board()["open"] == []


def test_the_committees_against_their_own_terms(clinic):
    from app.utils import governance as gov

    boss, today = _boss(clinic), local_today()
    with clinic["app"].app_context():
        rows = {r["key"]: r for r in gov.committees()}
        assert all(rows[k]["required"] for k in ("environment", "ipc", "dtc", "quality", "mortality"))
        assert not rows["environment"]["late"], "no terms written — nothing to be late against"
    boss.post("/quality/committees/environment/charter", data={"membership": "مسؤول السلامة، الهندسة، العدوى",
                                                               "duties": "مراجعة الجولات والتجارب",
                                                               "reports_to": "مجلس الإدارة", "every_days": "30"})
    with clinic["app"].app_context():
        assert {r["key"]: r for r in gov.committees()}["environment"]["late"]
    boss.post("/quality/committee?c=environment", data={"committee": "environment", "held_on": today.isoformat(),
                                                        "attendees": "الفريق", "minutes": "راجعنا جولة الربع",
                                                        "circulated_to": "رؤساء الأقسام"})
    boss.post(f"/quality/committees/environment/review/{today.year - 1}", data={"text": "اجتمعت ١١ مرة"})
    with clinic["app"].app_context():
        row = {r["key"]: r for r in gov.committees()}["environment"]
        assert not row["late"] and row["this_year"] == 1 and row["reviewed"]
    page = boss.get("/quality/committee?c=environment").get_data(as_text=True)
    assert "رؤساء الأقسام" in page


def test_the_governing_body_hears_every_quarter_and_answers(clinic):
    from app.models import GovernanceReport
    from app.utils import governance as gov

    boss, today = _boss(clinic), local_today()
    with clinic["app"].app_context():
        missing = gov.reports_board()["missing"]
        assert missing and all(k in ("performance", "environment") for k, _ in missing)
        kind, quarter = missing[0]
    boss.post("/quality/governing-report", data={"kind": kind, "quarter": quarter, "sent_on": today.isoformat(),
                                                 "summary": "الأداء والجولات"})
    with clinic["app"].app_context():
        board = gov.reports_board()
        assert (kind, quarter) not in board["missing"] and len(board["awaiting"]) == 1
        rid = GovernanceReport.query.one().id
    boss.post(f"/quality/governing-report/{rid}/feedback", data={"feedback": "تمام، ركّزوا على العناية",
                                                                 "feedback_on": today.isoformat()})
    with clinic["app"].app_context():
        assert gov.reports_board()["awaiting"] == []


def test_an_ethical_issue_is_resolved_with_its_decision_and_who_was_told(clinic):
    from app.models import EthicsIssue

    boss, today = _boss(clinic), local_today().isoformat()
    boss.post("/quality/ethics", data={"kind": "conflict_of_interest", "raised_on": today,
                                       "summary": "طبيب بيحوّل لمعمل بيملك فيه"})
    with clinic["app"].app_context():
        eid = EthicsIssue.query.one().id
    boss.post(f"/quality/ethics/{eid}", data={"discussion": "اتناقشت", "resolved_on": today})
    with clinic["app"].app_context():
        assert EthicsIssue.query.one().resolved_on is None
    boss.post(f"/quality/ethics/{eid}", data={"decision": "إفصاح كتابي ووقف التحويل", "communicated_to": "المدير الطبي",
                                             "teaching": "حالة في محاضرة الشهر", "resolved_on": today})
    with clinic["app"].app_context():
        assert EthicsIssue.query.one().resolved_on == local_today()


def test_contracts_and_suppliers_are_evaluated_every_year(clinic):
    from app.models import ContractedService, Supplier
    from app.utils import governance as gov

    boss, today = _boss(clinic), local_today().isoformat()
    boss.post("/quality/contracts", data={"name": "المغسلة", "kind": "non_clinical", "provider": "شركة النظافة",
                                          "head": "مدير الخدمات", "criteria": "ترخيص وسعر",
                                          "measures": "زمن التسليم والشكاوى"})
    with clinic["app"].app_context():
        assert len(gov.services_board()["due"]) == 1
        sid = ContractedService.query.one().id
        clinic["db"].session.add(Supplier(name="مورّد المستلزمات"))
        clinic["db"].session.commit()
        sup = Supplier.query.filter_by(name="مورّد المستلزمات").one().id
    boss.post(f"/quality/contracts/{sid}/evaluate", data={"evaluated_on": today, "decision": "terminate",
                                                          "results": "تأخير متكرر"})
    boss.post(f"/quality/supplier/{sup}/evaluate", data={"evaluated_on": today, "decision": "keep",
                                                          "results": "ملتزم"})
    with clinic["app"].app_context():
        assert gov.services_board()["due"] == [] and not ContractedService.query.one().is_active
        assert sup not in [r["supplier"].id for r in gov.suppliers_board()["due"]]


def test_a_staff_health_record_is_private_and_a_positive_result_is_acted_on(clinic):
    from app.models import StaffHealthEntry
    from app.utils import staff_health as sh

    boss, doc = _boss(clinic), clinic["sign_in"]("doc")
    did = clinic["ids"]["doctor"]
    assert doc.get(f"/quality/staff-health/{did}").status_code == 403
    today = local_today().isoformat()
    boss.post(f"/quality/staff-health/{did}", data={"kind": "screening", "on": today, "detail": "HBsAg",
                                                    "result": "positive"})
    boss.post(f"/quality/staff-health/{did}", data={"kind": "exposure", "on": today, "detail": "وخز إبرة"})
    with clinic["app"].app_context():
        assert StaffHealthEntry.query.count() == 0
    boss.post(f"/quality/staff-health/{did}", data={"kind": "screening", "on": today, "detail": "HBsAg",
                                                    "result": "positive", "action": "تحويل لأمراض الكبد",
                                                    "informed_on": today})
    boss.post(f"/quality/staff-health/{did}", data={"kind": "restriction", "on": today, "detail": "بعيد عن العمليات",
                                                    "restricted_until": (local_today() + timedelta(days=30)).isoformat()})
    with clinic["app"].app_context():
        assert StaffHealthEntry.query.count() == 2
        assert [e.user_id for e in sh.board()["restricted"]] == [did]
    assert "data-health-entry" in boss.get(f"/quality/staff-health/{did}").get_data(as_text=True)


def test_smoking_and_a_spill_are_incidents(clinic):
    from app.models.incident import CATEGORIES

    assert "smoking" in CATEGORIES and "hazmat" in CATEGORIES
