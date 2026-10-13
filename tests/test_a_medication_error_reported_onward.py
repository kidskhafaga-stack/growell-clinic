"""الخطأ الدوائي اتبلّغ لمين — GAHAR MMS.17 (أ–هـ)، والمعدّل.

* كل خطأ بيتسجّل عليه اتبلّغ لمين: الطبيب، لجنة الدواء، الجودة، الإدارة، الجهة؛
* الجهة المختصة من غير رقم بلاغ ما تتحفظش؛
* الملخص بيقول عدد البلاغات لكل ١٠٠٠ جرعة اتعطت في نفس المدة.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import ward  # noqa: E402,F401


def test_reported_onward_and_counted_against_doses(ward):
    from app.models import MedicationError

    chem = ward["sign_in"]("chem")
    chem.post("/pharmacy/errors", data={"what_happened": "جرعة مضاعفة اتمسكت", "stage": "prescribing",
                                        "outcome": "B"})
    with ward["app"].app_context():
        rid = MedicationError.query.one().id
    chem.post(f"/pharmacy/errors/{rid}/informed", data={"informed": ["prescriber", "authority"]})
    with ward["app"].app_context():
        assert ward["db"].session.get(MedicationError, rid).informed is None, "authority needs a number"
    chem.post(f"/pharmacy/errors/{rid}/informed",
              data={"informed": ["prescriber", "ptc", "authority"], "authority_ref": "EDA-55"})
    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationError, rid)
        assert row.informed_to == ["prescriber", "ptc", "authority"] and row.authority_ref == "EDA-55"
    page = chem.get("/pharmacy/errors").get_data(as_text=True)
    assert "data-error-rate" in page and 'data-informed="prescriber,ptc,authority"' in page
