"""Who the clinic cannot reach, and what it would take to fix each one.

Reported: *"the 13 cases are a number in a notification right now — I want a
screen reception can ring from and add the number on."*

A count is a statement that something is wrong. It is not a way to put it
right: acting on it meant opening a patient's file, finding the field, saving,
going back, and doing it again thirteen times. So the number stayed thirteen.

Two different failures are collected here, and they are not equally serious:

* **unreachable** — nobody on this child's file has a phone number at all. No
  appointment reminder, no result to call about, no way to say the clinic is
  closed today. This is the one that costs somebody a visit, and it had no
  notification of its own.
* **teen** — a child of thirteen or over with no personal number, which is the
  one the existing notification counts. The family is reachable; the young
  person is not reachable directly.

Both rows carry the number to *ring from* where one exists, because a work list
that tells you to phone somebody without giving you the number is a list you
work through with the patient file open in another tab.
"""
from app.models import Patient
from app.models.patient import own_phone_cutoff


def _guardian_phone(patient):
    """Any number on any guardian of this child, primary first."""
    family = getattr(patient, "family", None)
    if family is None:
        return None, None
    parents = sorted(getattr(family, "parents", []) or [],
                     key=lambda p: (0 if p.is_primary_contact else 1))
    for parent in parents:
        number = (parent.phone or parent.phone_alt or "").strip()
        if number:
            return parent, number
    return (parents[0] if parents else None), None


def _row(patient, kind, lang="ar"):
    guardian, number = _guardian_phone(patient)
    return {
        "patient": patient,
        "kind": kind,
        "guardian": guardian,
        "guardian_id": guardian.id if guardian else None,
        "guardian_name": guardian.display_name(lang) if guardian else None,
        "phone": number,
        # Which field this row's box writes to. Saying so on screen matters:
        # a teen's own number and their mother's number are different facts,
        # and one box that quietly picks is a box that quietly picks wrong.
        "target": "own" if kind == "teen" or guardian is None else "guardian",
    }


def unreachable(lang="ar", limit=None):
    """Active patients with no number anywhere — not their own, not a
    guardian's. The query cannot express "no guardian has a phone" without a
    join per parent, so the shortlist comes from the database and the last
    check is done in Python over a set that is small by definition."""
    query = (Patient.query
             .filter(Patient.is_active.is_(True))
             .order_by(Patient.created_at.desc()))
    rows = []
    for patient in query.all():
        if (patient.own_phone or "").strip():
            continue
        if _guardian_phone(patient)[1]:
            continue
        rows.append(_row(patient, "unreachable", lang))
        if limit and len(rows) >= limit:
            break
    return rows


def teens_without_own_phone(lang="ar", limit=None):
    """Old enough to be rung directly, and no number to ring."""
    query = (Patient.query
             .filter(Patient.is_active.is_(True),
                     Patient.date_of_birth <= own_phone_cutoff(),
                     Patient.own_phone.is_(None) | (Patient.own_phone == ""))
             .order_by(Patient.date_of_birth))
    rows = [_row(p, "teen", lang) for p in query.all()]
    # A teen whose family has no number either is already on the harder list;
    # showing them twice makes the two counts add up to more than the problem.
    rows = [r for r in rows if r["phone"]]
    return rows[:limit] if limit else rows


def worklist(lang="ar"):
    """Both lists, hardest first, with their counts."""
    hard = unreachable(lang)
    teens = teens_without_own_phone(lang)
    return {
        "unreachable": hard,
        "teens": teens,
        "counts": {"unreachable": len(hard), "teens": len(teens),
                   "total": len(hard) + len(teens)},
    }


def save_number(patient, raw, target, guardian_id=None):
    """Write one number where the row said it would go.

    Returns ``(ok, normalised)``. Refuses a number that has no digits in it
    rather than storing punctuation somebody typed by accident — a stored
    non-number is worse than a blank, because the blank is on a work list and
    the non-number is not.
    """
    from app.models import Parent
    from app.utils.whatsapp import normalize_phone

    number = normalize_phone(raw)
    if not number:
        return False, None
    if target == "guardian" and guardian_id:
        parent = Parent.query.filter_by(id=guardian_id).first()
        if parent is None or parent.family_id != getattr(patient, "family_id", None):
            return False, None
        parent.phone = number
        return True, number
    patient.own_phone = number
    return True, number
