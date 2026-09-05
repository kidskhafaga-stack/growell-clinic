"""The rota, and what it owes — the questions a duty screen asks.

One file so that "what has this doctor earned from cover" has a single
answer. It is the same discipline the invoice lines are under: a doctor's pay
is a number two calculations must never disagree about.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.duty import DUTY_PAYABLE, DUTY_STATUSES, Duty, DutySlot
from app.utils.clock import local_today


def slots(include_inactive=False):
    """The shifts this clinic runs, in the order somebody put them in."""
    query = DutySlot.query
    if not include_inactive:
        query = query.filter(DutySlot.is_active.is_(True))
    return query.order_by(DutySlot.sort_order, DutySlot.start_time,
                          DutySlot.id).all()


def rate_for(slot, doctor=None):
    """What ``slot`` pays ``doctor`` — their own figure, or the slot's."""
    if slot is None:
        return 0.0
    return slot.rate_for(doctor)


def assign(doctor, slot, on_date=None, unit=None, user=None, note=None):
    """Put somebody on the rota. Returns the duty.

    Rostered, and worth nothing yet — see :func:`confirm`. The rate is copied
    onto the row now rather than looked up when the month is paid, so a rate
    changed in March leaves February's rota alone.

    Raises ``ValueError`` when there is no doctor or no slot, and lets the
    unique constraint refuse a second row for the same person, slot and day
    — a rota screen that lets somebody click twice must not pay twice.
    """
    if doctor is None or slot is None:
        raise ValueError("duty needs a doctor and a slot")
    duty = Duty(
        doctor_id=getattr(doctor, "id", doctor),
        slot_id=getattr(slot, "id", slot),
        unit_id=getattr(unit, "id", unit) if unit is not None else None,
        on_date=on_date or local_today(),
        status="rostered",
        amount=rate_for(slot, doctor) or None,
        note=(note or "").strip()[:160] or None,
        created_by=getattr(user, "id", None))
    db.session.add(duty)
    return duty


def confirm(duty, user=None):
    """Say the duty happened. This is the press that makes it payable.

    Deliberately a separate act from rostering, and deliberately not
    automatic: nothing in this program can see whether somebody was in the
    department at three in the morning, and a rota that pays itself is a rota
    that pays for nights nobody covered.
    """
    if duty is None:
        return None
    duty.status = DUTY_PAYABLE
    duty.confirmed_at = datetime.utcnow()
    duty.confirmed_by = getattr(user, "id", None)
    return duty


def mark_absent(duty, user=None, note=None):
    """Record that it did not happen. Pays nothing, and says why if told."""
    if duty is None:
        return None
    duty.status = "absent"
    duty.confirmed_at = datetime.utcnow()
    duty.confirmed_by = getattr(user, "id", None)
    if note:
        duty.note = note.strip()[:160] or None
    return duty


def roster(date_from, date_to, unit_id=None, doctor_id=None):
    """Every duty in a window, oldest first — the board."""
    query = Duty.query.filter(Duty.on_date >= date_from,
                              Duty.on_date <= date_to)
    if unit_id is not None:
        query = query.filter(Duty.unit_id == unit_id)
    if doctor_id is not None:
        query = query.filter(Duty.doctor_id == doctor_id)
    return query.order_by(Duty.on_date, Duty.slot_id, Duty.id).all()


def unconfirmed(upto=None):
    """Duties whose day has passed and nobody has said what happened.

    The visible gap. Without this the rota fills with rows that are neither
    worked nor absent, and at the end of the month somebody has to decide in
    a hurry — which is when a night that was covered gets missed and a night
    that was not gets paid.
    """
    upto = upto or local_today()
    return (Duty.query
            .filter(Duty.status == "rostered", Duty.on_date < upto)
            .order_by(Duty.on_date, Duty.id).all())


def earned(doctor_id, date_from=None, date_to=None):
    """What cover has earned this doctor — worked duties only."""
    query = (db.session.query(db.func.sum(Duty.amount))
             .filter(Duty.doctor_id == doctor_id,
                     Duty.status == DUTY_PAYABLE))
    if date_from is not None:
        query = query.filter(Duty.on_date >= date_from)
    if date_to is not None:
        query = query.filter(Duty.on_date <= date_to)
    return round(query.scalar() or 0, 2)


def by_slot(doctor_id, date_from, date_to):
    """``[{label, count, share}]`` — their cover, grouped the way it is paid.

    One row per shift type, because "eleven nights and four evenings" is the
    sentence a doctor checks their pay against. Worked only: a rostered night
    is not money and showing it in a money list is how a doctor is told they
    earned something they have not.
    """
    rows = {}
    duties = (Duty.query
              .filter(Duty.doctor_id == doctor_id,
                      Duty.status == DUTY_PAYABLE,
                      Duty.on_date >= date_from,
                      Duty.on_date <= date_to).all())
    for duty in duties:
        key = duty.slot_id
        row = rows.get(key)
        if row is None:
            label = duty.slot.name if duty.slot else "—"
            row = rows[key] = {"label": label, "count": 0, "share": 0.0}
        row["count"] += 1
        row["share"] += duty.pay
    return sorted(({"label": r["label"], "count": r["count"],
                    "share": round(r["share"], 2)} for r in rows.values()),
                  key=lambda r: -r["share"])


def counts(date_from, date_to, unit_id=None):
    """``{status: how many}`` over a window — the board's own summary."""
    query = (db.session.query(Duty.status, db.func.count(Duty.id))
             .filter(Duty.on_date >= date_from, Duty.on_date <= date_to))
    if unit_id is not None:
        query = query.filter(Duty.unit_id == unit_id)
    found = dict(query.group_by(Duty.status).all())
    return {status: found.get(status, 0) for status in DUTY_STATUSES}


def week_of(on_date=None):
    """The Saturday-to-Friday week a date falls in — the Egyptian working week.

    The same convention ``DoctorSchedule.WEEKDAY_ORDER`` already keeps, so a
    rota and a booking calendar do not start their weeks on different days.
    """
    on_date = on_date or local_today()
    # Python's Monday=0 .. Sunday=6; Saturday is 5.
    back = (on_date.weekday() - 5) % 7
    start = on_date - timedelta(days=back)
    return start, start + timedelta(days=6)
