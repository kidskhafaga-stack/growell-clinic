"""Quality control, internal and external — GAHAR DAS.18 and DAS.19.

Step six of the laboratory plan:

* a control material carries the target mean and SD the laboratory wrote;
  a run is read as SDs from that target, and drawn on a Levey-Jennings
  chart;
* the rejection rules are the laboratory's choice; with none chosen the
  person who ran it judges; with rules chosen a run breaking a rejecting
  rule fails by itself, and 1-2s only warns;
* a failed run without an action is said on the rack until one is written;
* the month's control data is reviewed by somebody authorized, and only by
  them;
* external rounds are kept with their grade, who reviewed it, and the
  remedial action an unacceptable grade needs.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401


def _material(c, mean="100", sd="5"):
    from app.models import QcMaterial

    c["sign_in"]("boss").post("/labs/quality/materials", data={
        "name": "Glucose control", "level": "L1", "target_mean": mean, "target_sd": sd,
        "unit": "mg/dL"})
    with c["app"].app_context():
        row = QcMaterial.query.order_by(QcMaterial.id.desc()).first()
        return row.id if row else None


def _run(c, mid, value, **extra):
    c["sign_in"]("boss").post(f"/labs/quality/material/{mid}/run", data={"value": value, **extra})


def _runs(c, mid):
    from app.models import QcRun

    with c["app"].app_context():
        return [(r.value, r.accepted, r.rule_broken) for r in
                QcRun.query.filter_by(material_id=mid).order_by(QcRun.id).all()]


def test_the_target_is_the_lab_s_and_needs_an_sd(lab):
    from app.models import QcMaterial

    _material(lab, sd="0")
    with lab["app"].app_context():
        assert QcMaterial.query.count() == 0
    mid = _material(lab)
    page = lab["sign_in"]("boss").get(f"/labs/quality/material/{mid}").get_data(as_text=True)
    assert "data-qc-run" in page


def test_with_no_rules_whoever_ran_it_judges(lab):
    mid = _material(lab)
    _run(lab, mid, "118")
    _run(lab, mid, "101", accepted="0", action="ركّبنا تشغيلة كاشف جديدة")
    assert _runs(lab, mid) == [(118.0, True, None), (101.0, False, None)]


def test_chosen_rules_judge_by_themselves(lab):
    boss = lab["sign_in"]("boss")
    boss.post("/labs/quality/rules", data={"rule": ["1_2s", "1_3s", "2_2s"]})
    mid = _material(lab)
    _run(lab, mid, "111")          # +2.2 SD: warning only
    _run(lab, mid, "112")          # second beyond +2: 2-2s
    _run(lab, mid, "84")           # -3.2 SD: 1-3s
    _run(lab, mid, "100")
    assert _runs(lab, mid) == [(111.0, True, "1_2s"), (112.0, False, "2_2s"),
                               (84.0, False, "1_3s"), (100.0, True, None)]
    page = boss.get(f"/labs/quality/material/{mid}").get_data(as_text=True)
    assert 'data-point="failed"' in page and 'data-point="ok"' in page


def test_a_failed_run_is_said_on_the_rack_until_its_action_is_written(lab):
    from app.models import QcRun

    mid = _material(lab)
    _run(lab, mid, "70", accepted="0")
    boss = lab["sign_in"]("boss")
    assert "data-qc-failures" in boss.get("/labs/").get_data(as_text=True)
    with lab["app"].app_context():
        run_id = QcRun.query.one().id
    boss.post(f"/labs/quality/run/{run_id}/action", data={"action": "معايرة الجهاز وإعادة الكنترول"})
    assert "data-qc-failures" not in boss.get("/labs/").get_data(as_text=True)


def test_the_month_is_reviewed_by_somebody_authorized_only(lab):
    from app.models import QcReview

    mid = _material(lab)
    _run(lab, mid, "100")
    from app.utils.clock import local_today

    month = local_today().strftime("%Y-%m")
    lab["sign_in"]("doc").post("/labs/quality/review", data={"month": month})
    with lab["app"].app_context():
        assert QcReview.query.count() == 0
    lab["sign_in"]("boss").post("/labs/quality/review", data={"month": month, "note": "تمام"})
    with lab["app"].app_context():
        assert [(r.month, r.note) for r in QcReview.query.all()] == [(month, "تمام")]
    assert "data-reviewed" in lab["sign_in"]("boss").get("/labs/quality").get_data(as_text=True)


def test_external_rounds_graded_reviewed_and_remedied(lab):
    from app.models import EqaRound

    boss = lab["sign_in"]("boss")
    boss.post("/labs/eqa", data={"provider": "برنامج الكفاءة القومي", "round_code": "2026-3",
                                 "tests": "CBC, Glucose", "kind": "proficiency"})
    with lab["app"].app_context():
        rid = EqaRound.query.one().id
    boss.post(f"/labs/eqa/{rid}/grade", data={"outcome": "unacceptable"})
    with lab["app"].app_context():
        assert lab["db"].session.get(EqaRound, rid).reviewed_at is None, "unacceptable needs its action"
    boss.post(f"/labs/eqa/{rid}/grade", data={"outcome": "unacceptable",
                                              "remedial_action": "إعادة معايرة وتدريب الفني"})
    with lab["app"].app_context():
        row = lab["db"].session.get(EqaRound, rid)
        assert (row.outcome, row.reviewed_by) == ("unacceptable", lab["ids"]["admin"])
    assert "data-round-graded" in boss.get("/labs/eqa").get_data(as_text=True)
