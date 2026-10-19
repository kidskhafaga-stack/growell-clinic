"""أدوات التقييم جوه الكشف (DOCTOR_EASE_PLAN.md ب-٤).

* كل أداة بنودها ونقطها ومرجعها في ``data/visit_scores.json``؛ والبرنامج بيجمع
  بس — والفئة بتتكتب بس لما المرجع نفسه بيحددها؛
* الدرجة بتتحفظ مع الكشف كقراءة عادية (فتعمل منحنى)، والسيرفر بيجمع تاني من
  الإجابات — اللي الصفحة بتبعته مش هو اللي بيتحفظ؛
* الأداة اللي نصها متعلّم ما بتتحفظش، واللي اتمسحت بتتشال؛
* السن بيختار بند السن لوحده في McIsaac، والجفاف بيقول لو المريض بره سن الأداة.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_every_tool_is_whole_and_sourced():
    from app.utils import visit_scores

    tools = visit_scores.catalogue_tools()
    assert {t["key"] for t in tools} >= {"westley", "cds", "mcisaac", "cact", "act"}
    for t in tools:
        assert t["reference"] and t["code"].startswith("score_")
        lo = sum(min(o["points"] for o in it["options"]) for it in t["items"])
        hi = sum(max(o["points"] for o in it["options"]) for it in t["items"])
        assert (lo, hi) == (t["min"], t["max"]), t["key"]
        if t.get("bands"):
            assert t["bands"][-1]["max"] == t["max"] and t.get("bands_reference")
    westley = visit_scores.by_code()["score_westley"]
    # Westley as published: consciousness 0/5, cyanosis 0/4/5, stridor 0/1/2,
    # air entry 0/1/2, retractions 0/1/2/3; 3–7 moderate.
    assert [[o["points"] for o in it["options"]] for it in westley["items"]] == [
        [0, 5], [0, 4, 5], [0, 1, 2], [0, 1, 2], [0, 1, 2, 3]]
    assert visit_scores.band(westley, 5)["en"] == "Moderate"
    assert visit_scores.total_of(westley, [0, 0, 1, None, 0]) is None


def test_a_finished_score_is_saved_as_a_reading_and_added_up_again(clinic):
    from app.models import Measurement, Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        p = db.session.get(Patient, clinic["ids"]["child"])
        p.date_of_birth = date(2023, 1, 1)       # in the dehydration scale's ages? no: > 36 m
        db.session.commit()
    doc = clinic["sign_in"]("doc")
    url = f"/visits/{clinic['ids']['visit']}/record"
    page = doc.get(url).get_data(as_text=True)
    assert 'data-score="westley"' in page and 'data-score="cds"' in page
    assert "Westley CR" in page                          # the source beside it
    doc.post(url, data={
        "chief_complaint": "كحة",
        # Westley: disoriented? no(0) · cyanosis none(0) · stridor at rest(2) ·
        # air entry decreased(1) · retractions moderate(2) = 5
        "sc_westley_conscious": "0", "sc_westley_cyanosis": "0", "sc_westley_stridor": "2",
        "sc_westley_air_entry": "1", "sc_westley_retractions": "2",
        # Half a dehydration scale: not saved.
        "sc_cds_appearance": "1", "sc_cds_eyes": "1",
    })
    with clinic["app"].app_context():
        rows = {m.code: m for m in Measurement.query.filter_by(visit_id=clinic["ids"]["visit"]).all()}
        assert rows["score_westley"].value_num == 5 and rows["score_westley"].value_text == "0.0.2.1.2"
        assert "score_cds" not in rows
    page = doc.get(url).get_data(as_text=True)
    assert "5 / 17" in page and "متوسط" in page
    # An answer the item does not have is refused, not trusted.
    doc.post(url, data={"chief_complaint": "كحة", "sc_westley_conscious": "9",
                        "sc_westley_cyanosis": "0", "sc_westley_stridor": "0",
                        "sc_westley_air_entry": "0", "sc_westley_retractions": "0"})
    with clinic["app"].app_context():
        assert Measurement.query.filter_by(code="score_westley").one().value_num == 5
    doc.post(url, data={"chief_complaint": "كحة", "sc_westley_clear": "1"})
    with clinic["app"].app_context():
        assert Measurement.query.filter_by(code="score_westley").count() == 0


def test_age_answers_the_age_item_and_the_ages_are_said(clinic):
    from app.models import Patient, Visit
    from app.utils import visit_scores

    db = clinic["db"]
    with clinic["app"].app_context():
        p = db.session.get(Patient, clinic["ids"]["child"])
        p.date_of_birth = date.today().replace(year=date.today().year - 6)
        db.session.commit()
        v = db.session.get(Visit, clinic["ids"]["visit"])
        st = visit_scores.state(v, visit_scores.all_tools())
        assert st["mcisaac"]["picks"] == {4: 0}          # 3–14 years → +1
        assert st["cds"]["in_age"] is False              # 72 months, the scale is 1–36
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-score-age" in page


def test_the_score_draws_a_curve_under_the_tool_s_name(clinic):
    from app.models import Measurement, Visit
    from app.utils import series

    db = clinic["db"]
    with clinic["app"].app_context():
        v1 = db.session.get(Visit, clinic["ids"]["visit"])
        v2 = Visit(patient_id=v1.patient_id, doctor_id=v1.doctor_id, visit_date=v1.visit_date)
        db.session.add(v2)
        db.session.flush()
        for v, n in ((v1, 7), (v2, 3)):
            db.session.add(Measurement(patient_id=v.patient_id, visit_id=v.id, code="score_westley",
                                       panel="score", value_num=n))
        db.session.commit()
        names = [c["name"] for c in series.curves_for(v1.patient_id, "en")]
        assert "Westley croup score" in names


def _cact_text(complete=True):
    items = []
    for i in range(7):
        n = 4 if i < 4 else 6
        items.append({"ar": f"سؤال {i + 1}", "en": "" if complete else "",
                      "options_ar": [f"إجابة {k}" for k in range(n)], "options_en": []})
    if not complete:
        items[6]["options_ar"][5] = ""
    return items


def test_a_licensed_tool_has_only_its_shape_until_the_clinic_enters_the_wording(clinic):
    from app.utils import visit_scores

    cact = next(t for t in visit_scores.catalogue_tools() if t["key"] == "cact")
    # The shape only: no question or answer text ships with the program.
    assert all("label_ar" not in it and "label_en" not in it for it in cact["items"])
    assert all(set(o) == {"points"} for it in cact["items"] for o in it["options"])
    assert [[o["points"] for o in it["options"]] for it in cact["items"]] == \
        [[0, 1, 2, 3]] * 4 + [[5, 4, 3, 2, 1, 0]] * 3
    with clinic["app"].app_context():
        assert "cact" not in {t["key"] for t in visit_scores.tools_for()}
    doc = clinic["sign_in"]("doc")
    page = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'data-score="cact"' not in page

    boss = clinic["sign_in"]("boss")
    assert doc.get("/visits/scores/licensed").status_code == 403
    assert "data-to-licensed" in boss.get("/settings/").get_data(as_text=True)

    def post(holder, items):
        form = {"tool": "cact", "holder": holder, "ref": "LIC-1"}
        for i, it in enumerate(items):
            form[f"q_{i}_ar"] = it["ar"]
            for k, o in enumerate(it["options_ar"]):
                form[f"o_{i}_{k}_ar"] = o
        return boss.post("/visits/scores/licensed", data=form)

    post("", _cact_text())                       # no licence holder: stays hidden
    post("GSK", _cact_text(complete=False))      # one answer missing: stays hidden
    with clinic["app"].app_context():
        assert "cact" not in {t["key"] for t in visit_scores.tools_for()}
    post("GSK", _cact_text())
    with clinic["app"].app_context():
        tool = next(t for t in visit_scores.tools_for() if t["key"] == "cact")
        assert tool["items"][0]["label_ar"] == "سؤال 1" and tool["licence_holder"] == "GSK"
    page = boss.get("/visits/scores/licensed").get_data(as_text=True)
    assert "data-lic-on" in page
    page = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'data-score="cact"' in page and "سؤال 1" in page and "GSK" in page
