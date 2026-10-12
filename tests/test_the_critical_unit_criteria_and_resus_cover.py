"""الوحدة الحرجة — GAHAR CSS.01 (ب) ودليل ٣.

* معايير الدخول والخروج بكلام المستشفى، بتتكتب في الإعداد وتبان على شاشة الوحدة؛
* شهادات الموظفين، ودورات الإنعاش قايمة المستشفى؛
* كشف النوبتجيات بيقول أنهي شيفت في وحدة حرجة مفيهوش حد شهادته سارية — ومن غير القايمة ما بيحكمش.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def picu(clinic):
    from app.models import Setting, User
    from app.models.duty import DutySlot
    from app.models.place import Unit
    from app.utils import duty as rota
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        for m in ("icu", "beds", "duty"):
            Setting.set(f"mod_enabled:{m}", "1")
        unit = Unit(name="العناية المركزة للأطفال", kind="icu", sort_order=0)
        night = DutySlot(name="ليل", start_time=time(20, 0), end_time=time(8, 0))
        db.session.add_all([unit, night])
        db.session.flush()
        doc = User.query.filter_by(username="doc").first()
        rota.assign(doc, night, on_date=local_today(), unit=unit)
        db.session.commit()
        clinic.update(unit=unit.id, doc=doc.id)
    return clinic


def test_criteria_written_in_setup_and_read_on_the_board(picu):
    boss = picu["sign_in"]("boss")
    assert f'data-unit-criteria="{picu["unit"]}"' in boss.get("/beds/setup").get_data(as_text=True)
    boss.post(f"/beds/unit/{picu['unit']}/criteria",
              data={"admit_criteria": "فشل تنفسي محتاج تنفس صناعي", "discharge_criteria": "مستقر ٢٤ ساعة من غير دعم"})
    page = boss.get("/icu/").get_data(as_text=True)
    assert "data-criteria" in page and "فشل تنفسي" in page


def test_a_shift_without_a_valid_resus_course_is_named(picu):
    boss = picu["sign_in"]("boss")
    page = boss.get("/duty/").get_data(as_text=True)
    assert "data-resus-unset" in page and "data-resus-gaps" not in page, "no list, no judgement"
    boss.post("/duty/certificates/add", data={"what": "courses", "courses": "PALS, NRP"})
    assert "data-resus-gaps" in boss.get("/duty/").get_data(as_text=True)
    boss.post("/duty/certificates/add", data={"what": "cert", "user_id": picu["doc"], "course": "PALS",
                                              "expires_on": (date.today() - timedelta(days=1)).isoformat()})
    assert "data-resus-gaps" in boss.get("/duty/").get_data(as_text=True), "an expired course does not count"
    boss.post("/duty/certificates/add", data={"what": "cert", "user_id": picu["doc"], "course": "pals",
                                              "expires_on": (date.today() + timedelta(days=300)).isoformat()})
    page = boss.get("/duty/").get_data(as_text=True)
    assert "data-resus-gaps" not in page and "data-to-certificates" in page
