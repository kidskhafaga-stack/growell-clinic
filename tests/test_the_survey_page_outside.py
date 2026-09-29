"""The survey page outside the clinic, and what crosses to it.

Asked as: *«أرفع جزء التقييمات على Vercel وأعمل حفظ على داتا بيز خارجية وأعمل
سينك مع البرنامج — أحسن ما أخرّج كل البرنامج على النت»*.

What is held here:

* nothing crosses until ``clinic.env`` names the page and its key, and the
  program falls back to its own page until then;
* what goes out is the clinic's name and logo, the unit and the questions —
  never the child's name, the phone number or the doctor;
* answers that come back are judged by the same path rules as the clinic's own
  page, raise a complaint when low, are kept here before they are deleted
  there, and are taken once;
* the page's own functions refuse a caller without the key, keep one answer
  per code, and speak to Supabase the way its own clients do (run with Node).
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

KEY = "k" * 32
PAGE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "outside", "survey"))


@pytest.fixture()
def outside(clinic, monkeypatch):
    """The page, as an in-memory store behind the same four calls."""
    from app.models import Setting, Patient
    from app.utils import survey_outside

    monkeypatch.setenv("SURVEY_PAGE_URL", "https://survey.example.app")
    monkeypatch.setenv("SURVEY_SYNC_KEY", KEY)
    store = {"brand": None, "surveys": {}, "answers": {}, "calls": [],
             "refuse": set()}

    def fake(action, payload=None):
        payload = payload or {}
        store["calls"].append((action, json.loads(json.dumps(payload))))
        if action == "push":
            store["brand"] = payload.get("brand")
            took = [s for s in payload.get("surveys", [])
                    if s["token"] not in store["refuse"]]
            for s in took:
                store["surveys"][s["token"]] = s["config"]
            return {"ok": True, "pushed": [s["token"] for s in took]}
        if action == "pull":
            return {"ok": True, "answers": [{"token": t, "payload": p}
                                            for t, p in store["answers"].items()]}
        if action == "done":
            for t in payload.get("tokens", []):
                store["answers"].pop(t, None)
                store["surveys"].pop(t, None)
            return {"ok": True}
        raise AssertionError(action)

    monkeypatch.setattr(survey_outside, "_call", fake)
    with clinic["app"].app_context():
        Setting.set("survey_mode", "outside")
        Setting.set("clinic_name_ar", "جروويل")
        kid = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        kid.full_name, kid.own_phone = "يوسف أحمد", "01012345678"
        clinic["db"].session.commit()
    clinic["store"] = store
    return clinic


def _send(clinic):
    """A survey after a visit, the way the program sends it."""
    from app.models import Feedback, Patient, User
    from app.utils import feedback

    with clinic["app"].app_context(), clinic["app"].test_request_context():
        fb = Feedback(patient_id=clinic["ids"]["child"], token=Feedback.new_token(),
                      doctor_id=clinic["ids"]["doctor"])
        clinic["db"].session.add(fb)
        clinic["db"].session.flush()
        log = feedback.deliver(fb, clinic["db"].session.get(Patient, clinic["ids"]["child"]),
                               doctor=clinic["db"].session.get(User, clinic["ids"]["doctor"]))
        clinic["db"].session.commit()
        return fb.token, log.body


def test_nothing_crosses_until_clinic_env_says_where(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import feedback, survey_outside

    monkeypatch.delenv("SURVEY_PAGE_URL", raising=False)
    monkeypatch.setenv("SURVEY_SYNC_KEY", KEY)
    with clinic["app"].app_context():
        Setting.set("survey_mode", "outside")
        clinic["db"].session.commit()
        assert survey_outside.configured() is False
        assert feedback.survey_delivery()[0] == "link"          # its own page
    monkeypatch.setenv("SURVEY_PAGE_URL", "http://not-tls.example")
    with clinic["app"].app_context():
        assert survey_outside.configured() is False             # https only
    monkeypatch.setenv("SURVEY_PAGE_URL", "https://survey.example.app")
    monkeypatch.setenv("SURVEY_SYNC_KEY", "short")
    with clinic["app"].app_context():
        assert survey_outside.configured() is False             # a real key


def test_what_goes_out_is_the_clinic_and_the_questions_not_the_family(outside):
    token, body = _send(outside)
    assert f"https://survey.example.app/?t={token}" in body
    sent = outside["store"]["surveys"][token]
    text = json.dumps(sent, ensure_ascii=False) + json.dumps(outside["store"]["brand"], ensure_ascii=False)
    assert "يوسف" not in text and "01012345678" not in text and "أحمد" not in text
    assert "د. أحمد" not in text
    assert outside["store"]["brand"]["name"] == "جروويل"
    assert [s["key"] for s in sent["steps"]][:3] == ["doctor", "service", "finance"]
    assert any(c["value"] == "finance:price" for c in sent["steps"][2]["concerns"])


def test_answers_come_back_by_the_same_rules_and_are_deleted_there(outside):
    from app.models import Feedback, MessageLog

    token, _ = _send(outside)
    outside["store"]["answers"][token] = {
        "doctor_rating": ["5"], "finance_rating": ["1"], "nps": ["3"],
        "concern": ["finance:price", "doctor:bogus"], "comment": ["غالي"],
        "a_q99": ["x"]}
    with outside["app"].app_context(), outside["app"].test_request_context():
        from app.utils import survey_outside
        res = survey_outside.sync()
        fb = Feedback.query.filter_by(token=token).one()
        assert res == {"pushed": 0, "answered": 1, "error": None}
        assert (fb.status, fb.doctor_rating, fb.finance_rating, fb.nps) == ("submitted", 5, 1, 3)
        assert fb.concerns == "finance:price" and fb.answers is None
        assert fb.outside_state == "answered"
        assert MessageLog.query.filter_by(template_type="feedback_complaint").count() == 1
    assert outside["store"]["answers"] == {} and token not in outside["store"]["surveys"]
    # Taken once: the same answer arriving again changes nothing.
    outside["store"]["answers"][token] = {"doctor_rating": ["1"]}
    with outside["app"].app_context(), outside["app"].test_request_context():
        survey_outside.sync()
        assert Feedback.query.filter_by(token=token).one().doctor_rating == 5
    assert outside["store"]["answers"] == {}


def test_a_survey_that_could_not_go_out_waits_and_goes_next_time(outside, monkeypatch):
    from app.models import Feedback
    from app.utils import survey_outside

    real = survey_outside._call

    def down(action, payload=None):
        raise OSError("no internet")

    monkeypatch.setattr(survey_outside, "_call", down)
    token, body = _send(outside)
    assert token in body                                    # the family still gets it
    with outside["app"].app_context():
        assert Feedback.query.filter_by(token=token).one().outside_state == "pending"
        assert survey_outside.sync()["error"] == "OSError"
    monkeypatch.setattr(survey_outside, "_call", real)
    with outside["app"].app_context():                  # as the command line does
        assert survey_outside.sync()["pushed"] == 1
        assert Feedback.query.filter_by(token=token).one().outside_state == "out"


def test_a_survey_the_page_did_not_take_stays_waiting(outside):
    from app.models import Feedback
    from app.utils import survey_outside

    token, _ = _send(outside)
    with outside["app"].app_context():
        fb = Feedback.query.filter_by(token=token).one()
        fb.outside_state = "pending"
        outside["db"].session.commit()
    outside["store"]["refuse"].add(token)
    with outside["app"].app_context():
        survey_outside.sync()
        assert Feedback.query.filter_by(token=token).one().outside_state == "pending"


def test_the_heartbeat_syncs_at_most_every_ten_minutes(outside):
    from app.utils import survey_outside

    with outside["app"].app_context(), outside["app"].test_request_context():
        assert survey_outside.maybe_sync() is not None
        assert survey_outside.maybe_sync() is None
    assert sum(1 for c in outside["store"]["calls"] if c[0] == "pull") == 1


def test_the_builder_shows_it_and_only_an_admin_syncs(outside):
    page = outside["sign_in"]("boss").get("/messages/survey").get_data(as_text=True)
    assert "data-mode-outside" in page and "survey.example.app" in page
    assert outside["sign_in"]("desk").post("/messages/survey/sync").status_code == 403
    outside["sign_in"]("boss").post("/messages/survey/sync")
    assert any(c[0] == "pull" for c in outside["store"]["calls"])


# ------------------------------------------------------------- the page ---
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_pages_functions_with_a_fake_supabase():
    """Runs outside/survey/test/functions.test.js: the key, one answer per
    code, the filters and headers Supabase's own clients send."""
    out = subprocess.run(["node", os.path.join(PAGE, "test", "functions.test.js")],
                         cwd=PAGE, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "all passed" in out.stdout
