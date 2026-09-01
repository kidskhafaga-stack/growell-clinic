"""One place that knows every clinical number the program can be told to use.

Phase 3 of EMERGENCY_NEWBORN_PLAN.md, and it exists because of a mistake made
one commit earlier in the same session. A guard test was written that proved
the heart and respiratory rate bands are held in one module, and the commit
message said *"the numbers are written down in exactly one place"*. That was
true of those two and false of everything else: the fever thresholds live in
`red_flags`, and the oxygen limits lived there too as constants nothing could
change.

The fix is not to move every number into one table. `red_flags` and
`vital_bands` answer different clinical questions — *should this child be seen
now* versus *is this reading inside the usual range* — and merging them would
flatten a distinction that matters. What was missing is **ownership**: a
number a clinic can be told to act on must have a declared owner, a unit, a
default, a source, and a way to change it that a person can find.

So this is a register, not a store. The rules still live and run in the
modules that own them. What is here is the description of each one.

**Editable, and not losable.** Every entry keeps its default; a clinic's
change is an override recorded beside it, never on top of it. That rule is
the whole reason a clinic can be trusted with these at all — a default that
can be edited *away* is a default nobody can get back.

**And direction is a field, not a guess.** "This edit makes the rule less
sensitive" points a different way for each parameter: a *higher* fever
threshold hides children, and a *lower* oxygen threshold hides them. Without
saying which way is which, a screen cannot warn about the edits worth warning
about — and those are the only edits that can quietly turn a safety rule off.
"""
UP, DOWN = "up", "down"

# Where each number comes from. Copied from the module that owns it rather
# than invented here: `red_flags` already states its own provenance in its
# docstring, and a register that showed a blank source next to every default
# would make the field furniture on the first screen anybody opened.
NICE = ("NICE traffic-light guidance and the usual teaching on fever "
        "without source in infants")
PAEDS = "Ordinary paediatric practice"


def _fever_rules():
    """The four age bands, two numbers each — as `red_flags` already holds
    them, read from there so this cannot drift from what actually runs."""
    from app.utils.red_flags import DEFAULT_BANDS

    labels = ["0–3m", "3–6m", "6–36m", "36m+"]
    out = []
    for index, (_months, fever, urgent) in enumerate(DEFAULT_BANDS):
        for name, default, action in (("fever", fever, "watch"),
                                      ("urgent", urgent, "urgent")):
            out.append({
                "key": f"triage_{name}_{index}",
                "parameter": "temperature",
                "unit": "°C",
                "default": default,
                "owner": "red_flags",
                "source": NICE,
                # A higher number means a hotter child before anybody is told.
                "direction": UP,
                "context": labels[index],
                "action": action,
            })
    return out


def _spo2_rules():
    from app.utils.red_flags import SPO2_URGENT, SPO2_WATCH

    return [
        {"key": "triage_spo2_urgent", "parameter": "spo2", "unit": "%",
         "default": SPO2_URGENT, "owner": "red_flags", "source": PAEDS,
         # A lower number means a bluer child before anybody is told.
         "direction": DOWN, "context": "any age", "action": "urgent"},
        {"key": "triage_spo2_watch", "parameter": "spo2", "unit": "%",
         "default": SPO2_WATCH, "owner": "red_flags", "source": PAEDS,
         "direction": DOWN, "context": "any age", "action": "watch"},
    ]


def registry():
    """Every clinical number a clinic can change, with what it means."""
    return _fever_rules() + _spo2_rules()


def by_key():
    return {rule["key"]: rule for rule in registry()}


def value(key):
    """What is in force for this rule: the clinic's number, or the default.

    Falls back on anything unreadable rather than raising, for the same
    reason
    `red_flags.bands()` does: a threshold that cannot be parsed must not be
    able to stop a screen from rendering, and the default is the safe answer.
    """
    rule = by_key().get(key)
    if rule is None:
        return None
    from app.models import Setting

    try:
        raw = (Setting.get(key) or "").strip()
    except Exception:  # noqa: BLE001 — settings table may not be ready
        return rule["default"]
    if not raw:
        return rule["default"]
    try:
        return float(raw)
    except ValueError:
        return rule["default"]


def is_override(key):
    """Whether the clinic has set this one, rather than taking the
    default."""
    from app.models import Setting

    try:
        return bool((Setting.get(key) or "").strip())
    except Exception:  # noqa: BLE001
        return False


def less_sensitive(key, new_value):
    """Would this change make the rule catch **fewer** children?

    The question the editing screen has to be able to ask before it saves.
    `red_flags` says in its own words why: *a threshold set high enough not to
    cry wolf over toddlers is a threshold that silently ignores the infants who
    need it most — so it is not a setting anybody should be able to flatten by
    accident.* An accident is exactly what this is for; the screen warns, the
    person confirms, and nothing is refused.
    """
    rule = by_key().get(key)
    if rule is None or new_value is None:
        return False
    try:
        proposed = float(new_value)
    except (TypeError, ValueError):
        return False
    if rule["direction"] == UP:
        return proposed > float(rule["default"])
    return proposed < float(rule["default"])


def for_screen():
    """Every rule with what is in force, ready to render."""
    rows = []
    for rule in registry():
        current = value(rule["key"])
        rows.append({**rule, "value": current,
                     "overridden": is_override(rule["key"]),
                     "weaker": less_sensitive(rule["key"], current)})
    return rows
