"""The anaesthetist's privilege — GAHAR SAS.16, evidence 3.

*"Anesthesia and sedation are administered by qualified physicians
**according to their approved clinical privileges**."*

The surgeon's booking was already read against the surgeon's privileges
(SAS.02 أ). The other doctor in the room was not: whoever was named to give
the anaesthetic was named, and nothing said whether this hospital had
privileged them to give *that* anaesthetic.

The same record and the same rules — judged on the day of the case, warned
about and never refused, accepted only with a reason — with the one
difference the anaesthetist's work makes: the scope is a **kind of
anaesthetic**, because the same hernia is a general anaesthetic in one room
and a caudal in the next.
"""
from datetime import timedelta

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
        db.session.add_all([room, hernia])
        db.session.flush()
        op = Operation(patient_id=clinic["ids"]["child"], theatre_id=room.id,
                       procedure="فتق إربي", status="scheduled",
                       on_date=local_today() + timedelta(days=2),
                       service_id=hernia.id,
                       surgeon_id=clinic["ids"]["admin"],
                       anaesthetist_id=clinic["ids"]["doctor"],
                       anaesthesia_kind="general")
        db.session.add(op)
        db.session.commit()
        clinic["ids"].update(op=op.id, hernia=hernia.id, room=room.id)
    return clinic


def _op(case):
    from app.models import Operation

    return case["db"].session.get(Operation, case["ids"]["op"])


def _grant(case, who="doctor", **scope):
    from app.models import User
    from app.utils import privileges

    with case["app"].app_context():
        boss = case["db"].session.get(User, case["ids"]["admin"])
        row = privileges.grant(case["ids"][who], user=boss, **scope)
        case["db"].session.commit()
        return row is not None


def _state(case):
    from app.utils import theatres as theatre

    with case["app"].app_context():
        return theatre.anaesthesia_privilege_state(_op(case))


def _set(case, **fields):
    with case["app"].app_context():
        op = _op(case)
        for name, value in fields.items():
            setattr(op, name, value)
        case["db"].session.commit()


# ------------------------------------------------------------ the scope ----
def test_nothing_written_down_is_privileged_for_nothing(case):
    assert _state(case) == "outside"


def test_a_grant_for_the_kind_covers_it(case):
    assert _grant(case, anaesthesia_kind="general")
    assert _state(case) == "ok"


def test_no_kind_covers_another(case):
    """General does not read as sedation. Which kinds a hospital folds into
    which is its committee's call, not the program's."""
    _grant(case, anaesthesia_kind="general")
    _set(case, anaesthesia_kind="sedation")
    assert _state(case) == "outside"


def test_a_procedure_privilege_is_not_an_anaesthetic_one(case):
    """The surgeon's scope and the anaesthetist's do not stand in for each
    other, in either direction."""
    from app.models import Service
    from app.utils import privileges

    _grant(case, service_id=case["ids"]["hernia"])
    assert _state(case) == "outside"
    _grant(case, who="admin", anaesthesia_kind="general")
    with case["app"].app_context():
        hernia = case["db"].session.get(Service, case["ids"]["hernia"])
        assert privileges.state(case["ids"]["admin"], hernia) == "outside"


@pytest.mark.parametrize("scope", [
    {"anaesthesia_kind": "local"},          # the surgeon's, not a privilege
    {"anaesthesia_kind": "light"},          # a word nothing is booked as
    {"anaesthesia_kind": "general", "service_type": "procedure"},
    {"anaesthesia_kind": "general", "service_id": 1},
])
def test_refused_scopes(case, scope):
    from app.utils import privileges

    assert not _grant(case, **scope)
    with case["app"].app_context():
        assert privileges.all_for(case["ids"]["doctor"]) == []


def test_supervised_is_kept_apart(case):
    _grant(case, anaesthesia_kind="general",
           supervisor_id=case["ids"]["admin"], supervision="حضور كامل")
    assert _state(case) == "supervised"
    _grant(case, anaesthesia_kind="general")
    assert _state(case) == "ok"


# -------------------------------------------------------- when it asks ----
@pytest.mark.parametrize("kind", ["local", None])
def test_local_or_unchosen_needs_no_check(case, kind):
    _set(case, anaesthesia_kind=kind)
    assert _state(case) == "not_needed"


def test_nobody_named_is_the_missing_person_not_a_privilege(case):
    _set(case, anaesthetist_id=None)
    assert _state(case) == "unknown"


# ------------------------------------------------------------- the day ----
def test_judged_on_the_day_of_the_operation(case):
    """A privilege granted to start after the case does not cover it; one
    that lapses after it does."""
    from app.utils.clock import local_today

    _grant(case, anaesthesia_kind="general",
           valid_until=local_today() + timedelta(days=1))
    assert _state(case) == "outside"      # stands today, not on the day
    _grant(case, anaesthesia_kind="general",
           valid_from=local_today() + timedelta(days=2))
    assert _state(case) == "ok"           # not yet today, but on the day


def test_the_booking_forms_map_is_judged_on_its_day_too(case):
    from app.utils import privileges
    from app.utils.clock import local_today

    _grant(case, anaesthesia_kind="general",
           valid_from=local_today() + timedelta(days=5))
    _grant(case, anaesthesia_kind="sedation",
           supervisor_id=case["ids"]["admin"])
    with case["app"].app_context():
        got = privileges.anaesthesia_map(
            [case["ids"]["doctor"]], ("general", "sedation", "regional"),
            local_today())[case["ids"]["doctor"]]
    assert got == {"general": "outside", "sedation": "supervised",
                   "regional": "outside"}


# ---------------------------------------------------- accepting the gap ----
def test_accepting_needs_a_reason_and_keeps_the_gap_visible(case):
    doc = case["sign_in"]("doc")
    url = f"/theatres/operation/{case['ids']['op']}/anaesthesia-privilege"
    doc.post(url, data={"reason": "  "})
    assert _state(case) == "outside"
    doc.post(url, data={"reason": "الأخصائي الوحيد المتاح الليلة"})
    assert _state(case) == "acknowledged"
    with case["app"].app_context():
        op = _op(case)
        assert op.anaesthesia_ack_by == case["ids"]["doctor"]
        # The surgeon's gap is a separate decision and is untouched.
        assert op.privilege_ack_at is None


def test_an_acceptance_never_hides_a_privilege_granted_after_it(case):
    case["sign_in"]("doc").post(
        f"/theatres/operation/{case['ids']['op']}/anaesthesia-privilege",
        data={"reason": "الوحيد المتاح"})
    _grant(case, anaesthesia_kind="general")
    assert _state(case) == "ok"


def test_nothing_to_accept_writes_nothing(case):
    _grant(case, anaesthesia_kind="general")
    case["sign_in"]("doc").post(
        f"/theatres/operation/{case['ids']['op']}/anaesthesia-privilege",
        data={"reason": "احتياطي"})
    with case["app"].app_context():
        assert _op(case).anaesthesia_ack_at is None


def test_another_anaesthetist_is_another_gap(case):
    """An acceptance was of the doctor who was named. Swapping them must not
    let a second gap pass under the first one's reason."""
    case["sign_in"]("doc").post(
        f"/theatres/operation/{case['ids']['op']}/anaesthesia-privilege",
        data={"reason": "الوحيد المتاح"})
    case["sign_in"]("boss").post(
        f"/theatres/operation/{case['ids']['op']}/edit",
        data={"procedure": "فتق إربي", "service_id": case["ids"]["hernia"],
              "surgeon_id": case["ids"]["admin"],
              "anaesthetist_id": case["ids"]["admin"]})
    with case["app"].app_context():
        assert _op(case).anaesthetist_id == case["ids"]["admin"]
        assert _op(case).anaesthesia_ack_reason is None
    assert _state(case) == "outside"


def test_saving_the_case_unchanged_keeps_the_acceptance(case):
    case["sign_in"]("doc").post(
        f"/theatres/operation/{case['ids']['op']}/anaesthesia-privilege",
        data={"reason": "الوحيد المتاح"})
    case["sign_in"]("boss").post(
        f"/theatres/operation/{case['ids']['op']}/edit",
        data={"procedure": "فتق إربي", "service_id": case["ids"]["hernia"],
              "surgeon_id": case["ids"]["admin"],
              "anaesthetist_id": case["ids"]["doctor"]})
    assert _state(case) == "acknowledged"


# ----------------------------------------------------------- the screens ----
def test_the_privileges_screen_grants_a_kind_of_anaesthetic(case):
    boss = case["sign_in"]("boss")
    boss.post("/theatres/privileges",
              data={"doctor_id": case["ids"]["doctor"], "scope": "anaesthesia",
                    "anaesthesia_kind": "general", "kind": "standard",
                    # The other scopes' boxes are posted too, as a browser
                    # posts every select — the chosen scope decides.
                    "service_type": "procedure",
                    "service_id": case["ids"]["hernia"]})
    assert _state(case) == "ok"
    page = boss.get(f"/theatres/privileges?doctor={case['ids']['doctor']}"
                    ).get_data(as_text=True)
    assert 'data-gas-scope="general"' in page


def test_the_other_scopes_ignore_the_anaesthesia_box(case):
    """A browser posts every select. A type grant must not arrive carrying
    the anaesthesia box's value and be refused as two scopes."""
    from app.utils import privileges

    case["sign_in"]("boss").post(
        "/theatres/privileges",
        data={"doctor_id": case["ids"]["doctor"], "scope": "type",
              "service_type": "procedure", "anaesthesia_kind": "general",
              "kind": "standard"})
    with case["app"].app_context():
        rows = privileges.all_for(case["ids"]["doctor"])
        assert [(r.service_type, r.anaesthesia_kind) for r in rows] == [
            ("procedure", None)]


def test_the_case_page_names_the_gap_and_takes_a_reason(case):
    page = case["sign_in"]("boss").get(
        f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert 'data-gas-privilege="outside"' in page
    assert "/anaesthesia-privilege" in page


def test_the_case_page_is_quiet_for_a_local_case(case):
    _set(case, anaesthesia_kind="local")
    page = case["sign_in"]("boss").get(
        f"/theatres/operation/{case['ids']['op']}").get_data(as_text=True)
    assert "data-gas-privilege" not in page


def test_the_list_flags_it_and_the_form_knows_before_booking(case):
    from app.utils.clock import local_today

    day = (local_today() + timedelta(days=2)).isoformat()
    page = case["sign_in"]("boss").get(f"/theatres/?date={day}"
                                       ).get_data(as_text=True)
    assert "data-gas-outside" in page
    assert "data-gas-warning" in page
    assert f'"{case["ids"]["doctor"]}": {{"general": "outside"' in page
    _grant(case, anaesthesia_kind="general")
    page = case["sign_in"]("boss").get(f"/theatres/?date={day}"
                                       ).get_data(as_text=True)
    assert "data-gas-outside" not in page
    assert f'"{case["ids"]["doctor"]}": {{"general": "ok"' in page


def test_the_map_costs_the_same_however_many_doctors(case):
    """Rendered with every booking form, so it must not grow a query per
    doctor per kind."""
    from sqlalchemy import event

    from app.utils import privileges

    def cost(keys):
        seen = []

        def count(*_):
            seen.append(1)

        engine = case["db"].engine
        event.listen(engine, "before_cursor_execute", count)
        try:
            privileges.anaesthesia_map([case["ids"][k] for k in keys],
                                       ("general", "regional", "sedation"))
        finally:
            event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    _grant(case, anaesthesia_kind="general")
    with case["app"].app_context():
        cost(("doctor",))  # the clinic's clock is read once, then cached
        assert cost(("doctor",)) == cost(("doctor", "admin", "desk"))
