"""Answering patients: opening hours, the out-of-hours reply, canned answers.

The rules that matter here are the ones about restraint: the clinic says it is
closed *once*, not to every message; it says nothing at all when it can't
actually send; and the AI writes a draft, never a delivered reply.
"""
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Family, Parent, Patient, Setting

        fam = Family(family_name="عائلة")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, full_name="الأم",
                              relation="mother", phone="01000000001"))
        child = Patient(patient_number="S1", full_name="طفل", gender="male",
                        date_of_birth=date(2019, 1, 1), family_id=fam.id)
        db.session.add(child)
        # Sat–Thu, 16:00–22:00, automatic sending on.
        Setting.set("wa_away_enabled", "1")
        Setting.set("wa_open_days", "5,6,0,1,2,3")
        Setting.set("wa_open_from", "16:00")
        Setting.set("wa_open_to", "22:00")
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "wapilot")
        Setting.set("clinic_name", "جروويل")
        db.session.commit()
        yield {"app": app, "db": db, "child": child}


# ------------------------------------------------------------------ hours --
@pytest.mark.parametrize("moment, expected", [
    (datetime(2026, 7, 25, 18, 0), True),    # Saturday evening, mid-shift
    (datetime(2026, 7, 25, 9, 0), False),    # Saturday morning, before opening
    (datetime(2026, 7, 25, 23, 30), False),  # Saturday, after closing
    (datetime(2026, 7, 24, 18, 0), False),   # Friday — closed all day
])
def test_opening_hours(clinic, moment, expected):
    from app.utils.service_desk import is_open

    with clinic["app"].app_context():
        assert is_open(moment) is expected


def test_an_evening_shift_may_run_past_midnight(clinic):
    """16:00 → 02:00 is an ordinary evening clinic, not a typo."""
    from app.models import Setting
    from app.utils.service_desk import is_open

    with clinic["app"].app_context():
        Setting.set("wa_open_to", "02:00")
        clinic["db"].session.commit()
        assert is_open(datetime(2026, 7, 25, 23, 30)) is True   # Sat night
        assert is_open(datetime(2026, 7, 26, 1, 0)) is True     # into Sunday
        assert is_open(datetime(2026, 7, 26, 3, 0)) is False    # after closing
        # Saturday 01:00 belongs to Friday's shift, and Friday is closed.
        assert is_open(datetime(2026, 7, 25, 1, 0)) is False


# ------------------------------------------------------------- away reply --
def _inbound(clinic, phone="01000000001", body="فيه حد؟"):
    from app.models import MessageLog

    row = MessageLog(direction="in", body=body, to_phone=phone, status="received",
                     patient_id=clinic["child"].id)
    clinic["db"].session.add(row)
    clinic["db"].session.flush()
    return row


def test_out_of_hours_the_clinic_answers_once(clinic, monkeypatch):
    """And only once — nobody should meet a robot that argues back."""
    from app.models import MessageLog
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: False)

        assert sd.maybe_send_away_reply(_inbound(clinic)) is not None
        clinic["db"].session.commit()
        assert sd.maybe_send_away_reply(_inbound(clinic)) is None

        sent = MessageLog.query.filter_by(template_type="away").all()
        assert len(sent) == 1
        assert "جروويل" in sent[0].body          # {clinic} was filled in


def test_during_working_hours_nothing_is_sent(clinic, monkeypatch):
    from app.models import MessageLog
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: True)
        assert sd.maybe_send_away_reply(_inbound(clinic)) is None
        assert MessageLog.query.filter_by(template_type="away").count() == 0


def test_the_cooldown_expires(clinic, monkeypatch):
    from app.models import MessageLog
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: False)
        sd.maybe_send_away_reply(_inbound(clinic))
        clinic["db"].session.commit()
        old = MessageLog.query.filter_by(template_type="away").one()
        old.created_at = datetime.utcnow() - timedelta(
            hours=sd.AWAY_COOLDOWN_HOURS + 1)
        clinic["db"].session.commit()
        assert sd.maybe_send_away_reply(_inbound(clinic)) is not None


def test_in_manual_mode_the_clinic_stays_quiet(clinic, monkeypatch):
    """Manual mode turns every message into a click-to-send link, and a link
    nobody is there to click at 1 a.m. is not an auto-reply."""
    from app.models import MessageLog, Setting
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: False)
        Setting.set("crm_mode", "manual")
        clinic["db"].session.commit()
        assert sd.maybe_send_away_reply(_inbound(clinic)) is None
        assert MessageLog.query.filter_by(template_type="away").count() == 0


def test_switched_off_means_off(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: False)
        Setting.set("wa_away_enabled", "0")
        clinic["db"].session.commit()
        assert sd.maybe_send_away_reply(_inbound(clinic)) is None


def test_a_rating_reply_gets_no_away_message(clinic, monkeypatch):
    """Answering "5" to a survey is not a question waiting for the clinic."""
    from app.models import Feedback, MessageLog
    from app.utils import service_desk as sd
    from app.utils.inbound import handle_inbound

    with clinic["app"].app_context():
        monkeypatch.setattr(sd, "is_open", lambda *a, **k: False)
        clinic["db"].session.add(Feedback(patient_id=clinic["child"].id,
                                          token=uuid.uuid4().hex,
                                          status="sent"))
        clinic["db"].session.commit()
        res = handle_inbound({"from_phone": "01000000001", "text": "5"}, "test")
        clinic["db"].session.commit()
        assert res["captured"] is True
        assert res["away"] is False
        assert MessageLog.query.filter_by(template_type="away").count() == 0


# ----------------------------------------------------------- quick replies --
def test_quick_replies_seed_once_and_stay_the_clinics_own(clinic):
    from app.models import QuickReply
    from app.utils.service_desk import quick_replies, seed_quick_replies

    with clinic["app"].app_context():
        assert seed_quick_replies() > 0
        clinic["db"].session.commit()
        before = QuickReply.query.count()
        assert seed_quick_replies() == 0        # never a second time
        QuickReply.query.first().is_active = False
        clinic["db"].session.commit()
        assert len(quick_replies()) == before - 1


def test_a_canned_answer_is_filled_in_before_it_is_offered(clinic):
    from app.utils.service_desk import render_reply

    with clinic["app"].app_context():
        out = render_reply("أهلاً {patient}، مواعيد {clinic}: {hours}",
                           clinic["child"])
        assert "طفل" in out and "جروويل" in out
        assert "{patient}" not in out and "{hours}" not in out


# ---------------------------------------------------------------- ai draft --
def test_the_ai_refuses_to_draft_when_it_is_our_turn_that_was_last(clinic):
    """Nothing new was asked, so a "reply" would just be filler."""
    from app.models import MessageLog
    from app.utils.service_desk import draft_reply

    with clinic["app"].app_context():
        msgs = [MessageLog(direction="out", body="أهلاً", to_phone="1",
                           created_at=datetime.utcnow())]
        assert draft_reply(msgs)["ok"] is False


def test_the_ai_draft_is_returned_not_sent(clinic, monkeypatch):
    from app.models import MessageLog
    from app.utils import ai
    from app.utils import service_desk as sd

    with clinic["app"].app_context():
        monkeypatch.setattr(ai, "is_ready", lambda: True)
        monkeypatch.setattr(ai, "chat",
                            lambda messages, system=None, config=None:
                            {"ok": True, "text": " اتفضل يا فندم "})
        msgs = [MessageLog(direction="in", body="مواعيدكم إيه؟", to_phone="1",
                           created_at=datetime.utcnow())]
        result = sd.draft_reply(msgs, clinic["child"])
        assert result == {"ok": True, "text": "اتفضل يا فندم"}
        # Drafting must not put anything on the wire.
        assert MessageLog.query.filter_by(direction="out").count() == 0


def test_without_ai_configured_the_button_says_so(clinic):
    from app.models import MessageLog
    from app.utils.service_desk import draft_reply

    with clinic["app"].app_context():
        msgs = [MessageLog(direction="in", body="سؤال", to_phone="1",
                           created_at=datetime.utcnow())]
        assert draft_reply(msgs)["error"] == "not_configured"


def test_the_hours_label_reads_like_a_human_wrote_it(clinic):
    from app.utils.service_desk import hours_label

    with clinic["app"].test_request_context("/"):
        label = hours_label()
        assert "السبت" in label and "16:00" in label and "22:00" in label


def test_time_parsing_survives_nonsense(clinic):
    """A malformed setting must fall back, not crash the webhook."""
    from app.models import Setting
    from app.utils.service_desk import _parse_time, hours_config, is_open

    with clinic["app"].app_context():
        Setting.set("wa_open_from", "not-a-time")
        Setting.set("wa_open_days", "")
        clinic["db"].session.commit()
        cfg = hours_config()
        assert cfg["days"]                       # fell back to the default set
        assert _parse_time(cfg["from"], "16:00") == time(16, 0)
        is_open(datetime(2026, 7, 25, 18, 0), cfg)   # must not raise
