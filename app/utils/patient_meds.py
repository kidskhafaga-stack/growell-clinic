"""Reading and changing what a child is already on.

The value is in one line of :func:`ingredient_ids`, which is what lets the
interaction check see past the prescription being written. Everything else here
is bookkeeping around it.

Two rules worth stating, because both are easy to get wrong in the obvious
direction:

**Stopping is not deleting.** A medicine the child was on until March explains
a result, a rash, a decision somebody else made. Removing the row destroys that
and leaves the file looking as though the drug was never given.

**A row nobody could link is still worth having.** Parents say "the white
syrup". That row cannot join an interaction check and it can still stop the
next doctor from starting a second one — so free text is accepted, and the
program is simply honest that it can reason about some rows and not others.
"""
from app.utils.clock import local_today


def current(patient):
    """Medicines being taken now, oldest first."""
    if patient is None:
        return []
    from app.models import PatientMedication

    patient_id = getattr(patient, "id", patient)
    return (PatientMedication.query
            .filter(PatientMedication.patient_id == patient_id,
                    PatientMedication.stopped_on.is_(None))
            .order_by(PatientMedication.started_on,
                      PatientMedication.id).all())


def history(patient):
    """Everything ever recorded, current first, then most recently stopped."""
    if patient is None:
        return []
    from app.models import PatientMedication

    patient_id = getattr(patient, "id", patient)
    rows = (PatientMedication.query
            .filter(PatientMedication.patient_id == patient_id)
            .order_by(PatientMedication.id.desc()).all())
    return sorted(rows, key=lambda r: (r.stopped_on is not None,
                                       -(r.id or 0)))


def ingredient_ids(patient):
    """Ingredient ids of what the child is on — the point of the whole file.

    The interaction check reads the drugs being written and nothing else, so a
    child on carbamazepine handed a macrolide produced no warning: the
    carbamazepine was written months ago and was never in the list. These ids
    put it there.

    Rows with no ingredient link contribute nothing, which is the honest
    answer — the program cannot check what it cannot identify, and pretending
    otherwise would be worse than the gap.
    """
    return [row.generic_id for row in current(patient) if row.generic_id]


def add(patient, name, user=None, **fields):
    """Record a medicine. ``name`` is the only thing required."""
    from app.extensions import db
    from app.models import PatientMedication

    name = (name or "").strip()
    if not name:
        return None
    row = PatientMedication(
        patient_id=getattr(patient, "id", patient),
        name=name,
        added_by=getattr(user, "id", None),
        started_on=fields.pop("started_on", None) or local_today(),
        **{k: v for k, v in fields.items() if v not in ("", None)})
    db.session.add(row)
    db.session.commit()
    return row


def stop(row, user=None, reason=None, on=None):
    """End a medicine without losing that it was ever given.

    Stopping twice is not an error and does not move the date: the first stop
    is the one that happened, and a double-click on a slow screen must not
    quietly rewrite the record.
    """
    from app.extensions import db

    if row is None or row.stopped_on is not None:
        return row
    row.stopped_on = on or local_today()
    row.stopped_by = getattr(user, "id", None)
    row.stop_reason = (reason or "").strip() or None
    db.session.commit()
    return row


# --- the reconciliation ---------------------------------------------------

def review(medication, decision, user=None, visit=None, note=None):
    """Write down what was decided about one medicine at this encounter.

    A stop decision also stops the medicine — the review is the document and
    ``PatientMedication`` is the state, and it would be a poor document that
    said "stopped" beside a drug the program still thinks the child is on.
    """
    from app.extensions import db
    from app.models import REVIEW_DECISIONS, MedicationReview

    if medication is None or decision not in REVIEW_DECISIONS:
        return None
    row = MedicationReview(
        patient_id=medication.patient_id,
        medication_id=medication.id,
        visit_id=getattr(visit, "id", visit),
        decision=decision,
        note=(note or "").strip() or None,
        reviewed_by=getattr(user, "id", None))
    db.session.add(row)
    if decision == "stop":
        stop(medication, user=user, reason=note)
    db.session.commit()
    return row


def reviewed_ids(patient, visit):
    """Medicines already reviewed at this encounter.

    So the screen can show what is left rather than asking twice — and so
    "everything on the list was looked at" is a question the program can
    actually answer.
    """
    if patient is None or visit is None:
        return set()
    from app.models import MedicationReview

    rows = (MedicationReview.query
            .filter(MedicationReview.patient_id == getattr(patient, "id", patient),
                    MedicationReview.visit_id == getattr(visit, "id", visit))
            .all())
    return {row.medication_id for row in rows}


def reconciled(patient, visit):
    """Has every medicine on the list been decided about at this encounter?

    ``True`` with an empty list as well — a child on nothing has a reviewed
    list, and answering "no" there would put a permanent warning on the
    healthy majority and teach everybody to ignore it.
    """
    outstanding = [m for m in current(patient)
                   if m.id not in reviewed_ids(patient, visit)]
    return not outstanding
