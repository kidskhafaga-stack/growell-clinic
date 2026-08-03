"""Whether a course is finished — said out loud, not left to be counted.

The program already knew how many doses each product has: Rotarix two,
RotaTeq three, Prevenar three primary and a booster. What it never did was
*say* so. A card reading "3/4" makes the reader do the arithmetic and still
leaves the question that actually matters unanswered — is the missing one a
primary dose the child is behind on, or the booster that falls due next year?
Those are a phone call and a diary note, and they are not the same job.

Two states are therefore kept apart:

``complete``      — every dose given, booster included. Nothing to chase.
``booster_left``  — the primary series is done and only the booster remains.
                    The child is protected; the reminder is not urgent.
``in_progress``   — a primary dose is still outstanding.
``not_started``   — nothing given here.

**And what was imported is marked as inferred.** The old export has no dose
column, so an imported course was numbered from the order of its dates. A child
with three doses of a four-dose course may have had the first three here — or
have started elsewhere and had doses two, three and four. Nothing in the data
can tell those apart, and the clinic said plainly that this is the doctor's
call. So the state is shown with what it was worked out from, beside the
correction that changes it, rather than asserted as fact.
"""
COMPLETE = "complete"
BOOSTER_LEFT = "booster_left"
IN_PROGRESS = "in_progress"
NOT_STARTED = "not_started"


def course_state(doses):
    """The state of one vaccine's course, from the dose rows of a plan item.

    ``doses`` are the dicts :func:`app.utils.vaccines.patient_plan` builds —
    each carrying ``status``, ``booster`` and ``imported``. Nothing is queried
    and nothing is recomputed here: this reads the plan the screen is already
    showing, so the sentence at the top of a card can never disagree with the
    pills underneath it.
    """
    primary = [d for d in doses if not d.get("booster")]
    boosters = [d for d in doses if d.get("booster")]
    given = [d for d in doses if d.get("status") == "done"]
    given_primary = [d for d in primary if d.get("status") == "done"]
    given_boosters = [d for d in boosters if d.get("status") == "done"]

    if not given:
        state = NOT_STARTED
    elif len(given) >= len(doses):
        state = COMPLETE
    elif boosters and len(given_primary) >= len(primary):
        state = BOOSTER_LEFT
    else:
        state = IN_PROGRESS

    return {
        "state": state,
        "given": len(given), "total": len(doses),
        "primary_given": len(given_primary), "primary_total": len(primary),
        "boosters_given": len(given_boosters), "boosters_total": len(boosters),
        "left": max(len(doses) - len(given), 0),
        # True when any dose behind this answer came from an import, so the
        # screen can say the numbering was worked out rather than observed.
        "inferred": any(d.get("imported") for d in given),
    }


def annotate(plan):
    """Add ``course`` to every item of a plan, in place, and return it."""
    for item in plan:
        item["course"] = course_state(item.get("doses") or [])
    return plan


def summarise(plan):
    """How many courses sit in each state — for the chips at the top."""
    counts = {COMPLETE: 0, BOOSTER_LEFT: 0, IN_PROGRESS: 0, NOT_STARTED: 0}
    for item in plan:
        state = (item.get("course") or course_state(item.get("doses") or []))
        counts[state["state"]] += 1
    return counts
