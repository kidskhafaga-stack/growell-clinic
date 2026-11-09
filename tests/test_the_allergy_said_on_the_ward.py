"""The allergy said on the ward (DOCTOR_EASE_PLAN ٤-ب — د-١).

Found in the inpatient review: the stay's drug chart and the pharmacy's two
screens asked the allergy check for ``.hit`` — a key its answer never had — so
a child with «Amoxicillin» on the file could be written, reviewed and given
amoxicillin with no warning on any of them. And the drug round, where the
dose is actually given, did not say the allergy at all.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def _allergic_stay(ward, drug="Amoxicillin"):
    from app.models import Patient

    pid = _child(ward, "يوسف")
    with ward["app"].app_context():
        ward["db"].session.get(Patient, pid).allergies = "Amoxicillin"
        ward["db"].session.commit()
    stay = _admit(ward, pid)
    ward["sign_in"]("boss").post(f"/beds/admission/{stay}/medication",
                                 data={"drug_name": drug, "dose": "250 mg",
                                       "route": "oral", "every_hours": "8"})
    return stay


def test_the_stay_s_drug_chart_says_the_allergy(ward):
    stay = _allergic_stay(ward)
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-allergy="match"' in page
    assert "Amoxicillin" in page.split('data-allergy="match"', 1)[1][:400]


def test_the_drug_round_says_it_where_the_dose_is_given(ward):
    _allergic_stay(ward)
    page = ward["sign_in"]("boss").get("/beds/drugs").get_data(as_text=True)
    assert 'data-allergy="match"' in page


def test_the_pharmacist_s_chart_says_it(ward):
    stay = _allergic_stay(ward)
    r = ward["sign_in"]("boss").get(f"/pharmacy/ward/{stay}")
    assert r.status_code == 200
    assert 'data-allergy="match"' in r.get_data(as_text=True)


def test_a_cross_reacting_family_is_a_caution(ward):
    stay = _allergic_stay(ward, drug="Cefalexin")
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-allergy="caution"' in page


def test_no_allergy_no_line(ward):
    from app.models import Patient

    pid = _child(ward, "مريم")
    stay = _admit(ward, pid)
    ward["sign_in"]("boss").post(f"/beds/admission/{stay}/medication",
                                 data={"drug_name": "Amoxicillin", "dose": "250 mg",
                                       "route": "oral", "every_hours": "8"})
    with ward["app"].app_context():
        assert not ward["db"].session.get(Patient, pid).allergies
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-allergy=" not in page
