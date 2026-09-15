"""الشاشات اللي القرّاء كانوا مستنينها.

`test_every_door_leads_somewhere` بيقول إن الباب موجود. الملف ده بيقول إن
**اللي وراه صح**: إن اللوحة بتوري اللي المفروض توريه، وما بتوريش حاجة مش
بتاعتها، وإن العدد اللي عليها هو نفس العدد اللي على شاشة الإقامة.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        for module in ("beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        unit = Unit(name="الداخلي", kind="ward")
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        for order, name in enumerate(("د١", "د٢")):
            clinic["db"].session.add(
                Bed(space_id=space.id, name=name, sort_order=order))
        other = Patient(patient_number="WB-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=500))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
        clinic["ids"]["other_child"] = other.id
    return clinic


def _admit(clinic, patient_id=None, bed="د١"):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id or clinic["ids"]["child"]),
                          Bed.query.get(clinic["beds"][bed]),
                          when=datetime.utcnow() - timedelta(hours=4))
        clinic["db"].session.commit()
        return row.id


def _blood(clinic, stay, urgency="routine", hang=True):
    clinic["sign_in"]("doc").post(
        f"/beds/admission/{stay}/blood",
        data={"product": "prbc", "indication": "هيموجلوبين ٥",
              "urgency": urgency}, follow_redirects=True)
    from app.models import BloodRequest

    with clinic["app"].app_context():
        req = (BloodRequest.query.filter_by(admission_id=stay)
               .order_by(BloodRequest.id.desc()).first())
        rid = req.id
    if hang:
        clinic["sign_in"]("doc").post(f"/beds/blood/{rid}/hang",
                                      data={"bag_checked": "yes"},
                                      follow_redirects=True)
    return rid


# ------------------------------------------------------ the ward's board ----
def test_a_bag_nobody_is_watching_reaches_the_board(ward):
    """The reader existed and no screen called it. This is the screen."""
    stay = _admit(ward)
    _blood(ward, stay)

    page = ward["sign_in"]("doc").get("/beds/watch")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f'data-watch-stay="{stay}"' in body
    assert 'data-watch-bags="1"' in body


def test_an_unassessed_risk_reaches_the_board(ward):
    stay = _admit(ward)

    body = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)
    assert f'data-watch-stay="{stay}"' in body
    for kind in ("fall", "pressure", "vte"):
        assert f'data-watch-risk="{kind}"' in body


def test_an_emergency_request_nobody_has_issued_reaches_the_board(ward):
    stay = _admit(ward)
    _blood(ward, stay, urgency="emergency", hang=False)

    body = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)
    assert "data-watch-emergencies" in body
    assert "هيموجلوبين ٥" in body


def test_an_emergency_already_given_leaves_the_board(ward):
    """A request with blood hung against it is handled. Leaving it on a
    chasing list is how a chasing list stops being read."""
    stay = _admit(ward)
    _blood(ward, stay, urgency="emergency", hang=True)

    body = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)
    assert "data-watch-emergencies" not in body


def test_a_discharged_stay_is_not_on_the_board(ward):
    """«محتاج متابعة دلوقتي» is a question about children who are here."""
    from app.models.admission import Admission

    stay = _admit(ward)
    _blood(ward, stay)
    with ward["app"].app_context():
        Admission.query.get(stay).discharged_at = datetime.utcnow()
        ward["db"].session.commit()

    body = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)
    assert f'data-watch-stay="{stay}"' not in body


def test_a_watched_bag_with_assessed_risks_is_not_on_the_board(ward):
    """And the board says so in words rather than drawing an empty table — a
    blank screen reads as broken, which is how somebody stops opening it."""
    from app.models import Transfusion
    from app.utils import risks

    stay = _admit(ward)
    _blood(ward, stay)
    with ward["app"].app_context():
        bag = Transfusion.query.one().id
        for kind in ("fall", "pressure", "vte"):
            risks.save_policy(kind, on=False)
        ward["db"].session.commit()
    ward["sign_in"]("doc").post(f"/beds/blood/bag/{bag}/watch",
                                data={"pulse_bpm": "120"},
                                follow_redirects=True)

    body = ward["sign_in"]("doc").get("/beds/watch").get_data(as_text=True)
    assert f'data-watch-stay="{stay}"' not in body
    assert "data-watch-board" in body


def test_the_board_and_the_stay_screen_count_the_same_bags(ward):
    """Both read `blood.unwatched`. The count was once worked out again in
    Jinja on the stay screen, which is two spellings of one rule — the shape a
    sweep caught in `followup` and the shape that lets a screen disagree with
    its own reader."""
    stay = _admit(ward)
    _blood(ward, stay)

    client = ward["sign_in"]("doc")
    board = client.get("/beds/watch").get_data(as_text=True)
    screen = client.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-watch-bags="1"' in board
    assert 'data-blood-summary="unwatched"' in screen


def test_the_board_is_shut_when_the_ward_is_off(ward):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()
    assert ward["sign_in"]("doc").get("/beds/watch").status_code == 404


# -------------------------------------------- the clinic's overdue goals ----
def test_a_goal_past_its_date_reaches_its_own_screen(ward):
    """ICD.15 (هـ) asks for outcomes *with timeframes*. A timeframe nothing
    ever looks at is a date in a box — and this reader had no screen."""
    from app.utils.clock import local_today

    child = ward["ids"]["child"]
    ward["sign_in"]("doc").post(
        f"/patients/{child}/care-plan/goal",
        data={"need": "يمشي من غير مساعدة",
              "by_when": (local_today() - timedelta(days=4)).isoformat()},
        follow_redirects=True)

    page = ward["sign_in"]("doc").get("/patients/care-plans")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    # `data-overdue-goal="` with the equals: the bare prefix also matches the
    # container's own `data-overdue-goals`, which is on the page either way —
    # a needle that can never be absent tests nothing.
    assert 'data-overdue-goal="' in body
    assert "يمشي من غير مساعدة" in body


def test_a_goal_that_was_met_is_not_chased(ward):
    from app.models import CarePlanGoal
    from app.utils.clock import local_today

    child = ward["ids"]["child"]
    ward["sign_in"]("doc").post(
        f"/patients/{child}/care-plan/goal",
        data={"need": "يمشي",
              "by_when": (local_today() - timedelta(days=4)).isoformat()},
        follow_redirects=True)
    with ward["app"].app_context():
        goal = CarePlanGoal.query.one().id
    ward["sign_in"]("doc").post(f"/patients/care-plan/goal/{goal}/progress",
                                data={"progress": "met"}, follow_redirects=True)

    body = ward["sign_in"]("doc").get(
        "/patients/care-plans").get_data(as_text=True)
    assert 'data-overdue-goal="' not in body
    # And it says so in words rather than drawing an empty table.
    assert "data-overdue-goals" in body


def test_the_goals_screen_is_the_clinical_ones(ward):
    """A plan of care is a clinical record, so the desk does not read it."""
    assert ward["sign_in"]("doc").get(
        "/patients/care-plans").status_code == 200
    assert ward["sign_in"]("desk").get(
        "/patients/care-plans", follow_redirects=False).status_code in (302, 403)


# ------------------------------------------------ the child's own record ----
def test_the_file_carries_this_childs_blood_across_stays(ward):
    """The stay screen shows one admission's. A transfusion six months ago is
    exactly what a doctor seeing this child again needs to find — the same gap
    the labs tab and the stays tab were built for."""
    stay = _admit(ward)
    _blood(ward, stay)

    body = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert "data-blood-history" in body
    assert 'data-tab="blood"' in body
    assert "هيموجلوبين ٥" in body


def test_another_childs_blood_is_not_on_this_file(ward):
    _admit(ward, bed="د١")
    theirs = _admit(ward, patient_id=ward["ids"]["other_child"], bed="د٢")
    _blood(ward, theirs)

    body = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert "data-blood-history" not in body


def test_a_file_with_no_blood_carries_no_blood_tab(ward):
    """A tab labelled «الدم» on the file of a child who never had any is
    furniture — the rule the stays and operations tabs already follow."""
    body = ward["sign_in"]("doc").get(
        f"/patients/{ward['ids']['child']}").get_data(as_text=True)
    assert 'data-tab="blood"' not in body


def test_a_clinic_with_no_ward_pays_nothing_for_the_blood_history(ward):
    """The reader joins a table a clinic with no beds can never have a row in
    — the third time a module guard has been the fix for exactly this."""
    from app.blueprints.patients.routes import _blood_history
    from app.models import Setting
    from app.utils.facility import module_enabled

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()
        assert not module_enabled("beds")
        assert _blood_history(ward["ids"]["child"]) == []


# ------------------------------------------------ the setting that had none ----
def test_the_monitoring_interval_can_be_set_from_a_screen(ward):
    """It was read by the code and settable only by editing the database — a
    policy the standard asks the hospital for that the hospital could not
    state."""
    from app.utils import blood

    ward["sign_in"]("boss").post("/settings/risks", data={
        "on_fall": "1", "hours_fall": "", "tool_fall": "",
        "on_pressure": "1", "hours_pressure": "", "tool_pressure": "",
        "on_vte": "1", "hours_vte": "", "tool_vte": "",
        "blood_watch_minutes": "15"}, follow_redirects=True)

    with ward["app"].app_context():
        assert blood.interval_minutes() == 15


def test_taking_the_interval_back_out_makes_it_quiet_again(ward):
    from app.models import Setting
    from app.utils import blood

    with ward["app"].app_context():
        Setting.set(blood.INTERVAL_SETTING, "15")
        ward["db"].session.commit()
    ward["sign_in"]("boss").post("/settings/risks", data={
        "on_fall": "1", "on_pressure": "1", "on_vte": "1",
        "blood_watch_minutes": ""}, follow_redirects=True)

    with ward["app"].app_context():
        assert Setting.get(blood.INTERVAL_SETTING) == ""
        assert blood.interval_minutes() is None


def test_the_interval_screen_shows_what_is_stored(ward):
    from app.models import Setting
    from app.utils import blood

    with ward["app"].app_context():
        Setting.set(blood.INTERVAL_SETTING, "30")
        ward["db"].session.commit()

    body = ward["sign_in"]("boss").get(
        "/settings/risks").get_data(as_text=True)
    assert "data-blood-watch-policy" in body
    assert 'value="30"' in body
