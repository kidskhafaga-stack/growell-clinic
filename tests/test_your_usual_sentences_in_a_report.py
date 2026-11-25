"""«جملك المعتادة مع الفحص ده» — SMART_PATTERNS_PLAN ج-٤ د (imaging).

The owner said reports are written both in the program and as PDF files
(25 Nov): the habit is counted from the ones written here.

* a reporter's sentences per kind of study — a line or a full stop is a
  sentence — kept at 10 reports and 30 %, findings and impression apart;
* shown above the report's boxes for the person writing it, his own or the
  department's together; a sentence already in the report is not offered;
* pressing one only puts it in the box — the report is saved by «Save», and
  the sentences used are counted then; «مش عايز ده» hides one for good.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_what_a_scan_gave_the_child import _order, xray  # noqa: E402,F401

NORMAL = "The ventricles are normal in size. No midline shift"
NO_BLEED = "No intracranial haemorrhage"


@pytest.fixture()
def reports(xray):
    """Ten brain CTs reported by the administrator: «normal ventricles» and
    «no midline shift» in all, «no bleed» as the impression in 8, and a
    line about a fracture in 2. Today's CT is waiting for its report."""
    from app.models import VisitInvestigation

    c = xray
    with c["app"].app_context():
        db = c["db"]
        for i in range(10):
            text = NORMAL + ("\nLinear fracture of the left parietal bone." if i < 2 else "")
            db.session.add(VisitInvestigation(
                visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                investigation_id=c["ids"]["ct"], kind="imaging", name="مقطعية مخ",
                status="resulted", result_text=text,
                result_comment=NO_BLEED if i < 8 else "Normal study",
                resulted_by=c["ids"]["admin"],
                resulted_at=datetime.utcnow() - timedelta(days=3 + i)))
        db.session.commit()
    c["ids"]["today_ct"] = _order(c)
    return c


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        dp.refresh()
        c["db"].session.commit()


def test_a_report_s_sentences(xray):
    from app.utils import doctor_patterns as dp

    assert dp.phrases("The ventricles are normal in size. No midline shift.\n- Impression: normal") \
        == ["The ventricles are normal in size", "No midline shift", "Impression: normal"]
    assert dp.phrases("ok.") == [], "too short to be a sentence"


def test_counted_per_reporter_and_study(reports):
    from app.models import OrderPattern

    _refresh(reports)
    with reports["app"].app_context():
        rows = {(r.frequency, r.name): r for r in OrderPattern.query.filter_by(
            dept="imaging", doctor_id=reports["ids"]["admin"], kind="phrase")}
        assert rows[("text", "The ventricles are normal in size")].share == 100.0
        assert rows[("comment", NO_BLEED)].share == 80.0
        assert ("text", "Linear fracture of the left parietal bone") not in rows, "20 %"


def test_offered_above_the_report_and_saved_by_save(reports):
    from app.models import SuggestionFeedback, VisitInvestigation
    from app.utils import doctor_patterns as dp

    _refresh(reports)
    boss = reports["sign_in"]("boss")
    oid = reports["ids"]["today_ct"]
    page = boss.get(f"/imaging/order/{oid}").get_data(as_text=True)
    assert 'data-habits-dept="imaging"' in page
    assert 'data-text="The ventricles are normal in size"' in page and 'data-box="text"' in page
    assert f'data-text="{NO_BLEED}"' in page
    with reports["app"].app_context():
        assert reports["db"].session.get(VisitInvestigation, oid).result_text is None, \
            "nothing is written by showing"
        pid = dp.phrase_id("text", "The ventricles are normal in size")
    boss.post(f"/imaging/order/{oid}/report",
              data={"result_text": "The ventricles are normal in size", "result_comment": "",
                    "habit_phrase": [str(pid)]})
    with reports["app"].app_context():
        assert SuggestionFeedback.query.filter_by(action="taken", kind="phrase", item_id=pid).count() == 1
    page = boss.get(f"/imaging/order/{oid}").get_data(as_text=True)
    assert 'data-text="The ventricles are normal in size"' not in page, "already in the report"


def test_not_this_hides_a_sentence(reports):
    from app.utils import doctor_patterns as dp

    _refresh(reports)
    boss = reports["sign_in"]("boss")
    oid = reports["ids"]["today_ct"]
    with reports["app"].app_context():
        pid = dp.phrase_id("comment", NO_BLEED)
    boss.post(f"/imaging/order/{oid}/habit-never", data={"item_id": pid})
    page = boss.get(f"/imaging/order/{oid}").get_data(as_text=True)
    assert f'data-text="{NO_BLEED}"' not in page


def test_my_habits_names_the_study(reports):
    _refresh(reports)
    page = reports["sign_in"]("boss").get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-dept="imaging"' in page and "مقطعية مخ" in page
