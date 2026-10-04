"""A child found by whatever the person at the desk knows.

«البحث رقم التليفون اسم الطفل اسم الام كده تاريخ الميلاد فى كل حته». One
rule (`apply_patient_search`) behind every patient search and picker:

* the child's name, file number, national id — as before;
* **the mother's, father's or guardian's name**;
* **any phone** on record — the child's or a guardian's, however it is typed;
* **the date of birth**, as a day in the usual ways of writing one, or a year;
* **several words narrow it down** — «سارة 2021» — and a phrase that found a
  child before still finds them;
* Arabic-Indic digits are digits;
* every picker answers with a line that tells two children of one name apart.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def families(clinic):
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        fam1 = Family(family_name="عائلة سالم")
        fam2 = Family(family_name="عائلة حسن")
        db.session.add_all([fam1, fam2])
        db.session.flush()
        db.session.add_all([
            Parent(family_id=fam1.id, relation="mother", full_name="منى عبد الله",
                   phone="0100 123-4567"),
            Parent(family_id=fam2.id, relation="mother", full_name="هبة إبراهيم",
                   phone="0122 999 8888")])
        a = Patient(patient_number="P-100", full_name="سارة سالم", gender="female",
                    date_of_birth=date(2021, 5, 3), family_id=fam1.id, is_active=True)
        b = Patient(patient_number="P-200", full_name="سارة حسن", gender="female",
                    date_of_birth=date(2019, 2, 14), family_id=fam2.id, is_active=True)
        db.session.add_all([a, b])
        db.session.commit()
        clinic["ids"].update(sara1=a.id, sara2=b.id)
    return clinic


def _find(c, q):
    from app.models import Patient
    from app.utils.patients import apply_patient_search

    with c["app"].app_context():
        return sorted(p.id for p in apply_patient_search(Patient.query, q).all())


def test_by_the_mother_s_name(families):
    assert _find(families, "منى") == [families["ids"]["sara1"]]
    assert _find(families, "هبة إبراهيم") == [families["ids"]["sara2"]]


def test_by_any_phone_however_typed(families):
    assert _find(families, "01001234567") == [families["ids"]["sara1"]]
    assert _find(families, "٠١٢٢٩٩٩") == [families["ids"]["sara2"]], "Arabic-Indic digits"


@pytest.mark.parametrize("typed", ["2021-05-03", "3/5/2021", "03-05-2021", "3.5.2021",
                                   "٣/٥/٢٠٢١"])
def test_by_the_date_of_birth_however_written(families, typed):
    assert _find(families, typed) == [families["ids"]["sara1"]]


def test_several_words_narrow_it_down(families):
    ids = families["ids"]
    assert _find(families, "سارة") == sorted([ids["sara1"], ids["sara2"]])
    assert _find(families, "سارة 2019") == [ids["sara2"]]
    assert _find(families, "سارة منى") == [ids["sara1"]]
    assert _find(families, "سارة 0122") == [ids["sara2"]]
    # The whole phrase still finds what it found before.
    assert _find(families, "سارة سالم") == [ids["sara1"]]
    assert _find(families, "P-200") == [ids["sara2"]]


def test_every_picker_tells_two_of_one_name_apart(families):
    boss = families["sign_in"]("boss")
    from app.models import Setting

    with families["app"].app_context():
        for m in ("emergency", "beds", "theatres"):
            Setting.set(f"mod_enabled:{m}", "1")
        families["db"].session.commit()
    for url in ("/emergency/patient-search", "/beds/patient-search",
                "/theatres/patient-search", "/prescriptions/patient-search"):
        rows = boss.get(url + "?q=سارة").get_json()
        hints = {r["id"]: r["hint"] for r in rows}
        assert "2021-05-03" in hints[families["ids"]["sara1"]], url
        assert "منى عبد الله" in hints[families["ids"]["sara1"]], url
        assert hints[families["ids"]["sara1"]].endswith("…4567"), url
    booking = boss.get("/appointments/patient-search?q=سارة").get_json()["patients"]
    assert all(r["hint"] for r in booking)


def test_the_invoice_and_follow_up_searches_follow_the_same_rule(families):
    from app.models import Invoice
    from app.utils.clock import local_today

    with families["app"].app_context():
        db = families["db"]
        db.session.add(Invoice(patient_id=families["ids"]["sara2"], invoice_number="INV-9",
                               invoice_date=local_today(), status="unpaid"))
        db.session.commit()
    page = families["sign_in"]("boss").get("/finance/invoices?q=هبة").get_data(as_text=True)
    assert "INV-9" in page
