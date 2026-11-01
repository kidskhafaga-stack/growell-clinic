"""«تحليل الأسباب» — عظم السمكة وباريتو (RCA_PLAN.md).

صاحب العيادة على شاشة برنامج تاني: *«الداش بورد دي حلوه للجودة جوه
المستشفيات والإدارة العليا»* — واختار: المشكلة تيجي من مؤشر بعيد عن هدفه،
ومن الشكاوى والحوادث «من النظام»، ويدوي؛ والسبب يفتح مشروع تحسين والمؤشر
يقول اتحسّن ولا لأ؛ والشاشة للجودة والإدارة **ولرئيس كل قسم على قسمه**.

* **الأسباب قايمة واحدة مرسومة مرتين**: باريتو بالأتقل الأول وخط الـ٨٠٪
  وعدد «الأسباب القليلة المهمة»، وعظم السمكة بالفئات — نفس الفئات التمانية
  اللي الشكوى بتتقفل بيها؛
* **«من النظام» محسوب مش مكتوب**: الشكاوى بسببها الجذري وموضوعها، والحوادث
  بالفئة اللي المراجِع اختارها ونوعها — وفي قسم واحد بس لو المشكلة لقسم؛
* **المؤشر**: قيمته يوم ما التحليل اتفتح بتتحفظ، والشاشة بتقول اتحسّن ولا
  اتسوأ — والمؤشرات البعيدة عن هدفها بتتعرض «حلّلها»؛
* **رئيس القسم** بيشوف مشاكل قسمه بس، وبيفتح مشكلة لقسمه بس؛ واللي مش من
  الجودة ولا رئيس قسم ما بيدخلش.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def q(clinic):
    """A quality reviewer, a department with a head, and a falls measure off
    its target."""
    from app.models import MeasureValue, PerformanceMeasure, User
    from app.utils import cost_centres, rca

    db = clinic["db"]
    with clinic["app"].app_context():
        head = User(username="head", full_name="رئيسة القسم", role="doctor", is_active=True)
        head.set_password("secret")
        db.session.add(head)
        db.session.flush()
        cost_centres.ensure_all()
        centres = cost_centres.listing()
        centres[0].head_id = head.id
        m = PerformanceMeasure(name="الوقوع لكل ١٠٠٠ يوم", kind="clinical", area="safety",
                               definition="x", data_source="الحوادث", frequency="شهري",
                               numerator="وقعات", denominator="أيام", per=1000, target=1.0,
                               higher_better=False, is_active=True)
        db.session.add(m)
        db.session.flush()
        for period, n in (("2026-08", 2), ("2026-09", 4)):
            db.session.add(MeasureValue(measure_id=m.id, period=period, numerator=n, denominator=2000))
        db.session.commit()
        ids = {"head": head.id, "centre": centres[0].id, "other_centre": centres[1].id,
               "measure": m.id}
    rca.forget_heads()
    yield {**clinic, **ids}
    rca.forget_heads()


def _user(env, name):
    from app.models import User

    return User.query.filter_by(username=name).one()


def test_pareto_orders_heaviest_first_and_finds_the_vital_few():
    from app.utils import rca

    rows = [{"category": "process", "text": t, "weight": w, "source": "manual"}
            for t, w in (("أ", 5), ("ب", 50), ("ج", 30), ("د", 10), ("هـ", 5))]
    rows.sort(key=lambda r: -r["weight"])
    p = rca.pareto(rows)
    assert [r["text"] for r in p["rows"]][:2] == ["ب", "ج"]
    assert p["total"] == 100 and p["rows"][-1]["running"] == 100.0
    # 50 → 80: the second cause reaches the line, so two are the vital few.
    assert p["vital"] == 2 and [r["vital"] for r in p["rows"]] == [True, True, False, False, False]
    chart = rca.pareto_chart(p["rows"])
    assert chart["bars"][0]["x"] > chart["bars"][-1]["x"], "heaviest drawn on the right"
    assert rca.pareto([])["vital"] == 0 and rca.pareto_chart([]) is None


def test_the_fishbone_draws_only_bones_that_hold_something(q):
    from app.utils import rca

    rows = rca.pareto([{"category": b, "text": f"{b}{k}", "weight": 10 - k, "source": "manual"}
                       for b in ("people", "equipment") for k in range(5)]
                      + [{"category": "unclear", "text": "؟", "weight": 3, "source": "manual"}])["rows"]
    fish = rca.fishbone(rows, title="الوقوع في العنبر لكل ألف يوم إقامة عند الأطفال")
    assert {b["bone"] for b in fish["bones"]} == {"people", "equipment"}, "never a bone called unclear"
    assert all(len(b["twigs"]) == rca.PER_BONE for b in fish["bones"])
    assert len(fish["title"]) <= 2 and fish["title"][-1].endswith("…")
    for b in fish["bones"]:
        assert 0 < b["lx"] - fish["pill_w"] / 2 and b["lx"] + fish["pill_w"] / 2 < fish["w"]


def test_a_measure_problem_keeps_its_baseline_and_says_if_it_moved(q):
    from app.models import MeasureValue, PerformanceMeasure, RcaProblem
    from app.utils import rca

    with q["app"].app_context():
        # Off its target, and nobody studying it yet: offered.
        assert [m.id for m, _ in rca.off_target_measures()] == [q["measure"]]
    boss = q["sign_in"]("boss")
    boss.post("/quality/rca/new", data={"source": "measure", "measure_id": q["measure"]})
    with q["app"].app_context():
        p = RcaProblem.query.one()
        assert (p.title, p.baseline, p.baseline_period) == ("الوقوع لكل ١٠٠٠ يوم", 2.0, "2026-09")
        assert rca.off_target_measures() == [], "studied now"
        q["db"].session.add(MeasureValue(measure_id=q["measure"], period="2026-10",
                                         numerator=2, denominator=2000))
        q["db"].session.commit()
        m = q["db"].session.get(PerformanceMeasure, q["measure"])
        state = rca.measure_state(m, p.baseline)
        assert state["now"] == 1.0 and state["better"] is True and state["change_pct"] == -50
    page = boss.get(f"/quality/rca?p={p.id}").get_data(as_text=True)
    assert "data-rca-since" in page and "اتحسّن" in page


def test_causes_written_then_a_project_opened_from_one(q):
    from app.models import ImprovementProject, RcaCause, RcaProblem

    boss = q["sign_in"]("boss")
    boss.post("/quality/rca/new", data={"source": "manual", "title": "تأخير صرف الدوا"})
    with q["app"].app_context():
        pid = RcaProblem.query.one().id
    for bone, text, w in (("process", "مفيش ترتيب أولوية", "20"), ("people", "صيدلي واحد بالليل", "12"),
                          ("equipment", "الطابعة بتقف", "3")):
        boss.post(f"/quality/rca/{pid}/cause", data={"category": bone, "text": text, "weight": w})
    boss.post(f"/quality/rca/{pid}/cause", data={"category": "nonsense", "text": "x"})
    boss.post(f"/quality/rca/{pid}/cause", data={"category": "people", "text": ""})
    with q["app"].app_context():
        assert RcaCause.query.count() == 3
        cid = RcaCause.query.filter_by(text="مفيش ترتيب أولوية").one().id

    page = boss.get(f"/quality/rca?p={pid}").get_data(as_text=True)
    for mark in ("data-rca-fish", "data-rca-pareto", "data-rca-bones", "data-rca-table",
                 'data-rca-bone="process"', "data-rca-headline"):
        assert mark in page
    assert "مفيش ترتيب أولوية" in page[page.index("data-rca-headline"):page.index("data-rca-fish")]

    boss.post(f"/quality/rca/cause/{cid}/project", data={"aim": ""})
    with q["app"].app_context():
        assert ImprovementProject.query.count() == 0, "an aim is the person's to write"
    boss.post(f"/quality/rca/cause/{cid}/project", data={"aim": "أقل من ٣٠ دقيقة في ٣ شهور"})
    with q["app"].app_context():
        proj = ImprovementProject.query.one()
        assert proj.title == "مفيش ترتيب أولوية" and "تأخير صرف الدوا" in proj.problem
        assert q["db"].session.get(RcaCause, cid).project_id == proj.id
    assert f'data-rca-project="{cid}"' in boss.get(f"/quality/rca?p={pid}").get_data(as_text=True)

    boss.post(f"/quality/rca/cause/{cid}", data={"weight": "25", "category": "policy"})
    with q["app"].app_context():
        c = q["db"].session.get(RcaCause, cid)
        assert (c.weight, c.category) == (25, "policy")
    boss.post(f"/quality/rca/cause/{cid}", data={"remove": "1"})
    with q["app"].app_context():
        assert not q["db"].session.get(RcaCause, cid).is_active


def test_counted_from_the_complaints_and_the_incidents(q):
    from app.models import Complaint, Incident, RcaProblem
    from app.utils import complaint_cases as cases
    from app.utils import cs_board, rca

    with q["app"].test_request_context("/"):
        boss = _user(q, "boss")
        for root, cat, centre in (("process", "process", q["centre"]), ("process", "process", q["centre"]),
                                  ("people", "respect", q["centre"]), (None, None, q["centre"]),
                                  ("process", "process", q["other_centre"])):
            c = cases.open_case("شكوى", kind="complaint", channel="desk", cost_centre_id=centre,
                                category=cat, user=boss, notify=False)
            c.root_cause = root
        cases.open_case("اقتراح", kind="suggestion", channel="desk", cost_centre_id=q["centre"],
                        user=boss, notify=False)
        for bone, kind in (("equipment", "fall"), ("equipment", "fall"), (None, "infection")):
            q["db"].session.add(Incident(number=f"I-{kind}-{bone}-{datetime.utcnow().timestamp()}",
                                         occurred_at=datetime.utcnow() - timedelta(days=1),
                                         category=kind, affected="patient", what_happened="x",
                                         cause_category=bone))
        q["db"].session.commit()
        start, end = cs_board.period(None, None)

        mine = rca.open_problem({"source": "complaints", "cost_centre_id": str(q["centre"])}, boss)
        rows = {(r["category"], r["label"]): r["weight"] for r in rca.causes(mine, start, end)}
        assert rows == {("process", "cmp.cat_process"): 2, ("people", "cmp.cat_respect"): 1,
                        ("unclear", "rca.no_category"): 1}, "this department only, complaints only"

        incidents = rca.open_problem({"source": "incidents"}, boss)
        rows = {(r["category"], r["label"]): r["weight"] for r in rca.causes(incidents, start, end)}
        assert rows == {("equipment", "incident.c_fall"): 2, ("unclear", "incident.c_infection"): 1}
        assert rca.causes(incidents, start, end, only="manual") == []
        q["db"].session.commit()


def test_the_incident_review_chooses_the_bone(q):
    from app.models import Incident

    with q["app"].app_context():
        row = Incident(number="I-1", occurred_at=datetime.utcnow(), category="fall",
                       affected="patient", what_happened="وقع من السرير")
        q["db"].session.add(row)
        q["db"].session.commit()
        iid = row.id
    boss = q["sign_in"]("boss")
    assert "data-cause-category" in boss.get(f"/incidents/{iid}").get_data(as_text=True)
    boss.post(f"/incidents/{iid}/review", data={"classification": "adverse_harm",
                                                "cause_category": "equipment"})
    boss.post(f"/incidents/{iid}/review", data={"classification": "adverse_harm",
                                                "cause_category": "made-up"})
    with q["app"].app_context():
        assert q["db"].session.get(Incident, iid).cause_category is None
    boss.post(f"/incidents/{iid}/review", data={"classification": "adverse_harm",
                                                "cause_category": "equipment"})
    with q["app"].app_context():
        assert q["db"].session.get(Incident, iid).cause_category == "equipment"


def test_a_head_sees_their_department_and_nobody_else_gets_in(q):
    from app.models import RcaProblem

    boss = q["sign_in"]("boss")
    boss.post("/quality/rca/new", data={"source": "manual", "title": "مشكلة قسمها",
                                        "cost_centre_id": q["centre"]})
    boss.post("/quality/rca/new", data={"source": "manual", "title": "مشكلة قسم تاني",
                                        "cost_centre_id": q["other_centre"]})
    with q["app"].app_context():
        theirs = RcaProblem.query.filter_by(title="مشكلة قسم تاني").one().id

    head = q["sign_in"]("head")
    page = head.get("/quality/rca").get_data(as_text=True)
    assert "مشكلة قسمها" in page and "مشكلة قسم تاني" not in page
    assert "data-nav-rca" in page and "data-quality-nav" not in page
    assert head.post(f"/quality/rca/{theirs}/cause",
                     data={"category": "people", "text": "x"}).status_code == 403
    head.post("/quality/rca/new", data={"source": "manual", "title": "في قسم تاني",
                                        "cost_centre_id": q["other_centre"]})
    head.post("/quality/rca/new", data={"source": "manual", "title": "في قسمي",
                                        "cost_centre_id": q["centre"]})
    with q["app"].app_context():
        assert RcaProblem.query.filter_by(title="في قسم تاني").count() == 0
        assert RcaProblem.query.filter_by(title="في قسمي").count() == 1

    desk = q["sign_in"]("desk")
    assert desk.get("/quality/rca").status_code == 403
    assert "data-nav-rca" not in desk.get("/").get_data(as_text=True)


def test_a_head_is_chosen_on_the_departments_screen(q):
    from app.models import CostCentre
    from app.utils import rca

    boss = q["sign_in"]("boss")
    assert "data-centre-head" in boss.get("/finance/cost-centres").get_data(as_text=True)
    with q["app"].app_context():
        c = q["db"].session.get(CostCentre, q["other_centre"])
        name = c.name_ar
    boss.post(f"/finance/cost-centres/{q['other_centre']}", data={
        "name_ar": name, "is_active": "1", "head_id": q["ids"]["desk"]})
    with q["app"].app_context():
        assert q["db"].session.get(CostCentre, q["other_centre"]).head_id == q["ids"]["desk"]
        assert q["ids"]["desk"] in rca.heads()
    assert q["sign_in"]("desk").get("/quality/rca").status_code == 200


def test_closing_and_reopening(q):
    from app.models import RcaProblem

    boss = q["sign_in"]("boss")
    boss.post("/quality/rca/new", data={"source": "manual", "title": "مشكلة"})
    with q["app"].app_context():
        pid = RcaProblem.query.one().id
    boss.post(f"/quality/rca/{pid}/close")
    boss.post(f"/quality/rca/{pid}/cause", data={"category": "people", "text": "بعد القفل"})
    with q["app"].app_context():
        p = q["db"].session.get(RcaProblem, pid)
        assert p.closed_at is not None and not p.causes
    boss.post(f"/quality/rca/{pid}/close")
    with q["app"].app_context():
        assert q["db"].session.get(RcaProblem, pid).closed_at is None
