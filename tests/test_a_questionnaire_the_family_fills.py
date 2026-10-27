"""الاستبيانات اللي الأهل والمدرس بيملوها (ASSESSMENTS_PLAN.md ت-٤).

The owner: *«الاستبيانات اللي الأهل والمدرس بيملوها بنفسهم … ياريت نعمل ده
برده»* — with Vanderbilt, M-CHAT and SDQ waiting on whether using them inside
a program is allowed. It is not without their owners' permission, so:

* the program carries each questionnaire's **shape** only — and the shape
  agrees with the score boxes the assessment form already had;
* **no wording ships**: the clinic types it, names whose permission it uses,
  and a doctor opens it; until then it appears nowhere;
* it goes out on the clinic's tablet, as a link, or on paper typed in later;
  whoever fills it sees the questions and never a score;
* the arithmetic is the tool's own: reversed items, counts, averages, and the
  SDQ's scaling up of a part with one or two missing — nothing else is
  guessed;
* the scores reach the assessment only when the specialist presses for it.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_an_assessment_the_specialist_writes import _start, neuro  # noqa: E402,F401

ROOT = os.path.join(os.path.dirname(__file__), "..")
SHAPES = json.load(open(os.path.join(ROOT, "app", "data", "questionnaires.json"), encoding="utf-8"))
TOOLS = json.load(open(os.path.join(ROOT, "app", "data", "assessments.json"), encoding="utf-8"))["tools"]


def _items(sh):
    return [n for _s, a, b in sh["item_scales"] for n in range(a, b + 1)]


def _words(sh, lang="ar"):
    """Test wording — numbered placeholders, not any tool's real questions."""
    data = {f"items_{lang}": "\n".join(f"سؤال تجريبي {n}" for n in _items(sh)),
            "holder": "جهة الإذن (اختبار)", "ref": "خطاب رقم ١ (اختبار)",
            "notice": "© سطر الحقوق (اختبار)"}
    for scale, pts in sh["scales"].items():
        for i, _p in enumerate(pts):
            data[f"opt_{scale}_{i}_{lang}"] = f"اختيار {i}"
    return data


def _open(c, key):
    """The clinic types the words and a doctor opens the questionnaire."""
    sh = SHAPES["questionnaires"][key]
    assert c["sign_in"]("psy").post(f"/assessments/questionnaires/{key}", data=_words(sh)).status_code == 302
    c["sign_in"]("doc").post(f"/assessments/questionnaires/{key}/open", data={"note": "راجعته"})


def _req(c, rid):
    from app.models import QuestionnaireRequest

    with c["app"].app_context():
        r = c["db"].session.get(QuestionnaireRequest, rid)
        return {"status": r.status, "scores": r.scores, "answers": r.answers, "token": r.token,
                "mode": r.mode, "entered_by": r.entered_by}


def _last_request(c):
    from app.models import QuestionnaireRequest

    with c["app"].app_context():
        return QuestionnaireRequest.query.order_by(QuestionnaireRequest.id.desc()).first().id


# ------------------------------------------------------------ the shape --
def test_every_shape_agrees_with_the_score_boxes_it_fills():
    for key, sh in SHAPES["questionnaires"].items():
        items = _items(sh)
        assert items == list(range(1, len(items) + 1)), key
        tool = TOOLS[sh["tool"]]
        fields = {f["key"]: f for f in tool["fields"]}
        assert set(sh["informants"]) <= {"parent", "teacher", "self"}, key
        assert sh["permission"] in ("written", "published") and sh["owner"] and sh["source"], key
        assert all(1 <= n <= len(items) for n in sh.get("reverse") or []), key
        seen = {}
        for part in sh["parts"]:
            assert part["field"] in fields, (key, part["field"])
            if part["rule"] == "parts":
                assert all(p in seen for p in part["parts"]), key
                continue
            assert part["rule"] in ("sum", "mean", "count_at_least", "count_equal"), key
            assert all(1 <= n <= len(items) for n in part["items"]), key
            f = fields[part["field"]]
            # A count can never pass the box's own maximum.
            if part["rule"].startswith("count"):
                assert len(part["items"]) == f["max"], (key, part["key"])
            seen[part["key"]] = part
    # SCARED's five parts and SDQ's five scales each take every item once.
    scared = SHAPES["questionnaires"]["scared"]
    parts = [p for p in scared["parts"] if p["key"] != "total"]
    assert sorted(n for p in parts for n in p["items"]) == list(range(1, 42))
    sdq = SHAPES["questionnaires"]["sdq"]
    assert sorted(n for p in sdq["parts"] if p["rule"] == "sum" for n in p["items"]) == list(range(1, 26))


def test_no_wording_ships_with_the_program():
    for key, sh in SHAPES["questionnaires"].items():
        assert "items" not in sh and "text" not in sh, key
        for scale, pts in sh["scales"].items():
            assert all(isinstance(p, int) for p in pts), (key, scale)


# ------------------------------------------------------------ the lock ---
def test_a_questionnaire_without_its_words_appears_nowhere(neuro):
    aid = _start(neuro, kind="adhd")
    page = neuro["sign_in"]("psy").get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-q-offer" not in page and "data-q-none" in page
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/questionnaire",
                                  data={"key": "vanderbilt_parent", "mode": "tablet"})
    from app.models import QuestionnaireRequest

    with neuro["app"].app_context():
        assert QuestionnaireRequest.query.count() == 0


def test_the_words_and_the_permission_then_a_doctor(neuro):
    from app.models import QuestionnaireText

    sh = SHAPES["questionnaires"]["mchat_rf"]
    psy = neuro["sign_in"]("psy")
    page = psy.get("/assessments/questionnaires/mchat_rf").get_data(as_text=True)
    assert "data-qn-blockers" in page and 'data-blocker="wording"' in page
    assert "mchatscreen.com" in page, "says whose permission is needed"

    wrong = dict(_words(sh), items_ar="سطر واحد بس")
    page = psy.post("/assessments/questionnaires/mchat_rf", data=wrong, follow_redirects=True).get_data(as_text=True)
    assert "data-qn-count-wrong" in page

    no_notice = dict(_words(sh), notice="")
    psy.post("/assessments/questionnaires/mchat_rf", data=no_notice)
    page = psy.get("/assessments/questionnaires/mchat_rf").get_data(as_text=True)
    assert 'data-blocker="notice"' in page, "the M-CHAT's owners ask for their line"

    psy.post("/assessments/questionnaires/mchat_rf", data=_words(sh))
    psy.post("/assessments/questionnaires/mchat_rf/open")
    with neuro["app"].app_context():
        assert QuestionnaireText.query.filter_by(key="mchat_rf").one().status == "draft", \
            "only a doctor opens it"
    neuro["sign_in"]("doc").post("/assessments/questionnaires/mchat_rf/open")
    with neuro["app"].app_context():
        assert QuestionnaireText.query.filter_by(key="mchat_rf").one().status == "active"

    psy.post("/assessments/questionnaires/mchat_rf", data=dict(_words(sh), items_ar=_words(sh)["items_ar"] + "x"))
    with neuro["app"].app_context():
        assert QuestionnaireText.query.filter_by(key="mchat_rf").one().status == "draft", \
            "new words close it until a doctor reopens"


# --------------------------------------------------------- the arithmetic --
def _score(key, answers):
    from app.utils import questionnaires as qn

    sh = SHAPES["questionnaires"][key]
    form = {"scales": {s: [{"v": v} for v in pts] for s, pts in sh["scales"].items()},
            "items": [{"n": n, "scale": s} for s, a, b in sh["item_scales"] for n in range(a, b + 1)],
            "reverse": sh.get("reverse") or [], "parts": sh["parts"]}
    return qn.score(form, {str(k): v for k, v in answers.items()})


def test_vanderbilt_counts_often_and_very_often_and_each_performance_mark():
    answers = {n: 0 for n in range(1, 48)}
    answers.update({1: 2, 2: 3, 3: 1, 10: 3, 19: 2, 41: 2})
    answers.update({48: 4, 49: 5, 50: 5, 51: 3, 52: 1, 53: 2, 54: 4, 55: 3})
    got = _score("vanderbilt_parent", answers)
    assert got["inattentive"] == 2 and got["hyperactive"] == 1 and got["odd"] == 1
    assert got["conduct"] == 0 and got["anxiety"] == 1
    assert got["perf_4"] == 2 and got["perf_5"] == 2


def test_mchat_turns_items_2_5_and_12_round():
    # «No» (1) is the at-risk answer, except on 2, 5 and 12 where «yes» (0) is.
    all_typical = {n: (1 if n in (2, 5, 12) else 0) for n in range(1, 21)}
    assert _score("mchat_rf", all_typical)["total"] == 0
    assert _score("mchat_rf", {**all_typical, 2: 0, 7: 1})["total"] == 2


def test_sdq_reverses_five_items_and_scales_a_part_with_one_missing():
    answers = {n: 0 for n in range(1, 26)}
    for n in (7, 11, 14, 21, 25):
        answers[n] = 2          # «certainly true» on a reversed item scores 0
    got = _score("sdq", answers)
    assert got["conduct"] == 0 and got["peer"] == 0 and got["total"] == 0
    answers[3], answers[8] = 2, 1
    del answers[24]             # one emotional item missing: 3 of 5 × 5/4
    got = _score("sdq", answers)
    assert got["emotional"] == 4, "(2+1+0+0)/4 × 5 = 3.75 → 4"
    for n in (13, 16):
        del answers[n]          # three missing: too few to scale
    assert _score("sdq", answers)["emotional"] is None and _score("sdq", answers)["total"] is None


def test_snap_iv_is_an_average_and_scared_a_sum_and_a_gap_is_empty():
    snap = {n: 0 for n in range(1, 27)}
    snap.update({1: 3, 2: 3, 3: 1})
    assert _score("snap_iv", snap)["inattention"] == 0.78
    del snap[20]
    assert _score("snap_iv", snap)["odd"] is None
    scared = {n: 1 for n in range(1, 42)}
    got = _score("scared", scared)
    assert got["total"] == 41 and got["panic"] == 13 and got["school"] == 4


# ------------------------------------------------- handing it over -------
def test_on_the_tablet_the_questions_only_and_then_into_the_assessment(neuro):
    from app.models import Assessment

    _open(neuro, "vanderbilt_parent")
    aid = _start(neuro, kind="adhd")
    psy = neuro["sign_in"]("psy")
    page = psy.get(f"/assessments/{aid}").get_data(as_text=True)
    assert 'data-q-offer="vanderbilt_parent"' in page and "data-q-tablet" in page
    reply = psy.post(f"/assessments/{aid}/questionnaire",
                     data={"key": "vanderbilt_parent", "mode": "tablet", "informant": "parent"})
    assert "/assessments/q/" in reply.headers["Location"]
    rid = _last_request(neuro)
    token = _req(neuro, rid)["token"]

    anon = neuro["app"].test_client()
    page = anon.get(f"/assessments/q/{token}").get_data(as_text=True)
    assert page.count("data-qn-item=") == 55 and "سؤال تجريبي 55" in page
    assert "data-qn-notice" in page and "inattentive" not in page, "no score, no field names"
    answers = {f"i_{n}": "0" for n in range(1, 48)}
    answers.update({f"i_{n}": "2" for n in range(10, 17)})
    answers.update({f"i_{n}": "5" for n in range(48, 56)})
    answers["i_9"] = "7"        # not a choice the item has: not taken
    page = anon.post(f"/assessments/q/{token}", data=answers).get_data(as_text=True)
    assert "data-qn-thanks" in page and "data-q-scores" not in page
    got = _req(neuro, rid)
    assert got["status"] == "done" and "9" not in got["answers"]
    assert got["scores"]["inattentive"] is None, "an item missing: the part stays empty"
    assert got["scores"]["hyperactive"] == 7 and got["scores"]["perf_5"] == 8
    assert "data-qn-thanks" in anon.post(f"/assessments/q/{token}", data=answers).get_data(as_text=True), \
        "answered once"
    assert _req(neuro, rid)["answers"] == got["answers"]

    with neuro["app"].app_context():
        assert not (neuro["db"].session.get(Assessment, aid).answers or {}).get("tools"), \
            "nothing writes itself into the record"
    page = psy.get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-q-scores" in page and "data-q-use" in page
    psy.post(f"/assessments/questionnaire/{rid}/use")
    with neuro["app"].app_context():
        tools = neuro["db"].session.get(Assessment, aid).answers["tools"]
        assert tools["vanderbilt_parent"]["hyperactive"] == 7
        assert "inattentive" not in tools["vanderbilt_parent"], "an empty part writes nothing"
    assert _req(neuro, rid)["status"] == "used"


def test_on_paper_typed_in_by_the_specialist(neuro):
    _open(neuro, "sdq")
    aid = _start(neuro, kind="behaviour")
    psy = neuro["sign_in"]("psy")
    reply = psy.post(f"/assessments/{aid}/questionnaire",
                     data={"key": "sdq", "mode": "paper", "informant": "teacher", "respondent": "أ. منى"})
    assert "/paper" in reply.headers["Location"]
    rid = _last_request(neuro)
    paper = psy.get(f"/assessments/questionnaire/{rid}/paper").get_data(as_text=True)
    assert paper.count("data-paper-item=") == 25 and "أ. منى" in paper and "© سطر الحقوق" in paper
    token = _req(neuro, rid)["token"]
    assert neuro["app"].test_client().get(f"/assessments/q/{token}").status_code == 404, \
        "a paper's token opens nothing from outside"
    page = psy.get(f"/assessments/questionnaire/{rid}/enter").get_data(as_text=True)
    assert page.count("data-qn-item=") == 25
    psy.post(f"/assessments/questionnaire/{rid}/enter", data={f"i_{n}": "1" for n in range(1, 26)})
    got = _req(neuro, rid)
    assert got["status"] == "done" and got["entered_by"] == neuro["psy"]
    assert got["scores"]["total"] == 20 and got["scores"]["prosocial"] == 5


def test_a_link_only_when_the_clinic_is_online(neuro):
    from app.models import MessageLog, Patient, Setting

    _open(neuro, "snap_iv")
    aid = _start(neuro, kind="adhd")
    psy = neuro["sign_in"]("psy")
    page = psy.get(f"/assessments/{aid}").get_data(as_text=True)
    assert 'data-q-offer="snap_iv"' in page
    assert "data-q-offline" in page and "data-q-link" not in page
    with neuro["app"].app_context():
        Setting.set("wa_public_base_url", "https://clinic.example.com")
        neuro["db"].session.get(Patient, neuro["ids"]["child"]).own_phone = "01001234567"
        neuro["db"].session.commit()
    page = psy.get(f"/assessments/{aid}").get_data(as_text=True)
    assert "data-q-link" in page
    psy.post(f"/assessments/{aid}/questionnaire",
             data={"key": "snap_iv", "mode": "link", "informant": "teacher", "phone": "01112223334"})
    with neuro["app"].app_context():
        log = MessageLog.query.one()
        assert log.template_type == "questionnaire_link" and "/assessments/q/" in log.body
    assert _req(neuro, _last_request(neuro))["mode"] == "link"


def test_an_approved_assessment_takes_no_scores(neuro):
    from app.utils import questionnaires as qn

    _open(neuro, "vanderbilt_parent")
    aid = _start(neuro, kind="adhd")
    psy = neuro["sign_in"]("psy")
    psy.post(f"/assessments/{aid}/questionnaire", data={"key": "vanderbilt_parent", "mode": "tablet"})
    rid = _last_request(neuro)
    neuro["app"].test_client().post(f"/assessments/q/{_req(neuro, rid)['token']}",
                                    data={f"i_{n}": "0" for n in range(1, 56)})
    psy.post(f"/assessments/{aid}/save", data={"then": "review"})
    neuro["sign_in"]("doc").post(f"/assessments/{aid}/approve")
    psy.post(f"/assessments/questionnaire/{rid}/use")
    assert _req(neuro, rid)["status"] == "done"
    assert qn.QuestionnaireError  # the refusal is a named one


def test_every_questionnaire_page_opens(neuro):
    doc = neuro["sign_in"]("doc")
    for key in SHAPES["questionnaires"]:
        page = doc.get(f"/assessments/questionnaires/{key}")
        assert page.status_code == 200, key
        assert page.get_data(as_text=True).count("data-qn-part=") == len(SHAPES["questionnaires"][key]["parts"]), key


def test_the_doors(neuro):
    page = neuro["sign_in"]("doc").get("/assessments/review").get_data(as_text=True)
    assert "data-to-questionnaires" in page
    page = neuro["sign_in"]("doc").get("/assessments/questionnaires").get_data(as_text=True)
    for key in SHAPES["questionnaires"]:
        assert f'data-qn-row="{key}"' in page
    assert neuro["app"].test_client().get("/assessments/q/nothing").status_code == 404
