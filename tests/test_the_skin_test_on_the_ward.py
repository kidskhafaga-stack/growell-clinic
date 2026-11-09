"""The skin test before an antibiotic injection on the ward (DOCTOR_EASE ٤-ب د-٢).

The owner chose **once per drug in the stay**: the first dose of an injected
antibiotic waits for a negative result, a positive one is never given and is
written on the child's allergies, and the doses after — and a second order for
the same drug in the same stay — do not ask again.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def _order(ward, stay, drug="Ceftriaxone", route="iv"):
    from app.models import MedicationOrder

    ward["sign_in"]("boss").post(f"/beds/admission/{stay}/medication",
                                 data={"drug_name": drug, "dose": "600 mg",
                                       "route": route, "every_hours": "12"})
    with ward["app"].app_context():
        return MedicationOrder.query.order_by(MedicationOrder.id.desc()).first().id


def _give(ward, oid):
    return ward["sign_in"]("boss").post(f"/beds/medication/{oid}/dose",
                                        data={"outcome": "given"},
                                        follow_redirects=True).get_data(as_text=True)


def _doses(ward, oid):
    from app.models import MedicationDose

    with ward["app"].app_context():
        return MedicationDose.query.filter_by(order_id=oid, outcome="given").count()


def _skin(ward, oid, result):
    return ward["sign_in"]("boss").post(f"/beds/medication/{oid}/skin-test",
                                        data={"result": result})


def test_the_first_dose_waits_for_a_negative_skin_test_then_never_asks_again(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    oid = _order(ward, stay)
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert f'data-order-skin="{oid}"' in page
    page = _give(ward, oid)
    assert _doses(ward, oid) == 0 and "اختبار الجلد" in page
    _skin(ward, oid, "negative")
    _give(ward, oid)
    assert _doses(ward, oid) == 1
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert f'data-order-skin="{oid}"' not in page, "once per drug in the stay"


def test_a_second_order_for_the_same_drug_in_the_stay_does_not_ask_again(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    first = _order(ward, stay)
    _skin(ward, first, "negative")
    _give(ward, first)
    ward["sign_in"]("boss").post(f"/beds/medication/{first}/stop", data={"reason": "جرعة جديدة"})
    second = _order(ward, stay)
    _give(ward, second)
    assert _doses(ward, second) == 1


def test_a_positive_test_is_never_given_and_is_an_allergy(ward):
    from app.models import Patient

    pid = _child(ward, "يوسف")
    stay = _admit(ward, pid)
    oid = _order(ward, stay)
    _skin(ward, oid, "positive")
    _give(ward, oid)
    assert _doses(ward, oid) == 0
    with ward["app"].app_context():
        assert "Ceftriaxone" in ward["db"].session.get(Patient, pid).allergies
    page = ward["sign_in"]("boss").get("/beds/drugs").get_data(as_text=True)
    assert 'data-skin-result="positive"' in page


def test_the_drug_round_asks_for_it_too(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    oid = _order(ward, stay)
    page = ward["sign_in"]("boss").get("/beds/drugs").get_data(as_text=True)
    assert f'data-order-skin="{oid}"' in page


def test_no_skin_test_for_a_syrup_or_a_drug_that_is_not_an_antibiotic(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    oral = _order(ward, stay, "Amoxicillin", "oral")
    other = _order(ward, stay, "Paracetamol", "iv")
    _give(ward, oral)
    _give(ward, other)
    assert _doses(ward, oral) == 1 and _doses(ward, other) == 1


def test_switched_off_by_a_hospital_that_does_not_skin_test(ward):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("er_skin_test", "0")
        ward["db"].session.commit()
    stay = _admit(ward, _child(ward, "يوسف"))
    oid = _order(ward, stay)
    _give(ward, oid)
    assert _doses(ward, oid) == 1
