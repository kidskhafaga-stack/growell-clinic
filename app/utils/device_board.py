"""The device studies waiting to be done — wherever the child is.

Asked as *«الاجهزة الثانية موجوده لانها ممكن تتواجد فى اي عيادة زي … الايكو
قياس التنفس … وultra sound كل ده ممكن تبقى فى عيادة وممكن تجرى فى الاقسام
الداخلية»*, and *«رسم المخ الى بيحتاج حجز ونوم»*.

An echo, a sonar, a spirometry, an ECG and an EEG are **not the lab and not
radiology**. They are device studies: the program has had them for a long
time (`models/device.py`), each with the measurements its report captures,
and they are done in a clinic room or at a bedside. What was missing was the
middle: a study **ordered** — from a visit, the emergency, a ward round — sat
on a list under the lab, and recording it did not answer the order.

So this is that middle:

* every diagnostic order not yet answered, from anywhere in the building,
  the child's bed beside it when there is one;
* a study that needs a booking is booked for a day and an hour, with what the
  family has to do before it — the list puts today's bookings first, in time
  order;
* recording it opens the device's own template (`visits.study_new`) and the
  study answers the order.

It sits with the visit, not with a module of its own: any clinic may do these.
The door to it is shown only where the clinic said it does one of them, or one
is waiting — a clinic that does none sees the menu it had.
"""
from datetime import datetime

from app.extensions import db

#: The capabilities that are device studies (`facility.CAPABILITY_GROUPS`).
CAPABILITIES = ("ecg", "echo", "eeg", "spirometry", "audiology", "ultrasound")


#: Set once the clinic does one of these: it ticked one of the capabilities,
#: or somebody ordered one. Kept with the module switches, which every page
#: already reads in one query — so the menu door costs nothing to decide.
FLAG = "mod_enabled:device_board"


def shown():
    """Whether the menu shows the door. No query of its own."""
    from flask_login import current_user

    try:
        from app.models import Setting
        from app.utils.facility import module_enabled

        return bool(getattr(current_user, "is_authenticated", False)
                    and current_user.can_access("visits")
                    and module_enabled("visits")
                    and Setting.group("mod_enabled").get(FLAG) == "1")
    except Exception:  # noqa: BLE001 — a menu link never breaks a page
        return False


def mark_used():
    from app.models import Setting

    if Setting.get(FLAG) != "1":
        Setting.set(FLAG, "1")


def note_on(connection):
    """The same, from inside a flush (an order just inserted): written on the
    flush's own connection, and the page's cached switches forgotten."""
    from sqlalchemy import text

    row = connection.execute(text("SELECT value FROM settings WHERE key = :k"),
                             {"k": FLAG}).first()
    if row is None:
        connection.execute(text("INSERT INTO settings (key, value, updated_at) "
                                "VALUES (:k, '1', :t)"),
                           {"k": FLAG, "t": datetime.utcnow()})
    elif row[0] != "1":
        connection.execute(text("UPDATE settings SET value = '1' WHERE key = :k"),
                           {"k": FLAG})
    else:
        return
    try:
        from app.utils.request_cache import forget

        forget("settings:group:mod_enabled")
        forget(f"setting:{FLAG}")
    except Exception:  # noqa: BLE001
        pass


def _open_query():
    from app.models import VisitInvestigation
    from app.utils import labs as bench

    return (VisitInvestigation.query
            .filter(VisitInvestigation.kind == bench.DIAGNOSTIC,
                    VisitInvestigation.status.in_(bench.OPEN_STATES),
                    db.or_(VisitInvestigation.done_outside.is_(False),
                           VisitInvestigation.done_outside.is_(None))))


def waiting_count():
    return _open_query().count()


def rows(now=None):
    """The open orders, in the order the room works them: today's bookings
    by time, then everything not booked (longest waiting first), then later
    bookings."""
    from sqlalchemy.orm import selectinload

    from app.models import VisitInvestigation
    from app.utils.clock import local_date

    now = now or datetime.utcnow()
    today = local_date(now)
    found = (_open_query()
             .options(selectinload(VisitInvestigation.patient),
                      selectinload(VisitInvestigation.investigation))
             .limit(300).all())

    def place(row):
        if row.booked_for is None:
            return (1, row.created_at or now)
        day = local_date(row.booked_for)
        if day is not None and today is not None and day <= today:
            return (0, row.booked_for)
        return (2, row.booked_for)

    return sorted(found, key=place)


def book(order, when, note=None, user=None):
    """Book this study for ``when`` (UTC). ``None`` clears the booking."""
    if order is None or order.kind != "diagnostic":
        raise ValueError("not a device study")
    order.booked_for = when
    order.booking_note = ((note or "").strip()[:160] or None) if when else None
    order.booked_by = getattr(user, "id", None) if when else None
    db.session.flush()
    return order


def device_for(order):
    """The device this order's test is done on, when the clinic has said."""
    test = getattr(order, "investigation", None)
    return getattr(test, "device", None) if test is not None else None


def answer(order, study, user=None):
    """The study answers the order: it is performed, and its conclusion is
    the order's result — so the doctor's inbox, the waiting-on chips and the
    file all read it as done."""
    from app.utils import labs as bench

    if order is None or order.kind != "diagnostic":
        return None
    if order.status == bench.RESULTED:
        return order
    if order.performed_at is None:
        bench.perform(order, user=user)
    study.order_id = order.id
    study.admission_id = order.admission_id
    text = (study.conclusion or "").strip()
    if not text:
        from app.i18n import t

        text = t("device_board.recorded", device=study.device.display_name()
                 if study.device else "")
    bench.record(order, text=text, user=user)
    return order


def booked_today(order, now=None):
    """Booked for today (or a day already gone and still not done)."""
    from app.utils.clock import local_date

    if order is None or order.booked_for is None:
        return False
    day, today = local_date(order.booked_for), local_date(now or datetime.utcnow())
    return day is not None and today is not None and day <= today
