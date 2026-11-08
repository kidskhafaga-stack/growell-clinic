"""A child who comes to the laboratory only — LAB_GLAB360_PLAN.md م-٦.

*«مريض جاي للمعمل بس»*: no consultation here, a paper from a doctor outside
asking for tests. Reviewed first, as the plan asked: the program had no way
to put that child on the bench's rack. Every order is a ``VisitInvestigation``
and every one sits on a visit, and the only visits were a doctor's
consultation, a WhatsApp follow-up, an emergency attendance or a stay.

So the request is written the way a stay's orders are (``utils/stay_orders``):
on an encounter of its own, ``channel="lab"``, already completed — it is not
waiting for a doctor, and it never appears in a doctor's queue. It records:

* **whose paper** — the outside doctor, kept once in the clinic's book of
  outside doctors (``referrals.external_doctor``), so the result can be sent
  back to them from the order (``lab_share``, م-٤);
* **the paper itself** — a photo or a PDF of the request, on the child's file
  beside the orders it asked for;
* **the tests** — the clinic's own catalogue, done here, each on the rack
  like any other order; whoever entered them is ``ordered_by``.

Nothing is charged here. The desk collects for a test once the sample is
drawn, the same as every other order (``labs.unbilled``).
"""
from datetime import datetime

from app.extensions import db
from app.utils.clock import local_today

#: What this encounter is called in ``Visit.channel``.
LAB = "lab"


class WalkInError(ValueError):
    """A refusal with a key (``lab_walkin.err_<key>``)."""


def register(patient, tests, user, doctor_name="", doctor_specialty="",
             doctor_place="", doctor_phone="", notes="", paper=None):
    """Write the request. ``tests``: ``Investigation`` rows (lab). ``paper``:
    a ``FileStorage`` of the outside doctor's request, or ``None``. Returns
    the encounter. The caller commits."""
    from app.models import PatientAttachment, Visit, VisitInvestigation
    from app.utils import referrals

    if patient is None:
        raise WalkInError("patient")
    tests = [x for x in tests if x is not None and x.is_active and x.kind == "lab"]
    if not tests:
        raise WalkInError("tests")
    doctor = referrals.external_doctor(doctor_name, doctor_specialty,
                                       doctor_place, doctor_phone)
    if doctor is None:
        raise WalkInError("doctor")
    stored = None
    if paper is not None and getattr(paper, "filename", ""):
        from app.utils.uploads import save_document

        stored = save_document(paper)
        if not stored:
            raise WalkInError("paper")
    db.session.flush()
    note = (notes or "").strip()[:2000] or None
    visit = Visit(patient_id=patient.id, doctor_id=user.id, visit_date=local_today(),
                  status="completed", completed_at=datetime.utcnow(), channel=LAB,
                  outside_doctor_id=doctor.id, notes=note)
    db.session.add(visit)
    db.session.flush()
    for test in tests:
        db.session.add(VisitInvestigation(
            visit_id=visit.id, patient_id=patient.id, investigation_id=test.id,
            kind="lab", name=test.name_ar, name_en=test.name_en,
            request_notes=note[:255] if note else None,
            # The family brought the child here: the order is the bench's
            # even for a test the clinic sends on (``lab_sendout``).
            done_outside=False,
            ordered_by=user.id))
    if stored:
        db.session.add(PatientAttachment(
            patient_id=patient.id, visit_id=visit.id, filename=stored,
            original_name=paper.filename, kind="other",
            label=f"طلب تحاليل — {doctor.name}"[:160], uploaded_by=user.id))
    db.session.flush()
    return visit


def lab_tests():
    """The tests the child can be booked for here: the laboratory's own
    catalogue, active, in house first."""
    from app.models import Investigation

    return (Investigation.query.filter_by(kind="lab", is_active=True)
            .order_by(Investigation.in_house.desc(), Investigation.category,
                      Investigation.name_ar).all())


def recent(limit=10):
    """The last children registered this way, for the screen's own list."""
    from app.models import Visit

    return (Visit.query.filter_by(channel=LAB)
            .order_by(Visit.id.desc()).limit(limit).all())
