"""Authorization decorators built on top of the role/module matrix."""
from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user

from app.i18n import t


def module_required(module):
    """Restrict a view to users whose role can access ``module``.

    Unauthenticated users are sent through Flask-Login; authenticated users
    without the permission get a 403.
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            from app.utils.facility import module_enabled
            if not module_enabled(module):
                abort(404)
            if not current_user.can_access(module):
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def capability_required(capability):
    """Restrict a view to users whose role holds a fine-grained ``capability``
    (e.g. ``patient_medical``). Layered on top of ``module_required``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not current_user.can(capability):
                abort(403, description=t("auth.no_permission"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def admin_required(view):
    """Restrict a view to administrators only."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403, description=t("auth.no_permission"))
        return view(*args, **kwargs)

    return wrapped


def client_ip():
    """Best-effort client IP, honoring a single proxy hop."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr
