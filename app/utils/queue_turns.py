"""The day's queue at each doctor's door — the reception screen, «اللي بعده»,
and «قرّب دورك» to the family.

**The number is the one the family was already told.** Each doctor's bookings
for the day, in the order of their time, numbered from one — the same count
the booking confirmation sends as «دورك رقم» (``messages.queue_position``),
so the number on the screen is the number on the family's phone. The clinic's
«ترتيب الكشف» setting (``queue_mode``) decides whether that number or the
booked time is what is shown.

**Where each child stands comes from what already happens:** arriving makes a
booking «مستني», the doctor opening the visit makes it «مع الدكتور», finishing
it makes it «خلص». The one moment that was missing is the call to the door:
«اللي بعده» stamps ``called_at`` on the next child who has arrived, and that
is the number the screen shows as «دلوقتي». A doctor who opens the next visit
without pressing anything is shown too — opening it is calling them in.

**«قرّب دورك» is off until the clinic turns it on** (``queue_near_notify``).
On, it sends the family one WhatsApp message when only a few children are
still before them (``queue_near_ahead``, 2 unless the clinic says otherwise)
— so they can wait outside, or set off from home in time — once per booking,
through the same sender as every other message: the opt-out, the daily cap
and the send window all hold.

No names on the screen: a waiting room is public, so it shows the doctor,
the عيادة and the numbers.
"""
from datetime import datetime

from app.extensions import db

NOTIFY = "queue_near_notify"
AHEAD = "queue_near_ahead"
DEFAULT_AHEAD = 2
TEMPLATE = "queue_near"
#: Still to be seen today, in the order of the numbers.
NOT_YET = ("scheduled", "waiting")


def day_list(doctor_id, day):
    """The doctor's bookings that day that count in the numbering — the same
    list (and order) the booking confirmation counts."""
    from app.models import Appointment
    from app.models.appointment import ACTIVE_STATUSES

    return (Appointment.query
            .filter(Appointment.doctor_id == doctor_id,
                    Appointment.appt_date == day,
                    Appointment.status.in_(ACTIVE_STATUSES))
            .order_by(Appointment.appt_time, Appointment.id).all())


def mode():
    from app.models import Setting

    return "time" if (Setting.get("queue_mode", "number") or "") == "time" else "number"


def label(appt, number, how=None):
    """What a family is called by: its number, or its booked time."""
    return appt.time_label if (how or mode()) == "time" else str(number)


def _called(appt):
    """When this child was called in — pressed, or the doctor opened the visit."""
    if appt.status not in ("waiting", "in_progress", "completed"):
        return None
    return appt.called_at or appt.started_at


def state(doctor_id, day, how=None):
    """``{"now", "next", "waiting", "not_arrived", "left"}`` for one doctor.

    ``now`` is ``(label, appt)`` of the last child called in, or None; ``next``
    the arrived children not yet called, in order; ``not_arrived`` how many
    booked children have not come yet; ``left`` how many are still to be seen.
    """
    how = how or mode()
    rows = list(enumerate(day_list(doctor_id, day), start=1))
    called = [(stamp, n, a) for n, a in rows if (stamp := _called(a)) is not None]
    now = None
    if called:
        _stamp, n, a = max(called, key=lambda t: (t[0], t[1]))
        now = (label(a, n, how), a)
    upcoming = [(label(a, n, how), a) for n, a in rows
                if a.status == "waiting" and a.called_at is None]
    return {"now": now, "next": upcoming,
            "not_arrived": sum(1 for _n, a in rows if a.status == "scheduled"),
            "left": sum(1 for _n, a in rows if a.status in NOT_YET and a.called_at is None)}


def doctors_on(day):
    """The doctors with bookings that day, with their عيادة if one is set."""
    from app.models import Appointment, RoomAssignment, User
    from app.models.appointment import ACTIVE_STATUSES

    ids = [r[0] for r in (db.session.query(Appointment.doctor_id)
                          .filter(Appointment.appt_date == day,
                                  Appointment.status.in_(ACTIVE_STATUSES))
                          .distinct().all()) if r[0]]
    if not ids:
        return []
    rooms = {r.doctor_id: r.room for r in
             RoomAssignment.query.filter(RoomAssignment.on_date == day,
                                         RoomAssignment.doctor_id.in_(ids)).all()}
    doctors = User.query.filter(User.id.in_(ids)).all()
    out = [(d, rooms.get(d.id)) for d in doctors]
    return sorted(out, key=lambda pair: ((pair[1].sort_order if pair[1] else 9999),
                                         (pair[1].code if pair[1] else ""),
                                         pair[0].full_name or ""))


def board(day, doctor_id=None):
    """One row per doctor: ``{"doctor", "room", **state}``."""
    how = mode()
    out = []
    for doctor, room in doctors_on(day):
        if doctor_id and doctor.id != doctor_id:
            continue
        out.append({"doctor": doctor, "room": room, **state(doctor.id, day, how)})
    return out


def call_next(doctor_id, day, now=None):
    """Call the next child who has arrived. Returns the booking, or None when
    nobody is waiting. The caller commits."""
    upcoming = state(doctor_id, day)["next"]
    if not upcoming:
        return None
    _label, appt = upcoming[0]
    appt.called_at = now or datetime.utcnow()
    db.session.flush()
    return appt


def notify_on():
    from app.models import Setting

    return (Setting.get(NOTIFY, "0") or "0") == "1"


def ahead_limit():
    from app.models import Setting

    try:
        value = int(Setting.get(AHEAD, str(DEFAULT_AHEAD)) or DEFAULT_AHEAD)
    except ValueError:
        return DEFAULT_AHEAD
    return max(0, min(value, 10))


def near_turn(doctor_id, day, user_id=None, lang="ar", now=None):
    """Send «قرّب دورك» to every family now within the limit who has not had
    it. Returns the message logs. Nothing when the clinic has it off. The
    caller commits."""
    if not notify_on():
        return []
    from app.models import Setting
    from app.utils import whatsapp as wa

    how = mode()
    limit = ahead_limit()
    remaining = [(n, a) for n, a in enumerate(day_list(doctor_id, day), start=1)
                 if a.status in NOT_YET and a.called_at is None]
    clinic = Setting.get("clinic_name_ar") or Setting.get("clinic_name") or ""
    sent = []
    for ahead, (number, appt) in enumerate(remaining):
        if ahead > limit:
            break
        if appt.near_sent_at is not None:
            continue
        phone = appt.patient.contact_phone if appt.patient else None
        if not phone:
            continue
        body = wa.render(wa.template_body(TEMPLATE), {
            "patient": appt.patient.display_name(lang),
            "first_name": (appt.patient.display_name(lang) or "").split(" ")[0],
            "doctor": appt.doctor.display_name(lang) if appt.doctor else "",
            "queue": label(appt, number, how), "ahead": ahead, "clinic": clinic,
        })
        log = wa.send(body, phone, patient_id=appt.patient_id,
                      appointment_id=appt.id, user_id=user_id,
                      template_type=TEMPLATE)
        appt.near_sent_at = now or datetime.utcnow()
        sent.append(log)
    db.session.flush()
    return sent


def after_change(appt, user_id=None, lang="ar"):
    """Called wherever a booking moves on its day (arrived, called, opened,
    finished): sends what has become due. Never breaks the screen it runs
    from."""
    if appt is None or not appt.doctor_id or appt.appt_date is None:
        return []
    try:
        from app.utils.clock import local_today

        if appt.appt_date != local_today():
            return []
        with db.session.begin_nested():
            return near_turn(appt.doctor_id, appt.appt_date,
                             user_id=user_id, lang=lang)
    except Exception:  # noqa: BLE001 - a message never stops the queue
        return []
