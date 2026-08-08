"""Finding the brother who is already a patient here.

"Add sibling" only ever led to a blank new-patient form, and that is the wrong
half of the problem. In a clinic that has been open a while the sibling is
**already registered** — with his own file number, his own vaccination card and
his own history — from before anybody thought to link the family. Sending
somebody to create him again produces two files for one child, and the second
one is the one the next receptionist finds.

So there are two actions, not one: **link somebody who exists**, and create a
new file when they really do not.

And the program can do most of the finding. It already holds the two things a
receptionist would go on:

**The family name.** Egyptian names carry the father's and grandfather's names,
so two children of one family share their last two words far more reliably than
they share a surname field nobody fills in.

**The parents' phone.** A number is either the same or it is not, which makes
it the strongest signal on the screen — and it is the one thing a family gives
the clinic every single visit.

Nothing here links anybody. It proposes, with the reason it is proposing, and
a person confirms — because merging two children's files is not something to
be clever about.
"""
from app.utils.history_import import normalise_arabic

# How many trailing words of the name to compare. Two, because "محمد" alone is
# a quarter of Egypt and four words is a full match nobody needs help finding.
NAME_TAIL = 2


def name_key(full_name):
    """The last two words of a name, folded — the family part of it."""
    words = [w for w in normalise_arabic(full_name).split(" ") if w]
    return " ".join(words[-NAME_TAIL:]) if len(words) >= NAME_TAIL else ""


def _phones(family):
    """Every parent phone on a family, normalised to digits."""
    out = set()
    for parent in (getattr(family, "parents", None) or []):
        for value in (parent.phone, parent.phone_alt):
            digits = "".join(ch for ch in str(value or "") if ch.isdigit())
            if len(digits) >= 7:        # shorter than that is not a phone
                out.add(digits[-10:])   # compare the tail: 0100… vs +2010…
    return out


def suggest_siblings(patient, limit=8):
    """Patients who look like this child's brothers and sisters.

    ``[{patient, reason}]`` — the reason is shown, because "why is this person
    on my screen" decides whether somebody trusts the suggestion or ignores
    the whole feature.

    Anybody already in *this* family is excluded. Somebody filed with a family
    of their own is still shown — finding the brother is most of the value, and
    it is the commonest shape of the problem, since a child registered with a
    guardian always gets a family row.

    They carry ``in_family`` so the screen can say what pressing the button
    will do. It used to mean the screen refused instead, on the reasoning that
    joining two households is a merge of two sets of parents. A clinic showed
    that this was the wrong call: a real import had split one family in two,
    the screen suggested each sibling to the other, and every attempt to act
    on the suggestion was turned down. The commonest case here is not two
    households — it is one household the program divided.
    """
    from app.models import Patient

    if patient is None:
        return []

    mine = name_key(patient.full_name)
    my_phones = _phones(patient.family) if patient.family else set()
    if not mine and not my_phones:
        return []

    out = []
    rows = (Patient.query.filter(Patient.is_active.is_(True),
                                 Patient.id != patient.id).all())
    for other in rows:
        if other.family_id and other.family_id == patient.family_id:
            continue                    # already in this family
        reason = None
        if my_phones and _candidate_phones(other) & my_phones:
            reason = "phone"
        elif mine and name_key(other.full_name) == mine:
            reason = "name"
        if reason:
            out.append({"patient": other, "reason": reason,
                        # Filed with a family of their own. Still worth
                        # showing — finding the brother is most of the value —
                        # but joining them is a merge of two sets of parents,
                        # not a link, so the screen offers their file instead
                        # of a button that would only ever refuse.
                        "in_family": bool(other.family_id)})

    # The phone is the stronger signal, and the ones that can be linked in one
    # press come before the ones that need a person to go and look.
    out.sort(key=lambda row: (row["in_family"], row["reason"] != "phone",
                              row["patient"].full_name or ""))
    return out[:limit]


def _candidate_phones(other):
    """Every number that could identify this child's household.

    Their family's parents *and* their own phone. The first is what makes the
    rule fire at all — a child registered with a guardian always gets a family
    row, so a suggestion engine that only looked at family-less patients would
    have a phone rule that could never match anything.
    """
    numbers = _phones(getattr(other, "family", None))
    digits = "".join(ch for ch in str(getattr(other, "own_phone", "") or "")
                     if ch.isdigit())
    if len(digits) >= 7:
        numbers.add(digits[-10:])
    return numbers


def certain_sibling(patient):
    """The one candidate safe enough to link without asking — or None.

    The import links children by their father's name, which on real data puts
    strangers in one family: "محمد أحمد" is not a fact about a household. So
    this is deliberately much stricter than :func:`suggest_siblings`, which
    proposes anything worth a human glance.

    **Both signals must agree.** The same guardian phone *and* the same family
    part of the name. Either alone is common — siblings share a phone with
    their cousins in one shop's records, and two unrelated "محمد أحمد" walk in
    every week — but a household that matches on both is one household.

    **And the other child must have no family of their own.** Joining two
    existing families is a merge of two sets of parents, and no rule should
    ever do that on its own.
    """
    if patient is None:
        return None
    mine = name_key(patient.full_name)
    my_phones = _phones(patient.family) if patient.family else set()
    if not mine or not my_phones:
        return None            # one signal missing: nothing here is certain

    from app.models import Patient

    matches = []
    for other in Patient.query.filter(Patient.is_active.is_(True),
                                      Patient.id != patient.id).all():
        if other.family_id:
            continue
        if name_key(other.full_name) != mine:
            continue
        if not (_candidate_phones(other) & my_phones):
            continue
        matches.append(other)
    # Two candidates is not certainty, it is a coincidence with a witness.
    return matches[0] if len(matches) == 1 else None


def auto_link(patient):
    """Link the certain match, marked as the program's doing. Returns it or None.

    Marked, because an automatic link and a receptionist's link are not
    equally trustworthy and the screen has to be able to say which is which.
    Somebody undoing this one is correcting a guess, not overruling a
    colleague.
    """
    from app.extensions import db

    other = certain_sibling(patient)
    if other is None:
        return None
    other.family_id = patient.family_id
    other.family_auto = True
    db.session.flush()
    return other
