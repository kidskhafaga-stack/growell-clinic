"""The last open piece of GAHAR's medication reconciliation.

Asked for as "the easy part of GAHAR". Checking first turned up that most of
it was already built and the backlog had gone stale about it: the **consent**
record exists (``Consent``, with types and a printable form), the **problem
list** exists (``PatientProblem``, on the profile and the report), and the
**current medication list** was built earlier in this session. The backlog
listed all three as missing for accreditation.

What was genuinely absent is this: at an encounter, **every medicine on the
list is looked at and the decision is written down**.

**"Continue" is a decision and is stored like the others.** The prescription
writer already had a "continue" button that copied a past line into today's
prescription, and that cannot satisfy the standard — it records only the drugs
somebody chose to carry forward. A medicine deliberately continued, and a
medicine nobody looked at, leave exactly the same trace: nothing.
Reconciliation is the claim that the whole list was reviewed, so the boring
decisions are the ones that make the claim true.

**It lives on the visit, not on the prescription.** A visit where nothing is
prescribed still has a list that should have been looked at, and hanging this
off the prescription would mean it simply never happens on those days.

**The review is history; the medicine is state.** Whether the child is still on
something lives on ``PatientMedication`` and nowhere else. A review says what
was decided on a day and by whom, and stays true after somebody stops the drug
next month.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _med(clinic, name="تجريتول", **fields):
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        return meds.add(patient, name, **fields).id


def _decide(clinic, med_id, decision, note=None):
    data = {"decision": decision}
    if note:
        data["note"] = note
    return clinic["sign_in"]("doc").post(
        f"/visits/{clinic['ids']['visit']}/reconcile/{med_id}",
        data=data, follow_redirects=True)


# --- what was already there -----------------------------------------------

def test_the_consent_record_exists(clinic):
    """Listed in the backlog as missing for accreditation, and built."""
    from app.models.patient import CONSENT_TYPES, Consent

    assert Consent.__tablename__
    assert "general" in CONSENT_TYPES


def test_the_problem_list_exists(clinic):
    """Also listed as missing, also built — richer than the free-text field."""
    from app.models.patient import PatientProblem

    columns = {c.name for c in PatientProblem.__table__.columns}
    assert {"title", "status", "onset_date", "resolved_date"} <= columns


# --- the decision, recorded -----------------------------------------------

def test_continuing_a_medicine_is_recorded(clinic):
    """The decision that makes the whole document mean anything.

    If only stops and changes were stored, a reviewed list and an ignored list
    would be indistinguishable.
    """
    med_id = _med(clinic)
    _decide(clinic, med_id, "continue")

    with clinic["app"].app_context():
        from app.models import MedicationReview
        row = MedicationReview.query.filter_by(medication_id=med_id).first()
        assert row is not None, "a continue decision left no trace"
        assert row.decision == "continue"
        assert row.visit_id == clinic["ids"]["visit"]
        assert row.reviewed_by is not None


def test_continuing_does_not_stop_the_medicine(clinic):
    med_id = _med(clinic)
    _decide(clinic, med_id, "continue")

    with clinic["app"].app_context():
        from app.models import PatientMedication
        row = clinic["db"].session.get(PatientMedication, med_id)
        assert row.is_current is True


def test_stopping_records_the_decision_and_stops_it(clinic):
    """The document and the state must not disagree.

    A review saying "stopped" beside a drug the program still thinks the child
    is taking would be a poor document and a dangerous list.
    """
    med_id = _med(clinic)
    _decide(clinic, med_id, "stop", note="خلصت المدة")

    with clinic["app"].app_context():
        from app.models import MedicationReview, PatientMedication
        review = MedicationReview.query.filter_by(medication_id=med_id).first()
        assert review.decision == "stop"
        assert review.note == "خلصت المدة"

        med = clinic["db"].session.get(PatientMedication, med_id)
        assert med.is_current is False, (
            "the review says stopped and the list still says taking")


def test_modifying_leaves_it_running(clinic):
    """A changed dose is still a medicine the child is on."""
    med_id = _med(clinic)
    _decide(clinic, med_id, "modify", note="نص الجرعة")

    with clinic["app"].app_context():
        from app.models import MedicationReview, PatientMedication
        assert MedicationReview.query.filter_by(
            medication_id=med_id).first().decision == "modify"
        assert clinic["db"].session.get(PatientMedication, med_id).is_current is True


@pytest.mark.parametrize("decision", ["", "delete", "maybe", "CONTINUE "])
def test_an_unknown_decision_is_refused(clinic, decision):
    """A typed or stale value must not become a documented decision."""
    med_id = _med(clinic)
    _decide(clinic, med_id, decision)

    with clinic["app"].app_context():
        from app.models import MedicationReview
        assert MedicationReview.query.count() == 0


# --- "was the list reviewed?" ---------------------------------------------

def test_the_visit_knows_when_something_is_outstanding(clinic):
    med_id = _med(clinic)
    with clinic["app"].app_context():
        from app.models import Patient, Visit
        from app.utils import patient_meds as meds

        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        assert meds.reconciled(patient, visit) is False

    _decide(clinic, med_id, "continue")

    with clinic["app"].app_context():
        from app.models import Patient, Visit
        from app.utils import patient_meds as meds

        db = clinic["db"]
        assert meds.reconciled(db.session.get(Patient, clinic["ids"]["child"]),
                               db.session.get(Visit, clinic["ids"]["visit"])) is True


def test_a_child_on_nothing_counts_as_reviewed(clinic):
    """Answering "no" for the healthy majority would put a permanent warning
    on most visits and teach everybody to ignore it."""
    with clinic["app"].app_context():
        from app.models import Patient, Visit
        from app.utils import patient_meds as meds

        db = clinic["db"]
        assert meds.reconciled(db.session.get(Patient, clinic["ids"]["child"]),
                               db.session.get(Visit, clinic["ids"]["visit"])) is True


def test_a_decision_at_one_visit_is_not_one_at_the_next(clinic):
    """Reconciliation is per encounter — that is the whole point of it."""
    from datetime import date

    med_id = _med(clinic)
    _decide(clinic, med_id, "continue")

    with clinic["app"].app_context():
        from app.models import Patient, Visit
        from app.utils import patient_meds as meds

        db = clinic["db"]
        later = Visit(patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"], visit_date=date.today())
        db.session.add(later)
        db.session.commit()

        patient = db.session.get(Patient, clinic["ids"]["child"])
        assert meds.reconciled(patient, later) is False, (
            "last visit's review is being counted as this visit's")


# --- the screen -----------------------------------------------------------

def test_the_visit_screen_asks_for_a_decision(clinic):
    _med(clinic, "تجريتول", reason="صرع")
    body = (clinic["sign_in"]("doc")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))
    assert "تجريتول" in body
    for decision in ("continue", "stop", "modify"):
        assert f'value="{decision}"' in body, f"no way to record {decision}"


def test_a_reviewed_medicine_is_not_asked_about_twice(clinic):
    med_id = _med(clinic)
    doc = clinic["sign_in"]("doc")
    before = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'value="continue"' in before

    _decide(clinic, med_id, "continue")
    after = doc.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert 'value="continue"' not in after


def test_a_child_on_nothing_gets_no_reconciliation_block(clinic):
    """A block that appears on every visit and is empty is a block people
    learn to scroll past."""
    body = (clinic["sign_in"]("doc")
            .get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True))
    assert "مراجعة الأدوية المستمرة" not in body


def test_another_patients_medicine_cannot_be_reviewed_here(clinic):
    """The visit and the medicine have to be about the same child."""
    from datetime import date

    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        db = clinic["db"]
        other = Patient(patient_number="P-OTHER", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2022, 1, 1),
                        is_active=True)
        db.session.add(other)
        db.session.commit()
        stray = meds.add(other, "دوا غريب").id

    _decide(clinic, stray, "stop")

    with clinic["app"].app_context():
        from app.models import MedicationReview, PatientMedication
        assert MedicationReview.query.count() == 0
        assert clinic["db"].session.get(PatientMedication, stray).is_current is True
