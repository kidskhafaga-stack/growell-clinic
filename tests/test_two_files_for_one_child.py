"""ملفين لنفس الطفل بيبقوا ملف واحد — ويتلغى الدمج بالظبط لو اتعمل غلط.

* القايمة بتطلّع الملفات اللي شكلها لنفس الطفل (نفس الميلاد ونفس الاسم بعد
  توحيد الكتابة)، ومش بتدمج حاجة؛
* الدمج للمدير بس، بسبب، وبرقم الملف المدموج مكتوب للتأكيد؛
* **كل** صف بيشاور على الملف المدموج بيتنقل — من الجداول نفسها، مش من لستة؛
  واللي الملف الباقي عنده بداله (خطة نفس اللقاح) بيفضل مكانه؛
* البيانات الفاضية بتتملا، والحساسية بتتضاف ما بتتبدلش؛
* الملف المدموج بيتأرشف ويشاور على الباقي، وما يترجعش بـ«استرجاع»؛
* الإلغاء بيرجّع كل حاجة زي ما كانت.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def twins(clinic):
    """The fixture's child (P1) and the same child registered again (P2):
    a visit, an appointment-free plan for the same vaccine, an allergy, a
    phone the first file never had."""
    from app.models import Patient, VaccinePlanItem, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        p1 = db.session.get(Patient, clinic["ids"]["child"])
        p1.allergies = "Penicillin"
        p2 = Patient(patient_number="P2", full_name="طفلة", gender="male",
                     date_of_birth=date(2025, 1, 1), is_active=True,
                     own_phone="01001234567", allergies="Eggs")
        db.session.add(p2)
        db.session.flush()
        p1.full_name = "طفله"     # «طفله» and «طفلة» fold to one name
        v2 = Visit(patient_id=p2.id, doctor_id=clinic["ids"]["doctor"], visit_date=local_today())
        db.session.add(v2)
        db.session.add_all([
            VaccinePlanItem(patient_id=p1.id, vaccine_id=clinic["ids"]["pcv"]),
            VaccinePlanItem(patient_id=p2.id, vaccine_id=clinic["ids"]["pcv"]),
            VaccinePlanItem(patient_id=p2.id, vaccine_id=clinic["ids"]["opv"]),
        ])
        db.session.commit()
        clinic["p1"], clinic["p2"], clinic["v2"] = p1.id, p2.id, v2.id
    return clinic


def _merge(c, who="boss", confirm="P2", reason="اتسجّل تاني في الطوارئ"):
    return c["sign_in"](who).post("/patients/merge", data={
        "keep_id": c["p1"], "drop_id": c["p2"], "confirm": confirm, "reason": reason})


def test_the_list_finds_them_and_merges_nothing(twins):
    from app.models import Patient

    page = twins["sign_in"]("boss").get("/patients/merge").get_data(as_text=True)
    assert "data-merge-candidate" in page
    preview = twins["sign_in"]("boss").get("/patients/merge?keep=P1&drop=P2").get_data(as_text=True)
    assert "data-merge-confirm" in preview and "data-merge-left" in preview
    with twins["app"].app_context():
        assert twins["db"].session.get(Patient, twins["p2"]).is_active


def test_admin_only_with_a_reason_and_the_number_typed(twins):
    from app.models import PatientMerge

    assert twins["sign_in"]("desk").get("/patients/merge").status_code == 403
    assert _merge(twins, who="doc").status_code == 403
    _merge(twins, confirm="P1")
    _merge(twins, reason="")
    with twins["app"].app_context():
        assert PatientMerge.query.count() == 0


def test_everything_moves_and_is_written_down(twins):
    from app.models import Patient, VaccinePlanItem, Visit

    _merge(twins)
    with twins["app"].app_context():
        db = twins["db"]
        assert db.session.get(Visit, twins["v2"]).patient_id == twins["p1"]
        plans = {(v.patient_id, v.vaccine_id) for v in VaccinePlanItem.query}
        assert (twins["p1"], twins["ids"]["opv"]) in plans, "the plan the kept file lacked moved"
        assert (twins["p2"], twins["ids"]["pcv"]) in plans, "the one it had stays behind"
        keep, drop = db.session.get(Patient, twins["p1"]), db.session.get(Patient, twins["p2"])
        assert keep.own_phone == "01001234567", "an empty field is filled"
        assert "Penicillin" in keep.allergies and "Eggs" in keep.allergies, "allergies added, not chosen"
        assert (drop.is_active, drop.archive_reason, drop.merged_into) == (False, "merged", keep.id)
    page = twins["sign_in"]("boss").get(f"/patients/{twins['p2']}").get_data(as_text=True)
    assert "data-merged-into" in page
    # «Restore» does not bring an emptied file back.
    twins["sign_in"]("boss").post(f"/patients/{twins['p2']}/restore")
    with twins["app"].app_context():
        assert not twins["db"].session.get(Patient, twins["p2"]).is_active


def test_undo_puts_it_all_back(twins):
    from app.models import Patient, PatientMerge, VaccinePlanItem, Visit

    _merge(twins)
    with twins["app"].app_context():
        mid = PatientMerge.query.one().id
    twins["sign_in"]("boss").post(f"/patients/merge/{mid}/undo")
    with twins["app"].app_context():
        db = twins["db"]
        assert db.session.get(Visit, twins["v2"]).patient_id == twins["p2"]
        assert VaccinePlanItem.query.filter_by(patient_id=twins["p2"]).count() == 2
        keep, drop = db.session.get(Patient, twins["p1"]), db.session.get(Patient, twins["p2"])
        assert keep.own_phone is None and keep.allergies == "Penicillin"
        assert drop.is_active and drop.merged_into is None and drop.archive_reason is None
        assert db.session.get(PatientMerge, mid).is_undone


def test_every_patient_column_is_found_from_the_database(clinic):
    from app.utils import patient_merge

    with clinic["app"].app_context():
        found = {f"{t.name}.{c.name}" for t, c in patient_merge.patient_columns()}
    for must in ("visits.patient_id", "invoices.patient_id", "patient_vaccines.patient_id",
                 "visit_investigations.patient_id", "admissions.patient_id",
                 "ipc_alerts.patient_id"):
        assert must in found
    assert not any(k.startswith("patient_merges.") for k in found)
