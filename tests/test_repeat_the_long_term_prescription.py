"""تكرار روشتة المرض المزمن (DOCTOR_EASE_PLAN.md ب-٢).

* جنب كل مشكلة نشطة في قايمة المشاكل (في الكشف وفي شاشة الروشتة) «كرر آخر
  روشتة» لو فيه روشتة ليها — بالكود أو باسم المشكلة؛
* التكرار بيفتح روشتة **جديدة** فيها السطور القديمة، كل سطر شايل قاعدة الوزن
  بتاعة الدوا عشان الجرعة تتحسب من جديد على وزن النهارده، وشايل الجرعة القديمة
  والوزن اللي كانت عليه عشان يتقال لو اتغيرت؛
* الوزن الحديث بيتحط لوحده؛ القديم بيتعرض بتاريخه ومش بيتحط غير بضغطة؛
* روشتة مريض تاني ما بتتكررش؛ والدوا اللي جرعته مش بالوزن (أغلب أدوية الكبار)
  بيفضل بجرعته.
"""
import html
import json
import os
import re
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _setup(clinic, weight_days_ago=2, code="J45"):
    from app.models import (Drug, GrowthRecord, Patient, PatientProblem, Prescription,
                            PrescriptionItem)
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        pid = clinic["ids"]["child"]
        today = local_today()
        syrup = Drug(trade_name="Montelukast test", dose_per_kg=0.25, conc_mg_per_ml=None)
        tab = Drug(trade_name="Fixed tablet test")
        db.session.add_all([syrup, tab])
        db.session.flush()
        db.session.add_all([
            PatientProblem(patient_id=pid, title="ربو شعبي", icd_code=code, status="active"),
            PatientProblem(patient_id=pid, title="أنيميا", status="active"),
            GrowthRecord(patient_id=pid, record_date=today - timedelta(days=200), weight_kg=12),
            GrowthRecord(patient_id=pid, record_date=today - timedelta(days=weight_days_ago),
                         weight_kg=16)])
        old = Prescription(patient_id=pid, doctor_id=clinic["ids"]["doctor"],
                           rx_date=today - timedelta(days=150),
                           diagnosis="Asthma", diagnosis_code="J45.9")
        db.session.add(old)
        db.session.flush()
        db.session.add_all([
            PrescriptionItem(prescription_id=old.id, drug_id=syrup.id,
                             drug_name="Montelukast test", dose="3 mg", frequency="مرة يوميًا"),
            PrescriptionItem(prescription_id=old.id, drug_id=tab.id,
                             drug_name="Fixed tablet test", dose="1 tab", frequency="مرتين")])
        other = Patient(patient_number="P-OTHER", full_name="مريض تاني", gender="male", date_of_birth=today - timedelta(days=4000),
                        is_active=True)
        db.session.add(other)
        db.session.flush()
        theirs = Prescription(patient_id=other.id, diagnosis="Asthma", diagnosis_code="J45")
        db.session.add(theirs)
        db.session.flush()
        db.session.add(PrescriptionItem(prescription_id=theirs.id, drug_name="X", dose="1"))
        db.session.commit()
        return {"pid": pid, "rx": old.id, "theirs": theirs.id}


def _lines(page):
    """The lines the prescription screen opens with (its x-data argument)."""
    m = re.search(r'x-data="rxForm\((.*?)\)"\s', page, re.S)
    args = json.loads("[" + html.unescape(m.group(1)) + "]")
    return args[0], args[4]


def test_the_problem_list_offers_the_last_prescription(clinic):
    from app.models import PatientProblem
    from app.utils import rx_repeat

    ids = _setup(clinic)
    with clinic["app"].app_context():
        from app.models import Patient
        offers = rx_repeat.offers(clinic["db"].session.get(Patient, ids["pid"]))
        asthma = PatientProblem.query.filter_by(title="ربو شعبي").one().id
    # Matched by code (J45 ↔ J45.9); the anaemia has no prescription, so no offer.
    assert [(o["problem"], o["rx"], o["count"]) for o in offers] == [(asthma, ids["rx"], 2)]
    doctor = clinic["sign_in"]("doc")
    page = doctor.get(f"/visits/{clinic['ids']['visit']}/record").get_data(as_text=True)
    assert f'data-repeat="{ids["rx"]}"' in page and f"repeat={ids['rx']}" in page
    page = doctor.get(f"/prescriptions/new?patient_id={ids['pid']}").get_data(as_text=True)
    assert "data-repeat-offers" in page and f'data-repeat="{ids["rx"]}"' in page


def test_matched_by_name_when_there_is_no_code(clinic):
    from app.models import Patient, PatientProblem, Prescription
    from app.utils import rx_repeat

    ids = _setup(clinic, code=None)
    with clinic["app"].app_context():
        rx = clinic["db"].session.get(Prescription, ids["rx"])
        rx.diagnosis_code, rx.diagnosis = None, "ربو شعبي — نوبة خفيفة"
        clinic["db"].session.commit()
        offers = rx_repeat.offers(clinic["db"].session.get(Patient, ids["pid"]))
        assert [o["problem"] for o in offers] == [
            PatientProblem.query.filter_by(title="ربو شعبي").one().id]


def test_repeating_opens_a_new_prescription_with_the_old_lines(clinic):
    from app.models import Prescription

    ids = _setup(clinic)
    doctor = clinic["sign_in"]("doc")
    page = doctor.get(f"/prescriptions/new?patient_id={ids['pid']}&repeat={ids['rx']}"
                      ).get_data(as_text=True)
    weight, lines = _lines(page)
    assert weight == 16                                     # recent: used on its own
    by_name = {ln["name"]: ln for ln in lines}
    syrup, tab = by_name["Montelukast test"], by_name["Fixed tablet test"]
    assert syrup["dose_per_kg"] == 0.25 and syrup["prev_dose"] == "3 mg"
    assert syrup["prev_weight"] == 12                        # the weight on the old date
    assert tab["dose_per_kg"] is None and tab["dose"] == "1 tab"
    assert f'data-repeat-of="{ids["rx"]}"' in page and f'data-repeat="{ids["rx"]}"' in page
    assert 'value="Asthma"' in page or "Asthma" in page    # diagnosis carried
    # Nothing is written until the doctor saves.
    with clinic["app"].app_context():
        assert Prescription.query.filter_by(patient_id=ids["pid"]).count() == 1
    # Another patient's prescription is never repeated here.
    page = doctor.get(f"/prescriptions/new?patient_id={ids['pid']}&repeat={ids['theirs']}"
                      ).get_data(as_text=True)
    assert "data-repeat-of=" not in page and _lines(page)[1] == []


def test_an_old_weight_is_shown_but_not_used(clinic):
    ids = _setup(clinic, weight_days_ago=90)
    doctor = clinic["sign_in"]("doc")
    page = doctor.get(f"/prescriptions/new?patient_id={ids['pid']}&repeat={ids['rx']}"
                      ).get_data(as_text=True)
    weight, _ = _lines(page)
    assert weight == ""
    assert 'data-weight-on-file' in page and 'data-stale="1"' in page and "data-use-weight" in page
