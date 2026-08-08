"""Importing the same sheet twice must not make the register twice as big.

*"استيراد المرضى يراعي عدم التكرار وياخد الزيادة بس — زي ما عملنا في استيراد
التاريخ بالظبط."*

The patient import wrote every row it was given. A clinic re-uploads — because
it added a few months, because it corrected something in the old program, or
because it cannot remember whether it already did — and every child in the file
got a second file number, a second vaccination card and a second history. The
second one is what the next receptionist finds.

The history import already answers this: load one index up front, walk the rows
in memory, and write only what is new. This is the same idea for people, and
the only hard part is deciding what makes two rows the same person.

**Three keys, strongest first.**

*The old program's file number*, which is what ``reference_number`` is for and
is the only key that is meant to be unique. It is matched against the clinic's
own file numbers too, because after one import the old number is what carries
across.

*The national ID*, when the sheet has one. Also unique, when present, and
present far less often than anybody hopes.

*Name and date of birth together.* This is how a human decides, and the two
must agree: "محمد أحمد" is a quarter of Egypt, and a birthday shared by two
children in one clinic is a weekly occurrence. Names are folded the way every
Arabic comparison here is folded, so "أحمد" and "احمد" are one child rather
than two.

Nothing is updated. The request was the increment, not a merge: a row that
matches is left exactly as it is and reported as already present, because
overwriting a file somebody has since corrected by hand is a worse failure
than importing nothing at all.
"""
from app.utils.history_import import normalise_arabic


def _key(*parts):
    """One comparable string from several cells, or "" if any is missing."""
    folded = [normalise_arabic(p) for p in parts]
    if not all(folded):
        return ""
    return "|".join(folded)


def index():
    """Every way an existing patient can be recognised → their id.

    One query for the whole register, because a real sheet is thousands of
    rows and asking per row is the difference between an import that finishes
    while somebody watches and one they assume has hung.
    """
    from app.extensions import db
    from app.models import Patient

    rows = db.session.query(
        Patient.id, Patient.patient_number, Patient.reference_number,
        Patient.national_id, Patient.full_name, Patient.date_of_birth).all()

    found = {}
    for pid, number, reference, national, name, dob in rows:
        for key in _keys_of(number, reference, national, name, dob):
            found.setdefault(key, pid)
    return found


def _keys_of(number, reference, national, name, dob):
    """The keys one patient answers to. Prefixed, so a file number that
    happens to read like a national ID cannot match one."""
    keys = []
    for value in (reference, number):
        folded = normalise_arabic(value)
        if folded:
            keys.append("ref:" + folded)
    folded = normalise_arabic(national)
    if folded:
        keys.append("nid:" + folded)
    if dob is not None:
        pair = _key(name, dob.isoformat())
        if pair:
            keys.append("name:" + pair)
    return keys


def row_keys(row, dob):
    """The keys an import row answers to — the same shapes as an existing one."""
    return _keys_of(None, row.get("reference_number"), row.get("national_id"),
                    row.get("full_name"), dob)


def match(row, dob, seen):
    """What ``seen`` has under any of this row's keys, or None.

    Called twice by the import: once against the register, and once against
    the rows already read from this same sheet. A file that lists the same
    child twice is the same bug arriving in one upload instead of two — and
    the commoner of the two, since exporting from an old program often gives a
    row per visit rather than a row per child.
    """
    for key in row_keys(row, dob):
        if key in seen:
            return seen[key]
    return None
