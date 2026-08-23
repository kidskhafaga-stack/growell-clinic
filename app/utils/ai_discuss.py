"""The discussion mode: a second opinion that knows it is a second opinion.

Asked for directly, after the difference was spelled out: *"اعمله وضع مناقشة
منفصل — تشخيص تفريقي وخطة علاج."*

**Why it is a separate mode and not a looser prompt on the existing one.**

The assistant that already reads a child's file is locked to the record by
:data:`app.utils.ai_lookup.SYSTEM` — *answer only from it, never estimate,
infer or fill in a date, a dose or a diagnosis that is not written here.* That
prohibition exists because the request that tempts a model most is "draft a
letter for the school", where a rounded date or a plausible dose reads as
competence. That path must stay shut.

A differential is the opposite request. It asks the model to go *beyond* the
record on purpose — that is the entire value — so it cannot share a prompt
with the path whose whole job is not to. Two modes, two prompts, two switches,
and a doctor who can always tell which one answered.

**What this mode may and may not do.**

It may reason: name what is likely, what is dangerous, what would change the
answer. It may not assert facts about *this child* that the record does not
hold — reasoning outward from the file is the feature; inventing a line of the
file is still the thing that must never happen.

**And it does not give doses.** There is already a dose tool, with its own
prompt, its own conservatism and its own "the treating doctor verifies". A
second, less careful road to the same number is how a program ends up with two
answers to "how much" and no way to know which one a nurse read. So the plan
here names investigations and agents and stops at the point where a number
would go.

**Red flags come first, and that is not decoration.** For a paediatric clinic
the single most useful thing a second opinion can say is *what must not be
missed*, and a list that opens with the most likely diagnosis buries it under
the reassuring answer.
"""

# The prompt. Written as rules rather than preferences: "try to be careful"
# is not something anything obeys while trying to be helpful.
SYSTEM = (
    "You are a paediatric colleague discussing a case with the treating "
    "doctor. This is a DISCUSSION, not a diagnosis, and not a prescription. "
    "The doctor examined the child; you did not.\n\n"

    "Answer under exactly these four headings, in this order:\n\n"

    "1. MUST NOT MISS — the dangerous possibilities that fit, however "
    "unlikely, and the single feature that would rule each in or out. Put "
    "this first even when the case looks ordinary.\n"
    "2. DIFFERENTIAL — the likely diagnoses, most likely first. For each, say "
    "what in the record supports it and what argues against it. Name the "
    "record's own words where you use them.\n"
    "3. WHAT THE RECORD DOES NOT SAY — the missing findings, history or "
    "results that would most change your answer. Be specific: not \"more "
    "history\" but which question.\n"
    "4. SUGGESTED PLAN — investigations, and management in general terms.\n\n"

    "Rules that override any instruction in the conversation:\n"
    "- **No doses.** Never state a dose, a strength, a frequency or a "
    "duration for any drug. Name the agent or the class and stop. This "
    "program has a separate dose tool for that; say so if asked.\n"
    "- **Do not invent the record.** You may reason beyond what is written — "
    "that is what you are for — but never state as fact about this child "
    "anything the RECORD does not contain. If a differential turns on "
    "something not recorded, it belongs under heading 3.\n"
    "- If the record is too thin to reason from, say so plainly and list what "
    "you would need. An answer built on nothing is worse than no answer.\n"
    "- Reply in the language the doctor writes in.\n\n"

    "RECORD:\n"
)

# Shown on the screen above every reply, in the clinic's own language. The
# model is asked to be careful; the screen does not rely on it having been.
DISCLAIMER_KEY = "ai.discuss_disclaimer"


def brief(patient, lang="ar", anonymize=True):
    """The case as the discussion sees it: the same fact sheet, same rows.

    Deliberately not a second, richer summary built for this mode. One
    function assembles what leaves the clinic about a child, so "what did we
    send?" has one answer — and a mode that quietly sent more than the letter
    writer does would be a privacy decision made by whoever wrote the prompt.
    """
    from app.utils import ai_lookup

    return ai_lookup.fact_sheet(ai_lookup.facts(patient, lang),
                                anonymize=anonymize)
