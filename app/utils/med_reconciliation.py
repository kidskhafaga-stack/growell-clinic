"""Medication reconciliation at a stay's interfaces — GAHAR MMS.10 / GSR.18.
The model and the reasons are in ``app/models/med_reconciliation.py``.

**What each moment looks at:**

* admission — the home list (``PatientMedication`` still running);
* transfer — the ward chart (``MedicationOrder`` still running), once per
  move into another unit;
* discharge (home or to another hospital) — both lists.

**A moment is reconciled** when every item on its list has a decision, saved
together; a moment with nothing on its list is reconciled already (a child on
nothing has a reviewed list — the clinic's own rule, ``patient_meds``).

**What a decision does.** Only at discharge, and only what the doctor said:
a home medicine *stopped* there is stopped on the home list (as the clinic's
review does), and a ward order *continued* there joins the home list, so the
next visit's reconciliation finds what the child went home on. At admission
and transfer a decision is the record; the chart is changed on the chart.
"""
from app.extensions import db
from app.models.med_reconciliation import (ADMISSION, DECISIONS, DISCHARGE,
                                           INTERFACES, TRANSFER,
                                           MedReconciliation)


def _unit_id(stay):
    bed = getattr(stay, "bed", None)
    unit = getattr(bed, "unit", None) if bed is not None else None
    return getattr(unit, "id", None)


def transfers(admission):
    """The stays that began in another unit than the one before — the moves
    that are a transfer, not a bed changed in the same ward."""
    stays = sorted(admission.stays or [], key=lambda s: (s.since, s.id))
    return [stay for before, stay in zip(stays, stays[1:])
            if _unit_id(stay) != _unit_id(before)]


def items(admission, interface):
    """``[(kind, row)]`` to decide at ``interface`` — ``kind`` is ``home``
    or ``order``."""
    from app.utils import drug_round, patient_meds

    home = [("home", m) for m in patient_meds.current(admission.patient_id)]
    ward = [("order", o) for o in
            (drug_round.running_orders([admission.id]).get(admission.id) or [])]
    if interface == ADMISSION:
        return home
    if interface == TRANSFER:
        return ward
    return home + ward


def label(kind, row):
    if kind == "home":
        bits = [row.name, row.dose, row.frequency]
    else:
        bits = [row.drug_name, row.dose,
                f"q{row.every_hours}h" if row.every_hours else None]
    return " · ".join(b for b in bits if b)


def decisions(admission, interface, stay=None):
    """The saved rows for this moment, newest first."""
    query = MedReconciliation.query.filter(
        MedReconciliation.admission_id == admission.id,
        MedReconciliation.interface == interface)
    if interface == TRANSFER:
        query = query.filter(MedReconciliation.stay_id == getattr(stay, "id", stay))
    return query.order_by(MedReconciliation.decided_at.desc(),
                          MedReconciliation.id.desc()).all()


def is_done(admission, interface, stay=None):
    return bool(decisions(admission, interface, stay)) or not items(admission, interface)


def status(admission):
    """For the stay's page: each moment, done or still open. Discharge is
    counted open only once the child has left — before that it is offered,
    not owed."""
    out = {"admission": {"done": is_done(admission, ADMISSION),
                         "n": len(items(admission, ADMISSION))},
           "transfers": [{"stay": s, "done": is_done(admission, TRANSFER, s)}
                         for s in transfers(admission)],
           "discharge": {"done": bool(decisions(admission, DISCHARGE))
                         or not items(admission, DISCHARGE),
                         "owed": admission.discharged_at is not None,
                         "n": len(items(admission, DISCHARGE))}}
    out["open"] = (int(not out["admission"]["done"])
                   + sum(1 for t in out["transfers"] if not t["done"])
                   + int(out["discharge"]["owed"] and not out["discharge"]["done"]))
    return out


def save(admission, interface, form, user=None, stay=None):
    """Write one decision per item. Returns what is still undecided — and
    writes nothing then: a moment half-reconciled is not reconciled, and the
    screen keeps what was chosen. The caller commits."""
    if interface not in INTERFACES:
        raise ValueError(interface)
    todo = items(admission, interface)
    missing = [(kind, row.id) for kind, row in todo
               if form.get(f"d_{kind}_{row.id}") not in DECISIONS]
    if missing:
        return missing
    for kind, row in todo:
        decision = form.get(f"d_{kind}_{row.id}")
        note = (form.get(f"n_{kind}_{row.id}") or "").strip()[:200] or None
        db.session.add(MedReconciliation(
            admission_id=admission.id, patient_id=admission.patient_id,
            interface=interface,
            stay_id=getattr(stay, "id", None) if interface == TRANSFER else None,
            home_med_id=row.id if kind == "home" else None,
            order_id=row.id if kind == "order" else None,
            name=label(kind, row)[:200], decision=decision, note=note,
            decided_by=getattr(user, "id", None)))
        if interface == DISCHARGE:
            _carry_home(admission, kind, row, decision, user, note)
    db.session.flush()
    return []


def _carry_home(admission, kind, row, decision, user, note):
    """Discharge only, and only what was decided — see the module's note."""
    from app.models import PatientMedication
    from app.utils import patient_meds

    if kind == "home" and decision == "stop":
        patient_meds.stop(row, user=user, reason=note)
        return
    if kind != "order" or decision != "continue":
        return
    generic_id = getattr(getattr(row, "drug", None), "generic_id", None)
    for med in patient_meds.current(admission.patient_id):
        same = (generic_id and med.generic_id == generic_id) or \
            (med.name or "").strip().casefold() == (row.drug_name or "").strip().casefold()
        if same:
            return
    db.session.add(PatientMedication(
        patient_id=admission.patient_id, name=row.drug_name[:160],
        drug_id=row.drug_id, generic_id=generic_id, dose=row.dose,
        frequency=f"q{row.every_hours}h" if row.every_hours else None,
        notes=note, added_by=getattr(user, "id", None)))


__all__ = ["ADMISSION", "DECISIONS", "DISCHARGE", "INTERFACES", "TRANSFER",
           "decisions", "is_done", "items", "label", "save", "status", "transfers"]
