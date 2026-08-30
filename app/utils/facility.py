"""Facility profile — three *separate* layers, configured not forked:

1. **Facility Type** — the administrative shape only (single-doctor clinic,
   medical center, hospital…). Used only to preset sensible defaults.
2. **Capabilities** (Services & Specialties) — what the facility actually
   offers (vaccination, ECG, ultrasound, lab, pharmacy…), grouped and
   multi-select. Any facility may offer any mix, regardless of its type.
3. **Modules** — the software modules switched on. Derived automatically from
   the chosen capabilities, then freely overridable.

Templates bundle a type + a capability set as a one-click starting point.
Nothing here is hardcoded into business logic — screens ask ``module_enabled``.
"""
import json

from app.models import Setting
from app.models.permissions import MODULES

# Modules that make no sense to disable — the app can't run without them.
ALWAYS_ON = {"dashboard", "settings", "users"}

# Modules that are **off until a clinic switches them on**, even on a copy
# that has never run the setup wizard.
#
# Everything else is on by default, and that is right for the paediatric core:
# it is what the program was before the wizard existed, and a clinic upgrading
# into a version that added the wizard must not lose screens it was using
# yesterday. A specialty is the opposite case. A paediatric clinic is not a
# dental clinic, and turning dentistry on for every existing clinic because
# the module now exists would put a tooth chart on their patients' files and
# a dental price list in their books without anybody asking for either.
#
# So the default runs the other way here: nothing until somebody says so.
OPT_IN_MODULES = {"dentistry"}

# Modules an admin may turn on/off.
TOGGLEABLE_MODULES = [m for m in MODULES if m not in ALWAYS_ON]

# Every facility gets these regardless of capabilities.
BASE_MODULES = ["patients", "appointments", "finance", "reports", "messages", "ai"]

# --- Layer 1: administrative facility types (NOT services) -----------------
# Each carries a default capability set the wizard pre-ticks; fully editable.
FACILITY_TYPES = {
    "single_doctor":     {"icon": "person-badge",
                          "caps": ["general_consultation", "followup"]},
    "multi_doctor":      {"icon": "people",
                          "caps": ["general_consultation", "followup"]},
    "polyclinic":        {"icon": "hospital",
                          "caps": ["general_consultation", "followup"]},
    "medical_center":    {"icon": "buildings",
                          "caps": ["general_consultation", "followup",
                                   "laboratory", "ultrasound", "pharmacy"]},
    "hospital":          {"icon": "hospital",
                          "caps": ["general_consultation", "followup", "laboratory",
                                   "ultrasound", "xray", "pharmacy",
                                   "emergency_care", "ward", "icu"]},
    "diagnostic_center": {"icon": "activity",
                          "caps": ["ecg", "echo", "ultrasound", "laboratory"]},
    "pediatric_center":  {"icon": "emoji-smile",
                          "caps": ["general_consultation", "followup",
                                   "vaccination", "growth_monitoring"]},
    "specialized_center": {"icon": "star",
                           "caps": ["general_consultation", "followup"]},
}
DEFAULT_FACILITY_TYPE = "pediatric_center"

# --- Layer 2: capabilities (services & specialties), grouped ---------------
CAPABILITY_GROUPS = {
    "clinical":   ["general_consultation", "followup", "vaccination",
                   "growth_monitoring", "emergency_care", "home_care",
                   "dentistry"],
    "diagnostic": ["ecg", "echo", "eeg", "spirometry", "audiology",
                   "vision_screening"],
    "imaging":    ["ultrasound", "xray", "ct", "mri"],
    "laboratory": ["laboratory", "sample_collection", "pathology"],
    "pharmacy":   ["pharmacy", "clinical_pharmacy"],
    "inpatient":  ["observation", "day_care", "ward", "nicu", "icu"],
}
ALL_CAPABILITIES = [c for group in CAPABILITY_GROUPS.values() for c in group]

# --- Layer 3: which modules each capability needs (existing modules only) ---
CAPABILITY_MODULES = {
    "general_consultation": {"visits"},
    "followup": {"visits"},
    "vaccination": {"vaccinations", "inventory"},
    "growth_monitoring": {"growth"},
    "dentistry": {"dentistry", "visits"},
    "emergency_care": {"visits"},
    "home_care": {"visits"},
    "ecg": {"visits"}, "echo": {"visits"}, "eeg": {"visits"},
    "spirometry": {"visits"}, "audiology": {"visits"}, "vision_screening": {"visits"},
    "ultrasound": {"visits", "inventory"}, "xray": {"visits", "inventory"},
    "ct": {"visits", "inventory"}, "mri": {"visits", "inventory"},
    "laboratory": {"visits"}, "sample_collection": {"visits"}, "pathology": {"visits"},
    "pharmacy": {"prescriptions", "inventory"}, "clinical_pharmacy": {"prescriptions"},
    "observation": {"visits"}, "day_care": {"visits"}, "ward": {"visits"},
    "nicu": {"visits"}, "icu": {"visits"},
}

# Ready-made presets: type + capabilities (modules derived).
TEMPLATES = {
    "pediatric_clinic":   {"icon": "emoji-smile", "type": "pediatric_center",
                           "caps": ["general_consultation", "followup",
                                    "vaccination", "growth_monitoring"]},
    "pediatric_dental_clinic": {"icon": "emoji-smile",
                                "type": "specialized_center",
                                "caps": ["general_consultation", "followup",
                                         "dentistry"]},
    "cardiology_clinic":  {"icon": "heart-pulse", "type": "specialized_center",
                           "caps": ["general_consultation", "followup",
                                    "ecg", "echo"]},
    "vaccination_center": {"icon": "shield-plus", "type": "specialized_center",
                           "caps": ["vaccination"]},
    "medical_center":     {"icon": "buildings", "type": "medical_center",
                           "caps": ["general_consultation", "followup",
                                    "laboratory", "ultrasound", "xray", "pharmacy"]},
}


# --- reads -----------------------------------------------------------------
def facility_type():
    return Setting.get("facility_type") or DEFAULT_FACILITY_TYPE


def is_configured():
    return Setting.get("facility_configured") == "1"


def capabilities():
    """The capability keys the facility offers (persisted as a JSON list)."""
    raw = Setting.get("facility_capabilities")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [c for c in data if c in CAPABILITY_MODULES]


def default_caps_for(type_key):
    preset = FACILITY_TYPES.get(type_key) or FACILITY_TYPES[DEFAULT_FACILITY_TYPE]
    return list(preset["caps"])


def derive_modules(caps):
    """Modules implied by a capability set: the base set + each capability's
    required modules (limited to real, toggleable modules)."""
    wanted = set(BASE_MODULES)
    for cap in caps:
        wanted |= CAPABILITY_MODULES.get(cap, set())
    return [m for m in TOGGLEABLE_MODULES if m in wanted]


def module_enabled(module):
    """Is ``module`` switched on?

    ``ALWAYS_ON`` modules are never disabled. The rest are on until the wizard
    runs, which keeps a clinic upgrading into the wizard from losing screens
    it used yesterday — except the opt-in specialties, which are off until
    somebody asks for them however configured this copy is. See
    :data:`OPT_IN_MODULES`.
    """
    if module in ALWAYS_ON:
        return True
    if module in OPT_IN_MODULES:
        return Setting.get(f"mod_enabled:{module}") == "1"
    if not is_configured():
        return True
    return Setting.get(f"mod_enabled:{module}") != "0"


def enabled_modules():
    return [m for m in MODULES if module_enabled(m)]


# --- write -----------------------------------------------------------------
def apply_facility(type_key, facility_name, caps, modules):
    """Persist all three layers. ``caps``/``modules`` are the ticked sets.
    Does NOT commit — caller commits."""
    if type_key not in FACILITY_TYPES:
        type_key = DEFAULT_FACILITY_TYPE
    Setting.set("facility_type", type_key)
    if facility_name:
        Setting.set("clinic_name", facility_name)
    clean_caps = [c for c in caps if c in CAPABILITY_MODULES]
    Setting.set("facility_capabilities", json.dumps(clean_caps))
    wanted = set(modules)
    for m in TOGGLEABLE_MODULES:
        Setting.set(f"mod_enabled:{m}", "1" if m in wanted else "0")
    Setting.set("facility_configured", "1")
