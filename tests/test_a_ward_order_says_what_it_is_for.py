"""أمر الداخلي بيقول هو لإيه — GAHAR MMS.11 (هـ)(٨)(٩).

* الداعي والأقصى في اليوم ومعدّل التسريب والمدة بيتكتبوا بكلام الطبيب ويبانوا على الشارت؛
* «عند اللزوم» من غير داعي أو أقصى بيبان ناقص — ومش بيترفض، فاللي كان بيتكتب امبارح لسه بيتكتب.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def test_the_elements_are_written_and_a_bare_prn_is_shown_not_refused(ward):
    from app.models import MedicationOrder

    stay = _admit(ward, _child(ward, "يوسف"))
    boss = ward["sign_in"]("boss")
    boss.post(f"/beds/admission/{stay}/medication",
              data={"drug_name": "Paracetamol", "dose": "150 mg", "route": "oral", "is_prn": "1",
                    "min_gap_hours": "6"})
    boss.post(f"/beds/admission/{stay}/medication",
              data={"drug_name": "Vancomycin", "dose": "150 mg", "route": "iv", "every_hours": "6",
                    "indication": "اشتباه تسمم دم", "rate": "على ساعة", "course_days": "10"})
    with ward["app"].app_context():
        rows = {o.drug_name: o for o in MedicationOrder.query.all()}
        assert rows["Paracetamol"].missing_elements == ["indication", "max_per_day"]
        assert rows["Vancomycin"].course_days == 10 and rows["Vancomycin"].rate == "على ساعة"
    page = boss.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-order-missing="indication"' in page and "اشتباه تسمم دم" in page
