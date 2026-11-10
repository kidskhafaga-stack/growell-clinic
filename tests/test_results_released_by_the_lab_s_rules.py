"""Auto-validation — the laboratory's rules, a person releases (LAB_GLAB360_PLAN م-١).

Off until the laboratory chooses its tests. For a chosen test a result passes
only when every analyte has a number inside an approved range, nothing is
critical or delta-flagged, today's control passed, and the sample was not
rejected or noted. The waiting list says «passes» or why not; one press by
somebody who may release releases what passed, in their name, «by the rules».
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_result_line_by_line import _fresh_cache, _order, _post, bench  # noqa: E402,F401


def _on(bench):
    from app.models import Setting

    with bench["app"].app_context():
        Setting.set("lab_verify_required", "1")
        bench["db"].session.commit()


def _control(bench, accepted=True):
    from app.models.lab_quality import QcMaterial, QcRun

    with bench["app"].app_context():
        m = QcMaterial(name="CRP level 1", analyte_id=bench["crp_a"], target_mean=3, target_sd=0.3)
        bench["db"].session.add(m)
        bench["db"].session.flush()
        bench["db"].session.add(QcRun(material_id=m.id, value=3.1, run_at=datetime.utcnow(),
                                      accepted=accepted))
        bench["db"].session.commit()


def _resulted(bench, value):
    oid = _order(bench, "crp", collected_minutes_ago=30)
    _post(bench, oid, crp_a=value)
    return oid


def _list(bench):
    return bench["sign_in"]("boss").get("/labs/verify").get_data(as_text=True)


def _row(bench, oid):
    from app.models import VisitInvestigation

    with bench["app"].app_context():
        r = bench["db"].session.get(VisitInvestigation, oid)
        return r.verified_at, r.verified_by_rules


def test_off_until_the_lab_chooses_its_tests(bench):
    _on(bench)
    _control(bench)
    _resulted(bench, "3")
    page = _list(bench)
    assert "data-auto-pass" not in page and "data-release-passing" not in page
    assert "data-to-autoverify" in page, "the door"


def test_a_result_that_passes_is_released_by_a_person_in_one_press(bench):
    _on(bench)
    _control(bench)
    bench["sign_in"]("boss").post("/labs/autoverify", data={"test_id": [str(bench["crp"])]})
    good = _resulted(bench, "3")
    high = _resulted(bench, "8")
    page = _list(bench)
    assert page.count("data-auto-pass") == 1
    assert "برّه المدى" in page.split("data-auto-why", 1)[1][:300]
    bench["sign_in"]("boss").post("/labs/verify/passing")
    assert _row(bench, good)[0] is not None and _row(bench, good)[1] is True
    assert _row(bench, high) == (None, None), "what did not pass waits as before"


def test_no_control_today_or_a_failed_one_is_no_pass(bench):
    _on(bench)
    bench["sign_in"]("boss").post("/labs/autoverify", data={"test_id": [str(bench["crp"])]})
    _resulted(bench, "3")
    assert "مفيش كنترول النهارده" in _list(bench)
    _control(bench, accepted=False)
    assert "كنترول النهارده اترفض" in _list(bench)


def test_a_draft_range_never_passes(bench):
    """Platelets have only a draft range — a CBC never passes on it."""
    from app.utils import lab_autoverify

    _on(bench)
    oid = _order(bench, "cbc", collected_minutes_ago=30)
    _post(bench, oid, hb="12", plt="250")
    with bench["app"].app_context():
        lab_autoverify.choose([bench["cbc"]])
        bench["db"].session.commit()
        from app.models import VisitInvestigation
        why = lab_autoverify.check(bench["db"].session.get(VisitInvestigation, oid))
        assert "no_range" in why
