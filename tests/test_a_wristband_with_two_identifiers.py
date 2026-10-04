"""The wristband — GAHAR ACT.03 (أ، د، هـ، و).

* two identifiers that are the child's, never the bed: the name and the file
  number (as text and barcode), with the date of birth;
* a newborn is «baby of» the mother, with the time of birth and the weight;
* a provisional file and an estimated birth date say so; allergies ride on it;
* reachable from the child's file, the stay and the emergency attendance.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _band(c, pid):
    return c["sign_in"]("boss").get(f"/patients/{pid}/wristband").get_data(as_text=True)


def test_two_identifiers_and_a_barcode(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.allergies = "بنسلين"
        clinic["db"].session.commit()
        name, number, born = child.full_name, child.patient_number, child.date_of_birth.isoformat()
    page = _band(clinic, clinic["ids"]["child"])
    for piece in (name, number, born, "<svg", "data-wb-allergy", "بنسلين"):
        assert piece in page, piece
    assert "data-wb-newborn" not in page
    assert "data-to-wristband" in clinic["sign_in"]("boss").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)


def test_a_newborn_is_baby_of_the_mother(clinic):
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam = Family(family_name="عائلة نور")
        db.session.add(fam)
        db.session.flush()
        db.session.add(Parent(family_id=fam.id, relation="mother", full_name="نور محمد"))
        baby = Patient(patient_number="P-NB1", full_name="رضيعة نور", gender="female",
                       date_of_birth=date.today() - timedelta(days=2), birth_time=time(4, 35),
                       birth_weight_kg=2.9, family_id=fam.id, is_active=True)
        db.session.add(baby)
        db.session.commit()
        bid = baby.id
    page = _band(clinic, bid)
    assert "data-wb-newborn" in page and "مولودة لـ نور محمد" in page
    assert "04:35" in page and "2.9 kg" in page


def test_a_provisional_file_says_so_on_the_band(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    boss = clinic["sign_in"]("boss")
    answer = boss.post("/emergency/arrive-now", data={"gender": "female", "age_value": "3",
                                                     "age_unit": "years"})
    from app.models import Patient

    with clinic["app"].app_context():
        pid = Patient.query.filter(Patient.identity_provisional.is_(True)).one().id
    page = _band(clinic, pid)
    assert "data-wb-provisional" in page and "~" in page
    attendance = boss.get(answer.headers["Location"]).get_data(as_text=True)
    assert "data-to-wristband" in attendance and "data-er-provisional" in attendance
