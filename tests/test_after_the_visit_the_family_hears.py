"""متابعة الأهل بعد الكشف (DOCTOR_EASE_PLAN.md ب-٦).

* «ابعت التعليمات للأهل»: كلام الطبيب نفسه، دلوقتي، على قناة الأهل لو الرد
  لسه مسموح فيها وإلا واتساب؛ ومن غير تعليمات محفوظة ما بيتبعتش؛
* تذكير بميعاد المتابعة قبلها بيوم — وساعة ما ييجي وقته بيتقرا تاني: اللي حجز
  أو جه مش بيتفكّر؛
* «الطفل عامل إيه؟» بعد كام يوم؛ والاتنين المتجدولين محتاجين الإرسال التلقائي
  شغال — رابط متجدول لبكرة محدش واقف قدامه؛
* كل رسالة مربوطة بالزيارة ومكتوبة في كارت المتابعة، وبتتلغي.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _automatic(clinic, types=("followup_due", "visit_checkin")):
    from app.models import MessageTemplate, Setting
    from app.utils.whatsapp import seed_system_templates

    seed_system_templates()
    Setting.set("crm_mode", "automatic")
    Setting.set("wa_provider", "cloud_api")
    for ttype in types:
        tpl = MessageTemplate.query.filter_by(occasion=ttype, is_system=True).first()
        tpl.send_mode, tpl.is_active = "auto", True
    clinic["db"].session.commit()


def _visit(clinic, due_in=None, instructions="سوائل كتير، والمضاد الحيوي ٧ أيام"):
    from app.models import Patient, Visit
    from app.utils.clock import local_today

    db = clinic["db"]
    v = db.session.get(Visit, clinic["ids"]["visit"])
    v.followup_instructions = instructions
    v.followup_due = (local_today() + timedelta(days=due_in)) if due_in else None
    p = db.session.get(Patient, v.patient_id)
    if not p.contact_phone:
        p.own_phone = "01000000001"
    db.session.commit()
    return v


def _post(clinic, **form):
    return clinic["sign_in"]("doc").post(f"/visits/{clinic['ids']['visit']}/aftercare", data=form)


def test_the_instructions_go_now_as_the_doctor_wrote_them(clinic):
    from app.models import MessageLog

    with clinic["app"].app_context():
        _visit(clinic, due_in=7)
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-aftercare" in page and "data-ac-instructions" in page
    _post(clinic, action="instructions")
    with clinic["app"].app_context():
        log = MessageLog.query.filter_by(template_type="visit_instructions").one()
        assert log.visit_id == clinic["ids"]["visit"]
        assert "سوائل كتير، والمضاد الحيوي ٧ أيام" in log.body and "ميعاد المتابعة" in log.body
        # Manual mode: a link for a person to press, shown on the card.
        assert log.status in ("link", "sent", "queued")
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'data-ac-log="visit_instructions"' in page
    # No instructions saved: nothing is sent.
    with clinic["app"].app_context():
        _visit(clinic, instructions="")
    _post(clinic, action="instructions")
    with clinic["app"].app_context():
        assert MessageLog.query.filter_by(template_type="visit_instructions").count() == 1


def test_on_the_family_s_own_channel_when_a_reply_is_still_allowed(clinic, monkeypatch):
    from app.models import MessageLog
    from app.utils import aftercare, inbox, social_outbound

    with clinic["app"].app_context():
        v = _visit(clinic)
        monkeypatch.setattr(inbox, "reply_channel", lambda key: "telegram")
        seen = {}

        def fake_reply(key, channel, body, **kw):
            seen.update(key=key, channel=channel, automated=kw.get("automated"))
            row = MessageLog(patient_id=v.patient_id, body=body, direction="out",
                             channel=channel, provider=channel, status="sent",
                             template_type=kw.get("template_type"))
            clinic["db"].session.add(row)
            return row, None

        monkeypatch.setattr(social_outbound, "reply", fake_reply)
        from app.models import User
        log = aftercare.send_instructions(v, User.query.filter_by(username="doc").one())
        assert seen == {"key": f"p{v.patient_id}", "channel": "telegram", "automated": True}
        assert log.channel == "telegram" and log.visit_id == v.id


def test_the_follow_up_reminder_is_dropped_once_they_book(clinic):
    from app.models import Appointment, MessageLog
    from app.utils import aftercare
    from app.utils import whatsapp as wa
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        _automatic(clinic)
        _visit(clinic, due_in=6)
    # Manual mode refuses to queue — tested by switching one type back.
    _post(clinic, action="due")
    with clinic["app"].app_context():
        log = MessageLog.query.filter_by(template_type="followup_due").one()
        assert log.status == "scheduled" and log.visit_id == clinic["ids"]["visit"]
        assert aftercare.still_wanted(log)
        due_day = local_today() + timedelta(days=5)
        assert log.scheduled_at.date() in (due_day, due_day - timedelta(days=1))
        # They book.
        v = log.visit_id
        from app.models import Visit
        visit = clinic["db"].session.get(Visit, v)
        clinic["db"].session.add(Appointment(
            patient_id=visit.patient_id, doctor_id=visit.doctor_id,
            appt_date=local_today() + timedelta(days=6), status="scheduled",
            appt_time=datetime.now().time().replace(microsecond=0)))
        clinic["db"].session.commit()
        assert not aftercare.still_wanted(log)
        log.scheduled_at = datetime.utcnow() - timedelta(minutes=1)
        clinic["db"].session.commit()
        wa.dispatch_due()
        assert clinic["db"].session.get(MessageLog, log.id).status == "skipped"
        assert clinic["db"].session.get(MessageLog, log.id).error == "not_needed"


def test_the_check_in_needs_automatic_sending_and_can_be_cancelled(clinic):
    from app.models import MessageLog

    with clinic["app"].app_context():
        _visit(clinic)
    _post(clinic, action="checkin", days="3")          # manual mode: nothing queued
    with clinic["app"].app_context():
        assert MessageLog.query.filter_by(template_type="visit_checkin").count() == 0
        _automatic(clinic)
    _post(clinic, action="checkin", days="3")
    with clinic["app"].app_context():
        log = MessageLog.query.filter_by(template_type="visit_checkin").one()
        assert log.status == "scheduled" and "عامل إيه" in log.body
    page = clinic["sign_in"]("doc").get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert "data-ac-checkin-queued" in page
    _post(clinic, action="cancel_checkin")
    with clinic["app"].app_context():
        assert MessageLog.query.filter_by(template_type="visit_checkin").count() == 0
