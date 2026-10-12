"""Staff certificates — see ``models/staff_certificate``."""
from datetime import date, timedelta

from app.extensions import db
from app.models.staff_certificate import StaffCertificate

#: The courses that count as resuscitation training — the hospital's list,
#: comma-separated; empty until written.
RESUS_SETTING = "resus_courses"
CRITICAL_KINDS = ("icu", "nicu")


class CertError(ValueError):
    """A refusal with a locale key (``certs.err_<key>``)."""


def resus_courses():
    from app.models import Setting

    return [c.strip() for c in (Setting.get(RESUS_SETTING) or "").split(",") if c.strip()]


def set_resus_courses(raw):
    from app.models import Setting

    Setting.set(RESUS_SETTING, ",".join(c.strip() for c in (raw or "").split(",") if c.strip()))


def _day(raw):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def add(form, user):
    from app.models import User

    who = db.session.get(User, _int(form.get("user_id")) or 0)
    course = (form.get("course") or "").strip()[:80]
    if who is None or not course:
        raise CertError("who_course")
    issued, expires = _day(form.get("issued_on")), _day(form.get("expires_on"))
    if issued and expires and expires < issued:
        raise CertError("dates")
    row = StaffCertificate(user_id=who.id, course=course, number=(form.get("number") or "").strip()[:80] or None,
                           issued_on=issued, expires_on=expires, added_by=getattr(user, "id", None))
    db.session.add(row)
    db.session.flush()
    return row


def _int(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def valid_on(user_id, day, courses):
    wanted = {c.lower() for c in courses}
    for c in StaffCertificate.query.filter_by(user_id=user_id).all():
        if c.course.strip().lower() in wanted and (c.expires_on is None or c.expires_on >= day):
            return True
    return False


def resus_gaps(start, end):
    """``[(day, slot, unit)]`` in ``[start, end]`` where a critical unit has a
    shift rostered and nobody on it holds a valid resuscitation course; or
    ``None`` while the hospital has not named its courses."""
    from app.models.duty import Duty
    from app.models.place import Unit

    courses = resus_courses()
    if not courses:
        return None
    units = {u.id: u for u in Unit.query.filter(Unit.kind.in_(CRITICAL_KINDS),
                                                Unit.is_active.is_(True)).all()}
    if not units:
        return []
    duties = (Duty.query.filter(Duty.unit_id.in_(list(units)), Duty.on_date >= start,
                                Duty.on_date <= end, Duty.status != "absent").all())
    shifts = {}
    for d in duties:
        shifts.setdefault((d.on_date, d.slot_id, d.unit_id), []).append(d)
    gaps = []
    for (day, slot_id, unit_id), rows in sorted(shifts.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        if not any(valid_on(r.doctor_id, day, courses) for r in rows):
            gaps.append((day, rows[0].slot, units[unit_id]))
    return gaps


def expiring(within_days=None):
    """Certificates already expired or ending soon — ``within_days`` is the
    caller's window; nothing is judged without one."""
    today = date.today()
    q = StaffCertificate.query.filter(StaffCertificate.expires_on.isnot(None))
    if within_days is not None:
        q = q.filter(StaffCertificate.expires_on <= today + timedelta(days=within_days))
    return q.order_by(StaffCertificate.expires_on).all()


__all__ = ["CRITICAL_KINDS", "CertError", "RESUS_SETTING", "add", "expiring", "resus_courses",
           "resus_gaps", "set_resus_courses", "valid_on"]
