"""The lab result to the family — after the doctor saw it. LAB_GLAB360_PLAN.md م-٤.

The owner's three decisions:

* «بعد ما الدكتور يشوفها» — a released result goes to the family only when
  the doctor presses «seen»;
* «لأ، تستنى الدكتور يكلّم الأهل» — a critical result or a sensitive test
  waits until the doctor has called them;
* «أيوه، بنفس الحماية» — the referring doctor gets the same link.

And the link: the lab's report as written, opened with the child's date of
birth, ending after its days, locked after five wrong answers; every send and
every opening kept. Off until the clinic turns it on — and from that day only.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_result_line_by_line import _order as order_cbc, _post, bench  # noqa: E402,F401
from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401

BORN = "2025-01-01"          # the test child's date of birth (conftest)


@pytest.fixture()
def sending(lab):
    """Sending switched on, the child with a phone, and a referring doctor."""
    from app.models import ExternalDoctor, Patient, Setting
    from app.utils import lab_share

    with lab["app"].app_context():
        lab_share.switch(True)
        # Reachable from outside: the result goes as a link. (Without it,
        # as a file — `test_offline_*` below.)
        Setting.set("wa_public_base_url", "https://clinic.example.com")
        child = lab["db"].session.get(Patient, lab["ids"]["child"])
        child.own_phone, child.full_name = "01001234567", "سليم وجدي"
        doc = ExternalDoctor(name="د. سامح المحوِّل", phone="01112223334", place="عيادة سامح")
        lab["db"].session.add(doc)
        lab["db"].session.commit()
        lab["ext"] = doc.id
    return lab


def _answered(lab, test="cbc", critical=False, minutes_ago=0):
    """A result written and released."""
    from app.models import VisitInvestigation

    oid = _order(lab, test=test)
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, oid)
        now = datetime.utcnow() - timedelta(minutes=minutes_ago)
        row.status, row.result_value, row.resulted_at = "resulted", 12.0, now
        row.collected_at = now - timedelta(minutes=30)
        row.ordered_by = lab["ids"]["doctor"]
        if critical:
            row.critical_at = now
        lab["db"].session.commit()
    return oid


def _shares(lab):
    from app.models import ResultShare

    with lab["app"].app_context():
        return [(s.audience, sorted(s.order_ids), s.token) for s in ResultShare.query.order_by(ResultShare.id)]


def test_off_until_the_clinic_turns_it_on_and_then_from_that_day(lab):
    from app.utils import lab_share

    old = _answered(lab, minutes_ago=5)
    doc = lab["sign_in"]("doc")
    assert doc.get("/labs/results/to-see").status_code == 404
    assert "data-share-box" not in lab["sign_in"]("boss").get(f"/labs/order/{old}").get_data(as_text=True)
    with lab["app"].app_context():
        lab_share.switch(True)
        lab["db"].session.commit()
    new = _answered(lab)
    page = doc.get("/labs/results/to-see").get_data(as_text=True)
    assert f'data-see-row="{new}"' in page and f'data-see-row="{old}"' not in page


def test_nothing_goes_until_the_doctor_says_seen(sending):
    oid = _answered(sending)
    doc = sending["sign_in"]("doc")
    assert _shares(sending) == []
    page = doc.get("/labs/results/to-see").get_data(as_text=True)
    assert f'data-see-row="{oid}"' in page
    reply = doc.post("/labs/results/seen", data={"order": [oid]})
    assert reply.status_code == 200                       # the WhatsApp button page
    assert "https://clinic.example.com/labs/r/" in reply.get_data(as_text=True)
    assert [(a, ids) for a, ids, _t in _shares(sending)] == [("family", [oid])]
    assert f'data-see-row="{oid}"' not in doc.get("/labs/results/to-see").get_data(as_text=True)
    # Pressing again sends nothing twice.
    doc.post("/labs/results/seen", data={"order": [oid]})
    assert len(_shares(sending)) == 1


def test_a_result_not_released_is_not_on_the_list(sending):
    from app.models import Setting, VisitInvestigation
    from app.utils import lab_release

    with sending["app"].app_context():
        Setting.set(lab_release.SETTING, "1")
        sending["db"].session.commit()
    oid = _answered(sending)
    doc = sending["sign_in"]("doc")
    assert f'data-see-row="{oid}"' not in doc.get("/labs/results/to-see").get_data(as_text=True)
    doc.post("/labs/results/seen", data={"order": [oid]})
    assert _shares(sending) == []
    with sending["app"].app_context():
        row = sending["db"].session.get(VisitInvestigation, oid)
        row.verified_at = datetime.utcnow()
        sending["db"].session.commit()
    assert f'data-see-row="{oid}"' in doc.get("/labs/results/to-see").get_data(as_text=True)


def test_a_critical_result_waits_for_the_doctors_call(sending):
    from app.models import VisitInvestigation

    oid = _answered(sending, critical=True)
    doc = sending["sign_in"]("doc")
    doc.post("/labs/results/seen", data={"order": [oid]})
    assert _shares(sending) == []                          # seen, not sent
    page = doc.get("/labs/results/to-see").get_data(as_text=True)
    assert f'data-call-row="{oid}"' in page and 'data-hold="critical"' in page
    doc.post(f"/labs/results/{oid}/called", data={"note": "كلّمت الأم"})
    assert [(a, ids) for a, ids, _t in _shares(sending)] == [("family", [oid])]
    with sending["app"].app_context():
        row = sending["db"].session.get(VisitInvestigation, oid)
        assert row.family_called_at is not None and row.family_called_note == "كلّمت الأم"


def test_a_sensitive_test_waits_too_and_the_lab_marks_which(sending):
    from app.models import Investigation

    boss = sending["sign_in"]("boss")
    boss.post(f"/labs/tests/{sending['urine']}/details", data={"sensitive": ["0", "1"]})
    with sending["app"].app_context():
        assert sending["db"].session.get(Investigation, sending["urine"]).sensitive is True
        assert not sending["db"].session.get(Investigation, sending["cbc"]).sensitive
    plain, quiet = _answered(sending), _answered(sending, test="urine")
    doc = sending["sign_in"]("doc")
    doc.post("/labs/results/seen", data={"order": [plain, quiet]})
    assert [(a, ids) for a, ids, _t in _shares(sending)] == [("family", [plain])]
    assert 'data-hold="sensitive"' in doc.get("/labs/results/to-see").get_data(as_text=True)


def test_only_a_doctor_says_seen(sending):
    oid = _answered(sending)
    desk = sending["sign_in"]("desk")
    assert desk.get("/labs/results/to-see").status_code == 403
    boss = sending["sign_in"]("boss")                       # runs the lab, not a doctor
    page = boss.get("/labs/results/to-see?scope=all").get_data(as_text=True)
    assert f'data-see-row="{oid}"' in page and "data-seen-form" in page
    boss.post("/labs/results/seen", data={"order": [oid]})
    assert _shares(sending) == []


def test_the_link_asks_the_birth_date_and_shows_the_report_as_written(sending):
    from app.models import ResultShare

    oid = _answered(sending)
    sending["sign_in"]("doc").post("/labs/results/seen", data={"order": [oid]})
    token = _shares(sending)[0][2]
    anon = sending["app"].test_client()
    page = anon.get(f"/labs/r/{token}").get_data(as_text=True)
    # Before the date: not the child's name, not a result.
    assert "data-public-ask" in page and "سليم" not in page and "P1" not in page
    assert "data-card" not in page
    wrong = anon.post(f"/labs/r/{token}", data={"born": "2024-02-02"}).get_data(as_text=True)
    assert "data-public-wrong" in wrong and "data-card" not in wrong
    right = anon.post(f"/labs/r/{token}", data={"born": BORN}).get_data(as_text=True)
    assert f'data-card="{oid}"' in right and "data-result-sheet" in right
    assert "سليم وجدي" in right
    with sending["app"].app_context():
        share = ResultShare.query.one()
        assert share.opens == 1 and share.opened_at is not None and share.failures == 1
    # The order page says it was opened.
    order = sending["sign_in"]("boss").get(f"/labs/order/{oid}").get_data(as_text=True)
    assert 'data-share-log="family"' in order and "data-share-opened" in order


def test_five_wrong_answers_lock_it_and_an_old_link_ends(sending):
    from app.models import ResultShare

    oid = _answered(sending)
    sending["sign_in"]("doc").post("/labs/results/seen", data={"order": [oid]})
    token = _shares(sending)[0][2]
    anon = sending["app"].test_client()
    for _ in range(5):
        anon.post(f"/labs/r/{token}", data={"born": "2020-01-01"})
    locked = anon.post(f"/labs/r/{token}", data={"born": BORN})
    assert locked.status_code == 410 and "data-card" not in locked.get_data(as_text=True)
    with sending["app"].app_context():
        share = ResultShare.query.one()
        share.failures, share.expires_at = 0, datetime.utcnow() - timedelta(minutes=1)
        sending["db"].session.commit()
    assert anon.post(f"/labs/r/{token}", data={"born": BORN}).status_code == 410
    assert anon.get("/labs/r/not-a-real-token").status_code == 404


def test_the_referring_doctor_gets_the_same_link(sending):
    oid = _answered(sending)
    doc = sending["sign_in"]("doc")
    page = doc.get(f"/labs/order/{oid}").get_data(as_text=True)
    assert "data-to-doctor-form" in page
    reply = doc.post("/labs/results/to-doctor",
                     data={"order": [oid], "doctor_id": sending["ext"], "back": "order"})
    assert reply.status_code == 200 and "01112223334"[-7:] in reply.get_data(as_text=True)
    shares = _shares(sending)
    assert [(a, ids) for a, ids, _t in shares] == [("doctor", [oid])]
    anon = sending["app"].test_client()
    assert "data-public-ask" in anon.get(f"/labs/r/{shares[0][2]}").get_data(as_text=True)
    # Not to a doctor without a phone, and never a held result.
    crit = _answered(sending, critical=True)
    doc.post("/labs/results/to-doctor", data={"order": [crit], "doctor_id": sending["ext"]})
    assert len(_shares(sending)) == 1


def test_the_bell_and_the_results_page_lead_to_the_list(sending):
    _answered(sending)
    doc = sending["sign_in"]("doc")
    page = doc.get("/visits/results").get_data(as_text=True)
    assert "data-to-results-to-see" in page
    with sending["app"].app_context():
        from app.utils import lab_share
        assert lab_share.to_see_count() == 1


# ----------------------------------------------- the report, and paper --
def test_the_report_is_cards_with_the_labs_flags_bars_and_earlier_values(sending):
    """«عايز منظر التحليل أفضل والشكل يكون تفاعلي» — and printable, «ده حق
    المريض». Each value on a bar against the lab's own reference, the arrow
    from the lab's flag, the child's earlier values behind a tap, a summary,
    a filter, and a print button."""
    from app.models import VisitInvestigation
    from app.utils import lab_cards, lab_share

    before = _answered(sending, minutes_ago=60 * 24 * 30)
    now = _answered(sending)
    with sending["app"].app_context():
        for oid, value in ((before, 13.0), (now, 10.0)):
            row = sending["db"].session.get(VisitInvestigation, oid)
            row.result_value, row.result_low, row.result_high, row.result_unit = value, 11.5, 15.5, "g/dL"
        sending["db"].session.commit()
        row = sending["db"].session.get(VisitInvestigation, now)
        cards, summary = lab_cards.cards([row])
        line = cards[0]["lines"][0]
        assert line["flag"] == "low" and line["bar"]["at"] < line["bar"]["band"][0]
        assert [v for _d, v in line["history"]] == [13.0, 10.0]
        assert summary == {"tests": 1, "readings": 1, "flagged": 1}
        assert "↓" in lab_cards.numbers_text([row])
    with sending["app"].test_request_context():
        row = sending["db"].session.get(VisitInvestigation, now)
        page = lab_share.sheet([row], row.patient)
    assert "built-in" not in page and "{" not in page.split("<body>")[1].split("<script>")[0]
    for mark in ('data-line-flag="low"', "bar__dot low", "data-history", "data-sum-flagged=\"1\"",
                 'data-show="out"', "data-print", "@media print"):
        assert mark in page, mark
    # Self-contained: nothing fetched from anywhere, so the file opens offline.
    assert "<link " not in page and "src=\"http" not in page and "url(" not in page


# ------------------------------------------ when the clinic is not online --
def _offline(lab):
    from app.models import Setting

    with lab["app"].app_context():
        Setting.set("wa_public_base_url", "")
        lab["db"].session.commit()


def test_offline_the_family_gets_the_report_as_a_file(sending):
    from app.models import MessageLog

    _offline(sending)
    oid = _answered(sending)
    doc = sending["sign_in"]("doc")
    assert "data-offline-hint" in doc.get("/labs/results/to-see").get_data(as_text=True)
    reply = doc.post("/labs/results/seen", data={"order": [oid]}).get_data(as_text=True)
    assert "data-download-file" in reply and "data-open-whatsapp" in reply
    assert "/labs/r/" not in reply                         # no link that opens nothing
    shares = _shares(sending)
    assert [(a, ids) for a, ids, _t in shares] == [("family", [oid])]
    with sending["app"].app_context():
        from app.models import ResultShare
        share = ResultShare.query.one()
        assert share.mode == "file"
        assert MessageLog.query.one().template_type == "lab_result_file"
        sid = share.id
    got = doc.get(f"/labs/results/file/{sid}")
    assert got.status_code == 200 and "attachment" in got.headers["Content-Disposition"]
    assert ".html" in got.headers["Content-Disposition"]
    assert f'data-card="{oid}"' in got.get_data(as_text=True)
    order = sending["sign_in"]("boss").get(f"/labs/order/{oid}").get_data(as_text=True)
    assert 'data-share-mode="file"' in order and "data-share-file" in order
    # Nobody else downloads it.
    assert sending["sign_in"]("desk").get(f"/labs/results/file/{sid}").status_code == 403


def test_offline_the_referring_doctor_gets_the_numbers_and_the_file(sending):
    from app.models import MessageLog

    _offline(sending)
    oid = _answered(sending)
    reply = sending["sign_in"]("doc").post(
        "/labs/results/to-doctor", data={"order": [oid], "doctor_id": sending["ext"]})
    assert "data-download-file" in reply.get_data(as_text=True)
    with sending["app"].app_context():
        log = MessageLog.query.one()
        assert log.template_type == "lab_result_doctor_file"
        assert "12" in log.body and "/labs/r/" not in log.body


def test_offline_through_the_cloud_api_the_file_goes_by_itself(sending, monkeypatch):
    """Uploaded to Meta, then sent as a document — no link to the clinic."""
    import json

    from app.models import MessageLog, Setting
    from app.utils import whatsapp as wa

    _offline(sending)
    with sending["app"].app_context():
        for key, value in (("crm_mode", "automatic"), ("wa_provider", "cloud_api"),
                           ("wa_cloud_token", "t"), ("wa_cloud_phone_id", "123")):
            Setting.set(key, value)
        sending["db"].session.commit()
    sent = {}

    def upload(url, fields, field, data, name, ctype, headers, timeout=20):
        sent["upload"] = (url, name, data[:15])
        return 200, json.dumps({"id": "MEDIA1"})

    def post(url, payload, headers, timeout=20):
        sent["message"] = payload
        return 200, json.dumps({"messages": [{"id": "wamid.1"}]})

    monkeypatch.setattr(wa, "_post_multipart_bytes", upload)
    monkeypatch.setattr(wa, "_post_json", post)
    oid = _answered(sending)
    reply = sending["sign_in"]("doc").post("/labs/results/seen", data={"order": [oid]})
    assert reply.status_code == 302                         # nothing to press
    assert sent["upload"][0].endswith("/123/media") and sent["upload"][2].startswith(b"<!doctype html")
    assert sent["message"]["type"] == "document" and sent["message"]["document"]["id"] == "MEDIA1"
    with sending["app"].app_context():
        assert MessageLog.query.one().status == "sent"


def test_a_test_of_several_values_shows_each_on_its_bar(bench):
    """A blood count: each analyte its own line, the flag the laboratory's
    approved range gave it, and a line with only a draft range unflagged."""
    from app.models import VisitInvestigation
    from app.utils import lab_cards

    oid = order_cbc(bench, collected_minutes_ago=30)
    _post(bench, oid, hb="9.8", plt="300")
    with bench["app"].app_context():
        row = bench["db"].session.get(VisitInvestigation, oid)
        cards, summary = lab_cards.cards([row])
        lines = {ln["name"]: ln for ln in cards[0]["lines"]}
        assert lines["Hemoglobin"]["flag"] == "low" and lines["Hemoglobin"]["bar"]
        assert lines["Hemoglobin"]["ref"] == "10.5 – 13.5"
        assert not lines["Platelets"]["flag"]            # a draft range calls nothing
        assert summary["flagged"] == 1


def test_both_languages_are_inside_one_opens_and_the_other_is_a_press_away(sending):
    """«اللغة اللي هتتبعت بيها … ممكن الأهل عربي أو إنجليزي» — the family's
    file opens in Arabic, the referring doctor's in English, and each has
    the other behind «عربي | English»."""
    from app.models import ResultShare

    _offline(sending)
    oid = _answered(sending)
    doc = sending["sign_in"]("doc")
    doc.post("/labs/results/seen", data={"order": [oid]})
    doc.post("/labs/results/to-doctor", data={"order": [oid], "doctor_id": sending["ext"]})
    with sending["app"].app_context():
        family, doctor = [s.id for s in ResultShare.query.order_by(ResultShare.id)]
    for sid, opens, other in ((family, "ar", "en"), (doctor, "en", "ar")):
        page = doc.get(f"/labs/results/file/{sid}").get_data(as_text=True)
        assert f'data-open-lang="{opens}"' in page
        assert f'data-lang="{opens}" lang="{opens}"' in page
        assert f'data-lang="{other}" lang="{other}" dir="{"ltr" if other == "en" else "rtl"}" hidden' in page
        assert 'data-lang-to="ar"' in page and 'data-lang-to="en"' in page
    assert "نتيجة التحاليل" in page and "Lab results" in page
