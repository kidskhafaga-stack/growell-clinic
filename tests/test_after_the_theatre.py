"""After the operation: the plan (SAS.12), and the recovery record (SAS.20).

**SAS.12** — *"Postoperative care plan is determined and recorded before
patient transfer."* Eight elements by name, written by the surgeon before the
child leaves the room, and updated as the child changes — every update a
version, so the plan in force at two o'clock can still be read at four.

**SAS.20** — the recovery record after an anaesthetic. The sedation record
already carried most of its eleven items; three were missing because the
columns that existed describe the theatre — medicines, fluids and blood given
**in recovery** — and (h), the child's condition on leaving *"according to
defined criteria"*, had no criteria for it to be judged by. The criteria are
the hospital's; the program chooses no scale.
"""
from datetime import datetime, timedelta

import pytest


@pytest.fixture()
def suite(clinic):
    """A room, a surgeon and a second doctor, two procedures, one child."""
    from app.models import Service, Setting, Theatre, User

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:theatres", "1")
        Setting.set("mod_enabled:beds", "1")
        tonsils = Service(name="استئصال لوز", code="SVC-T", price=3000,
                          category="procedure", is_active=True)
        circ = Service(name="طهارة", code="SVC-C", price=900,
                       category="procedure", is_active=True)
        surgeon = User(username="surg", full_name="د. جرّاح", role="doctor",
                       is_active=True)
        surgeon.set_password("secret")
        registrar = User(username="reg", full_name="د. مقيم", role="doctor",
                         is_active=True)
        registrar.set_password("secret")
        room = Theatre(name="غرفة ١", is_active=True)
        db.session.add_all([tonsils, circ, surgeon, registrar, room])
        db.session.commit()
        clinic["ids"].update(tonsils=tonsils.id, circ=circ.id,
                             surgeon=surgeon.id, registrar=registrar.id,
                             room=room.id)
    return clinic


def _op(suite, service="tonsils", status="done", recovery_at=None):
    from app.models import Operation
    from app.utils.clock import local_today

    with suite["app"].app_context():
        row = Operation(patient_id=suite["ids"]["child"],
                        theatre_id=suite["ids"]["room"], procedure="عملية",
                        status=status, on_date=local_today(),
                        service_id=suite["ids"][service],
                        surgeon_id=suite["ids"]["surgeon"],
                        recovery_at=recovery_at)
        suite["db"].session.add(row)
        suite["db"].session.commit()
        return row.id


FULL = {"level": "ward", "position": "نص قاعد", "activity": "في السرير",
        "monitoring": "العلامات كل ساعة", "diet": "سوايل بعد ٤ ساعات",
        "medications": "باراسيتامول", "fluids": "محلول صيانة",
        "investigations": "صورة دم الصبح"}


def _write(suite, op_id, who="surgeon", at=None, **fields):
    from app.models import Operation, User
    from app.utils import postop_plan

    with suite["app"].app_context():
        db = suite["db"]
        op = db.session.get(Operation, op_id)
        user = db.session.get(User, suite["ids"][who])
        plan = postop_plan.write(op, user=user, at=at, **fields)
        db.session.commit()
        return plan.id


def _ask(suite, fn, op_id):
    from app.models import Operation
    from app.utils import postop_plan

    with suite["app"].app_context():
        return getattr(postop_plan, fn)(
            suite["db"].session.get(Operation, op_id))


# ======================================================= SAS.12 ========
def test_a_case_with_no_plan_says_so(suite):
    op = _op(suite)
    assert _ask(suite, "state", op) == "none"
    assert len(_ask(suite, "missing", op)) == 8


def test_all_eight_make_it_complete(suite):
    op = _op(suite)
    _write(suite, op, **FULL)
    assert _ask(suite, "state", op) == "complete"
    assert _ask(suite, "missing", op) == []


def test_a_forgotten_element_is_named(suite):
    """EOC 2 — *based on identified needs*: a plan without the diet says so."""
    op = _op(suite)
    _write(suite, op, **dict(FULL, diet="  "))
    assert _ask(suite, "state", op) == "short"
    assert _ask(suite, "missing", op) == ["diet"]


def test_an_unknown_level_is_refused(suite):
    from app.models import PostOpPlan

    op = _op(suite)
    boss = suite["sign_in"]("boss")
    boss.post(f"/theatres/operation/{op}/postop", data=dict(FULL, level="spa"))
    with suite["app"].app_context():
        assert PostOpPlan.query.count() == 0


def test_a_cancelled_case_takes_no_plan(suite):
    op = _op(suite, status="cancelled")
    with pytest.raises(ValueError):
        _write(suite, op, **FULL)


# ------------------------------------------------------------ versions ----
def test_an_update_is_a_new_version_and_the_old_one_stays(suite):
    """EOC 4 — updated as the child changes. The plan the recovery nurse
    followed before the update must still be readable after it."""
    op = _op(suite)
    first = _write(suite, op, **FULL)
    second = _write(suite, op, **dict(FULL, level="icu"))
    assert first != second
    with suite["app"].app_context():
        from app.models import Operation
        from app.utils import postop_plan

        row = suite["db"].session.get(Operation, op)
        versions = postop_plan.history(row)
        assert [v.level for v in versions] == ["ward", "icu"]
        assert postop_plan.current(row).level == "icu"


def test_saving_the_same_plan_twice_is_not_a_version(suite):
    op = _op(suite)
    first = _write(suite, op, **FULL)
    again = _write(suite, op, **FULL)
    assert first == again
    with suite["app"].app_context():
        from app.models import PostOpPlan

        assert PostOpPlan.query.count() == 1


# --------------------------------------------------------------- timing ----
def test_a_plan_written_after_leaving_the_room_is_late(suite):
    """EOC 3 names the event — *before leaving the procedure room* — and the
    program compares against the moment it already stamps."""
    left = datetime.utcnow() - timedelta(hours=2)
    op = _op(suite, recovery_at=left)
    _write(suite, op, at=left + timedelta(minutes=30), **FULL)
    assert _ask(suite, "late", op) is True


def test_a_plan_written_in_the_room_is_not(suite):
    left = datetime.utcnow() - timedelta(hours=2)
    op = _op(suite, recovery_at=left)
    _write(suite, op, at=left - timedelta(minutes=5), **FULL)
    assert _ask(suite, "late", op) is False


def test_an_update_on_the_ward_does_not_make_the_plan_late(suite):
    """The first version is what EOC 3 is about. Updating it at midnight is
    EOC 4 working, not a late plan."""
    left = datetime.utcnow() - timedelta(hours=6)
    op = _op(suite, recovery_at=left)
    _write(suite, op, at=left - timedelta(minutes=5), **FULL)
    _write(suite, op, at=left + timedelta(hours=5), **dict(FULL, level="icu"))
    assert _ask(suite, "late", op) is False


def test_a_child_still_in_the_room_is_not_late_yet(suite):
    op = _op(suite, status="in_theatre")
    _write(suite, op, **FULL)
    assert _ask(suite, "late", op) is None


# ------------------------------------------------------------ who wrote ----
def test_written_by_someone_else_is_said_not_refused(suite):
    """EOC 1 — *developed by the performing physician*. A registrar writing
    it at the surgeon's word is how a theatre runs; the screen says whose
    words these are."""
    op = _op(suite)
    _write(suite, op, who="registrar", **FULL)
    assert _ask(suite, "by_surgeon", op) is False
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{op}").get_data(as_text=True)
    assert "data-postop-not-surgeon" in page


def test_the_surgeons_own_plan_is_not_flagged(suite):
    op = _op(suite)
    _write(suite, op, **FULL)
    assert _ask(suite, "by_surgeon", op) is True
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{op}").get_data(as_text=True)
    assert "data-postop-not-surgeon" not in page


# ---------------------------------------------------- typing it once ----
def test_the_form_starts_from_this_surgeons_last_plan_for_the_procedure(suite):
    """«الطبيب ميكتبش كتير» — the second tonsillectomy's plan starts where
    the first one ended. Said on screen, and nothing saved until pressed."""
    from app.models import PostOpPlan

    earlier = _op(suite)
    _write(suite, earlier, **FULL)
    today = _op(suite)
    values, source = _ask(suite, "starting_point", today)
    assert source == "previous"
    assert values["diet"] == FULL["diet"]
    page = suite["sign_in"]("boss").get(
        f"/theatres/operation/{today}").get_data(as_text=True)
    assert "data-postop-from-previous" in page
    assert FULL["monitoring"] in page
    with suite["app"].app_context():
        assert PostOpPlan.query.filter_by(operation_id=today).count() == 0


def test_another_procedure_is_not_a_starting_point(suite):
    earlier = _op(suite, service="circ")
    _write(suite, earlier, **FULL)
    values, source = _ask(suite, "starting_point", _op(suite))
    assert source is None and values == {}


def test_another_doctors_words_are_not_a_starting_point(suite):
    """Their habits are not this surgeon's."""
    earlier = _op(suite)
    _write(suite, earlier, who="registrar", **FULL)
    values, source = _ask(suite, "starting_point", _op(suite))
    assert source is None


# ---------------------------------------------------------- on screen ----
def test_the_recovery_board_names_a_child_with_no_plan(suite):
    left = datetime.utcnow() - timedelta(minutes=20)
    op = _op(suite, recovery_at=left)
    board = suite["sign_in"]("boss").get("/theatres/recovery").get_data(as_text=True)
    assert f'data-postop-missing="{op}"' in board
    _write(suite, op, **FULL)
    board = suite["sign_in"]("boss").get("/theatres/recovery").get_data(as_text=True)
    assert f'data-postop-missing="{op}"' not in board
    assert f'data-postop-short="{op}"' not in board


def test_saving_from_the_screen_keeps_who(suite):
    from app.models import PostOpPlan

    op = _op(suite)
    reply = suite["sign_in"]("surg").post(
        f"/theatres/operation/{op}/postop", data=FULL, follow_redirects=True)
    assert reply.status_code == 200
    page = reply.get_data(as_text=True)
    assert 'data-postop-state="complete"' in page
    with suite["app"].app_context():
        row = PostOpPlan.query.one()
        assert row.by_id == suite["ids"]["surgeon"]


def test_the_queue_of_finished_cases_with_no_plan(suite):
    from app.utils import postop_plan

    bare = _op(suite)
    planned = _op(suite)
    _write(suite, planned, **FULL)
    _op(suite, status="in_theatre")
    with suite["app"].app_context():
        assert [o.id for o in postop_plan.unplanned()] == [bare]


def test_the_board_asks_once_for_every_plan(suite):
    from sqlalchemy import event

    from app.utils import postop_plan

    ops = [_op(suite) for _ in range(6)]
    for op in ops[:3]:
        _write(suite, op, **FULL)
    with suite["app"].app_context():
        engine = suite["db"].engine
        seen = []

        def count(*_a, **_k):
            seen.append(1)

        event.listen(engine, "before_cursor_execute", count)
        try:
            states = postop_plan.planned_ids(ops)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    assert len(seen) == 1
    assert set(states) == set(ops[:3])


# ======================================================= SAS.20 ========
def _episode(suite, kind="anaesthesia"):
    """An episode that has left theatre for recovery, with a reading."""
    from app.models import Observation, Patient, User
    from app.utils import sedation as sed

    with suite["app"].app_context():
        db = suite["db"]
        child = db.session.get(Patient, suite["ids"]["child"])
        doc = db.session.get(User, suite["ids"]["doctor"])
        row = sed.start(child, kind, user=doc)
        db.session.flush()
        db.session.add(Observation(patient_id=child.id, sedation_id=row.id,
                                   taken_at=datetime.utcnow(), spo2=98))
        sed.describe(row, technique="كلي", score="3", drugs="بروبوفول",
                     blood_given="لا", fluids_in_ml=100,
                     unusual_event="مفيش")
        sed.leave_theatre(row, "recovery", condition="مستقر", user=doc)
        db.session.commit()
        return row.id


def _missing(suite, rid):
    from app.models import SedationRecord
    from app.utils import sedation as sed

    with suite["app"].app_context():
        return sed.missing(suite["db"].session.get(SedationRecord, rid))


def test_recovery_after_an_anaesthetic_asks_what_was_given_there(suite):
    """(d), (e), (f) — in recovery, not in theatre. The theatre's columns are
    already filled here, and that must not answer for the recovery room."""
    gaps = _missing(suite, _episode(suite))
    assert {"recovery_drugs", "recovery_fluids", "recovery_blood"} <= set(gaps)


def test_recovery_after_sedation_does_not(suite):
    """SAS.24 does not list them; the list changes with the kind."""
    gaps = _missing(suite, _episode(suite, kind="sedation"))
    assert not {"recovery_drugs", "recovery_fluids",
                "recovery_blood"} & set(gaps)


def test_writing_them_closes_the_gaps(suite):
    rid = _episode(suite)
    boss = suite["sign_in"]("boss")
    boss.post(f"/theatres/sedation/{rid}/describe",
              data={"recovery_drugs": "مورفين ٠٫١ مجم/كجم وريد ١٤:١٠",
                    "recovery_fluids_in_ml": "50",
                    "recovery_blood": "لا"})
    gaps = _missing(suite, rid)
    assert not {"recovery_drugs", "recovery_fluids",
                "recovery_blood"} & set(gaps)


def test_a_negative_volume_is_not_a_measurement(suite):
    from app.models import SedationRecord
    from app.utils import sedation as sed

    rid = _episode(suite)
    with suite["app"].app_context():
        row = suite["db"].session.get(SedationRecord, rid)
        sed.describe(row, recovery_fluids_in_ml=-50)
        suite["db"].session.commit()
        assert row.recovery_fluids_in_ml is None


def test_the_recovery_board_shows_the_recovery_boxes(suite):
    rid = _episode(suite)
    board = suite["sign_in"]("boss").get("/theatres/sedation").get_data(as_text=True)
    assert f'data-recovery-given="{rid}"' in board


# ------------------------------------------------------------ criteria ----
def test_without_criteria_the_screen_says_so_once(suite):
    """No scale is chosen for the hospital. Until it writes its own, the
    board says so at the top — not on every child, because the gap is the
    clinic's, not the child's."""
    rid = _episode(suite)
    board = suite["sign_in"]("boss").get("/theatres/sedation").get_data(as_text=True)
    assert "data-recovery-criteria-unset" in board
    assert "data-criteria-met" not in board
    assert "recovery_criteria" not in _missing(suite, rid)


def test_without_criteria_nobody_is_asked_the_question_on_leaving(suite):
    """No criteria, no question — even after the child has gone. Otherwise
    every record in a clinic that has not written its criteria would read
    as short, and a colour that is always on teaches people to ignore it."""
    from app.models import SedationRecord, User
    from app.utils import sedation as sed

    rid = _episode(suite)
    with suite["app"].app_context():
        db = suite["db"]
        sed.leave_recovery(db.session.get(SedationRecord, rid), "ward",
                           score="9", event="مفيش",
                           user=db.session.get(User, suite["ids"]["doctor"]))
        db.session.commit()
    assert "recovery_criteria" not in _missing(suite, rid)


def test_the_criteria_are_written_on_the_settings_screen(suite):
    from app.utils import sedation as sed

    boss = suite["sign_in"]("boss")
    boss.post("/settings/risks",
              data={"recovery_criteria": "درجة الإفاقة المعتمدة ٩ أو أكتر"})
    with suite["app"].app_context():
        assert sed.criteria() == "درجة الإفاقة المعتمدة ٩ أو أكتر"
    _episode(suite)
    board = boss.get("/theatres/sedation").get_data(as_text=True)
    assert "data-recovery-criteria" in board
    assert "درجة الإفاقة المعتمدة" in board


def _criteria(suite, text="المعيار"):
    from app.models import Setting
    from app.utils import sedation as sed

    with suite["app"].app_context():
        Setting.set(sed.CRITERIA_SETTING, text)
        suite["db"].session.commit()


def test_with_criteria_leaving_without_an_answer_is_a_gap(suite):
    from app.models import SedationRecord, User
    from app.utils import sedation as sed

    _criteria(suite)
    rid = _episode(suite)
    assert "recovery_criteria" not in _missing(suite, rid), \
        "still in recovery: the leaving question has not come yet"
    with suite["app"].app_context():
        db = suite["db"]
        sed.leave_recovery(db.session.get(SedationRecord, rid), "ward",
                           score="9", event="مفيش",
                           user=db.session.get(User, suite["ids"]["doctor"]))
        db.session.commit()
    assert "recovery_criteria" in _missing(suite, rid)


@pytest.mark.parametrize("said, stored", [("yes", True), ("no", False)])
def test_not_met_is_an_answer(suite, said, stored):
    """A child who did not meet the criteria and went to intensive care has
    an answer on file — and it is not the same as nobody saying."""
    from app.models import SedationRecord

    _criteria(suite)
    rid = _episode(suite)
    suite["sign_in"]("boss").post(
        f"/theatres/sedation/{rid}/leave",
        data={"disposition": "icu", "score": "7", "event": "مفيش",
              "criteria_met": said})
    with suite["app"].app_context():
        row = suite["db"].session.get(SedationRecord, rid)
        assert row.recovery_criteria_met is stored
    assert "recovery_criteria" not in _missing(suite, rid)
