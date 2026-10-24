"""اسأل التقارير (REPORTS_PLAN.md ت-٣).

* السؤال بالكلام بيتحوّل لتقرير من منشئ التقارير، وبيظهر بإعداداته عشان تراجعه.
* اللي بيروح للذكاء الاصطناعي هو السؤال وأسماء خانات المنشئ بس: مفيش اسم طفل،
  ولا رقم، ولا حتى قايمة الدكاترة. اسم الدكتور أو الشركة في السؤال بيتطابق هنا.
* الرد اللي فيه مصدر مش مسموح أو خانة مش موجودة بيرجع للمسموح، مش أبعد.
* «اشرح النتيجة» بيبعت الجدول بأرقامه والدكاترة بأكواد.
* مفتاح لوحده، مقفول افتراضياً.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _on(clinic, ask=True):
    from app.models import Setting

    with clinic["app"].app_context():
        for key, value in (("ai_enabled", "1"), ("ai_provider", "claude"),
                           ("ai_api_key", "test-key"), ("ai_model", "test-model"),
                           ("ai_reports_ask", "1" if ask else "0")):
            Setting.set(key, value)
        clinic["db"].session.commit()


@pytest.fixture()
def model(monkeypatch):
    from app.utils import ai

    calls, replies = [], []

    def fake_chat(messages, system=None, config=None, feature=None):
        calls.append({"text": messages[0]["content"], "system": system, "feature": feature})
        return {"ok": True, "text": replies.pop(0) if replies else "{}"}

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls, replies


def test_off_by_default_and_no_box(clinic, model):
    calls, _ = model
    _on(clinic, ask=False)
    boss = clinic["sign_in"]("boss")
    assert "data-ask-form" not in boss.get("/reports/builder").get_data(as_text=True)
    boss.post("/reports/ask", data={"question": "إيرادات الدكاترة"})
    assert calls == []


def test_a_question_becomes_the_builder_s_settings(clinic, model):
    calls, replies = model
    _on(clinic)
    with clinic["app"].app_context():
        from app.models import Patient

        clinic["db"].session.get(Patient, clinic["ids"]["child"]).full_name = "زياد المميز"
        clinic["db"].session.commit()
    replies.append("```json\n" + json.dumps({
        "src": "bills", "preset": "month", "by": "doctor", "m": "billed", "vs": "prev",
        "filters": {"doctor": ["د. أحمد"], "payer_kind": ["cash"]},
        "understood": "قيمة فواتير د. أحمد النقدي الشهر ده قصاد اللي فات"}) + "\n```")
    boss = clinic["sign_in"]("boss")
    assert "data-ask-form" in boss.get("/reports/builder").get_data(as_text=True)
    reply = boss.post("/reports/ask", data={"question": "إيرادات د. أحمد النقدي الشهر ده قصاد اللي فات"})
    loc = reply.headers["Location"]
    assert reply.status_code == 302 and "/reports/builder?" in loc
    for part in ("src=bills", "preset=month", "by=doctor", "m=billed", "vs=prev",
                 f"f_doctor={clinic['ids']['doctor']}", "f_payer_kind=cash"):
        assert part in loc, part
    sent = calls[0]["text"] + (calls[0]["system"] or "")
    assert "زياد" not in sent and "P1" not in sent and "د. أحمد" in sent  # the question itself
    assert "المحاسب" not in sent and "الاستقبال" not in sent           # no list of staff
    assert calls[0]["feature"] == "reports_ask"
    page = boss.get(loc).get_data(as_text=True)
    assert "قيمة فواتير د. أحمد النقدي" in page


def test_what_the_person_may_not_use_is_not_offered_or_obeyed(clinic, model):
    """Somebody with the reports and not the finance rights: the money sources
    are not described to the model, and a reply asking for them is not obeyed."""
    from app.models import User
    from app.models.role import Role

    calls, replies = model
    _on(clinic)
    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(Role(name="reports_only", label_ar="تقارير", label_en="Reports",
                            modules="reports"))
        u = User(username="rep", full_name="التقارير", role="reports_only", is_active=True)
        u.set_password("secret")
        db.session.add(u)
        db.session.commit()
        assert not u.can("finance_manage")
    rep = clinic["sign_in"]("rep")
    assert rep.get("/reports/builder").status_code == 200
    replies.append(json.dumps({"src": "bills", "by": "nope", "m": "billed", "understood": "فلوس"}))
    loc = rep.post("/reports/ask", data={"question": "فلوس العيادة"}).headers["Location"]
    assert "src=bills" not in loc and "by=nope" not in loc
    assert "- bills" not in calls[0]["text"] and "- visits" in calls[0]["text"]


def test_unknown_names_are_said_not_guessed_and_nonsense_is_refused(clinic, model):
    _calls, replies = model
    _on(clinic)
    boss = clinic["sign_in"]("boss")
    replies.append(json.dumps({"src": "visits", "by": "month", "m": "count",
                               "filters": {"doctor": ["د. سمير"]}, "understood": "زيارات د. سمير"}))
    reply = boss.post("/reports/ask", data={"question": "زيارات د. سمير"}, follow_redirects=True)
    page = reply.get_data(as_text=True)
    assert "د. سمير" in page and "f_doctor" not in (reply.request.full_path or "")
    replies.append("مش فاهم")
    page = boss.post("/reports/ask", data={"question": "؟"}, follow_redirects=True).get_data(as_text=True)
    assert "رجّعش إعدادات تقرير مفهومة" in page
    replies.append(json.dumps({"src": None, "understood": "ده سؤال عن ملف طفل بعينه"}))
    page = boss.post("/reports/ask", data={"question": "مين الطفل اللي عنده ربو"},
                     follow_redirects=True).get_data(as_text=True)
    assert "مش من التقارير" in page


def test_explain_sends_the_table_with_doctors_as_codes(clinic, model):
    calls, replies = model
    _on(clinic)
    replies.append("- [D1] شاف أكتر زيارات الفترة دي.")
    boss = clinic["sign_in"]("boss")
    page = boss.post("/reports/builder/explain",
                     data={"query": "src=visits&preset=30&by=doctor&m=count"}).get_data(as_text=True)
    assert "data-explained=\"ok\"" in page and "د. أحمد شاف أكتر زيارات" in page
    sent = calls[0]["text"]
    assert "[D1]" in sent and "د. أحمد" not in sent and "طفل" not in sent
    assert calls[0]["feature"] == "reports_explain"


def test_the_switch_is_in_the_settings(clinic):
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert 'name="ai_reports_ask"' in page
