"""Falls, pressure ulcers and clots — the three risks GAHAR requires, ICD.10-12.

Three standards, one shape: *assess with a tool · reassess on a timeframe ·
general measures · **a tailored care plan** · all of it recorded in the
patient's medical record*. Nothing in this program looked for any of them.

What is tested here, in the order it matters:

1. **The program computes no score, and cannot be made to.** Every one of the
   three hands the tool to the hospital in as many words. What the tool said
   is stored as the hospital's own text and round-trips unchanged — including
   a level that looks like a number, which is the one a parser would eat.
2. **«معرّض» is asked separately from the level**, because «متوسط» is above the
   line in one hospital's policy and below it in another's. It is nullable:
   blank is nobody having said, which is not "no".
3. **`bare` is the finding.** All three standards end on the tailored plan, so
   at-risk-with-no-plan is its own state and the loudest thing on the screen.
   An assessment that concluded *not* at risk is finished and needs no plan.
4. **Nothing is ever overdue until the hospital states a frequency.** The
   standards ask the *hospital* for the timeframe, and a ward that has been
   running for two years must not wake up on upgrade morning covered in red.
5. **A stay reads its own assessments.** A fall assessment from a stay eight
   months ago is not this admission's, and another child's is nobody's — the
   two ways this screen could print a green tick for work nobody did.
6. **It tells, it never blocks.** No admission, move or discharge is refused
   because a risk is unassessed.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A hospital with a ward, two children, and a bed each."""
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        for module in ("beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        unit = Unit(name="القسم الداخلي", kind="ward")
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        for order, name in enumerate(("س١", "س٢")):
            clinic["db"].session.add(
                Bed(space_id=space.id, name=name, sort_order=order))
        # **A second child, on purpose.** A fixture with one patient lets any
        # missing `patient_id` filter pass every test in this file while the
        # screen prints another family's assessment.
        other = Patient(patient_number="R-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=700))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
        clinic["ids"]["other_child"] = other.id
    return clinic


def _admit(clinic, patient_id, bed_name="س١", minutes_ago=600):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        admission = place.admit(
            Patient.query.get(patient_id),
            Bed.query.get(clinic["beds"][bed_name]),
            when=datetime.utcnow() - timedelta(minutes=minutes_ago))
        clinic["db"].session.commit()
        return admission.id


def _write(clinic, admission_id, kind="fall", **form):
    """Record an assessment the way the ward does — through the route."""
    client = clinic["sign_in"]("doc")
    return client.post(f"/beds/admission/{admission_id}/risk",
                       data={"kind": kind, **form}, follow_redirects=True)


def _rows(clinic, **filters):
    from app.models import RiskAssessment

    with clinic["app"].app_context():
        return RiskAssessment.query.filter_by(**filters).all()


def _panel(clinic, admission_id, now=None):
    from app.models.admission import Admission
    from app.utils import risks

    with clinic["app"].app_context():
        return risks.panel(Admission.query.get(admission_id), now=now)


def _state_of(panel, kind):
    return next(item["state"] for item in panel if item["kind"] == kind)


def _due_of(panel, kind):
    return next(item["due"] for item in panel if item["kind"] == kind)


# --------------------------------------------------- the hospital's tool ----
def test_the_three_risks_are_the_standards_three(ward):
    """ICD.10 falls, ICD.11 pressure ulcers, ICD.12 VTE — and nothing else."""
    from app.models.risk_assessment import RISK_KINDS, STANDARDS

    assert RISK_KINDS == ("fall", "pressure", "vte")
    # A standard's code is not a translation — it is the same in Cairo as in
    # Geneva — so it lives beside the kinds and not in a locale file, where
    # the «this screen is in Arabic» guard would have been right to fail it.
    assert [STANDARDS[k] for k in RISK_KINDS] == ["ICD.10", "ICD.11", "ICD.12"]


def test_the_policy_screen_names_the_standard_each_risk_answers(ward):
    body = ward["sign_in"]("boss").get("/settings/risks").get_data(as_text=True)
    for code in ("ICD.10", "ICD.11", "ICD.12"):
        assert code in body


def test_what_the_tool_said_is_kept_word_for_word(ward):
    """**The clinic's vocabulary, stored and never read.**

    Every one of the three standards hands the assessment tool to the hospital
    — *"Assessment contents are based on guidelines"* — and ICD.11's intent
    says more than one international guideline recommends one. A level that
    looks like a number is the case a parser would quietly turn into a score
    nobody in the building decided on.
    """
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, tool="Humpty Dumpty", level="١٤ / عالي")

    row = _rows(ward, admission_id=admission)[0]
    assert row.tool == "Humpty Dumpty"
    assert row.level == "١٤ / عالي"


def test_at_risk_is_asked_and_not_worked_out_from_the_level(ward):
    """«متوسط» is above the line in one hospital and below it in another, so
    no reading of `level` tells this program whether the child needs a plan.
    The one bit it acts on is asked in plain words."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, level="متوسط", at_risk="yes", plan="")

    assert _state_of(_panel(ward, admission), "fall") == "bare"


def test_a_blank_answer_is_nobody_having_said_and_not_a_no(ward):
    """The three states the operative report's «or not» fields keep apart."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, level="اتعمل", at_risk="", family_told="")

    row = _rows(ward, admission_id=admission)[0]
    assert row.at_risk is None
    assert row.family_told is None
    assert _state_of(_panel(ward, admission), "fall") == "unsaid"


@pytest.mark.parametrize("said,expected", [("yes", True), ("no", False),
                                           ("", None), ("maybe", None),
                                           (None, None)])
def test_the_form_reads_three_answers_and_not_two(ward, said, expected):
    from app.blueprints.beds.routes import _yes_no

    assert _yes_no(said) is expected


# ------------------------------------------------- the plan is the point ----
def test_at_risk_with_no_plan_is_its_own_state(ward):
    """The element all three standards end on: *"General measures and tailored
    care plans are recorded in the patient's medical record."* Somebody looked,
    somebody said yes, and the last element is blank — a finding, not a gap."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="yes")

    assert _state_of(_panel(ward, admission), "fall") == "bare"


def test_writing_the_plan_moves_it_off_the_finding(ward):
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="yes", plan="الجنيب مرفوع، الجرس في إيده")

    assert _state_of(_panel(ward, admission), "fall") == "planned"


def test_a_plan_of_spaces_is_not_a_plan(ward):
    """Whitespace in the box is the shape a false green tick arrives in."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="yes", plan="   ")

    assert _state_of(_panel(ward, admission), "fall") == "bare"


def test_a_child_who_is_not_at_risk_needs_no_plan(ward):
    """*"Effective preventive measures … are those that are tailored to each
    patient and directed towards the risks being identified"* — no identified
    risk, nothing to tailor. Demanding a plan here would train a ward to type
    one for every child, which is how the ones that matter stop being read."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="no")

    assert _state_of(_panel(ward, admission), "fall") == "clear"


def test_a_risk_nobody_looked_at_has_a_row_anyway(ward):
    """An absence leaves nothing to find, so the list is built from the risks
    and the assessments are hung onto it. Otherwise «ما اتقيّمش» could never
    appear at all — the same argument the missed observation is built on."""
    admission = _admit(ward, ward["ids"]["child"])

    panel = _panel(ward, admission)
    assert [item["kind"] for item in panel] == ["fall", "pressure", "vte"]
    assert {item["state"] for item in panel} == {"none"}


def test_the_headline_counts_come_off_the_same_list_as_the_rows(ward):
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, kind="fall", at_risk="yes")
    _write(ward, admission, kind="pressure", at_risk="no")

    panel = _panel(ward, admission)
    assert risks.without_plan(panel) == ("fall",)
    assert risks.unassessed(panel) == ("vte",)


# ------------------------------------------- nothing is late until it is ----
def test_nothing_is_overdue_until_the_hospital_states_a_frequency(ward):
    """**Upgrade morning.** All three standards ask the *hospital* for the
    timeframe and the frequency. A ward that has been running for two years
    gains the record on the day it upgrades, and gains no red with it."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="no",
           at=(datetime.utcnow() - timedelta(days=400)).strftime(
               "%Y-%m-%dT%H:%M"))

    assert _due_of(_panel(ward, admission), "fall") == "quiet"


def test_once_the_policy_names_an_interval_a_stale_one_is_due(ward):
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="no")
    with ward["app"].app_context():
        risks.save_policy("fall", on=True, hours=24)
        ward["db"].session.commit()

    fresh = _due_of(_panel(ward, admission), "fall")
    later = _due_of(_panel(ward, admission,
                           now=datetime.utcnow() + timedelta(hours=25)), "fall")
    assert (fresh, later) == ("ok", "due")


def test_a_risk_nobody_assessed_is_not_also_called_overdue(ward):
    """Two marks on one gap. «ما اتقيّمش» is already the loudest thing on the
    screen, and a second badge beside it is noise a ward learns to skip."""
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        risks.save_policy("fall", on=True, hours=1)
        ward["db"].session.commit()

    panel = _panel(ward, admission)
    assert _state_of(panel, "fall") == "none"
    assert _due_of(panel, "fall") == "quiet"


@pytest.mark.parametrize("written", ["", "0", "-4", "كل يوم", None])
def test_an_interval_that_is_not_a_number_of_hours_is_no_interval(ward, written):
    """Zero especially: an interval of nought would make every assessment
    overdue in the second it was written."""
    from app.models import Setting
    from app.utils import risks

    with ward["app"].app_context():
        if written is not None:
            Setting.set("risk:hours:fall", written)
            ward["db"].session.commit()
        assert risks.interval_hours("fall") is None


# --------------------------------------------- whose assessment is whose ----
def test_a_stay_reads_its_own_assessments_and_not_the_last_ones(ward):
    """Assessing on admission is the whole of ICD.10 (أ) / ICD.11 (أ) /
    ICD.12 (أ). A fall assessment from a stay eight months ago showing here
    would be a green tick for work nobody on this stay has done."""
    from app.models.admission import Admission

    first = _admit(ward, ward["ids"]["child"], bed_name="س١")
    _write(ward, first, at_risk="no")
    with ward["app"].app_context():
        Admission.query.get(first).discharged_at = datetime.utcnow()
        ward["db"].session.commit()
    second = _admit(ward, ward["ids"]["child"], bed_name="س٢")

    assert _state_of(_panel(ward, second), "fall") == "none"
    assert _state_of(_panel(ward, first), "fall") == "clear"


def test_another_childs_assessment_never_reaches_this_stay(ward):
    mine = _admit(ward, ward["ids"]["child"], bed_name="س١")
    theirs = _admit(ward, ward["ids"]["other_child"], bed_name="س٢")
    _write(ward, theirs, at_risk="no", level="منخفض")

    assert _state_of(_panel(ward, mine), "fall") == "none"


def test_the_newest_assessment_is_the_one_the_screen_shows(ward):
    """Newest by when it was *done*, not by when it was typed — a reassessment
    written up at the desk still belongs to the hour at the bedside."""
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="yes", plan="الجنيب مرفوع")
    _write(ward, admission, at_risk="no",
           at=(datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"))

    assert _state_of(_panel(ward, admission), "fall") == "planned"


def test_the_assessment_carries_the_name_of_whoever_wrote_it(ward):
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="no")

    assert _rows(ward, admission_id=admission)[0].by_id == ward["ids"]["doctor"]


# ----------------------------------------------- what the place looks for ----
def test_all_three_are_looked_for_until_a_hospital_says_otherwise(ward):
    from app.utils import risks

    with ward["app"].app_context():
        assert risks.enabled_kinds() == ("fall", "pressure", "vte")


def test_a_risk_the_policy_does_not_cover_is_absent_and_not_unanswered(ward):
    """A paediatric ward whose policy does not cover VTE prophylaxis turns it
    off. A switch is a decision somebody made; a row reading «ما اتقيّمش» for
    eleven months is a decision nobody made."""
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        risks.save_policy("vte", on=False)
        ward["db"].session.commit()

    kinds = [item["kind"] for item in _panel(ward, admission)]
    assert kinds == ["fall", "pressure"]


def test_writing_into_a_switched_off_risk_is_refused(ward):
    """A row no screen in the program ever shows again is a row in a medical
    record that nobody can read — worse than no row."""
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        risks.save_policy("vte", on=False)
        ward["db"].session.commit()

    page = _write(ward, admission, kind="vte", at_risk="yes")
    assert page.status_code == 200
    assert _rows(ward, admission_id=admission, kind="vte") == []


def test_an_unreadable_switch_leaves_the_risk_being_looked_for(ward):
    """The failure of a misread setting is a ward assessing a risk it did not
    have to — never one that quietly stops looking."""
    from app.models import Setting
    from app.utils import risks

    with ward["app"].app_context():
        Setting.set("risk:kind:fall", "يدوب")
        ward["db"].session.commit()
        assert "fall" in risks.enabled_kinds()


def test_a_risk_that_is_not_one_of_the_three_is_refused(ward):
    """**And refused as its own thing, not as a switched-off one.**

    Two guards stand here and they are not the same rule: «not one of the
    three» is a programming error, «this hospital does not look for it» is a
    policy. A sweep showed the first could be deleted outright with the suite
    still green, because an unknown kind is never in the enabled set either —
    the twin-guard shape this codebase has now met four times. Both stay, and
    the refusal says which one fired.
    """
    from app.models import Patient
    from app.utils import risks

    with ward["app"].app_context():
        child = Patient.query.get(ward["ids"]["child"])
        with pytest.raises(ValueError, match="unknown risk"):
            risks.record(child, "sepsis")
        with pytest.raises(ValueError):
            risks.record(None, "fall")


def test_a_switched_off_risk_is_refused_as_a_switched_off_one(ward):
    """The other half of the pair, asserted at its own level."""
    from app.models import Patient
    from app.utils import risks

    with ward["app"].app_context():
        risks.save_policy("vte", on=False)
        ward["db"].session.commit()
        child = Patient.query.get(ward["ids"]["child"])
        with pytest.raises(ValueError, match="switched off"):
            risks.record(child, "vte")


# ----------------------------------------------------------- the screen ----
def test_the_stay_screen_names_every_risk_and_says_which_are_unassessed(ward):
    admission = _admit(ward, ward["ids"]["child"])

    page = ward["sign_in"]("doc").get(f"/beds/admission/{admission}")
    body = page.get_data(as_text=True)
    for kind in ("fall", "pressure", "vte"):
        assert f'data-risk="{kind}"' in body
    assert 'data-risk-state="none"' in body
    assert 'data-risk-summary="none"' in body


def test_the_screen_shows_the_plan_less_one_as_the_finding(ward):
    admission = _admit(ward, ward["ids"]["child"])
    _write(ward, admission, at_risk="yes")

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{admission}").get_data(as_text=True)
    assert 'data-risk-summary="bare"' in body
    assert 'data-risk-state="bare"' in body


def test_a_finished_stay_is_not_offered_a_bedside_assessment(ward):
    """An assessment written onto a closed stay is a bedside observation of a
    child who went home."""
    from app.models.admission import Admission

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        row = Admission.query.get(admission)
        row.discharged_at = datetime.utcnow()
        row.outcome = "home"
        ward["db"].session.commit()

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{admission}").get_data(as_text=True)
    assert "beds.risk_assessment" not in body
    assert f"/beds/admission/{admission}/risk" not in body


def test_nothing_here_stands_between_a_child_and_a_discharge(ward):
    """It tells, it never blocks — with all three risks unassessed."""
    from app.models.admission import Admission

    admission = _admit(ward, ward["ids"]["child"])
    ward["sign_in"]("doc").post(
        f"/beds/admission/{admission}/discharge",
        data={"outcome": "home"}, follow_redirects=True)
    with ward["app"].app_context():
        assert Admission.query.get(admission).discharged_at is not None


# ----------------------------------------------------------- the policy ----
def test_the_policy_screen_is_the_owners_and_not_a_doctors(ward):
    """Which risks the place's policy covers is configuration. Recording the
    assessment is the ward's, at the bedside, with no capability at all."""
    assert ward["sign_in"]("boss").get("/settings/risks").status_code == 200
    assert ward["sign_in"]("doc").get(
        "/settings/risks", follow_redirects=False).status_code in (302, 403)


def test_the_policy_remembers_the_tool_and_the_frequency(ward):
    from app.utils import risks

    ward["sign_in"]("boss").post("/settings/risks", data={
        "on_fall": "1", "tool_fall": "Humpty Dumpty", "hours_fall": "12",
        "on_pressure": "1", "tool_pressure": "Braden Q", "hours_pressure": "24",
        "hours_vte": "", "tool_vte": ""}, follow_redirects=True)

    with ward["app"].app_context():
        assert risks.tool_name("fall") == "Humpty Dumpty"
        assert risks.interval_hours("pressure") == 24
        assert risks.enabled_kinds() == ("fall", "pressure")


def test_taking_the_frequency_back_out_makes_it_quiet_again(ward):
    """A hospital whose policy no longer names a timeframe is stating that,
    and the screen goes quiet rather than keeping the old number.

    **Asserted on the stored row as well as on the reading.** `interval_hours`
    refuses a zero on the way out too, so a sweep found that the clearing
    could be deleted with the suite still green — and a settings row holding
    "0" is a policy that reads as «reassess every zero hours» to anybody
    looking at the table. Two guards, two assertions.
    """
    from app.models import Setting
    from app.utils import risks

    with ward["app"].app_context():
        risks.save_policy("fall", on=True, hours=6)
        ward["db"].session.commit()
        risks.save_policy("fall", on=True, hours="")
        ward["db"].session.commit()
        assert Setting.get("risk:hours:fall") == ""
        assert risks.interval_hours("fall") is None


@pytest.mark.parametrize("asked", [0, -3, "لا شيء"])
def test_an_interval_of_nothing_is_never_written_as_a_number(ward, asked):
    """Nought especially: an interval of zero hours would make every
    assessment overdue in the second it was written."""
    from app.models import Setting
    from app.utils import risks

    with ward["app"].app_context():
        risks.save_policy("pressure", on=True, hours=asked)
        ward["db"].session.commit()
        assert Setting.get("risk:hours:pressure") == ""


def test_the_ward_prefills_the_tool_the_policy_names(ward):
    """«المهم الطبيب ميكتبش كتير» — nobody types the name of their own
    hospital's tool twice."""
    from app.utils import risks

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        risks.save_policy("fall", on=True, tool="Humpty Dumpty")
        ward["db"].session.commit()

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{admission}").get_data(as_text=True)
    assert "Humpty Dumpty" in body


def test_the_policy_screen_is_reachable_from_settings(ward):
    """Six times in this project something was built and nothing led to it."""
    body = ward["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "/settings/risks" in body


def test_a_clinic_with_no_ward_is_not_offered_a_ward_policy(ward):
    """A clinic with no beds would be setting a policy for a screen it can
    never open."""
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()
    body = ward["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "/settings/risks" not in body


def test_the_ward_door_is_shut_when_the_module_is_off(ward):
    from app.models import Setting

    admission = _admit(ward, ward["ids"]["child"])
    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()
    page = ward["sign_in"]("doc").post(
        f"/beds/admission/{admission}/risk", data={"kind": "fall"})
    assert page.status_code == 404


# ------------------------------------------------------------ the words ----
def test_every_risk_word_is_written_in_both_languages(ward):
    """No screen in this program shows a raw key."""
    from app.i18n import _load_translations, _lookup

    tables = _load_translations()
    keys = ["title", "policy_title", "all_done", "n_bare", "n_unassessed",
            "overdue", "every_n", "tool", "level", "at_risk", "plan",
            "general_measures", "family_told", "record", "saved", "not_saved",
            "yes", "no", "unsaid", "hours", "policy_saved"]
    keys += [f"kind_{k}" for k in ("fall", "pressure", "vte")]
    keys += [f"state_{s}" for s in ("none", "unsaid", "clear", "bare",
                                    "planned")]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"risks.{key}"), f"{lang}:{key}"
