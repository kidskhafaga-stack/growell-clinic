"""Roles, modules and the role -> module access matrix.

Permissions in Phase 1 are module-level: a role either can or cannot reach a
given functional module. This is intentionally coarse-grained; finer actions
(view vs. edit vs. delete) can be layered on per module in later phases without
changing the role definitions here.
"""

# The five system roles described in the project plan.
ROLES = ["admin", "doctor", "reception", "accountant", "pharmacy"]

# Every functional module in the system. The string keys double as i18n keys
# under ``nav.*`` and as the permission identifiers used by the decorators.
MODULES = [
    "dashboard",
    "patients",
    "appointments",
    "visits",
    "growth",
    "vaccinations",
    "prescriptions",
    "inventory",
    "finance",
    "reports",
    "ai",
    "messages",
    "users",
    "settings",
]

# Module -> Bootstrap icon name, used by the sidebar navigation.
MODULE_ICONS = {
    "dashboard": "speedometer2",
    "patients": "people",
    "appointments": "calendar-week",
    "visits": "clipboard2-pulse",
    "growth": "graph-up",
    "vaccinations": "shield-plus",
    "prescriptions": "capsule",
    "inventory": "box-seam",
    "finance": "cash-coin",
    "reports": "bar-chart-line",
    "ai": "robot",
    "messages": "whatsapp",
    "users": "person-gear",
    "settings": "gear",
}

# Access matrix: which modules each role may reach. ``admin`` is granted every
# module dynamically in ``role_modules`` so new modules are covered by default.
ROLE_PERMISSIONS = {
    "admin": list(MODULES),
    "doctor": [
        "dashboard",
        "patients",
        "appointments",
        "visits",
        "growth",
        "vaccinations",
        "prescriptions",
        "ai",
    ],
    "reception": [
        "dashboard",
        "patients",
        "appointments",
        "messages",
    ],
    "accountant": [
        "dashboard",
        "finance",
        "reports",
    ],
    "pharmacy": [
        "dashboard",
        "inventory",
        "vaccinations",
        "prescriptions",
    ],
}


def role_modules(role):
    """Return the list of modules a role can access (admin gets everything)."""
    if role == "admin":
        return list(MODULES)
    return ROLE_PERMISSIONS.get(role, ["dashboard"])


def role_can_access(role, module):
    """True if ``role`` may access ``module``."""
    if role == "admin":
        return module in MODULES
    return module in ROLE_PERMISSIONS.get(role, [])
