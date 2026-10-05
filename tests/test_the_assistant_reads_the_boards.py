"""The assistant on the medical and management boards, and the doors to them.

Reported from a running clinic: «الشاشة دي كنت طلبت تعديلات عليها … مش شايف
التعديل» — the medical board had been built under the reports while every
door still opened the old analytics page; and «شاشة مرضايا مش ظاهرة اوصلها
منين». Then: «عايز ادخل الذكاء الصناعي فى التحليل».

* «تحليل المرضى» opens the medical board for whoever can open the reports,
  and the old page for anybody else;
* «مرضايا» is in the sidebar for whoever the boards' tab shows it to;
* the assistant reads a board, or answers a question about it, only when the
  clinic switched it on — from the board's figures, never a child's name or
  file number, with doctors as codes put back to names on this side; and
  nothing of its reply is kept.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_medical_board import _child, _seen  # noqa: E402
from tests.test_which_part_of_the_clinic_earned_it import (  # noqa: E402,F401
    _invoice, books)


def _ai(c, boards=True):
    from app.models import Setting

    with c["app"].app_context():
        for key, value in (("ai_enabled", "1"), ("ai_provider", "claude"),
                           ("ai_api_key", "test-key"), ("ai_model", "test-model"),
                           ("ai_boards", "1" if boards else "0")):
            Setting.set(key, value)
        c["db"].session.commit()


@pytest.fixture()
def asked(monkeypatch):
    from app.utils import ai

    calls = []

    def fake_chat(messages, system=None, config=None, feature=None):
        calls.append({"text": messages[0]["content"], "system": system,
                      "feature": feature})
        return {"ok": True, "text": "- [D1] رأى أكتر حالات الفترة دي."}

    monkeypatch.setattr(ai, "chat", fake_chat)
    return calls


# ------------------------------------------------------------- the doors --
def test_the_analytics_door_opens_the_medical_board(clinic):
    boss = clinic["sign_in"]()
    got = boss.get("/patients/analytics?days=90")
    assert got.status_code == 302
    assert "/reports/medical" in got.headers["Location"]
    assert "preset=90" in got.headers["Location"]
    # Somebody without the reports keeps the page they had.
    from app.models import User
    from app.models.role import Role

    with clinic["app"].app_context():
        role = Role(name="patients_only", label_ar="ملفات", label_en="Files",
                    modules="patients")
        clinic["db"].session.add(role)
        user = User(username="files", full_name="الملفات", role="patients_only",
                    is_active=True)
        user.set_password("secret")
        clinic["db"].session.add(user)
        clinic["db"].session.commit()
    page = clinic["sign_in"]("files").get("/patients/analytics")
    assert page.status_code == 200


def test_my_patients_is_in_the_sidebar_for_whoever_the_tab_shows_it_to(clinic):
    page = clinic["sign_in"]("doc").get("/dashboard").get_data(as_text=True)
    assert "data-nav-mine" in page
    page = clinic["sign_in"]("desk").get("/dashboard").get_data(as_text=True)
    assert "data-nav-mine" not in page


# --------------------------------------------------------- the assistant --
def test_off_until_the_clinic_turns_it_on(clinic, asked):
    page = clinic["sign_in"]().get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-board-ai-read" not in page and "data-board-ai-off" in page
    _ai(clinic, boards=False)
    got = clinic["sign_in"]().post("/reports/medical/ai?preset=30",
                                   data={"read": "1"}).get_data(as_text=True)
    assert asked == [] and "data-board-ai-error" in got
    _ai(clinic)
    page = clinic["sign_in"]().get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-board-ai-read" in page and "data-board-ai-off" not in page


def test_the_medical_board_is_read_from_its_figures_and_no_child(clinic, asked):
    _ai(clinic)
    child = _child(clinic, "Z9", gender="female")
    for _ in range(3):
        _seen(clinic, child, days_ago=2,
              dx=[("J20.9", "10", "Acute bronchitis", "final")])
    _seen(clinic, child, days_ago=3, dx=[(None, None, "سخونية 0123456789", "final")])
    page = clinic["sign_in"]().post("/reports/medical/ai?preset=30",
                                    data={"read": "1"}).get_data(as_text=True)
    (call,) = asked
    assert call["feature"] == "board_read"
    sent = call["text"]
    assert "J20.9" in sent and "visits: 5" in sent
    # Nothing a child can be found by, and the doctor as a code.
    for private in ("طفل Z9", "Z9", "0123456789", "د. أحمد"):
        assert private not in sent
    assert "[D1]" in sent
    # The reply comes back with the doctor's name, marked as the assistant's.
    assert "data-board-ai-reply" in page and "د. أحمد" in page
    assert "[D1]" not in page.split("data-board-ai-reply")[1]
    with clinic["app"].app_context():
        from app.models import ActivityLog

        assert ActivityLog.query.filter_by(action="ai.board_medical").count() == 1


def test_a_question_is_sent_with_the_figures_and_kept_nowhere(clinic, asked):
    _ai(clinic)
    page = clinic["sign_in"]().post(
        "/reports/medical/ai?preset=30",
        data={"ask": "1", "question": "ليه الزيارات قلّت؟"}).get_data(as_text=True)
    assert "ليه الزيارات قلّت؟" in asked[0]["text"]
    assert "never invent a number" in asked[0]["system"]
    assert "data-board-ai-reply" in page
    # A plain load shows the board without any reply: nothing was kept.
    again = clinic["sign_in"]().get("/reports/medical?preset=30").get_data(as_text=True)
    assert "data-board-ai-reply" not in again


def test_the_management_board_is_read_behind_its_capability(books, asked):
    _ai(books)
    _invoice(books, [("exam", 200, {}), ("lab", 100, {})], number="P1")
    page = books["sign_in"]("acct").post("/reports/management/ai?preset=30",
                                         data={"read": "1"}).get_data(as_text=True)
    assert "data-board-ai-reply" in page
    sent = asked[0]["text"]
    assert "revenue:" in sent and "Departments" in sent
    assert books["sign_in"]("doc").post("/reports/management/ai?preset=30",
                                        data={"read": "1"}).status_code in (302, 403)
    assert len(asked) == 1


def test_a_failed_call_says_why_in_words(clinic, monkeypatch):
    from app.utils import ai

    _ai(clinic)
    monkeypatch.setattr(ai, "chat",
                        lambda *a, **k: {"ok": False, "error": "err_quota"})
    page = clinic["sign_in"]().post("/reports/medical/ai?preset=30",
                                    data={"read": "1"}).get_data(as_text=True)
    assert "data-board-ai-error" in page and "err_quota" not in page


def test_every_feature_the_assistant_is_called_for_has_a_name_on_the_usage_screen():
    """The usage screen names each feature by ``ai.feature_<name>``; four
    were spent and shown as their raw keys before the boards added a fifth."""
    import json
    import re

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
    used = set()
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    used |= set(re.findall(r'feature="([a-z_]+)"', fh.read()))
    assert "board_read" in used and "lab_read" in used
    for lang in ("ar", "en"):
        with open(os.path.join(root, "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            names = json.load(fh)["ai"]
        assert not {f for f in used if f"feature_{f}" not in names}, lang
