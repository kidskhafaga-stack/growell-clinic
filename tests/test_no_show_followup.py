"""The child who did not come — and the one message that must not go out.

**Measured before building:** ``no_show`` is a terminal status in
``appointment.py``, and every use of it in the program is a report filter or a
percentage. Nothing was ever sent. The clinic has the family's number and knows
which doctor they were booked with, and did nothing with either.

**The rule these tests spend most of their length on is the rebooking.** A
family that misses an appointment very often rings the same afternoon, and
reception books them in. If the follow-up is still sitting in the queue, the
clinic then asks them to book an appointment they have already booked — which
reads as nobody in the clinic talking to anybody else.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TYPE = "no_show_followup"


@pytest.fixture()
def clinic_auto(clinic):
    """A clinic that sends by itself, with a number on the child's file."""
    with clinic["app"].app_context():
        from app.models import DoctorSchedule, MessageTemplate, Patient, Setting
        from app.utils.whatsapp import seed_system_templates

        seed_system_templates()
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        for occ in (TYPE, "appointment_reminder"):
            tpl = MessageTemplate.query.filter_by(occasion=occ, is_system=True).first()
            tpl.send_mode = "auto"
            tpl.is_active = True
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01012345678"
        for weekday in range(7):
            clinic["db"].session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=30, is_active=True))
        clinic["db"].session.commit()
    return clinic


def _missed(clinic, days_ahead=2):
    """An appointment booked through the screen, then marked no-show."""
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        on_date = local_today() + timedelta(days=days_ahead)
    client = clinic["sign_in"]("desk")
    client.post("/appointments/new", data={
        "patient_id": clinic["ids"]["child"],
        "doctor_id": clinic["ids"]["doctor"],
        "appt_date": on_date.isoformat(), "appt_time": "10:00",
        "appt_type": "new", "reason": "متابعة",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id

    client.post(f"/appointments/{appt_id}/status",
                data={"status": "no_show", "cancel_reason": ""},
                follow_redirects=True)
    return client, appt_id


def _followups(clinic):
    from app.models import MessageLog
    return MessageLog.query.filter_by(template_type=TYPE).all()


def test_a_missed_appointment_now_reaches_the_family(clinic_auto):
    """The gap: no_show fed the reports and stopped there."""
    _missed(clinic_auto)

    with clinic_auto["app"].app_context():
        rows = _followups(clinic_auto)
        assert len(rows) == 1, "nothing was sent to the family who did not come"
        assert rows[0].status == "scheduled"


def test_it_waits_rather_than_landing_while_they_are_still_in_traffic(clinic_auto):
    """Immediate would read as a rebuke, not an offer.

    A family sitting in the jam that made them miss the appointment does not
    need the clinic's message at that moment.
    """
    _missed(clinic_auto)

    with clinic_auto["app"].app_context():
        row = _followups(clinic_auto)[0]
        assert row.scheduled_at > datetime.utcnow() + timedelta(hours=1)


def test_the_clinic_sets_the_wait_on_the_template_like_every_other_delay(clinic_auto):
    """Here the template's own delay columns mean exactly what they say.

    Unlike the reminder — whose lead time had to become a separate setting
    because "before the appointment" is not a delay — this fires *after* an
    event, which is what ``delay_hours`` means everywhere else in the program.
    """
    with clinic_auto["app"].app_context():
        from app.models import MessageTemplate
        tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
        tpl.delay_days = 1
        tpl.delay_hours = 0
        clinic_auto["db"].session.commit()

    _missed(clinic_auto)

    with clinic_auto["app"].app_context():
        row = _followups(clinic_auto)[0]
        assert row.scheduled_at > datetime.utcnow() + timedelta(hours=20)


def test_rebooking_stops_the_message_before_it_goes(clinic_auto):
    """The rule this feature lives or dies by.

    They missed Tuesday, rang, and reception booked them for Thursday. The
    queued "shall we book you in?" is now the clinic asking for something it
    has already done — and it reads as nobody there talking to anybody else.
    """
    from app.utils.clock import local_today

    client, _ = _missed(clinic_auto)
    with clinic_auto["app"].app_context():
        assert len(_followups(clinic_auto)) == 1
        later = local_today() + timedelta(days=9)

    client.post("/appointments/new", data={
        "patient_id": clinic_auto["ids"]["child"],
        "doctor_id": clinic_auto["ids"]["doctor"],
        "appt_date": later.isoformat(), "appt_time": "11:00",
        "appt_type": "new", "reason": "متابعة",
    }, follow_redirects=True)

    with clinic_auto["app"].app_context():
        assert _followups(clinic_auto) == [], (
            "the family rebooked and is still being asked to book")


def test_two_missed_visits_do_not_become_two_messages(clinic_auto):
    """A family with two missed visits is one conversation, not two.

    Two identical messages within the hour is how a clinic's number stops
    being read at all.

    Scheduled directly rather than through two bookings: booking *clears* a
    pending follow-up, so a test that books in between passes with the guard
    deleted — which is exactly what the first version of this did. (Found by
    deleting the guard and watching the file stay green.)
    """
    _missed(clinic_auto, days_ahead=2)

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        from app.utils.no_show import schedule
        db = clinic_auto["db"]
        assert len(_followups(clinic_auto)) == 1

        second = Appointment(
            patient_id=clinic_auto["ids"]["child"],
            doctor_id=clinic_auto["ids"]["doctor"],
            appt_date=_followups(clinic_auto)[0].created_at.date(),
            appt_time=time(16, 0), duration_minutes=15, status="no_show")
        db.session.add(second)
        db.session.commit()

        assert schedule(second) is None, "the family was queued a second message"
        db.session.commit()
        assert len(_followups(clinic_auto)) == 1


def test_only_a_missed_visit_triggers_it_whoever_calls(clinic_auto):
    """The guard belongs to the function, not to the one route that calls it.

    The status route already checks before calling, so removing the check
    inside ``schedule`` leaves every other test here green. A batch over
    yesterday's diary — the obvious next caller — would then message everybody
    who came.
    """
    _missed(clinic_auto)

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        from app.utils.no_show import cancel_for_patient, schedule
        db = clinic_auto["db"]
        cancel_for_patient(clinic_auto["ids"]["child"])
        db.session.commit()

        for status in ("completed", "scheduled", "cancelled", "waiting"):
            appt = Appointment(
                patient_id=clinic_auto["ids"]["child"],
                doctor_id=clinic_auto["ids"]["doctor"],
                appt_date=datetime.utcnow().date(), appt_time=time(9, 0),
                duration_minutes=15, status=status)
            db.session.add(appt)
            db.session.flush()
            assert schedule(appt) is None, f"'{status}' was treated as a no-show"
        db.session.commit()
        assert _followups(clinic_auto) == []


def test_cancelling_is_not_missing(clinic_auto):
    """A family who told the clinic they could not come did the right thing.

    Following that up with "we missed you" punishes exactly the behaviour the
    clinic wants, so only ``no_show`` triggers it.
    """
    from app.utils.clock import local_today

    with clinic_auto["app"].app_context():
        on_date = local_today() + timedelta(days=3)
    client = clinic_auto["sign_in"]("desk")
    client.post("/appointments/new", data={
        "patient_id": clinic_auto["ids"]["child"],
        "doctor_id": clinic_auto["ids"]["doctor"],
        "appt_date": on_date.isoformat(), "appt_time": "12:00",
        "appt_type": "new", "reason": "متابعة",
    }, follow_redirects=True)
    with clinic_auto["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id

    client.post(f"/appointments/{appt_id}/status",
                data={"status": "cancelled", "cancel_reason": "سفر"},
                follow_redirects=True)

    with clinic_auto["app"].app_context():
        assert _followups(clinic_auto) == []


def test_nothing_is_queued_when_the_clinic_sends_by_hand(clinic_auto):
    """Same rule as the reminder: a scheduled click-to-send link is not a
    message, it is a row that looks like one."""
    with clinic_auto["app"].app_context():
        from app.models import Setting
        Setting.set("crm_mode", "manual")
        clinic_auto["db"].session.commit()

    _missed(clinic_auto)

    with clinic_auto["app"].app_context():
        assert _followups(clinic_auto) == []


def test_the_wording_offers_rather_than_scolds(clinic):
    """A family misses an appointment because a child got worse, or better, or
    because the day fell apart — none of which the clinic knows.

    So the text must not imply fault, and must give them something to do.
    """
    from app.models import TEMPLATE_DEFAULTS

    body = TEMPLATE_DEFAULTS[TYPE]
    assert "ردّوا" in body or "احجز" in body or "هنحجز" in body
    for scolding in ("للأسف", "تخلفتم", "لم تحضروا", "غياب"):
        assert scolding not in body


def test_the_template_ships_with_every_installation(clinic):
    """``seed_system_templates`` runs on every ``upgrade-db``, which is what
    ``update.bat`` calls — so this reaches the clinics already running."""
    with clinic["app"].app_context():
        from app.models import MessageTemplate
        from app.utils.whatsapp import seed_system_templates

        seed_system_templates()
        tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
        assert tpl is not None and tpl.body.strip()
