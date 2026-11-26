"""«عادتك مع التشخيص ده» for a rehabilitation plan — SMART_PATTERNS_PLAN ج-٤ هـ.

The owner said behaviour therapy is written inside rehabilitation (25 Nov).
An enrolment had no diagnosis and no planned number of sessions, so there
was nothing to count by; both are now on it, optional. These hold:

* the plan is saved with its diagnosis and planned sessions;
* a therapist's usual goals (each line of the plan) and planned sessions
  with a diagnosis are counted, at 10 plans and 30 %;
* they are on the rehabilitation form for the person writing it, by the
  diagnosis typed; what was pressed is counted when the form is sent;
* nothing where the programmes do not run.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

EYE = "Improve eye contact during play"
WORDS = "Two-word phrases on request"


@pytest.fixture()
def plans(clinic):
    """Ten autism plans written by the administrator: eye contact in all,
    two-word phrases in 7, 24 sessions in 7 and 12 in 3."""
    from app.models import Setting
    from app.models.care_program import ProgramEnrollment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:programs", "1")
        for i in range(10):
            plan = EYE + ("\n" + WORDS if i < 7 else "")
            db.session.add(ProgramEnrollment(
                patient_id=clinic["ids"]["child"], program="rehab", plan=plan,
                dx_code="F84.0", planned_sessions=24 if i < 7 else 12,
                started_on=local_today() - timedelta(days=30 + i * 20),
                ended_on=local_today() - timedelta(days=5 + i * 20), by_id=clinic["ids"]["admin"]))
        db.session.commit()
    return clinic


def _refresh(c):
    from app.utils import doctor_patterns as dp

    with c["app"].app_context():
        dp.refresh()
        c["db"].session.commit()


def test_counted_by_diagnosis(plans):
    from app.models import OrderPattern

    _refresh(plans)
    with plans["app"].app_context():
        rows = {(r.kind, r.name): r for r in OrderPattern.query.filter_by(
            dept="rehab", doctor_id=plans["ids"]["admin"], dx_key="F84.0")}
        assert rows[("phrase", EYE)].share == 100.0
        assert rows[("phrase", WORDS)].share == 70.0
        assert (rows[("sessions", "24")].share, rows[("sessions", "12")].share) == (70.0, 30.0)
        assert OrderPattern.query.filter_by(dept="rehab", dx_key="F84").count() > 0, \
            "and by its category"


def test_on_the_form_and_saved_with_the_plan(plans):
    from app.models import SuggestionFeedback
    from app.models.care_program import ProgramEnrollment
    from app.utils import doctor_patterns as dp

    _refresh(plans)
    boss = plans["sign_in"]("boss")
    page = boss.get("/programs/?p=rehab").get_data(as_text=True)
    assert 'name="dx_code"' in page and 'name="planned_sessions"' in page
    assert '"F84.0"' in page and EYE in page and 'data-habits-dept="rehab"' in page
    with plans["app"].app_context():
        pid = dp.phrase_id("goal", EYE)
        db = plans["db"]
        for row in ProgramEnrollment.query.all():
            row.ended_on = row.ended_on or row.started_on
        db.session.commit()
    boss.post("/programs/enroll", data={
        "program": "rehab", "patient_id": plans["ids"]["child"], "plan": EYE,
        "dx_code": "f84.0", "planned_sessions": "24",
        "habit_dx": "F84.0", "habit_phrase": [str(pid)], "habit_sessions": "24"})
    with plans["app"].app_context():
        new = ProgramEnrollment.query.filter_by(ended_on=None).one()
        assert (new.dx_code, new.planned_sessions) == ("F84.0", 24)
        taken = {(r.kind, r.item_id) for r in SuggestionFeedback.query.filter_by(action="taken")}
        assert taken == {("phrase", pid), ("sessions", 24)}


def test_other_programmes_have_no_diagnosis_box(plans):
    page = plans["sign_in"]("boss").get("/programs/?p=dialysis").get_data(as_text=True)
    assert 'name="dx_code"' not in page and "data-habits" not in page


def test_my_habits_names_the_sessions(plans):
    _refresh(plans)
    page = plans["sign_in"]("boss").get("/visits/my-habits").get_data(as_text=True)
    assert 'data-habits-dept="rehab"' in page and "24 جلسة" in page


def test_nothing_where_the_programmes_do_not_run(plans):
    from app.models import OrderPattern, Setting

    with plans["app"].app_context():
        Setting.set("facility_configured", "1")
        Setting.set("mod_enabled:programs", "0")
        plans["db"].session.commit()
    _refresh(plans)
    with plans["app"].app_context():
        assert OrderPattern.query.filter_by(dept="rehab").count() == 0
