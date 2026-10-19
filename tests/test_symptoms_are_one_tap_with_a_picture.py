"""لوح التخصص: الأعراض بزرار وأيقونة (DOCTOR_EASE_PLAN.md أ-٧).

قرار صاحب العيادة: «كل عَرَض نعم/لأ لوحده أسهل بس خليها بأشكال».

* كل عَرَض زرار عليه أيقونة؛ ضغطة = نعم، التانية = لأ، التالتة تمسح؛
* «مفيش جديد / الباقي لأ» بيعلّم اللي محدش لمسه لأ — على الشاشة؛
* اللي ما اتلمسش **ما بيتحفظش**: «ما اتسألش» مش «لأ»؛
* السيرفر بيقبل نعم أو لأ بس؛
* «آخر مرة: نعم» بتبان على الزرار، ومفيش نقل لوحده.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_clinic_that_does_not_work_specialties import (  # noqa: E402,F401
    _module, _page, _readings, _save, desk)


def test_the_chips_are_on_the_cardiology_panel(desk):
    _module(desk, True)
    page = _page(desk)
    assert 'data-flag-group="since_last"' in page
    assert 'data-flag="sym_breathless"' in page and "bi-lungs" in page
    assert 'name="m_sym_cyanosis"' in page and "data-flag-rest" in page
    # Not drawn twice as ordinary boxes below.
    assert page.count('name="m_sym_breathless"') == 1


def test_yes_and_no_are_kept_and_untouched_is_not(desk):
    _module(desk, True)
    _save(desk, specialty_panel="cardiology", m_sym_breathless="نعم", m_sym_syncope="لأ",
          m_sym_cyanosis="", m_sym_palpitations="maybe")
    got = _readings(desk)
    assert got["sym_breathless"].value_text == "نعم"
    assert got["sym_syncope"].value_text == "لأ"
    assert "sym_cyanosis" not in got, "not asked is not «no»"
    assert "sym_palpitations" not in got, "only yes or no is accepted"
    page = _page(desk)
    assert 'data-flag="sym_breathless" data-state="yes"' in page
    assert 'data-flag="sym_syncope" data-state="no"' in page
    # Cleared on the next save.
    _save(desk, specialty_panel="cardiology", m_sym_breathless="")
    assert "sym_breathless" not in _readings(desk)


def test_last_time_yes_shows_on_the_chip_and_is_not_copied(desk):
    from app.models import Measurement, Visit

    _module(desk, True)
    db = desk["db"]
    with desk["app"].app_context():
        now = db.session.get(Visit, desk["ids"]["visit"])
        before = Visit(patient_id=now.patient_id, doctor_id=now.doctor_id,
                       visit_date=now.visit_date - timedelta(days=30))
        db.session.add(before)
        db.session.flush()
        db.session.add(Measurement(patient_id=now.patient_id, visit_id=before.id,
                                   code="sym_breathless", panel="cardiology", value_text="نعم"))
        db.session.commit()
    page = _page(desk)
    start = page.index('data-flag="sym_breathless"')
    chip = page[start:page.index("</button>", start)]
    assert "data-flag-was" in chip and 'data-state=""' in chip
    assert 'name="m_sym_breathless" value=""' in chip
