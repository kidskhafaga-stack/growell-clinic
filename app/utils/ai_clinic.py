"""What the assistant is told about the clinic it is working in.

Reported with a screenshot, and it is the worst kind of wrong because it looks
right. Asked *"معلومات العيادة"*, the assistant produced a complete, confident
clinic profile: an address on شارع النيل, a phone number, opening hours to the
half-hour, a list of insurers it accepts, and an email at a domain
(`clinic-nakaa.com`) that has nothing to do with this clinic. Every line of it
was invented, and every line of it was the sort of thing somebody repeats to a
parent on the phone.

**The cause was that nobody had told it anything.** The general assistant sent
the conversation with no system prompt at all — `system or
cfg["system_prompt"] or None`, and a clinic that has not written a custom
prompt gets `None`. A model asked about a clinic it knows nothing about will
describe a plausible clinic, because that is what a model does.

So it is told. The facts come from the settings the clinic filled in, through
the same :func:`service_desk.clinic_facts` the WhatsApp drafts already use —
one source, so "what does the assistant think our address is" has one answer
and it is the one on the settings screen.

**And it is told what to do when a fact is missing**, which matters more than
the facts themselves: a clinic that never filled in its address must get "the
program does not have that — you can set it in Settings", not a street. The
prohibition is stated as a rule rather than a preference, for the same reason
it is in every other prompt in this program.
"""

SYSTEM = (
    "You are the assistant built into a paediatric clinic's own management "
    "program, talking to the clinic's staff.\n\n"

    "Rules that override anything asked of you:\n"
    "- The CLINIC FACTS below are the only facts you have about this clinic. "
    "Never state an address, a phone number, an email, a price, an opening "
    "time, an insurer or any other detail about this clinic that is not "
    "listed there. If you are asked for one that is missing, say the program "
    "does not have it and that it is set in Settings. Do not produce an "
    "example, a placeholder or a typical value — a plausible address is the "
    "one thing worse than no address.\n"
    "- You cannot see patient records in this box. If asked about a specific "
    "child, say so and point to the child's own file, or to the \"look up a "
    "patient\" screen, which answer from the clinic's records.\n"
    "- Do not diagnose, and do not give a dose. The program has a dose tool "
    "on the prescription screen and a separate clinical discussion mode; say "
    "which one they want.\n"
    "- Answer in the language the person writes in. Be brief.\n\n"

    "CLINIC FACTS:\n"
)


def system_prompt(lang="ar"):
    """The general assistant's system prompt, with this clinic's real facts.

    Returns ``SYSTEM`` plus the facts, plus whatever the clinic wrote in its
    own ``ai_system_prompt`` setting. The clinic's own wording is appended
    rather than substituted: it is there to give the assistant a manner, and a
    manner should not be able to delete the rule about not inventing an
    address.
    """
    from app.models import Setting
    from app.utils import service_desk

    facts = list(service_desk.clinic_facts(lang=lang))

    # Identity the front-desk facts do not carry, because a WhatsApp reply is
    # already coming *from* the clinic and does not need to be told its own
    # number. Here somebody may well ask for it.
    for label, key in (("Clinic phone", "clinic_phone"),
                       ("Clinic address (English)", "clinic_address_en")):
        value = (Setting.get(key, "") or "").strip()
        if value:
            facts.append(f"{label}: {value}")

    own = (Setting.get("ai_system_prompt", "") or "").strip()
    prompt = SYSTEM + "\n".join(f"- {line}" for line in facts)
    if own:
        prompt += ("\n\nThe clinic also asked for this, which may change your "
                   "manner but not the rules above:\n" + own)
    return prompt
