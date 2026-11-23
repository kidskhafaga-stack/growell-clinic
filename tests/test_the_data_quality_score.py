"""Data quality — one score per department and in all (SMART_PATTERNS_PLAN ج-١).

From the vaccination unit's program the owner brought the method: a 0–100
score that is a weighted average of checks, a door from each check to its
records, a sheet of them, and the score kept day by day. These hold it here:

* the score's arithmetic — «higher is better» is the share that is right,
  «lower is better» 100 − 5 × the share that is wrong and never below zero;
  a check with nothing to look at is left out, not counted as 100 or 0;
* the checks count real records, and «Fix» lists them, each opening where a
  person fixes it — the program fixes nothing; the same list is a sheet;
* a department shows only where its module runs — a clinic sees no
  emergency card;
* the overall score: the patient file 30, the rest shared by the work done;
* the weights are the administrator's, and the score is kept once a day.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def test_the_arithmetic():
    from app.utils import data_quality as dq

    assert dq.score_of(0, 0, "lower") is None, "nothing to look at, no score"
    assert dq.score_of(1, 10, "higher") == 90.0, "the share that is right"
    assert dq.score_of(2, 100, "lower") == 90.0, "2 % wrong costs ten points"
    assert dq.score_of(19, 100, "lower") == 5.0
    assert dq.score_of(30, 100, "lower") == 0.0, "never below zero"
    # Worse is always lower — the vaccination program's switch at 20 % made
    # 21 % wrong score better than 19 %.
    assert dq.score_of(21, 100, "lower") <= dq.score_of(19, 100, "lower")
    assert dq.weighted([(100, 30), (None, 70)]) == 100.0, "no score, no weight"
    assert dq.weighted([(100, 50), (50, 50)]) == 75.0
    assert (dq.colour(95), dq.colour(70), dq.colour(10), dq.colour(None)) == \
        ("green", "amber", "red", "none")


@pytest.fixture()
def messy(clinic):
    """The clinic's child with no phone and no family; its visit completed
    with no diagnosis and no weight; a dose given twice the same day with
    no lot."""
    from app.models import PatientVaccine, Visit
    from app.utils.clock import local_today

    db = clinic["db"]
    with clinic["app"].app_context():
        visit = db.session.get(Visit, clinic["ids"]["visit"])
        visit.status = "completed"
        for _ in range(2):
            db.session.add(PatientVaccine(
                patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
                brand_id=clinic["ids"]["brand"], dose_number=1,
                given_date=local_today(), doctor_id=clinic["ids"]["doctor"]))
        db.session.commit()
    return clinic


def _checks(c):
    from app.utils import data_quality as dq

    with c["app"].app_context():
        data = dq.board()
        return data, {k["key"]: k for s in data["sections"] for k in s["checks"]}


def test_the_checks_count_real_records(messy):
    data, checks = _checks(messy)
    assert (checks["guardian_phone"]["bad"], checks["guardian_phone"]["total"]) == (1, 1)
    assert checks["guardian_phone"]["score"] == 0.0
    assert checks["family_linked"]["bad"] == 1
    assert (checks["visit_no_dx"]["bad"], checks["visit_no_weight"]["bad"]) == (1, 1)
    assert checks["dose_same_day"]["bad"] == 2 and checks["dose_no_lot"]["bad"] == 2
    assert checks["dose_before_birth"]["bad"] == 0
    assert checks["dose_before_birth"]["score"] == 100.0
    assert data["overall"] is not None


def test_a_fix_lists_the_records_and_a_sheet_carries_them(messy):
    boss = messy["sign_in"]("boss")
    page = boss.get("/reports/data-quality").get_data(as_text=True)
    assert 'data-dq-fix="visit_no_dx"' in page
    assert 'data-dq-fix="dose_before_birth"' not in page, "nothing to fix, no door"
    rows = boss.get("/reports/data-quality/visit_no_dx").get_data(as_text=True)
    assert 'data-dq-rows="1"' in rows
    assert f"/visits/{messy['ids']['visit']}" in rows, "opens the visit itself"
    sheet = boss.get("/reports/data-quality/visit_no_dx/sheet.csv")
    assert sheet.status_code == 200 and sheet.mimetype == "text/csv"
    body = sheet.get_data(as_text=True)
    assert body.startswith("﻿") and "P1" in body
    assert boss.get("/reports/data-quality/made_up").status_code == 404


def test_fixing_the_record_raises_the_score(messy):
    from app.models import Diagnosis

    before = _checks(messy)[1]["visit_no_dx"]["score"]
    with messy["app"].app_context():
        messy["db"].session.add(Diagnosis(visit_id=messy["ids"]["visit"],
                                          code="J06.9", title="URTI"))
        messy["db"].session.commit()
    after = _checks(messy)[1]["visit_no_dx"]
    assert (before, after["bad"], after["score"]) == (0.0, 0, 100.0)


def test_a_department_shows_only_where_its_module_runs(messy):
    from app.models import EmergencyVisit, Setting

    data, _ = _checks(messy)
    assert "emergency" not in [s["key"] for s in data["sections"]]
    page = messy["sign_in"]("boss").get("/reports/data-quality").get_data(as_text=True)
    assert 'data-dq-section="emergency"' not in page
    with messy["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        messy["db"].session.add(EmergencyVisit(
            patient_id=messy["ids"]["child"], arrived_at=datetime.utcnow() - timedelta(hours=3),
            departed_at=datetime.utcnow(), disposition="home"))
        messy["db"].session.commit()
    data, checks = _checks(messy)
    assert "emergency" in [s["key"] for s in data["sections"]]
    assert checks["er_no_triage"]["bad"] == 1 and checks["er_no_disposition"]["bad"] == 0


def test_the_overall_shares(messy):
    data, _ = _checks(messy)
    shares = {s["key"]: s["share"] for s in data["sections"]}
    assert shares["patient"] == 30
    # One visit and two doses in the window: the 70 shared one to two.
    assert (shares["clinic"], shares["vaccines"]) == (23.3, 46.7)


def test_the_weights_are_the_administrator_s(messy):
    desk = messy["sign_in"]("desk")
    assert desk.post("/reports/data-quality", data={"w_visit_no_dx": "5"}).status_code in (302, 403)
    messy["sign_in"]("boss").post("/reports/data-quality", data={"w_visit_no_dx": "5",
                                                                 "w_dose_no_lot": "abc"})
    _, checks = _checks(messy)
    assert checks["visit_no_dx"]["weight"] == 5
    assert checks["dose_no_lot"]["weight"] == 35, "a word is not a weight"


def test_the_score_is_kept_once_a_day(messy):
    from app.models import DqDaily

    boss = messy["sign_in"]("boss")
    boss.get("/reports/data-quality")
    boss.get("/reports/data-quality")
    with messy["app"].app_context():
        assert DqDaily.query.filter_by(section="all").count() == 1
        assert {r.section for r in DqDaily.query} >= {"all", "patient", "clinic", "vaccines"}


def test_the_screen_has_its_door(messy):
    page = messy["sign_in"]("boss").get("/reports/").get_data(as_text=True)
    assert "/reports/data-quality" in page
