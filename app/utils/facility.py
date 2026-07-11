"""Facility profile — turns the same code base into different kinds of health
facilities through configuration instead of forks.

The super-admin picks a *facility type* (single doctor, peds center, vaccination
center, audiology center, …) which seeds a sensible set of enabled modules; each
module can then be toggled on/off independently. Nothing here is hardcoded into
business logic — screens and the sidebar simply ask :func:`module_enabled`.
"""
from app.models import Setting
from app.models.permissions import MODULES

# Modules that make no sense to disable — the app can't run without them.
ALWAYS_ON = {"dashboard", "settings", "users"}

# The modules an admin may turn on/off from the wizard.
TOGGLEABLE_MODULES = [m for m in MODULES if m not in ALWAYS_ON]

# Facility presets: key -> default set of enabled toggleable modules. These are
# only *defaults* the admin can override; ALWAYS_ON modules are implicit.
_CLINICAL = ["patients", "appointments", "visits", "growth", "vaccinations",
             "prescriptions", "inventory", "finance", "reports", "messages", "ai"]

FACILITY_TYPES = {
    "single_doctor":    {"icon": "person-badge", "modules": _CLINICAL},
    "multi_doctor":     {"icon": "people", "modules": _CLINICAL},
    "medical_center":   {"icon": "hospital", "modules": _CLINICAL},
    "peds_center":      {"icon": "emoji-smile", "modules": _CLINICAL},
    "vaccination_center": {"icon": "shield-plus",
                           "modules": ["patients", "appointments", "vaccinations",
                                       "inventory", "finance", "reports", "messages", "ai"]},
    "audiology_center": {"icon": "ear",
                         "modules": ["patients", "appointments", "visits",
                                     "finance", "reports", "messages", "ai"]},
    "imaging_center":   {"icon": "radioactive",
                         "modules": ["patients", "appointments", "visits",
                                     "finance", "reports", "messages", "ai"]},
}

DEFAULT_FACILITY_TYPE = "peds_center"


def facility_type():
    return Setting.get("facility_type") or DEFAULT_FACILITY_TYPE


def is_configured():
    """True once the first-run wizard has been completed."""
    return Setting.get("facility_configured") == "1"


def default_modules_for(type_key):
    preset = FACILITY_TYPES.get(type_key) or FACILITY_TYPES[DEFAULT_FACILITY_TYPE]
    return list(preset["modules"])


def module_enabled(module):
    """Is ``module`` switched on for this facility?

    Before the wizard runs everything is on (backward compatible). ALWAYS_ON
    modules are never disabled.
    """
    if module in ALWAYS_ON:
        return True
    if not is_configured():
        return True
    return Setting.get(f"mod_enabled:{module}") != "0"


def enabled_modules():
    return [m for m in MODULES if module_enabled(m)]


def apply_facility(type_key, facility_name, enabled):
    """Persist the facility profile. ``enabled`` is the set/list of toggleable
    modules the admin ticked. Does NOT commit — caller commits."""
    if type_key not in FACILITY_TYPES:
        type_key = DEFAULT_FACILITY_TYPE
    Setting.set("facility_type", type_key)
    if facility_name:
        Setting.set("clinic_name", facility_name)
    wanted = set(enabled)
    for m in TOGGLEABLE_MODULES:
        Setting.set(f"mod_enabled:{m}", "1" if m in wanted else "0")
    Setting.set("facility_configured", "1")
