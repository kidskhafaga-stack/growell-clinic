"""The developer's door — opened by the owner, timed, and written down.

See :mod:`app.models.support_access` for why it is a door and not an account.
This module is the rules; the request hooks in ``app/__init__.py`` are where
they are enforced on every request, so no screen has to remember them.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.support_access import DURATIONS, SupportAction, SupportWindow

#: Screens that stay the owner's alone even inside a window — each one is a
#: way to leave without a trace or to come back without a door. Matched on
#: the endpoint, for any method but a plain read.
OWNER_ONLY_PREFIXES = (
    # Staff accounts: a developer who could make an account could make one
    # for themselves that outlives the window.
    "users.",
    # This door.
    "settings.support",
)
OWNER_ONLY_ENDPOINTS = frozenset({
    "settings.reset_data",      # wipes the log of what they did
    "settings.backup_restore",  # replaces the live database, log and all
    "settings.backup_upload",   # the first half of the same thing
    "settings.licence_install",
})


# ------------------------------------------------------------ reading ----
def open_window(user, now=None):
    """The window open for this account right now, or ``None``."""
    if user is None or not getattr(user, "is_vendor", False):
        return None
    from app.utils.request_cache import remember

    def load():
        return (SupportWindow.query
                .filter(SupportWindow.user_id == user.id,
                        SupportWindow.closed_at.is_(None))
                .order_by(SupportWindow.expires_at.desc()).first())

    row = remember(f"support_window:{user.id}", load) if now is None else load()
    if row is None or not row.open_at(now):
        return None
    return row


def any_open(now=None):
    """Every window open right now, for the banner the admins see."""
    now = now or datetime.utcnow()
    rows = (SupportWindow.query.filter(SupportWindow.closed_at.is_(None),
                                       SupportWindow.expires_at > now)
            .order_by(SupportWindow.expires_at).all())
    return rows


def vendors():
    from app.models import User

    return (User.query.filter(User.is_vendor.is_(True))
            .order_by(User.username).all())


def windows(limit=30):
    return (SupportWindow.query.order_by(SupportWindow.opened_at.desc(),
                                         SupportWindow.id.desc())
            .limit(limit).all())


def owner_only(endpoint, method):
    """Is this request one the developer may not make, even inside a
    window? Reads are allowed everywhere — the log records them — except
    this door's own screen; writes to the owner's own screens are not."""
    endpoint = endpoint or ""
    if endpoint.startswith("settings.support"):
        return True
    if method in ("GET", "HEAD", "OPTIONS"):
        return False
    return (endpoint in OWNER_ONLY_ENDPOINTS
            or endpoint.startswith(OWNER_ONLY_PREFIXES))


# ------------------------------------------------------------ writing ----
def _in_person(owner):
    """The owner, as themselves — never a developer holding the owner's
    powers through a window."""
    return (owner is not None and bool(getattr(owner, "is_super_admin", False))
            and owner.is_admin and not getattr(owner, "is_vendor", False))


def make_vendor(owner, username, full_name, password):
    """Create the developer's account. Only the owner, in person.

    An administrator's role, because inside a window it has to reach
    everything; and nothing at all outside one, because the checks on the
    user itself close every door while no window is open.
    """
    from app.models import User

    if not _in_person(owner):
        raise PermissionError("owner only")
    username = (username or "").strip()[:64]
    full_name = (full_name or "").strip()[:120]
    if not username or not full_name or len(password or "") < 8:
        raise ValueError("incomplete")
    if User.query.filter_by(username=username).first() is not None:
        raise ValueError("taken")
    user = User(username=username, full_name=full_name, role="admin",
                is_vendor=True, is_super_admin=False, is_active=True)
    user.set_password(password)
    db.session.add(user)
    return user


def set_vendor_password(owner, vendor, password):
    """The owner changes the developer's password — after every visit, if
    they like; nobody else can."""
    if not _in_person(owner):
        raise PermissionError("owner only")
    if vendor is None or not vendor.is_vendor:
        raise ValueError("not a support account")
    if len(password or "") < 8:
        raise ValueError("short")
    vendor.set_password(password)
    return vendor


def open_for(owner, vendor, hours, reason, now=None):
    """Open the door for one developer account. Only the owner, in person.

    One open window per account: opening again while one is open is refused
    rather than stacked, so there is never a question of which one is the
    real one.
    """
    now = now or datetime.utcnow()
    if not _in_person(owner):
        raise PermissionError("owner only")
    if vendor is None or not vendor.is_vendor or not vendor.is_active:
        raise ValueError("not a support account")
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        raise ValueError("duration")
    if hours not in DURATIONS:
        raise ValueError("duration")
    reason = (reason or "").strip()[:255]
    if not reason:
        raise ValueError("no reason")
    if open_window(vendor, now=now) is not None:
        raise ValueError("already open")
    row = SupportWindow(user_id=vendor.id, reason=reason, opened_at=now,
                        opened_by=owner.id,
                        expires_at=now + timedelta(hours=hours))
    db.session.add(row)
    return row


def close(owner, window, now=None):
    """Close it now. The owner, in person — a developer cannot keep a
    window open, and does not need to close one."""
    if not _in_person(owner):
        raise PermissionError("owner only")
    if window is None or window.closed_at is not None:
        return None
    window.closed_at = now or datetime.utcnow()
    window.closed_by = owner.id
    return window


def record(window, method, endpoint, path, status=None, refused=False,
           ip_address=None, now=None):
    """Write one request down. The caller commits."""
    if window is None:
        return None
    row = SupportAction(window_id=window.id, at=now or datetime.utcnow(),
                        method=(method or "")[:8],
                        endpoint=(endpoint or "")[:120] or None,
                        path=(path or "")[:255] or None, status=status,
                        refused=bool(refused),
                        ip_address=(ip_address or "")[:45] or None)
    db.session.add(row)
    return row
