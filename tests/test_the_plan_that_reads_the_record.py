"""The one plan the other eleven standards point at — GAHAR ICD.15.

> *An individualized plan of care is developed for **every patient**.*

Seven elements, and the design is which of them a person types. Three are
already written down elsewhere, so the program reads them; four are nobody
else's answer, so it asks. That split is what this file tests.

What is tested here, in the order it matters:

1. **The plan points at the record and never copies it.** Element (ب) — *based
   on assessments… including the result of diagnostic tests* — is read live
   from the problem list, the risk assessments, the readings and the results.
   A snapshot would be the stale copy, and it would be the one on the plan.
2. **«محتاجة تحديث» is a comparison, not a flag.** Element (و) is one moment
   against another, so it is right the second a nurse writes a reading — and
   no column anywhere has to be remembered.
3. **A plan with no goals is not a plan.** Element (هـ) is the body; `empty`
   is its own word, and a signature under an empty plan is refused.
4. **Three answers about the family, not two.** Evidence 3 has a surveyor
   *interview the family* about their involvement, so a blank standing for
   «لأ» would be the program claiming something the family will deny.
5. **One live plan per child.** Pressing «ابدأ خطة» twice must not give a
   child two plans — a child with four plans has none.
6. **It tells, it never blocks**, and a clinic upgrading into this version
   sees a quiet door rather than a red mark on every file.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def file_with(clinic):
    """The clinic, plus a second child — so a missing filter cannot pass."""
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        other = Patient(patient_number="CP-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=800))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["ids"]["other_child"] = other.id
    return clinic


def _start(clinic, patient_id, **form):
    client = clinic["sign_in"]("doc")
    return client.post(f"/patients/{patient_id}/care-plan", data=form,
                       follow_redirects=True)


def _goal(clinic, patient_id, need="مشي بعد الجبس", **form):
    client = clinic["sign_in"]("doc")
    return client.post(f"/patients/{patient_id}/care-plan/goal",
                       data={"need": need, **form}, follow_redirects=True)


def _sign(clinic, patient_id, who="doc"):
    return clinic["sign_in"](who).post(
        f"/patients/{patient_id}/care-plan/sign", follow_redirects=True)


def _plan(clinic, patient_id):
    from app.utils import care_plan

    with clinic["app"].app_context():
        return care_plan.current(patient_id)


def _state(clinic, patient_id):
    from app.utils import care_plan

    with clinic["app"].app_context():
        return care_plan.state(care_plan.current(patient_id))


def _problem(clinic, patient_id, title="ربو"):
    from app.models import PatientProblem

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientProblem(
            patient_id=patient_id, title=title, status="active"))
        clinic["db"].session.commit()


# ------------------------------------------- (ب) the record answers it ----
def test_the_plan_reads_the_record_and_never_copies_it(file_with):
    """*"Based on assessments of the patient performed by the various
    healthcare disciplines… including the result of diagnostic tests."*

    Two copies of one reading are two chances to disagree, and the one on the
    plan is the one nobody updates — the argument this codebase has already
    made about the device studies and the lab curves.
    """
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _start(file_with, child)
    _problem(file_with, child, "ربو")

    with file_with["app"].app_context():
        found = {i["key"]: i["rows"] for i in care_plan.stands_on(child)}
    assert [p.title for p in found["problems"]] == ["ربو"]
    # Nothing was written onto the plan itself when the problem was added.
    plan = _plan(file_with, child)
    assert plan is not None


def test_what_it_stands_on_is_this_childs_and_nobody_elses(file_with):
    """**Every one of the five reads, not the first one.**

    Three of them reach their rows through a join on the visit, and a sweep
    showed that dropping `Visit.patient_id` from the diagnoses left the suite
    green — which would have printed another family's diagnoses on this
    child's plan of care. The same shape that shipped once already on the
    labs tab, caught the same way.
    """
    from app.models import Diagnosis, PatientProblem, Visit
    from app.models.risk_assessment import RiskAssessment
    from app.models.visit import VisitInvestigation
    from app.utils import care_plan
    from app.utils.clock import local_today

    mine, theirs = file_with["ids"]["child"], file_with["ids"]["other_child"]
    with file_with["app"].app_context():
        their_visit = Visit(patient_id=theirs, visit_date=local_today(),
                            doctor_id=file_with["ids"]["doctor"])
        file_with["db"].session.add(their_visit)
        file_with["db"].session.add(PatientProblem(
            patient_id=theirs, title="سكري", status="active"))
        file_with["db"].session.add(RiskAssessment(
            patient_id=theirs, kind="fall", at=datetime.utcnow()))
        file_with["db"].session.flush()
        file_with["db"].session.add(Diagnosis(
            visit_id=their_visit.id, title="تشخيص مش بتاعه"))
        file_with["db"].session.add(VisitInvestigation(
            visit_id=their_visit.id, patient_id=theirs,
            name="تحليل مش بتاعه"))
        file_with["db"].session.commit()

        found = {i["key"]: i["rows"] for i in care_plan.stands_on(mine)}
    assert found["problems"] == []
    assert found["diagnoses"] == []
    assert found["risks"] == []
    assert found["results"] == []
    assert found["readings"] == []


def test_a_resolved_problem_is_not_something_the_plan_stands_on(file_with):
    """A plan built on a problem that is over is a plan for last year."""
    from app.models import PatientProblem
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    with file_with["app"].app_context():
        file_with["db"].session.add(PatientProblem(
            patient_id=child, title="التهاب", status="resolved"))
        file_with["db"].session.commit()
        found = {i["key"]: i["rows"] for i in care_plan.stands_on(child)}
    assert found["problems"] == []


def test_the_two_read_elements_are_never_asked_of_a_doctor(file_with):
    """(ب) and (و) are answered by the record and by time. Listing them among
    the blanks would ask a doctor to type something no box accepts."""
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _start(file_with, child)

    with file_with["app"].app_context():
        gaps = care_plan.missing(care_plan.current(child))
        written = [el["letter"] for el in
                   care_plan.assemble(care_plan.current(child), child)
                   if not el["written"]]
    assert "ب" not in gaps and "و" not in gaps
    assert written == ["ب", "و"]


# ------------------------------------------- (و) a comparison, not a flag ----
def test_a_plan_goes_stale_the_second_the_record_moves(file_with):
    """*"Updated as appropriate based on the reassessment of the patient."*

    Stored as a column this is something somebody has to remember to set, and
    the morning nobody remembers is the morning it matters.
    """
    from app.models import CarePlan

    child = file_with["ids"]["child"]
    _start(file_with, child)
    _goal(file_with, child)
    _sign(file_with, child)
    assert _state(file_with, child) == "current"

    # An assessment lands after the plan was last touched — nobody tells the
    # plan anything, and the plan knows.
    _problem(file_with, child, "حساسية")
    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).first()
        plan.updated_at = datetime.utcnow() - timedelta(days=2)
        file_with["db"].session.commit()

    assert _state(file_with, child) == "stale"


def test_touching_the_plan_settles_it_again(file_with):
    from app.models import CarePlan

    child = file_with["ids"]["child"]
    _start(file_with, child)
    _goal(file_with, child)
    _sign(file_with, child)
    _problem(file_with, child, "حساسية")
    with file_with["app"].app_context():
        CarePlan.query.filter_by(patient_id=child).first().updated_at = (
            datetime.utcnow() - timedelta(days=2))
        file_with["db"].session.commit()
    assert _state(file_with, child) == "stale"

    # Adding a goal is a change to the plan, and `add_goal` says so — the
    # reason `touch` is called explicitly rather than left to `onupdate`,
    # which fires only on the row that changed.
    _goal(file_with, child, need="متابعة الحساسية")
    assert _state(file_with, child) == "current"


def test_a_plan_updated_for_that_very_assessment_is_not_stale(file_with):
    """The boundary, and it is not decoration: ``>=`` would call a plan stale
    in the same instant somebody updated it **for** the assessment that
    landed — a mark that appears the moment the work is done."""
    from app.models import CarePlan
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _goal(file_with, child)
    _problem(file_with, child, "ربو")

    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).one()
        plan.updated_at = care_plan.last_assessment_at(child)
        file_with["db"].session.commit()
        assert care_plan.needs_update(plan) is False


def test_a_plan_with_no_stamp_yet_is_not_read_as_stale(file_with):
    """A plan object that has not been flushed has no ``updated_at``, and
    comparing a datetime against ``None`` raises rather than answering. The
    screen draws a plan the second it is opened, so this path is reachable."""
    from app.models import CarePlan
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _problem(file_with, child, "ربو")
    with file_with["app"].app_context():
        unflushed = CarePlan(patient_id=child)
        assert care_plan.needs_update(unflushed) is False
        assert care_plan.state(unflushed) == "empty"


def test_a_child_with_no_plan_is_not_also_called_out_of_date(file_with):
    """Two marks on one absence. The gap is the gap."""
    from app.utils import care_plan

    with file_with["app"].app_context():
        assert care_plan.needs_update(None) is False
    assert _state(file_with, file_with["ids"]["child"]) == "none"


# ------------------------------------------------ (هـ) the body of it ----
def test_a_plan_with_no_goals_is_its_own_word(file_with):
    """*"Includes identified needs, interventions, and desired outcomes with
    timeframes."* A cover with nothing under it is element (هـ) missing, and
    calling it «written» is the false green tick this codebase keeps removing.
    """
    child = file_with["ids"]["child"]
    _start(file_with, child)

    assert _state(file_with, child) == "empty"


def test_an_empty_plan_cannot_be_signed(file_with):
    """A signature there is a claim that somebody supervised the making of
    nothing — and the one state that would read as complete while the body of
    the plan is missing."""
    child = file_with["ids"]["child"]
    _start(file_with, child)
    _sign(file_with, child)

    plan = _plan(file_with, child)
    assert plan.mrp_signed_at is None
    assert _state(file_with, child) == "empty"


def test_a_goal_with_no_need_is_refused(file_with):
    from app.models import CarePlanGoal

    child = file_with["ids"]["child"]
    _start(file_with, child)
    _goal(file_with, child, need="   ")

    with file_with["app"].app_context():
        assert CarePlanGoal.query.count() == 0


def test_a_need_with_nothing_else_yet_is_kept(file_with):
    """A need identified with no intervention decided is a real and common
    thing to write at the moment it is found. Refusing it sends it to the
    margin of a paper chart."""
    from app.models import CarePlanGoal

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="تغذية")

    with file_with["app"].app_context():
        row = CarePlanGoal.query.one()
        assert (row.need, row.intervention, row.outcome) == ("تغذية", None, None)


def test_the_timeframe_is_compared_against_something(file_with):
    """*"desired outcomes **with timeframes**"* — a date in a box that nothing
    ever reads is not a timeframe."""
    from app.models import CarePlan
    from app.utils.clock import local_today

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="يمشي",
          by_when=(local_today() - timedelta(days=3)).isoformat())

    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).first()
        assert [g.need for g in plan.overdue_goals] == ["يمشي"]


def test_a_goal_that_was_met_is_not_overdue(file_with):
    from app.models import CarePlan, CarePlanGoal
    from app.utils.clock import local_today

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="يمشي",
          by_when=(local_today() - timedelta(days=3)).isoformat())
    with file_with["app"].app_context():
        goal_id = CarePlanGoal.query.one().id
    file_with["sign_in"]("doc").post(
        f"/patients/care-plan/goal/{goal_id}/progress",
        data={"progress": "met"}, follow_redirects=True)

    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).first()
        assert plan.overdue_goals == []


def test_a_goal_found_not_met_is_closed_and_not_overdue(file_with):
    """«ما اتحقّقش» is a conclusion, not an outstanding errand. A goal somebody
    reviewed and closed as unmet is being monitored — element (ز) answered —
    and going on flagging its date as overdue would bury the ones still open.
    """
    from app.models import CarePlan, CarePlanGoal
    from app.utils.clock import local_today

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="يمشي",
          by_when=(local_today() - timedelta(days=3)).isoformat())
    with file_with["app"].app_context():
        goal_id = CarePlanGoal.query.one().id
    file_with["sign_in"]("doc").post(
        f"/patients/care-plan/goal/{goal_id}/progress",
        data={"progress": "not_met", "progress_note": "الجبس اتأخر"},
        follow_redirects=True)

    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).one()
        assert CarePlanGoal.query.one().is_closed is True
        assert plan.open_goals == []
        assert plan.overdue_goals == []


def test_a_goal_with_no_date_is_never_overdue(file_with):
    """Most goals have no date, and a plan that flagged all of them would
    teach a ward to skip the flag."""
    from app.models import CarePlan

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="تغذية")

    with file_with["app"].app_context():
        plan = CarePlan.query.filter_by(patient_id=child).first()
        assert plan.overdue_goals == []


# ------------------------------------------------------- (ز) monitoring ----
@pytest.mark.parametrize("progress", ["open", "progressing", "met", "not_met"])
def test_the_four_progress_answers_are_recorded(file_with, progress):
    from app.models import CarePlanGoal

    child = file_with["ids"]["child"]
    _goal(file_with, child)
    with file_with["app"].app_context():
        goal_id = CarePlanGoal.query.one().id
    file_with["sign_in"]("doc").post(
        f"/patients/care-plan/goal/{goal_id}/progress",
        data={"progress": progress, "progress_note": "راجعناه"},
        follow_redirects=True)

    with file_with["app"].app_context():
        row = CarePlanGoal.query.one()
        assert row.progress == progress
        assert row.progress_by == file_with["ids"]["doctor"]
        assert row.progress_at is not None


def test_a_progress_the_screen_cannot_draw_is_refused(file_with):
    from app.models import CarePlanGoal

    child = file_with["ids"]["child"]
    _goal(file_with, child)
    with file_with["app"].app_context():
        goal_id = CarePlanGoal.query.one().id
    file_with["sign_in"]("doc").post(
        f"/patients/care-plan/goal/{goal_id}/progress",
        data={"progress": "kind_of"}, follow_redirects=True)

    with file_with["app"].app_context():
        assert CarePlanGoal.query.one().progress == "open"


def test_monitoring_counts_as_answered_once_any_goal_is_reviewed(file_with):
    """Not when every goal is closed — a plan whose goals are all still open
    is being monitored the moment one of them is looked at."""
    from app.models import CarePlanGoal
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="أ")
    _goal(file_with, child, need="ب")
    with file_with["app"].app_context():
        assert "ز" in care_plan.missing(care_plan.current(child))
        goal_id = CarePlanGoal.query.filter_by(need="أ").one().id
    file_with["sign_in"]("doc").post(
        f"/patients/care-plan/goal/{goal_id}/progress",
        data={"progress": "progressing"}, follow_redirects=True)

    with file_with["app"].app_context():
        assert "ز" not in care_plan.missing(care_plan.current(child))


# -------------------------------------------------- (ج) three answers ----
def test_a_blank_about_the_family_is_not_a_no(file_with):
    """Evidence 3 has a surveyor interview the family about their involvement,
    so an empty box standing for «لأ» would be the program telling a hospital
    it had done something the family will say it did not."""
    child = file_with["ids"]["child"]
    _start(file_with, child, family_involved="")

    assert _plan(file_with, child).family_involved is None


def test_saying_the_family_was_not_involved_answers_the_element(file_with):
    """«لأ» is an answer. Counting element (ج) as blank because the answer was
    negative would leave a checklist demanding a doctor re-type a thing they
    already said — and the same reading would make «لأ» indistinguishable from
    nobody having been asked, which is the distinction the column exists for.
    """
    from app.utils import care_plan

    child = file_with["ids"]["child"]
    _start(file_with, child, family_involved="no",
           family_note="الأم مش موجودة دلوقتي")

    with file_with["app"].app_context():
        plan = care_plan.current(child)
        assert plan.family_involved is False
        assert "ج" not in care_plan.missing(plan)


@pytest.mark.parametrize("said,expected", [("yes", True), ("no", False),
                                           ("", None), ("مش عارف", None)])
def test_the_form_reads_three_answers_and_not_two(file_with, said, expected):
    from app.blueprints.patients.routes import _tri

    assert _tri(said) is expected


def test_saving_one_part_of_the_cover_does_not_clear_the_others(file_with):
    """The screen saves the cover a piece at a time, and a save that blanked
    the rest would lose the family's answer every time somebody corrected the
    guideline."""
    child = file_with["ids"]["child"]
    _start(file_with, child, family_involved="yes", family_note="الأم وافقت")
    _start(file_with, child, guideline="GINA 2024")

    plan = _plan(file_with, child)
    assert (plan.family_involved, plan.family_note) == (True, "الأم وافقت")
    assert plan.guideline == "GINA 2024"

    # **And the other way round**, which a sweep showed was untested: a save
    # that carried no guideline at all left it standing only by luck of the
    # order the two were written in.
    _start(file_with, child, family_note="الأب كمان")
    plan = _plan(file_with, child)
    assert plan.guideline == "GINA 2024"
    assert plan.family_involved is True


# --------------------------------------------------- one plan per child ----
def test_pressing_start_twice_does_not_give_a_child_two_plans(file_with):
    """A child with four plans has no plan: the ward would read one while the
    clinic updated another."""
    from app.models import CarePlan

    child = file_with["ids"]["child"]
    _start(file_with, child)
    _start(file_with, child)

    with file_with["app"].app_context():
        assert CarePlan.query.filter_by(patient_id=child).count() == 1


def test_one_childs_plan_is_never_another_childs(file_with):
    from app.models import CarePlan

    mine, theirs = file_with["ids"]["child"], file_with["ids"]["other_child"]
    _start(file_with, mine)
    _goal(file_with, mine, need="بتاعي")
    _start(file_with, theirs)

    with file_with["app"].app_context():
        assert CarePlan.query.count() == 2
        theirs_plan = CarePlan.query.filter_by(patient_id=theirs).one()
        assert theirs_plan.goals == []


# ------------------------------------------------------ (أ) the signature ----
def test_the_signature_is_the_doctors_and_not_the_desks(file_with):
    """Element (أ) is a claim about a named clinician supervising the plan. A
    name from an account that does not carry the clinical record would be a
    name against a claim it cannot make.

    The two requests run **outside** any shared app context: Flask-Login
    caches the user on ``g``, which belongs to the application context, so two
    clients inside one ``with app.app_context()`` are both served as whoever
    signed in first — and the test would compare the page with itself.
    """
    child = file_with["ids"]["child"]
    _goal(file_with, child)

    refused = file_with["sign_in"]("desk").post(
        f"/patients/{child}/care-plan/sign", follow_redirects=False)
    assert refused.status_code in (302, 403)
    assert _plan(file_with, child).mrp_signed_at is None

    _sign(file_with, child, who="doc")
    assert _plan(file_with, child).mrp_signed_at is not None


def test_written_and_signed_are_two_events(file_with):
    """A registrar drafts the plan and the consultant signs it; one stamp for
    both would say the consultant wrote it."""
    child = file_with["ids"]["child"]
    _goal(file_with, child)
    _sign(file_with, child, who="boss")

    plan = _plan(file_with, child)
    assert plan.written_by == file_with["ids"]["doctor"]
    assert plan.mrp_signed_by == file_with["ids"]["admin"]


# ------------------------------------------------------------ the screen ----
def test_the_file_offers_a_door_and_says_nothing_about_the_absence(file_with):
    """A clinic upgrading into this version has no plan for anybody. The file
    offers the door and stays quiet — nothing here blocks a visit."""
    page = file_with["sign_in"]("doc").get(
        f"/patients/{file_with['ids']['child']}")
    body = page.get_data(as_text=True)

    # **That the file renders at all**, asserted before anything about its
    # contents. Without this line a template that raised passed every
    # "X is not on the page" check below it — a 500 has none of them — which
    # is how a sweep found this test proving nothing about the panel.
    assert page.status_code == 200
    assert 'data-care-plan-door="none"' in body
    assert 'data-care-plan-start' in body
    # And neither the tab button nor the panel, because there is nothing in
    # either.
    #
    # **Each on its own marker.** This read ``"tab=='care_plan'" not in
    # body`` — two equals — while the panel writes
    # ``x-show="tab==='care_plan'"`` with three. The needle was never in
    # the page under any condition, so the line passed without testing
    # anything, and a sweep that removed the panel's guard outright went
    # green. The class of bug this file exists to catch, found in it.
    assert 'data-tab="care_plan"' not in body
    assert 'data-care-plan>' not in body


def test_the_tab_appears_once_there_is_a_plan(file_with):
    child = file_with["ids"]["child"]
    _goal(file_with, child, need="يمشي")

    body = file_with["sign_in"]("doc").get(
        f"/patients/{child}").get_data(as_text=True)
    assert "tab_care_plan" not in body or 'data-tab="care_plan"' in body
    assert 'data-care-plan-state="unsigned"' in body
    assert "يمشي" in body


def test_the_screen_shows_what_the_plan_stands_on(file_with):
    child = file_with["ids"]["child"]
    _goal(file_with, child)
    _problem(file_with, child, "ربو")

    body = file_with["sign_in"]("doc").get(
        f"/patients/{child}").get_data(as_text=True)
    for key in ("problems", "diagnoses", "risks", "readings", "results"):
        assert f'data-stands-on="{key}"' in body


def test_nothing_here_stands_between_a_child_and_a_visit(file_with):
    """It tells, it never blocks — with no plan at all."""
    from app.models import Visit

    child = file_with["ids"]["child"]
    before = None
    with file_with["app"].app_context():
        before = Visit.query.filter_by(patient_id=child).count()
    page = file_with["sign_in"]("doc").get(f"/patients/{child}")
    assert page.status_code == 200
    with file_with["app"].app_context():
        assert Visit.query.filter_by(patient_id=child).count() == before


# ------------------------------------------------------------- the words ----
def test_every_plan_word_is_written_in_both_languages(file_with):
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    keys = ["title", "open", "start", "none_yet", "short", "cover", "need",
            "intervention", "outcome", "by_when", "overdue", "n_overdue",
            "progress", "progress_note", "add_goal", "no_goals", "sign",
            "sign_hint", "signed", "signed_by", "cannot_sign_empty", "saved",
            "goal_added", "needs_a_need", "progress_saved", "bad_progress",
            "family_note", "preferences", "yes", "no", "unsaid",
            "from_the_record", "sign_is_the_doctors"]
    keys += [f"state_{s}" for s in ("none", "empty", "unsigned", "stale",
                                    "current")]
    keys += [f"el_{e}" for e in ("disciplines", "assessments", "family",
                                 "guideline", "goals", "updated", "progress")]
    keys += [f"on_{o}" for o in ("problems", "diagnoses", "risks", "readings",
                                 "results")]
    keys += [f"progress_{p}" for p in ("open", "progressing", "met",
                                       "not_met")]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"care_plan.{key}"), f"{lang}:{key}"
    for lang in ("ar", "en"):
        assert _lookup(tables, lang, "patients.tab_care_plan")


def test_the_seven_elements_are_the_standards_seven(file_with):
    from app.utils.care_plan import ELEMENTS

    assert [letter for letter, _k, _c in ELEMENTS] == ["أ", "ب", "ج", "د",
                                                       "هـ", "و", "ز"]


def test_the_date_stays_a_date(file_with):
    """A timeframe stored as a duration — "in two weeks" — is a sentence whose
    meaning moves every day it is read."""
    from app.models import CarePlanGoal

    child = file_with["ids"]["child"]
    _goal(file_with, child, need="يمشي", by_when="2027-03-01")

    with file_with["app"].app_context():
        assert CarePlanGoal.query.one().by_when == date(2027, 3, 1)
