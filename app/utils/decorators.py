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


def cashier_access(view):
    """Allow the cashier/checkout screens to users who can reach the finance
    module *or* anyone holding the ``cashier`` capability (typically reception).

    Reception has to collect money and see what it collected — that used to
    require handing them the *whole* finance module (P&L, expenses, payroll,
    claims) or switching the clinic into small-clinic mode. The ``cashier``
    capability alone is enough for the till: everything else stays behind
    ``module_required("finance")``.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        from app.utils.facility import module_enabled
        if not module_enabled("finance"):
            abort(404)
        if current_user.can_access("finance") or current_user.can("cashier"):
            return view(*args, **kwargs)
        abort(403, description=t("auth.no_permission"))

    return wrapped


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


def owner_required(view):
    """Restrict a view to the institution owner (super-admin) — the
    institution/clinic-level settings a plain admin must not reshape
    (facility setup, multi-doctor config, data reset)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()
        if not current_user.is_owner:
            abort(403, description=t("auth.owner_only"))
        return view(*args, **kwargs)

    return wrapped


def client_ip():
    """Best-effort client IP, honoring a single proxy hop."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr
