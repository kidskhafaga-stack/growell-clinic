"""باقي التقييمات (ASSESSMENTS_PLAN.md ت-٢).

The owner's catalogue — autism, development, IQ, memory, language, learning,
behaviour, executive functions, attention, adaptive skills, motor
coordination, anxiety and mood, tics, sleep, headache, seizures — each a
form on the same pattern as ADHD, with its source.

* every kind opens, saves a score, and prints;
* every tool a form names exists and says where its numbers come from;
* **no invented criterion**: the only tools marked «meets the scale's
  criterion» are those whose own scoring instructions set the figure
  (Vanderbilt); a commercial tool carries no question and no scoring, only
  the boxes its official report fills;
* a count has its maximum, so a typo past it is refused.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_an_assessment_the_specialist_writes import _start, neuro  # noqa: E402,F401

_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "data", "assessments.json")

KINDS = ("adhd", "autism", "development", "iq", "memory", "language", "learning", "behaviour",
         "executive", "attention", "adaptive", "motor", "anxiety_mood", "tics", "sleep",
         "headache", "seizures")


def _catalogue():
    return json.load(open(_PATH, encoding="utf-8"))


def test_the_catalogue_holds_every_kind_with_its_source():
    cat = _catalogue()
    assert set(KINDS) <= set(cat["kinds"])
    for key, kind in cat["kinds"].items():
        assert kind["name_ar"] and kind["name_en"] and kind["source"] and kind["source_ar"], key
        sections = kind["sections"]
        assert len({s["key"] for s in sections}) == len(sections), key
        for s in sections:
            if s["type"] == "tools":
                for tool in s.get("shown", []) + s.get("more", []):
                    assert tool in cat["tools"], (key, tool)
            if "options" in s:
                keys = [o["key"] for o in s["options"]]
                assert len(set(keys)) == len(keys), (key, s["key"])
                assert all(o["ar"] and o["en"] for o in s["options"]), (key, s["key"])


def test_no_tool_carries_a_criterion_its_own_instructions_do_not_set():
    tools = _catalogue()["tools"]
    with_criterion = {k for k, t in tools.items() if any("meets" in f for f in t["fields"])}
    assert with_criterion == {"vanderbilt_parent", "vanderbilt_teacher"}, with_criterion
    for key, tool in tools.items():
        assert tool["kind"] in ("published", "commercial", "device"), key
        assert tool["source"] and tool.get("source_ar"), key
        assert tool.get("rule_ar") and tool.get("rule_en"), key
        for f in tool["fields"]:
            assert f["ar"] and f["en"], (key, f["key"])
            if f["type"] == "count":
                assert isinstance(f.get("max"), int), (key, f["key"])


def test_every_kind_opens_saves_and_prints(neuro):
    from app.models import Assessment

    cat = _catalogue()
    psy = neuro["sign_in"]("psy")
    page = psy.get(f"/assessments/patient/{neuro['ids']['child']}").get_data(as_text=True)
    for key in KINDS:
        assert f'value="{key}"' in page, key
    for key in KINDS:
        aid = _start(neuro, kind=key)
        kind = cat["kinds"][key]
        tools = next(s for s in kind["sections"] if s["type"] == "tools")
        tool = (tools["shown"] or tools["more"])[0]
        field = cat["tools"][tool]["fields"][0]
        domains = next((s for s in kind["sections"] if s["type"] == "checks"), None)
        data = {"stage": "initial", "impression": "ملاحظة", f"use_{tool}": "1",
                f"t_{tool}_{field['key']}": "3"}
        if domains:
            data[domains["key"]] = [domains["options"][0]["key"]]
        assert psy.get(f"/assessments/{aid}").status_code == 200, key
        assert psy.post(f"/assessments/{aid}/save", data=data).status_code == 302, key
        with neuro["app"].app_context():
            row = neuro["db"].session.get(Assessment, aid)
            assert row.answers["tools"][tool][field["key"]] == 3, key
            if domains:
                assert row.answers[domains["key"]] == [domains["options"][0]["key"]], key
        report = psy.get(f"/assessments/{aid}/report").get_data(as_text=True)
        assert f'data-report-tool="{tool}"' in report, key


def test_a_count_past_its_maximum_is_refused(neuro):
    from app.models import Assessment

    aid = _start(neuro, kind="autism")
    neuro["sign_in"]("psy").post(f"/assessments/{aid}/save",
                                 data={"use_mchat_rf": "1", "t_mchat_rf_total": "25"})
    with neuro["app"].app_context():
        row = neuro["db"].session.get(Assessment, aid)
        assert (row.answers.get("tools") or {}).get("mchat_rf", {}).get("total") != 25
