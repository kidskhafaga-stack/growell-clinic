"""Marking the site — GAHAR SAS.05 · GSR.14.

*"The precise site where surgery or invasive procedure shall be performed is
clearly marked by the physician, along with the patient and/or family
involvement."* The hospital's policy has seven parts; the record answers
five of them for each case and the sixth over a period:

(a) the hospital's unified mark · (b) when a mark is needed · (c) marked by
the surgeon who will operate · (d) with the patient and family · (e) the
hospital's exempt procedures · (f) before the child is called to theatre ·
(g) monitoring.

Nothing refuses a marking. What happened is recorded, and what it missed is
named on the case and in the audit.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def case(clinic):
    from app.models import Operation, Service, Setting, Theatre
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        room = Theatre(name="غرفة ١", is_active=True)
        hernia = Service(name="فتق إربي", code="SVC-H", price=4000,
                         category="procedure", is_active=True)
        tonsils = Service(name="استئصال لوز", code="SVC-TN", price=3000,
                          category="procedure", is_active=True)
        db.session.add_all([room, hernia, tonsils])
        db.session.flush()
        op = Operation(patient_id=clinic["ids"]["child"], theatre_id=room.id,
                       procedure="فتق إربي", status="scheduled",
                       on_date=local_today(), service_id=hernia.id,
                       surgeon_id=clinic["ids"]["doctor"])
        db.session.add(op)
        db.session.commit()
        clinic["ids"].update(op=op.id, hernia=hernia.id, tonsils=tonsils.id,
                             room=room.id)
    return clinic


def _op(case, key="op"):
    from app.models import Operation

    return case["db"].session.get(Operation, case["ids"][key])


def _mark(case, who="doctor", side="left", with_whom="mother", unified=True,
          at=None):
    from app.models import User
    from app.utils import theatres as theatre

    with case["app"].app_context():
        user = case["db"].session.get(User, case["ids"][who])
        theatre.mark_site(_op(case), side, user, with_whom=with_whom,
                          unified=unified, at=at)
        case["db"].session.commit()


def _problems(case):
    from app.utils import site_marking

    with case["app"].app_context():
        return site_marking.problems(_op(case))


def _call(case, at):
    with case["app"].app_context():
        _op(case).called_at = at
        case["db"].session.commit()


# ----------------------------------------------------------------- (b) ----
def test_a_case_nobody_has_looked_at_needs_a_mark(case):
    """The case that must not pass as not needing one."""
    assert _problems(case) == ["marked", "unified", "by_surgeon",
                               "with_family"]


def test_no_side_needs_no_mark(case):
    _mark(case, side="not_applicable", unified=None, with_whom=None)
    assert _problems(case) == []


# ------------------------------------------------------ the whole thing ----
def test_marked_right_misses_nothing(case):
    _mark(case, at=datetime.utcnow() - timedelta(hours=2))
    _call(case, datetime.utcnow() - timedelta(hours=1))
    assert _problems(case) == []


# ----------------------------------------------------------------- (c) ----
def test_marked_by_someone_other_than_the_surgeon_is_named_not_refused(case):
    from app.utils import theatres as theatre

    _mark(case, who="admin")
    with case["app"].app_context():
        assert theatre.site_state(_op(case)) == "marked"
    assert _problems(case) == ["by_surgeon"]


# ----------------------------------------------------------------- (d) ----
@pytest.mark.parametrize("with_whom", ["none_present", None, "neighbour"])
def test_without_the_family_is_named(case, with_whom):
    """``none_present`` is an honest answer and stays visible; an unknown
    word is not kept."""
    _mark(case, with_whom=with_whom)
    assert _problems(case) == ["with_family"]
    with case["app"].app_context():
        assert _op(case).site_with in (None, "none_present")


# ----------------------------------------------------------------- (a) ----
def test_not_the_unified_mark_is_named(case):
    _mark(case, unified=False)
    assert _problems(case) == ["unified"]


def test_the_box_means_no_only_once_the_hospital_has_a_mark(case):
    """Unticked before the hospital wrote its mark is "nobody could have
    said", not "no"."""
    from app.models import Setting

    boss = case["sign_in"]("doc")
    boss.post(f"/theatres/operation/{case['ids']['op']}/site",
              data={"side": "left", "site_with": "mother"})
    with case["app"].app_context():
        assert _op(case).site_unified is None
        Setting.set("site_mark_style", "حروف الجرّاح بقلم ثابت")
        case["db"].session.commit()
    boss.post(f"/theatres/operation/{case['ids']['op']}/site",
              data={"side": "left", "site_with": "mother"})
    with case["app"].app_context():
        assert _op(case).site_unified is False


# ----------------------------------------------------------------- (f) ----
def test_marked_after_the_call_to_theatre_is_late(case):
    _call(case, datetime.utcnow() - timedelta(hours=2))
    _mark(case, at=datetime.utcnow() - timedelta(hours=1))
    assert _problems(case) == ["in_time"]


def test_called_with_no_mark_at_all_is_late_too(case):
    _call(case, datetime.utcnow() - timedelta(minutes=5))
    assert "in_time" in _problems(case)


def test_not_called_yet_is_not_late_yet(case):
    from app.utils import site_marking

    _mark(case)
    with case["app"].app_context():
        assert site_marking.checks(_op(case))["in_time"] is None
    assert _problems(case) == []


# ----------------------------------------------------------------- (e) ----
def test_an_exempt_procedure_needs_no_mark(case):
    boss = case["sign_in"]("boss")
    boss.post("/theatres/setup/site-marking",
              data={"style": "حروف الجرّاح", "exempt": [str(case["ids"]["hernia"])]})
    assert _problems(case) == []
    page = boss.get(f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert "data-site-exempt" in page


def test_unticking_lifts_the_exemption_and_nothing_else_is_touched(case):
    from app.models import Service

    boss = case["sign_in"]("boss")
    boss.post("/theatres/setup/site-marking",
              data={"exempt": [str(case["ids"]["hernia"])]})
    boss.post("/theatres/setup/site-marking", data={})
    with case["app"].app_context():
        db = case["db"]
        assert db.session.get(Service, case["ids"]["hernia"]).site_mark_exempt is False
        assert db.session.get(Service, case["ids"]["tonsils"]).site_mark_exempt is None


def test_only_an_administrator_writes_the_policy(case):
    from app.models import Service

    case["sign_in"]("doc").post("/theatres/setup/site-marking",
                                data={"exempt": [str(case["ids"]["hernia"])]})
    with case["app"].app_context():
        assert not case["db"].session.get(Service, case["ids"]["hernia"]).site_mark_exempt


# ----------------------------------------------------------------- (g) ----
def test_the_audit_counts_each_check_and_names_the_case(case):
    from app.utils import site_marking
    from app.utils.clock import local_today

    _mark(case, who="admin", with_whom="none_present")
    with case["app"].app_context():
        data = site_marking.report(local_today() - timedelta(days=1),
                                   local_today())
    assert data["needed"] == 1
    assert data["totals"]["by_surgeon"] == {"ok": 0, "no": 1, "open": 0}
    assert data["totals"]["in_time"] == {"ok": 0, "no": 0, "open": 1}
    assert [f["operation"].id for f in data["failing"]] == [case["ids"]["op"]]
    page = case["sign_in"]("boss").get("/theatres/site-marking").get_data(as_text=True)
    assert f'data-failing="{case["ids"]["op"]}"' in page


def test_the_theatre_list_has_a_door_to_the_audit(case):
    page = case["sign_in"]("boss").get("/theatres/").get_data(as_text=True)
    assert "/theatres/site-marking" in page


def test_the_checklist_still_reads_the_marking_as_before(case):
    """An update changes nothing for a running clinic: the sign-in item
    reads "marked" exactly as it did."""
    from app.utils import theatres as theatre

    _mark(case, who="admin", with_whom=None, unified=None)
    with case["app"].app_context():
        assert theatre.site_ok(_op(case)) is True
