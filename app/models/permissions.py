"""Roles, modules and the role -> module access matrix.

Permissions in Phase 1 are module-level: a role either can or cannot reach a
given functional module. This is intentionally coarse-grained; finer actions
(view vs. edit vs. delete) can be layered on per module in later phases without
changing the role definitions here.
"""

# The system roles. `nursing` joined them when nursing stations arrived: a
# nurse is not a doctor with fewer screens — they take the vitals and the
# reason for the visit before the child is seen, and they need the clinical
# module to do it and nothing that prices or bills.
ROLES = ["admin", "doctor", "reception", "accountant", "pharmacy", "nursing"]

# Every functional module in the system. The string keys double as i18n keys
# under ``nav.*`` and as the permission identifiers used by the decorators.
MODULES = [
    "dashboard",
    "patients",
    "appointments",
    "visits",
    "growth",
    "vaccinations",
    # A specialty, not part of the paediatric core. Off until a clinic says
    # otherwise — see `facility.OPT_IN_MODULES`.
    "dentistry",
    # The specialty panels: which extra questions a doctor is asked on the
    # visit screen. A module rather than a setting because a clinic that does
    # not work specialties should not have the section on its consultation
    # screen at all — not an empty picker, not a disabled control, absent.
    #
    # Admin-only and opt-in, for the two reasons those lists exist: nobody but
    # whoever runs the clinic ever opens it, and a general paediatric practice
    # is not asked a question it has no answer to.
    "panels",
    # Readings taken again and again at the interval a doctor set — the rounds.
    # A module because a clinic seeing outpatients has no rounds at all, and
    # opt-in for the same reason dentistry is: nobody is handed a ward screen
    # by upgrading. It is what emergency, the incubators, the ward and the
    # recovery room are all built on (see HOSPITAL_PLAN.md, أساس ١).
    "observations",
    # The place a child stays, and the stay itself: units, spaces, beds and
    # admissions. One module for four departments — emergency, the incubators,
    # intensive care and the ward differ by how often a child is looked at,
    # not by what a bed is (HOSPITAL_PLAN.md, ٤-ب). Opt-in: a clinic that sees
    # outpatients has no beds and must not find a ward screen after upgrading.
    "beds",
    # The two departments that have a screen of their own. Not two systems:
    # both are `utils/department.live` over the same place, stay and readings,
    # at different tempos — emergency ends in a decision, the incubators watch
    # four facts no other department needs. Opt-in like everything above them.
    "emergency",
    "nicu",
    # And the two slow ones. A ward is read in days rather than in minutes,
    # and intensive care is the same ward screen looked at four times as
    # often — the difference is the interval on the child's observation
    # order, which a doctor writes, not a branch in any file.
    #
    # Separate modules and not one "inpatient" module, for the reason all of
    # these are separate: a hospital that runs wards and no intensive care
    # must not find an intensive care screen after an update.
    "icu",
    "ward",
    # The operating theatres. **Not a department with beds** — a theatre is
    # booked, used for ninety minutes and cleaned, so it is a schedule and not
    # a place a child sleeps (HOSPITAL_PLAN.md ٤-ج). Its own module and not a
    # corner of `beds` for the reason all of these are separate: a hospital
    # that admits children and operates on none of them must not find a
    # theatre list after an update.
    "theatres",
    # The lab bench. Not the ordering — that has been on the visit screen for
    # years, and the reading has its own inbox. This is the middle nobody had
    # a screen for: the sample, and the person who runs it. Its own module and
    # opt-in, because a clinic that sends its tests out has no bench.
    "labs",
    # The counter. Not the writing — the prescription writer has existed for
    # years and the dose and interaction checks with it. This is the act
    # underneath: somebody reviews the paper, takes the box off the shelf and
    # hands it over. Opt-in, because a clinic whose families fill their
    # prescriptions outside has no counter.
    "pharmacy",
    # **The rota.** Who is covering the department tonight, and what the
    # clinic owes them for it — the second direction money goes in this
    # program, and the only one with no invoice behind it. Deliberately not a
    # corner of `beds`: a clinic with no wards and a resident covering the
    # night is the ordinary case, and gating this behind the inpatient module
    # would have hidden it from most of the clinics that run one.
    "duty",
    "prescriptions",
    "inventory",
    "finance",
    "reports",
    "ai",
    "messages",
    "users",
    "settings",
]

# Modules whose screens are guarded by ``admin_required`` from end to end, and
# which therefore **cannot** be handed to a role by ticking a box.
#
# Reported as: "I gave the doctor the settings screen and it gives me 404."
# The role editor offered the tick, the sidebar honoured it — `can_access`
# reads the role's module list — and every route behind it asks `is_admin`
# instead. So the doctor got a Settings link that answered 403, and a 404 on
# any address under it that does not exist. Measured across all fourteen
# modules by granting every one of them to a test role and opening each: these
# two were the only ones that refused.
#
# They are not simply removed from ``MODULES``: the sidebar, the module
# toggles and the icons all iterate that list, and an admin does reach both.
# What changes is that a role cannot be *granted* them, which is the promise
# that was not being kept.
ADMIN_ONLY_MODULES = ["users", "settings", "panels"]

# What a role checkbox may actually grant.
GRANTABLE_MODULES = [m for m in MODULES if m not in ADMIN_ONLY_MODULES]

# Module -> Bootstrap icon name, used by the sidebar navigation.
MODULE_ICONS = {
    "dashboard": "speedometer2",
    "patients": "people",
    "appointments": "calendar-week",
    "visits": "clipboard2-pulse",
    "growth": "graph-up",
    "vaccinations": "shield-plus",
    "dentistry": "emoji-smile",
    "panels": "clipboard-data",
    "observations": "activity",
    "beds": "hospital",
    "emergency": "thermometer-half",
    "nicu": "moisture",
    "icu": "heart-pulse",
    "ward": "buildings",
    "theatres": "scissors",
    "labs": "eyedropper",
    "pharmacy": "prescription2",
    "duty": "calendar-week",
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
        # A paediatric dentist is a doctor. Granting it costs a clinic that
        # does not do dentistry nothing — the module is off for them, and an
        # off module is unreachable whoever asks.
        "dentistry",
        # They order the rounds; the nurse records them.
        "observations",
        # Admitting and discharging is a clinical decision.
        "beds",
        "emergency",
        "nicu",
        "icu",
        "ward",
        # Surgeons and anaesthetists are doctors, and the checklist is signed
        # by whoever is standing at the table.
        "theatres",
        # They order the tests; seeing where one has got to is the same
        # question as "has anybody been to draw this child's blood".
        "labs",
        # The rota — reading it, which is what "who is on tonight" is. What a
        # night pays and who is put on it stay admin-only inside the screen.
        "duty",
        "prescriptions",
        "ai",
    ],
    # The vitals station and the child's file, and nothing else. No
    # prescriptions (they do not prescribe) and no finance (they do not bill).
    "nursing": [
        "dashboard",
        "patients",
        "appointments",
        "visits",
        "growth",
        "vaccinations",
        # The rounds are theirs to take. Whoever holds the thermometer at
        # three in the morning is the one this module was built for.
        "observations",
        # And they move children between beds, which is the same shift's work.
        "beds",
        "emergency",
        "nicu",
        "icu",
        "ward",
        # The scrub nurse runs the checklist more often than anybody. Leaving
        # them out would have meant the one stop nobody may skip is signed by
        # borrowing a doctor's login, which is how a signature stops meaning
        # anything.
        "theatres",
        # Whoever walks to the bed with the tube. A clinic with a lab
        # technician of its own makes a role for them — roles are data.
        "labs",
        # Nursing works the same nights, and "who is on with me" is the
        # question the rota exists to answer.
        "duty",
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
        # The counter itself, which is the job. The role was named for it and
        # could not reach it: they saw the prescription and had nowhere to
        # record that they had handed anything over.
        "pharmacy",
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
    # Writing a standing drug order for a child in a bed. **Not the same act
    # as giving one**, and the split is the oldest safety rule on a ward:
    # whoever holds the syringe is not the one who decided what is in it.
    #
    # A capability rather than `role == "doctor"`, because roles in this
    # program are editable and a hospital that invents "registrar" would
    # otherwise find that its registrars cannot prescribe and nothing on any
    # screen says why. Nursing keeps the ward and the drug round and does not
    # get this one.
    "medication_order",
]

ROLE_CAPABILITIES = {
    "admin": list(CAPABILITIES),
    "doctor": ["patient_medical", "medication_order"],
    "reception": ["cashier"],
    # They write into the child's clinical record — the vitals, the reason for
    # the visit — so they hold the medical capability and no money one.
    "nursing": ["patient_medical"],
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
