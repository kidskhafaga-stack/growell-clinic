"""ملصق الجرعة المحضّرة — GAHAR MMS.13 دليل ٥ (أ–ح).

الملصق بيتطبع من اللي اتكتب: الطفل بمعرّفين، الدوا، الاستخدام من الأمر،
المذيب و«يُستخدم قبل» والتحذير زي ما المحضّر كتبهم، وتاريخ التحضير. والدوا
عالي الخطورة في قايمة المستشفى بيتعلّم لوحده.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402,F401

from tests.test_the_chart_nobody_read import _admit, _child, _order, ward  # noqa: E402,F401


def test_the_label_carries_what_was_written(ward):
    from app.models import DosePrep
    from app.utils.clock import local_now

    stay = _admit(ward, _child(ward, "سلمى"))
    order = _order(ward, stay, drug="Vancomycin")
    chem = ward["sign_in"]("chem")
    bud = (local_now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")
    chem.post(f"/pharmacy/order/{order}/prepare",
              data={"label": "يتسرّب على ساعة", "diluent": "NS 50 ml", "beyond_use": bud,
                    "caution": "احمي من الضوء"})
    with ward["app"].app_context():
        prep = DosePrep.query.filter_by(order_id=order).one()
        assert prep.diluent == "NS 50 ml" and prep.beyond_use is not None
        pid = prep.id
    supply = chem.get("/pharmacy/supply").get_data(as_text=True)
    assert "data-prep-label" in supply
    label = chem.get(f"/pharmacy/prep/{pid}/label").get_data(as_text=True)
    for bit in ("سلمى", "Cسلمى", "Vancomycin", "250 mg", "NS 50 ml", "احمي من الضوء"):
        assert bit in label, bit
    assert "data-label-high-alert" not in label
