"""Doctor privacy policy (workflow policies).

With ``doctors_see_own_only`` on (the default), a non-admin doctor is locked
to their own appointments and visits: the board is pinned to their column,
the visits list is filtered, and opening another doctor's visit record is
refused. Admins — and every non-doctor role (reception, nursing, cashier) —
are unaffected, since they coordinate across doctors by nature.
"""
from flask_login import current_user


def doctor_locked_id():
    """The doctor id the current user is locked to, or None when unrestricted."""
    from app.models import Setting

    if not getattr(current_user, "is_authenticated", False):
        return None
    if current_user.is_admin or current_user.role != "doctor":
        return None
    if Setting.get("doctors_see_own_only", "1") == "0":
        return None
    return current_user.id


def can_see_visit(visit):
    """Whether the current user may open this visit's record."""
    locked = doctor_locked_id()
    return locked is None or visit.doctor_id in (None, locked)
