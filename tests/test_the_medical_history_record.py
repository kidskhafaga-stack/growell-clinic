"""«Medical History Record» (MR 4-1) — the stay's admission history on paper.

The owner brought the hospital form: the child, the room, the treating
doctor, the department, the diet, weight and height; the complaints «include
circumstance of admission»; the present illness; past, family and
nutritional history; the medication reconciliation with its drug-related
problems; and the review of sixteen systems, «write detailed description
even if no abnormality is detected».

These hold it:

* the page has a door on the stay and prints in the form's order, in
  English too; what the record does not hold is lines for a pen;
* the nutritional history and the review of systems are written on the
  stay — and writing them does not make the initial assessment (ICD.06,
  «within 24 hours») look done;
* the reconciliation at admission is ticked by its decisions, and the
  clinical pharmacist's problems are listed under it;
* the nutritional history falls back to the dietitian's findings on this
  stay, never another stay's.
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, _order, ward  # noqa: E402,F401


def _page(ward, stay, lang=None):
    url = f"/beds/admission/{stay}/history-record" + (f"?lang={lang}" if lang else "")
    return ward["sign_in"]("boss").get(url).get_data(as_text=True)


def _after(page, mark, n=500):
    return page.split(mark, 1)[1][:n]


def test_the_record_has_a_door_and_the_form_s_sections(ward):
    from app.models.admission import Admission

    stay = _admit(ward, _child(ward, "سلمى"))
    with ward["app"].app_context():
        ward["db"].session.get(Admission, stay).reason = "تشنج مع حرارة في البيت"
        ward["db"].session.commit()
    stay_page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-to-history-record" in stay_page and "data-history-review" in stay_page
    page = _page(ward, stay)
    assert "data-history-record" in page
    assert "تشنج مع حرارة في البيت" in _after(page, "data-mhr-complaint")
    assert "غرفة ١" in _after(page, "data-mhr-room", 200), "the room is the bed's"
    # Nothing written: lines for a pen, and all sixteen systems listed.
    assert "mhr-line" in _after(page, "data-mhr-hpi")
    assert page.count("data-mhr-system=") == 16
    english = _page(ward, stay, lang="en")
    assert "Medical History Record" in english and "System history review" in english


def test_the_review_is_written_without_touching_the_24_hours(ward):
    from app.models import HistoryReview, MedicalAssessment
    from app.models.admission import Admission
    from app.utils import medical_assessment as medass

    stay = _admit(ward, _child(ward, "يوسف"))
    boss = ward["sign_in"]("boss")
    boss.post(f"/beds/admission/{stay}/history-review", data={})
    with ward["app"].app_context():
        assert HistoryReview.query.count() == 0, "nothing written, nothing saved"
    boss.post(f"/beds/admission/{stay}/history-review", data={
        "nutrition_history": "رضاعة طبيعية لحد ٦ شهور، أكل عائلي دلوقتي",
        "sys_general": "واعي ونشيط", "sys_respiratory": "صفير على الناحيتين"})
    with ward["app"].app_context():
        row = HistoryReview.query.one()
        assert row.systems == {"general": "واعي ونشيط",
                               "respiratory": "صفير على الناحيتين"}
        assert MedicalAssessment.query.count() == 0
        assert medass.clock(ward["db"].session.get(Admission, stay))["state"] == "overdue", \
            "a review of systems is not the initial assessment"
    page = _page(ward, stay)
    assert "رضاعة طبيعية" in _after(page, "data-mhr-nutrition_h")
    assert 'data-mhr-system="respiratory:on"' in page
    assert 'data-mhr-system="cardiovascular"' in page
    # Edited later: an emptied box is emptied.
    boss.post(f"/beds/admission/{stay}/history-review", data={
        "nutrition_history": "رضاعة طبيعية", "sys_general": "واعي ونشيط"})
    with ward["app"].app_context():
        assert HistoryReview.query.one().systems == {"general": "واعي ونشيط"}


def test_the_reconciliation_and_its_drug_problems(ward):
    from app.models import PatientMedication
    from app.models.admission import Admission
    from app.models.med_reconciliation import MedReconciliation
    from app.models.pharmacy_intervention import PharmacyIntervention

    pid = _child(ward, "مريم")
    stay = _admit(ward, pid)
    order_id = _order(ward, stay)
    with ward["app"].app_context():
        db = ward["db"]
        home = PatientMedication(patient_id=pid, name="Montelukast 4 mg", dose="4 mg")
        db.session.add(home)
        db.session.flush()
        db.session.add_all([
            MedReconciliation(admission_id=stay, patient_id=pid, interface="admission",
                              home_med_id=home.id, name=home.name, decision="continue"),
            MedReconciliation(admission_id=stay, patient_id=pid, interface="admission",
                              home_med_id=home.id, name=home.name, decision="stop",
                              note="مش محتاجه وهو على البخار"),
        ])
        db.session.add(PharmacyIntervention(
            number="PI-1", admission_id=stay, patient_id=pid, order_id=order_id,
            problem="dosage", severity="moderate", outcome="adr_prevented",
            problem_note="الجرعة أعلى من وزنه"))
        db.session.commit()
        assert db.session.get(Admission, stay) is not None
    page = _page(ward, stay)
    recon = _after(page, "data-mhr-recon", 3000)
    # One line per medicine, its latest decision.
    assert recon.count("data-mhr-recon-row=") == 1
    assert 'data-mhr-recon-row="stop"' in recon and "4 mg" in recon
    assert "مش محتاجه وهو على البخار" in recon
    drps = _after(page, "data-mhr-drps", 600)
    assert "PI-1" in drps and "الجرعة أعلى من وزنه" in drps


def test_the_nutritional_history_falls_back_to_this_stay_s_dietitian(ward):
    from app.models.admission import Admission
    from app.models.nutrition import NutritionAssessment
    from app.utils import nutrition

    pid = _child(ward, "ليلى")
    stay = _admit(ward, pid)
    with ward["app"].app_context():
        admission = ward["db"].session.get(Admission, stay)
        nutrition.assess(admission.patient, findings="بياكل كويس، وزنه على المنحنى",
                         admission=admission)
        ward["db"].session.commit()
    assert "وزنه على المنحنى" in _after(_page(ward, stay), "data-mhr-nutrition_h")
    with ward["app"].app_context():
        NutritionAssessment.query.one().admission_id = None
        ward["db"].session.commit()
    assert "وزنه على المنحنى" not in _after(_page(ward, stay), "data-mhr-nutrition_h"), \
        "another stay's findings are not this one's history"


def test_the_weight_on_admission_is_measured_on_this_stay(ward):
    from app.models import GrowthRecord
    from app.utils.clock import local_today

    pid = _child(ward, "عمر")
    stay = _admit(ward, pid)
    with ward["app"].app_context():
        ward["db"].session.add(GrowthRecord(patient_id=pid, record_date=local_today(),
                                            weight_kg=13.5, height_cm=92.0,
                                            source="ward"))
        ward["db"].session.commit()
    measures = _after(_page(ward, stay), "data-mhr-measures", 400)
    assert "13.5 kg" in measures and "92.0 cm" in measures
