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


# --- Fine-grained capabilities (layered on top of module access) -------
# Module access says "can reach this screen"; capabilities gate sensitive
# actions/sections *within* screens — e.g. reception can open a patient to
# register/book, but must not see the full medical file.
CAPABILITIES = [
    "patient_medical",   # view the full clinical file (visits, dx, rx, growth…)
    "cashier",           # collect payments + print receipts
    "finance_manage",    # full finance (P&L, expenses, payers, discounts)
    # Moving the clinic's own money between its tills, or in and out. Split
    # from "cashier" on purpose: taking money from patients and moving the
    # clinic's money are different jobs, and the person who does the first is
    # not automatically trusted with the second.
    "treasury_move",
    # Writing off a counting difference. Deliberately the narrowest of them
    # all, and admin-only below: an adjustment line is exactly how a shortage
    # disappears, so whoever counts the drawer must not be the one who erases
    # what they were short.
    "treasury_adjust",
    # Setting up customer service, as opposed to doing it. The desk answers
    # people, sends the birthday message and chases a failed delivery all day;
    # it does not repoint the clinic's WhatsApp connection or rewrite the text
    # that goes out under the clinic's name to everybody. Same split as
    # ``cashier`` against ``treasury_move``: taking the day's work and changing
    # what the day's work is are different jobs.
    #
    # It also decides the shape of the team. A small clinic gives reception the
    # module and nothing changes; a large one hires a customer-service desk,
    # and separating the two is granting this to one person rather than
    # rebuilding anything.
    "messages_setup",
]

ROLE_CAPABILITIES = {
    "admin": list(CAPABILITIES),
    "doctor": ["patient_medical"],
    "reception": ["cashier"],
    "accountant": ["cashier", "finance_manage", "treasury_move"],
    "pharmacy": [],
}


def role_capabilities(role):
    if role == "admin":
        return list(CAPABILITIES)
    return ROLE_CAPABILITIES.get(role, [])


def role_has_capability(role, capability):
    if role == "admin":
        return True
    return capability in ROLE_CAPABILITIES.get(role, [])


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
