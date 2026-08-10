"""The message that stops a family forgetting — and never sending a wrong one.

**The gap, measured before building.** ``SYSTEM_TEMPLATE_TYPES`` had no
``appointment_reminder``, and ``scheduled_at`` was never written from the
booking screen. The program had a *confirmation*, sent when the booking is
made — often weeks earlier — and by then it is a receipt. Nothing here had
ever reminded anybody about an appointment.

**Half of these tests are about not sending.** A reminder is a message the
clinic sends unprompted, to a family, about a specific hour. Every way of
getting that wrong is worse than silence: reminding somebody about a visit
they cancelled, telling them the hour it *used* to be at, sending twice, or
sending at 6 a.m. because the appointment's wall clock was read as UTC. So the
cancel/reschedule/duplicate/timezone cases carry as much weight here as the
happy path.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

TYPE = "appointment_reminder"


def _automatic(clinic):
    """A clinic whose messages actually leave by themselves.

    In manual mode every message is a click-to-send link, and a link scheduled
    for tomorrow morning is not a reminder — so nothing is queued at all. That
    is its own test below; the rest need the automatic case.
    """
    from app.models import MessageTemplate, Setting
    from app.utils.whatsapp import seed_system_templates

    seed_system_templates()
    Setting.set("crm_mode", "automatic")
    Setting.set("wa_provider", "cloud_api")
    tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
    tpl.send_mode = "auto"
    tpl.is_active = True
    clinic["db"].session.commit()
    return tpl


def _book(clinic, days_ahead=3, at=time(10, 0)):
    """A booking made through the screen reception actually uses."""
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        on_date = local_today() + timedelta(days=days_ahead)
    client = clinic["sign_in"]("desk")
    response = client.post("/appointments/new", data={
        "patient_id": clinic["ids"]["child"],
        "doctor_id": clinic["ids"]["doctor"],
        "appt_date": on_date.isoformat(),
        "appt_time": at.strftime("%H:%M"),
        "appt_type": "new",
        "reason": "متابعة",
    }, follow_redirects=True)
    assert response.status_code == 200
    return client, on_date


@pytest.fixture()
def clinic_auto(clinic):
    """A clinic set up to send, with a phone number on the child's file."""
    with clinic["app"].app_context():
        from app.models import DoctorSchedule, Patient
        _automatic(clinic)
        # ``contact_phone`` is derived (own number, else a guardian's), so the
        # number goes where a real file carries it.
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01012345678"
        # A working week, so the booking screen has slots to offer.
        for weekday in range(7):
            clinic["db"].session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=30, is_active=True))
        clinic["db"].session.commit()
    return clinic


def _reminders(clinic):
    from app.models import MessageLog
    return MessageLog.query.filter_by(template_type=TYPE).all()


# --- it exists at all ------------------------------------------------------

def test_booking_queues_a_reminder_before_the_appointment(clinic_auto):
    """The gap this closes, end to end through the booking screen."""
    _book(clinic_auto)

    with clinic_auto["app"].app_context():
        rows = _reminders(clinic_auto)
        assert len(rows) == 1, "booking queued no reminder"
        assert rows[0].status == "scheduled"
        assert rows[0].scheduled_at > datetime.utcnow()


def test_the_reminder_goes_out_a_day_before_in_the_clinics_own_clock(clinic_auto):
    """The conversion that is invisible from inside one timezone.

    The appointment is 10:00 on the clinic's wall clock; ``scheduled_at`` is
    compared against ``utcnow()``. Subtracting the lead time without converting
    would send the reminder off by exactly the clinic's offset — right, in
    Cairo, only for a machine that happens to be in Cairo.
    """
    from app.utils.clock import to_utc

    _, on_date = _book(clinic_auto, days_ahead=5, at=time(10, 0))

    with clinic_auto["app"].app_context():
        row = _reminders(clinic_auto)[0]
        expected = to_utc(datetime.combine(on_date, time(10, 0))) - timedelta(hours=24)
        assert row.scheduled_at == expected


def test_the_lead_time_is_the_clinics_to_set(clinic_auto):
    """Two hours before suits a clinic that books same-week; a day suits one
    that books a month out. Both are reasonable and neither is a default."""
    from app.models import Setting

    with clinic_auto["app"].app_context():
        Setting.set("wa_reminder_hours", "3")
        clinic_auto["db"].session.commit()

    _, on_date = _book(clinic_auto, days_ahead=4, at=time(14, 0))

    with clinic_auto["app"].app_context():
        from app.utils.clock import to_utc
        row = _reminders(clinic_auto)[0]
        expected = to_utc(datetime.combine(on_date, time(14, 0))) - timedelta(hours=3)
        assert row.scheduled_at == expected


@pytest.mark.parametrize("raw,hours", [
    ("", 24), ("nonsense", 24), ("0", 1), ("-5", 1), ("100000", 168),
])
def test_a_nonsense_lead_time_cannot_send_a_reminder_at_a_silly_moment(
        clinic_auto, raw, hours):
    """Settings are typed by people, and this one has no safe extremes.

    Zero means "at the appointment", which is not a reminder; a negative number
    means after it. Clamping keeps a mistyped box from becoming a message at
    the wrong hour rather than an exception on the booking screen.
    """
    from app.models import Setting
    from app.utils.appt_reminder import lead_hours

    with clinic_auto["app"].app_context():
        Setting.set("wa_reminder_hours", raw)
        clinic_auto["db"].session.commit()
        assert lead_hours() == hours


# --- and, mostly, it does not send the wrong thing -------------------------

def test_cancelling_the_visit_cancels_the_reminder(clinic_auto):
    """Otherwise the clinic tells a family to come to something that is not
    happening — the single worst message in this file."""
    client, _ = _book(clinic_auto)

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id
        assert len(_reminders(clinic_auto)) == 1

    client.post(f"/appointments/{appt_id}/status",
                data={"status": "cancelled", "cancel_reason": "سفر"},
                follow_redirects=True)

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == [], (
            "a reminder is still queued for a cancelled appointment")


def test_moving_the_visit_moves_the_reminder(clinic_auto):
    """A reminder naming the old hour is worse than none: the family reads it,
    believes it, and arrives when the doctor is with somebody else."""
    from app.utils.clock import local_today, to_utc

    client, _ = _book(clinic_auto, days_ahead=3, at=time(10, 0))

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id
        new_date = local_today() + timedelta(days=6)

    client.post(f"/appointments/{appt_id}/reschedule", data={
        "doctor_id": clinic_auto["ids"]["doctor"],
        "appt_date": new_date.isoformat(),
        "appt_time": "15:30",
    }, follow_redirects=True)

    with clinic_auto["app"].app_context():
        rows = _reminders(clinic_auto)
        assert len(rows) == 1, "rescheduling left two reminders queued"
        expected = to_utc(datetime.combine(new_date, time(15, 30))) - timedelta(hours=24)
        assert rows[0].scheduled_at == expected
        assert "15:30" in rows[0].body


def test_deleting_the_appointment_takes_its_reminder_with_it(clinic_auto):
    """A queued message outlives the row it points at.

    The appointment is deleted outright, but ``MessageLog`` keeps its own row
    and its own send time — so without this the reminder still goes out, to a
    family whose booking no longer exists anywhere in the program.
    """
    client, _ = _book(clinic_auto)

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id

    client.post(f"/appointments/{appt_id}/delete", follow_redirects=True)

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == []


def test_one_appointment_never_gets_two_reminders(clinic_auto):
    """Booking, then any later touch, must not stack messages.

    A family messaged twice about one visit stops reading the third.
    """
    client, _ = _book(clinic_auto)

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        appt_id = Appointment.query.order_by(Appointment.id.desc()).first().id

    # Status moves that keep the appointment alive must not stack messages…
    for status in ("waiting", "in_progress"):
        client.post(f"/appointments/{appt_id}/status", data={"status": status},
                    follow_redirects=True)

    with clinic_auto["app"].app_context():
        rows = _reminders(clinic_auto)
        assert len(rows) == 1, f"{len(rows)} reminders queued for one visit"

    # …and neither must queueing over a booking that already has one. This is
    # the backfill button pressed twice because the first press said nothing,
    # and it is the *only* path that reaches the duplicate guard: rescheduling
    # clears before it queues, so every other test here stays green with the
    # guard deleted. (Which is how this was found — twice.)
    with clinic_auto["app"].app_context():
        from app.models import Appointment
        from app.utils.appt_reminder import schedule
        appt = clinic_auto["db"].session.get(Appointment, appt_id)
        appt.status = "scheduled"
        clinic_auto["db"].session.commit()

        assert schedule(appt) is None, "a second reminder was queued"
        clinic_auto["db"].session.commit()
        assert len(_reminders(clinic_auto)) == 1


def test_nothing_is_queued_when_the_clinic_sends_by_hand(clinic_auto):
    """Manual mode makes every message a click-to-send link.

    A link scheduled for nine tomorrow morning is a link nobody is standing in
    front of: it would sit in the log looking like a reminder that went out.
    Better to queue nothing and say so once on the settings card.
    """
    from app.models import Setting

    with clinic_auto["app"].app_context():
        Setting.set("crm_mode", "manual")
        clinic_auto["db"].session.commit()

    _book(clinic_auto)

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == []


def test_nothing_is_queued_when_the_clinic_switched_the_type_off(clinic_auto):
    """The hub's on/off switch has to mean off here too, or the one place the
    clinic controls its messages stops being the one place."""
    with clinic_auto["app"].app_context():
        from app.models import MessageTemplate
        tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
        tpl.is_active = False
        clinic_auto["db"].session.commit()

    _book(clinic_auto)

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == []


def test_a_booking_for_later_today_gets_no_reminder(clinic_auto):
    """Its moment is already behind us.

    Sending it now would be a duplicate of the confirmation the family
    received thirty seconds ago, which reads as a mistake — because it is one.
    """
    _book(clinic_auto, days_ahead=0, at=time(23, 30))

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == []


def test_a_family_with_no_number_on_file_produces_no_failed_row(clinic_auto):
    """A file with no phone is an ordinary state, not a delivery failure.

    Queueing a doomed row per booking would fill the failures list — the place
    somebody looks to find real problems — with the same non-problem.
    """
    with clinic_auto["app"].app_context():
        from app.models import Patient
        child = clinic_auto["db"].session.get(Patient, clinic_auto["ids"]["child"])
        child.own_phone = None
        clinic_auto["db"].session.commit()

    _book(clinic_auto)

    with clinic_auto["app"].app_context():
        assert _reminders(clinic_auto) == []


# --- the clinics that already had a diary ----------------------------------

def test_the_appointments_already_booked_are_not_skipped(clinic_auto):
    """The week this is switched on, every appointment predates it.

    Without a backfill the feature "works" and reminds nobody for a fortnight,
    which is indistinguishable from being broken.
    """
    from app.utils.clock import local_today

    with clinic_auto["app"].app_context():
        from app.models import Appointment
        db = clinic_auto["db"]
        for offset in (1, 2, 3):
            db.session.add(Appointment(
                patient_id=clinic_auto["ids"]["child"],
                doctor_id=clinic_auto["ids"]["doctor"],
                appt_date=local_today() + timedelta(days=offset),
                appt_time=time(11, 0), duration_minutes=15,
                status="scheduled"))
        db.session.commit()

        from app.utils.appt_reminder import backfill
        made = backfill()
        assert made == 3, f"backfill queued {made} of 3 existing appointments"


def test_the_template_ships_with_every_installation(clinic):
    """A type with no seeded row is a switch that is not on the screen.

    ``seed_system_templates`` runs on every ``upgrade-db``, which is what
    ``update.bat`` calls — so this reaches clinics that already have the
    program, not only fresh installs.
    """
    with clinic["app"].app_context():
        from app.models import MessageTemplate
        from app.utils.whatsapp import seed_system_templates

        seed_system_templates()
        tpl = MessageTemplate.query.filter_by(occasion=TYPE, is_system=True).first()
        assert tpl is not None, "no template row for the reminder"
        assert tpl.body.strip(), "the reminder template shipped empty"


def test_the_default_text_does_not_say_tomorrow(clinic):
    """It is only tomorrow when the lead time happens to be 24 hours.

    Written that way first. A clinic setting three hours would have had the
    program telling families their appointment was "tomorrow" on the morning
    of the day itself — a message that is wrong because a *setting* changed,
    which is the kind of wrong nobody thinks to look for.
    """
    from app.models import TEMPLATE_DEFAULTS

    assert "بكرة" not in TEMPLATE_DEFAULTS[TYPE]
    assert "{date}" in TEMPLATE_DEFAULTS[TYPE]
    assert "{time}" in TEMPLATE_DEFAULTS[TYPE]


def test_the_reminder_says_what_to_do_if_the_time_no_longer_suits(clinic):
    """The reason to send it a day ahead rather than an hour.

    A reminder that only states the time collects the family who forgot. One
    that invites a reply also collects the slot back from the family who
    cannot come — which is the appointment the clinic can still fill.
    """
    from app.models import TEMPLATE_DEFAULTS

    assert "الرد" in TEMPLATE_DEFAULTS[TYPE] or "إبلاغ" in TEMPLATE_DEFAULTS[TYPE]
