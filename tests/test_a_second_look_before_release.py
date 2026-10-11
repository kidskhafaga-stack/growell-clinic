"""نظرة تانية من المساعد على النتيجة قبل اعتمادها — والاعتماد لبني آدم.

* مقفولة لحد ما المستشفى تفتح مفتاحها، والزرار مش بيظهر قبل كده؛
* اللي بيتبعت سطور التحليل والعمر والنوع — **من غير اسم ولا رقم ملف**؛
* الرد بيتقرا ضيّق: أربع أنواع بس، وبحد أقصى خمس نقط، وأي حاجة تانية بتتشال؛
* **مفيش حاجة بتتغير**: النتيجة زي ما هي، ومش معتمدة، ومفيش حاجة اتحفظت.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_result_line_by_line import _fresh_cache, _order, _post, _row, bench  # noqa: E402,F401

REPLY = {"points": [
    {"kind": "preanalytical", "text": "Platelets very high beside this haemoglobin — check the tube."},
    {"kind": "diagnosis", "text": "Iron deficiency anaemia."},
    {"kind": "delta", "text": "Haemoglobin fell sharply since last time."},
]}


def _ai(c, on=True):
    from app.models import Setting

    with c["app"].app_context():
        for k, v in (("ai_enabled", "1"), ("ai_provider", "claude"),
                     ("ai_api_key", "test-key"), ("ai_model", "test-model"),
                     ("ai_patient_context", "0"), ("ai_lab_review", "1" if on else "0")):
            Setting.set(k, v)
        c["db"].session.commit()


@pytest.fixture()
def posted(monkeypatch):
    sent = []

    class _Resp:
        ok = True
        status_code = 200
        text = ""

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, params=None, timeout=None):
        sent.append({"url": url, "json": json})
        import json as _j
        return _Resp({"content": [{"type": "text", "text": _j.dumps(REPLY)}]})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    return sent


def _written(bench):
    order = _order(bench, collected_minutes_ago=30)
    _post(bench, order, hb="8.1", plt="1200")
    return order


def test_off_until_the_hospital_turns_it_on(bench, posted):
    _ai(bench, on=False)
    order = _written(bench)
    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-lab-review" not in page
    bench["sign_in"]("boss").post(f"/labs/order/{order}/ai-review")
    assert posted == [], "nothing is sent while the switch is off"


def test_what_is_sent_has_no_name_and_what_comes_back_is_narrow(bench, posted):
    from app.models import Patient

    _ai(bench)
    order = _written(bench)
    page = bench["sign_in"]("boss").get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-lab-review-ask" in page
    reply = bench["sign_in"]("boss").post(f"/labs/order/{order}/ai-review").get_data(as_text=True)
    assert len(posted) == 1
    body = json.dumps(posted[0]["json"], ensure_ascii=False)
    with bench["app"].app_context():
        child = bench["db"].session.get(Patient, bench["ids"]["child"])
        for part in (child.full_name, child.patient_number,
                     getattr(child.parent, "guardian_name", None) if getattr(child, "parent", None) else None):
            if part:
                assert str(part) not in body, "nothing a child can be found by"
    assert "Hemoglobin: 8.1 g/dL" in body and "Platelets: 1200" in body
    assert "days" in body
    assert 'data-lab-review-point="preanalytical"' in reply
    assert 'data-lab-review-point="delta"' in reply
    assert "Iron deficiency" not in reply, "a diagnosis is not one of the four"


def test_nothing_changes_whatever_it_says(bench, posted):
    from app.models import Setting

    _ai(bench)
    with bench["app"].app_context():
        Setting.set("lab_verify_required", "1")
        bench["db"].session.commit()
    order = _written(bench)
    with bench["app"].app_context():
        before = (_row(bench, order).status, _row(bench, order).verified_at,
                  _row(bench, order).result_text)
    bench["sign_in"]("boss").post(f"/labs/order/{order}/ai-review")
    with bench["app"].app_context():
        row = _row(bench, order)
        assert (row.status, row.verified_at, row.result_text) == before


def test_a_reply_out_of_shape_is_said_not_shown(bench, monkeypatch):
    from app.utils import lab_review

    assert lab_review.parse_reply("I think it is fine") is None
    assert lab_review.parse_reply('{"points": []}') == []
    many = {"points": [{"kind": "implausible", "text": f"p{i}"} for i in range(9)]}
    assert len(lab_review.parse_reply(json.dumps(many))) == lab_review.MAX_POINTS
