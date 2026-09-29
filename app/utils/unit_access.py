"""Whether this person may read this child's stay — and the way in when not.

See ``models/unit_staff`` for why: a unit with a team listed is its team's,
the owner and admins see everything, and anybody else gets in by giving a
reason that is written down and lasts a shift.
"""
from datetime import datetime, timedelta

from app.extensions import db

#: How long a reason given at the glass keeps the door open.
SHIFT_HOURS = 12


def teams():
    """``{unit_id: {user_id, ...}}`` for every unit that has a team."""
    from app.models.unit_staff import UnitStaff

    out = {}
    for unit_id, user_id in db.session.query(UnitStaff.unit_id, UnitStaff.user_id).all():
        out.setdefault(unit_id, set()).add(user_id)
    return out


def unit_of(admission):
    stay = next((s for s in admission.stays if s.until is None), None)
    if stay is None and admission.stays:
        stay = sorted(admission.stays, key=lambda s: s.since)[-1]
    return stay.bed.space.unit if stay is not None and stay.bed is not None else None


def is_open_to(user, unit_id, all_teams=None):
    """Whether ``user`` reads this unit's stays without breaking the glass."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if user.is_admin:
        return True
    team = (all_teams if all_teams is not None else teams()).get(unit_id)
    return not team or user.id in team


def glass_broken(user, admission_id, now=None):
    """A reason this person gave for this stay within the last shift."""
    from app.models.unit_staff import BreakGlass

    now = now or datetime.utcnow()
    return BreakGlass.query.filter(
        BreakGlass.user_id == user.id, BreakGlass.admission_id == admission_id,
        BreakGlass.at >= now - timedelta(hours=SHIFT_HOURS)).first() is not None


def may_read(user, admission):
    unit = unit_of(admission)
    if unit is None or is_open_to(user, unit.id):
        return True
    return glass_broken(user, admission.id)


def break_glass(user, admission, reason):
    """Write down why, and open the stay to this person for a shift."""
    from app.models import ActivityLog
    from app.models.unit_staff import BreakGlass

    reason = (reason or "").strip()[:255]
    if len(reason) < 5:
        raise ValueError("reason")
    unit = unit_of(admission)
    row = BreakGlass(admission_id=admission.id, unit_id=getattr(unit, "id", None),
                     user_id=user.id, reason=reason)
    db.session.add(row)
    ActivityLog.record("stay.break_glass", user_id=user.id, entity="admission",
                       entity_id=admission.id, detail=reason)
    return row


def recent(days=30):
    """Every time the glass was broken lately, newest first — for the manager."""
    from app.models.unit_staff import BreakGlass

    since = datetime.utcnow() - timedelta(days=days)
    return (BreakGlass.query.filter(BreakGlass.at >= since)
            .order_by(BreakGlass.at.desc()).limit(200).all())


def set_team(unit, user_ids, by=None):
    """Make the unit's team exactly ``user_ids``. Returns (added, removed)."""
    from app.models import ActivityLog
    from app.models.unit_staff import UnitStaff

    wanted = {int(u) for u in user_ids}
    have = {row.user_id: row for row in UnitStaff.query.filter_by(unit_id=unit.id).all()}
    added = wanted - set(have)
    removed = set(have) - wanted
    for uid in added:
        db.session.add(UnitStaff(unit_id=unit.id, user_id=uid,
                                 added_by=getattr(by, "id", None)))
    for uid in removed:
        db.session.delete(have[uid])
    if added or removed:
        ActivityLog.record("unit.team", user_id=getattr(by, "id", None),
                           entity="unit", entity_id=unit.id,
                           detail=f"+{sorted(added)} -{sorted(removed)}")
    return added, removed
