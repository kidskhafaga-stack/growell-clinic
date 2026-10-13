"""The initial medical assessment — see ``models/medical_assessment``.

``assembled`` reads each of the ten elements from wherever the record already
holds it, and names its source; only the ones nothing holds are asked for.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models.medical_assessment import ELEMENTS, WITHIN_HOURS, MedicalAssessment

#: The elements this row itself can hold.
OWN = ("complaint", "present_illness", "medications", "social", "family", "exam", "specialty",
       "provisional_dx")


class AssessmentError(ValueError):
    """A refusal with a locale key (``medass.err_<key>``)."""


def _text(raw):
    return (raw or "").strip() or None


def for_stay(stay_id):
    return (MedicalAssessment.query.filter_by(admission_id=stay_id)
            .order_by(MedicalAssessment.id).first())


def _visit(stay):
    from app.models import Visit

    return db.session.get(Visit, stay.visit_id) if stay.visit_id else None


def assembled(stay):
    """``{element: (source_key, text)}`` for each element the record holds,
    the row's own text winning over the visit's."""
    from app.models import Diagnosis, PatientMedication, PatientProblem
    from app.models.patient import PanelHistory

    patient, visit, row = stay.patient, _visit(stay), for_stay(stay.id)
    out = {}

    def put(element, source, text):
        text = (text or "").strip()
        if text and element not in out:
            out[element] = (source, text)

    if row is not None:
        for e in OWN:
            put(e, "assessment", getattr(row, e))
    put("complaint", "visit", visit.chief_complaint if visit else None)
    put("complaint", "admission", stay.reason)
    put("exam", "visit", visit.clinical_exam if visit else None)
    put("past_history", "file", patient.chronic_diseases)
    problems = PatientProblem.query.filter_by(patient_id=patient.id).all()
    put("past_history", "problems", "، ".join(p.title for p in problems if p.title))
    put("allergies", "file", patient.allergies)
    meds = PatientMedication.query.filter_by(patient_id=patient.id, stopped_on=None).all()
    put("medications", "home_meds", "، ".join(m.name for m in meds))
    if visit is not None:
        dx = Diagnosis.query.filter_by(visit_id=visit.id).all()
        put("provisional_dx", "visit", "، ".join(d.title for d in dx))
    panels = PanelHistory.query.filter_by(patient_id=patient.id).all()
    put("specialty", "panel", "\n".join(p.text for p in panels if (p.text or "").strip()))
    return out


def missing(stay, known=None):
    known = assembled(stay) if known is None else known
    return [e for e in ELEMENTS if e not in known]


def done_at(stay):
    """When an initial assessment existed — the row, or the visit the child
    was admitted from."""
    row, visit = for_stay(stay.id), _visit(stay)
    moments = [m for m in ((row.at if row else None),
                           (visit.created_at if visit and (visit.clinical_exam or visit.chief_complaint)
                            else None)) if m]
    return min(moments) if moments else None


def clock(stay, now=None):
    """Ev. 3 — within 24 hours of hospitalization: ``on_time`` / ``late`` /
    ``due`` (still inside the 24 hours) / ``overdue``."""
    now = now or datetime.utcnow()
    due = stay.admitted_at + timedelta(hours=WITHIN_HOURS)
    at = done_at(stay)
    if at is not None:
        return {"state": "on_time" if at <= due else "late", "due": due, "at": at}
    return {"state": "due" if now <= due else "overdue", "due": due, "at": None}


def save(stay, form, user):
    """Write what the record did not have. Allergies and past history go to
    the child's file, not to this row."""
    row = for_stay(stay.id)
    wrote = False
    if row is None:
        row = MedicalAssessment(patient_id=stay.patient_id, admission_id=stay.id,
                                by_id=getattr(user, "id", None))
    for e in OWN:
        value = _text(form.get(e))
        if value is not None:
            setattr(row, e, value)
            wrote = True
    patient = stay.patient
    allergies, past = _text(form.get("allergies")), _text(form.get("past_history"))
    if allergies and not (patient.allergies or "").strip():
        patient.allergies, wrote = allergies, True
    if past and not (patient.chronic_diseases or "").strip():
        patient.chronic_diseases, wrote = past, True
    if not wrote:
        raise AssessmentError("empty")
    if row.id is None:
        db.session.add(row)
    else:
        row.updated_at = datetime.utcnow()
    db.session.flush()
    return row


__all__ = ["AssessmentError", "assembled", "clock", "done_at", "for_stay", "missing", "save"]
