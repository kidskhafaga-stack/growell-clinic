"""Who do I call, right now.

Asked twice, and the second time to correct my reading of the first:

> «الطوارئ بيبقى فيه ليست مين موجود فى الطوارئ؟»

> «مين موجود فى **العمليات** طوارئ — مش فى قسم الطوارئ. قسم الطوارئ ليه ليست
> بشفتات مختلفة»

and then with the shape:

> «خلى كل لسيت لواحده — لسيت الطبيب الجراح لواحده وليست دكتور التخدير لواحده
> وليست التمريض لواحده. تحت الطلب او اون كول بيتحاسب طريقة مختلفة»

At three in the morning a child needs an emergency operation and somebody is
holding a phone. That person needs three lists, not one, and each name on them
has to say whether it belongs to somebody **in the building** or somebody at
home who will take twenty minutes.

**The whole difficulty is midnight.** A night shift runs from ten at night to
eight in the morning, so at two o'clock on Wednesday the person covering is on
*Tuesday's* rota. Every naive "today's duties" query answers that wrong, and
answers it wrong precisely in the hours the question is asked in. So a slot
that crosses midnight is looked for on **both** days, and the reach of each is
worked out from its own hours rather than from a rule about nights.

**And the clinic's clock, not the server's.** «Now» in a Cairo hospital on a
UTC server is three hours out — which, for a question whose whole answer is
which shift is running, means the wrong name for a quarter of every day.
"""
from datetime import timedelta

from app.models import Duty, DutyRole, DutySlot
from app.utils.clock import local_now, local_today


def _covers(slot, when, started_on, today):
    """Whether ``slot``, rostered for ``started_on``, is running at ``when``.

    ``when`` is a wall-clock time in the clinic and ``today`` the clinic's
    date, so this is pure arithmetic on what the slot itself says — no rule
    about what a "night" is, because a clinic that runs 14:00–02:00 has one
    and would not be caught by one.
    """
    if slot is None or slot.start_time is None or slot.end_time is None:
        return False
    if not slot.crosses_midnight:
        # An ordinary stretch covers only the day it is rostered for.
        return started_on == today and slot.start_time <= when < slot.end_time
    # One that runs past midnight covers the evening of its own day and the
    # small hours of the next.
    if started_on == today:
        return when >= slot.start_time
    if started_on == today - timedelta(days=1):
        return when < slot.end_time
    return False


def covering(at=None, roles_only=True):
    """Everybody covering right now, grouped by rota.

    Returns ``[{role, label, icon, present: [...], on_call: [...]}]`` — the
    two kinds kept apart rather than mixed and flagged, because they are two
    different actions for whoever is reading: fetch, or ring and wait.

    Rostered counts. A duty is not confirmed until afterwards — *«rostered is
    not worked»* is the rule that governs **pay**, and applying it here would
    empty the screen exactly when it is needed: nobody confirms a night shift
    at two in the morning, in the middle of it.
    """
    when = (at or local_now())
    today = when.date()
    clock = when.time()

    rows = (Duty.query
            .filter(Duty.on_date.in_([today, today - timedelta(days=1)]),
                    Duty.status != "absent")
            .all())
    live = [d for d in rows if _covers(d.slot, clock, d.on_date, today)]

    order = {row.key: i for i, row in enumerate(all_roles())}
    known = {row.key: row for row in all_roles()}
    buckets = {}
    for duty in live:
        buckets.setdefault(duty.role, {"present": [], "on_call": []})[
            "on_call" if duty.cover == "on_call" else "present"].append(duty)

    out = []
    for key, sides in buckets.items():
        role = known.get(key)
        if roles_only and key is None:
            # General cover — the resident on the department, belonging to no
            # theatre rota. Kept out of the theatre screen by default and
            # never dropped from the data, because they are on duty too.
            continue
        out.append({
            "role": key,
            "row": role,
            "icon": (role.icon if role is not None else "bi-people"),
            "present": sides["present"],
            "on_call": sides["on_call"],
        })
    out.sort(key=lambda r: (r["role"] is None, order.get(r["role"], 999)))
    return out


def all_roles():
    """Every rota, ordered — falling back to the built-in keys unseeded."""
    from app.models import DUTY_ROLE_ICONS, DUTY_ROLES

    try:
        rows = (DutyRole.query
                .order_by(DutyRole.sort_order, DutyRole.id).all())
    except Exception:                                   # noqa: BLE001
        rows = []
    return rows or [DutyRole(key=k, icon=DUTY_ROLE_ICONS.get(k), sort_order=i,
                             is_system=True)
                    for i, k in enumerate(DUTY_ROLES)]


def active_roles():
    return [r for r in all_roles() if r.is_active]


def ensure_seeded():
    """Fill the rota catalogue from the built-in list if it is empty."""
    from app.extensions import db
    from app.models import DUTY_ROLE_ICONS, DUTY_ROLES

    if DutyRole.query.first() is not None:
        return 0
    added = 0
    for order, key in enumerate(DUTY_ROLES):
        db.session.add(DutyRole(key=key, icon=DUTY_ROLE_ICONS.get(key),
                                sort_order=order, is_active=True,
                                is_system=True))
        added += 1
    db.session.commit()
    return added


def gaps(at=None, roles=None):
    """The rotas with **nobody** covering right now.

    The finding, said out loud rather than shown as an empty column. A
    theatre screen that lists two rotas and silently omits the third reads as
    "the anaesthetists are fine" to somebody scanning it at three in the
    morning — which is the one reading it must never produce.
    """
    covered = {r["role"] for r in covering(at) if r["present"] or r["on_call"]}
    wanted = roles if roles is not None else active_roles()
    return [row for row in wanted if row.key not in covered]


def roster(on_date=None, role=None):
    """One day's rota, for the planning screen rather than the phone."""
    query = Duty.query.filter(Duty.on_date == (on_date or local_today()))
    if role:
        query = query.filter(Duty.role == role)
    return query.order_by(Duty.slot_id, Duty.id).all()


def reachable(duty):
    """The number to ring — theirs, or nothing.

    ``None`` where the person has no phone recorded, which a screen must say
    rather than print an empty space: a name with no number on an on-call
    list is the list failing at the one moment it is read.
    """
    doctor = getattr(duty, "doctor", None)
    return (getattr(doctor, "phone", None) or "").strip() or None
