"""The side menu in sections, and the search at its top.

Asked after a video of a menu with a search box and sections that fold: a
hospital running every department had **38 doors in one column**, and the
settings and the incident board sat at the bottom of a list taller than the
screen.

**A clinic keeps its menu.** The owner's rule — nothing in the clinic changes
after an update unless asked — and the answer when asked: the sections appear
only where a hospital department is switched on. A clinic that runs none of
them sees the list it had, in the order it had, with the search box added
above it and nothing else.

**What the sections are.** Six, by who reaches for them: the clinic's day, the
hospital's departments, money and stock, quality, reports and messages, and
running the program. The order inside each is the menu's own order, so a door
moves into a section and never past its neighbours.

**Nothing is hidden by a section.** A folded section is folded for this
person only, on this browser, and the section holding the page they are on
never folds.
"""
from __future__ import annotations

# Section → the doors in it. Anything not named falls into «admin», so a door
# added later is never lost — at worst it is in the last section.
SECTIONS = ("clinic", "hospital", "money", "quality", "reports", "admin")

SECTION_OF = {
    # the clinic's day
    "dashboard": "clinic", "patients": "clinic", "appointments": "clinic",
    "visits": "clinic", "device_board": "clinic", "growth": "clinic",
    "vaccinations": "clinic", "dentistry": "clinic", "prescriptions": "clinic",
    "telemedicine": "clinic", "my_clinic": "clinic", "my_patients": "clinic",
    # the hospital's departments
    "observations": "hospital", "beds": "hospital", "emergency": "hospital",
    "nicu": "hospital", "icu": "hospital", "ward": "hospital",
    "theatres": "hospital", "labs": "hospital", "imaging": "hospital",
    "pharmacy": "hospital", "ambulance": "hospital",
    # money and stock
    "finance": "money", "cashier": "money", "inventory": "money",
    # quality
    "incident_report": "quality", "incidents": "quality",
    "complaints": "quality", "ipc": "quality", "programs": "quality",
    # reports and messages
    "reports": "reports", "ai": "reports", "messages": "reports",
    # running the program
    "duty": "admin", "teaching": "admin", "panels": "admin",
    "users": "admin", "settings": "admin", "guide": "admin",
}

SECTION_ICONS = {
    "clinic": "heart-pulse", "hospital": "hospital", "money": "cash-stack",
    "quality": "shield-check", "reports": "bar-chart", "admin": "gear",
}

# The departments that make a place a hospital. Not the lab, the films or the
# pharmacy: a clinic may run any of those and is still a clinic, and must not
# find its menu rearranged for it.
HOSPITAL_PARTS = ("beds", "emergency", "nicu", "icu", "ward", "theatres",
                  "ambulance")


def in_sections() -> bool:
    """Whether the menu is drawn in sections: only with a hospital part on."""
    from app.utils.facility import module_enabled

    return any(module_enabled(m) for m in HOSPITAL_PARTS)


def section_of(key: str) -> str:
    return SECTION_OF.get(key, "admin")


def arrange(items):
    """``[(section, [item, …]), …]`` in section order, empty sections left out.

    ``items`` are the menu's doors in the menu's own order, each a mapping
    with a ``key``; that order is kept inside every section.
    """
    rows = {s: [] for s in SECTIONS}
    for item in items:
        rows[section_of(item["key"])].append(item)
    return [(s, rows[s]) for s in SECTIONS if rows[s]]
