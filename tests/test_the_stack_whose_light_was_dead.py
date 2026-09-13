"""The equipment a case needs — there, **and** working.

GAHAR SAS.06 (ب) is five words and both of them matter:

> **b) The availability and functioning of needed equipment.**

and the intent names the moment and the shape:

> *"The hospital is required to ensure the availability and functioning of
> equipment needed for the surgery ... **before calling for the patient**. This
> equipment and tools **could differ according to the type of surgery** ... or
> the use of anesthesia and sedation."*

**Two questions per item, not one.** The stack is in the room but its light is
dead; the ventilator works but is in the other theatre. A single "checked" box
calls both of those ready, and the whole item exists to stop a case being
called for when it is not.

**The program never writes the list.** What a laparoscopic appendicectomy needs
is an operational judgement belonging to whoever runs the theatres. It is
written once against the *service*, because the standard says plainly that it
differs by procedure — and copied onto the case, so editing it next year cannot
rewrite what somebody checked in the room this morning.

**And what this is not.** The medical equipment *management* plan — the
inventory, the preventive maintenance, the calibration schedule "according to
the manufacturer's recommendations", the malfunction history — is a different
standard and a module of its own. An earlier note in this repository described
this item as "an asset register with calibration dates", which is that other
standard's work, not this one's. Nothing here should be read as covering it.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def surgery():
    """A case booked against a procedure that names what it needs."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, Setting, User
        from app.models.theatre import Operation, Theatre
        from app.utils.clock import local_today

        Setting.set("mod_enabled:theatres", "1")
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        room = Theatre(name="غرفة ١", sort_order=1)
        lap = Service(name="استئصال زائدة بالمنظار", category="procedure",
                      price=6000, is_active=True,
                      equipment_list="منظار ٥ مم\nمصدر إضاءة\nجهاز كي")
        # A procedure whose list nobody has written — the ordinary state, and
        # the one a default shipped from the program would quietly fill in.
        plain = Service(name="ختان", category="procedure", price=800,
                        is_active=True)
        db.session.add_all([boss, room, lap, plain])
        db.session.flush()

        kid = Patient(patient_number="P-1", full_name="طفل", gender="male",
                      is_active=True,
                      date_of_birth=local_today() - timedelta(days=1500))
        db.session.add(kid)
        db.session.flush()
        case = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="استئصال زائدة بالمنظار",
                         on_date=local_today(), status="scheduled",
                         service_id=lap.id)
        bare = Operation(patient_id=kid.id, theatre_id=room.id,
                         procedure="ختان", on_date=local_today(),
                         status="scheduled", service_id=plain.id)
        db.session.add_all([case, bare])
        db.session.commit()
        ids = {"boss": boss.id, "case": case.id, "bare": bare.id,
               "lap": lap.id, "kid": kid.id}

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _op(ctx, key="case"):
    from app.models.theatre import Operation
    return ctx["db"].session.get(Operation, ctx["ids"][key])


def _boss(ctx):
    from app.models import User
    return ctx["db"].session.get(User, ctx["ids"]["boss"])


def _items(ctx, key="case"):
    from app.utils import theatres as theatre
    return {r.name: r for r in theatre.equipment_for(_op(ctx, key))}


# ------------------------------------------------------------ the states --
def test_a_case_nobody_has_asked_about(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        assert theatre.equipment_state(_op(surgery)) == "unasked"
        assert theatre.equipment_ready(_op(surgery)) is False


def test_the_room_has_everything_is_a_recorded_answer(surgery):
    """A circumcision needs nothing the room does not always have, and that is
    the usual answer — it has to be sayable, and it is not the same as nobody
    asking."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), False, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "not_needed"
        assert theatre.equipment_ready(_op(surgery)) is True


def test_unasked_and_not_needed_are_not_the_same_state(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        assert theatre.equipment_state(_op(surgery)) == "unasked"
        theatre.set_equipment_needed(_op(surgery), False, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "not_needed"


def test_a_list_nobody_has_been_through_is_neither_ready_nor_short(surgery):
    """**The third state this program keeps having to put back.** Items copied
    onto the case that nobody has looked at yet are not missing and are not
    there — and a boolean would have to call them one or the other."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "checking"
        assert theatre.equipment_ready(_op(surgery)) is False
        assert all(r.state == "unchecked"
                   for r in theatre.equipment_for(_op(surgery)))


def test_saying_yes_with_nothing_named_is_half_an_answer(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery, "bare"), True,
                                     user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery, "bare")) == "none_named"


# ---------------------------------------------- there, and working, apart --
def test_a_thing_that_is_there_and_works_is_ready(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        answers = {r.id: {"present": True, "working": True}
                   for r in theatre.equipment_for(_op(surgery))}
        theatre.check_equipment(_op(surgery), answers, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "ready"
        assert theatre.equipment_ready(_op(surgery)) is True


def test_the_stack_whose_light_is_dead_is_not_ready(surgery):
    """**The case this file is named for.** It is in the room, so "available"
    is yes — and the standard asks two questions, not one."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        answers = {r.id: {"present": True, "working": True} for r in rows}
        answers[rows[1].id] = {"present": True, "working": False}
        theatre.check_equipment(_op(surgery), answers, user=_boss(surgery))
        surgery["db"].session.commit()

        assert theatre.equipment_state(_op(surgery)) == "short"
        assert _items(surgery)["مصدر إضاءة"].state == "broken"
        assert _items(surgery)["مصدر إضاءة"].present is True
        assert _items(surgery)["منظار ٥ مم"].state == "ready"


def test_a_thing_nobody_could_find_is_missing_not_broken(surgery):
    """"Not there" and "here and broken" are two different errands — go and
    find it, or go and get another one. Writing ``working=False`` for a thing
    that is absent sends somebody on the wrong one."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        theatre.check_equipment(
            _op(surgery),
            {rows[0].id: {"present": False, "working": True}},
            user=_boss(surgery))
        surgery["db"].session.commit()

        item = _items(surgery)["منظار ٥ مم"]
        assert item.state == "missing"
        assert item.present is False
        assert item.working is None, "an absent thing was recorded as tested"


def test_the_whole_case_is_short_while_any_one_item_is(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        answers = {r.id: {"present": True, "working": True} for r in rows}
        answers[rows[2].id] = {"present": False}
        theatre.check_equipment(_op(surgery), answers, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "short"


def test_who_checked_and_when_is_recorded(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        theatre.check_equipment(_op(surgery),
                                {rows[0].id: {"present": True, "working": True}},
                                user=_boss(surgery))
        surgery["db"].session.commit()
        assert _op(surgery).equipment_checked_by == surgery["ids"]["boss"]
        assert _op(surgery).equipment_checked_at is not None


# --------------------------------------------------- the list is theirs ----
def test_the_list_comes_from_the_procedure(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        assert theatre.equipment_list_for(_op(surgery)) == \
            ["منظار ٥ مم", "مصدر إضاءة", "جهاز كي"]


def test_a_procedure_with_no_list_gets_no_invented_one(surgery):
    """**The ordinary state, and the one a shipped default would fill in.**
    What a procedure needs in the room is the theatre's judgement; the program
    does not have one."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        assert theatre.equipment_list_for(_op(surgery, "bare")) == []
        theatre.set_equipment_needed(_op(surgery, "bare"), True,
                                     user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.equipment_for(_op(surgery, "bare")) == []


def test_editing_the_procedures_list_does_not_rewrite_a_checked_case(surgery):
    """Copied, not referenced. What was checked in the room this morning is a
    record of that morning."""
    from app.models import Service
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        assert len(theatre.equipment_for(_op(surgery))) == 3

        service = surgery["db"].session.get(Service, surgery["ids"]["lap"])
        service.equipment_list = "حاجة تانية خالص"
        surgery["db"].session.commit()
        names = [r.name for r in theatre.equipment_for(_op(surgery))]
        assert names == ["منظار ٥ مم", "مصدر إضاءة", "جهاز كي"]


def test_opening_it_again_keeps_the_answers(surgery):
    """Stocking the list is idempotent: a case somebody has been through must
    not lose its answers because a screen was opened twice."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        theatre.check_equipment(_op(surgery),
                                {rows[0].id: {"present": True, "working": True}},
                                user=_boss(surgery))
        surgery["db"].session.commit()

        theatre.stock_equipment(_op(surgery))
        surgery["db"].session.commit()
        assert len(theatre.equipment_for(_op(surgery))) == 3
        assert _items(surgery)["منظار ٥ مم"].state == "ready"


def test_a_line_written_twice_is_one_item(surgery):
    from app.models import Service
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        service = surgery["db"].session.get(Service, surgery["ids"]["lap"])
        service.equipment_list = "منظار ٥ مم\n  منظار ٥ مم  \n\nجهاز كي"
        surgery["db"].session.commit()
        assert theatre.equipment_list_for(_op(surgery)) == \
            ["منظار ٥ مم", "جهاز كي"]


def test_something_the_list_does_not_carry_can_be_added(surgery):
    """Most theatres, most days."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        theatre.add_equipment(_op(surgery), "مقص هارمونيك")
        surgery["db"].session.commit()
        assert "مقص هارمونيك" in _items(surgery)


def test_adding_the_same_thing_twice_adds_one(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        theatre.add_equipment(_op(surgery), "مقص هارمونيك")
        surgery["db"].session.commit()
        theatre.add_equipment(_op(surgery), "مقص هارمونيك")
        surgery["db"].session.commit()
        assert len(theatre.equipment_for(_op(surgery))) == 4


def test_a_blank_name_is_refused(surgery):
    """An empty row on a checklist is a line somebody ticks without reading."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        assert theatre.add_equipment(_op(surgery), "   ") is None
        assert theatre.add_equipment(_op(surgery), None) is None
        surgery["db"].session.commit()
        assert len(theatre.equipment_for(_op(surgery))) == 3


def test_a_missing_answer_is_refused(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        assert theatre.set_equipment_needed(_op(surgery), None) is None
        surgery["db"].session.commit()
        assert theatre.equipment_state(_op(surgery)) == "unasked"


# ------------------------------------------------- no checklist item added --
def test_no_checklist_item_was_added(surgery):
    """``missed`` is computed against the **current** item list. And
    ``pulse_oximeter`` is deliberately *not* derived from this: it is one named
    device on the patient, and answering it from a general equipment list would
    have the item say more than its name."""
    from app.models.theatre import CHECK_ITEMS, SIGN_IN, SIGN_OUT, TIME_OUT
    from app.utils import theatres as theatre

    every = set(CHECK_ITEMS[SIGN_IN]) | set(CHECK_ITEMS[TIME_OUT]) \
        | set(CHECK_ITEMS[SIGN_OUT])
    for invented in ("equipment", "equipment_ready", "instruments"):
        assert invented not in every
    assert set(theatre.derived_items()) == {
        "identity", "site_marked", "consent", "anaesthesia_check",
        "imaging_ready"}
    assert "pulse_oximeter" not in theatre.derived_items()


# ---------------------------------------------------------- on the screen --
def test_the_case_screen_lists_what_the_procedure_needs(surgery):
    from app.i18n import t
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()

    html = surgery["sign_in"]().get(
        f"/theatres/operation/{surgery['ids']['case']}").get_data(as_text=True)
    assert "منظار ٥ مم" in html and "مصدر إضاءة" in html
    with surgery["app"].test_request_context("/"):
        assert t("theatre.equipment_checking") in html
        assert t("theatre.equip_working") in html


def test_the_screen_records_what_was_found(surgery):
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        rows = theatre.equipment_for(_op(surgery))
        ids = [r.id for r in rows]

    data = {"needed": "yes"}
    for n, item_id in enumerate(ids):
        data[f"present_{item_id}"] = "yes"
        if n != 1:
            data[f"working_{item_id}"] = "yes"
    data[f"note_{ids[1]}"] = "اللمبة فصلت"
    surgery["sign_in"]().post(
        f"/theatres/operation/{surgery['ids']['case']}/equipment",
        data=data, follow_redirects=True)

    with surgery["app"].app_context():
        assert theatre.equipment_state(_op(surgery)) == "short"
        assert _items(surgery)["مصدر إضاءة"].state == "broken"
        assert _items(surgery)["مصدر إضاءة"].note == "اللمبة فصلت"


def test_the_screen_adds_one_the_list_does_not_carry(surgery):
    surgery["sign_in"]().post(
        f"/theatres/operation/{surgery['ids']['case']}/equipment",
        data={"needed": "yes", "new_item": "مقص هارمونيك"},
        follow_redirects=True)
    with surgery["app"].app_context():
        assert "مقص هارمونيك" in _items(surgery)


def test_the_screen_refuses_a_blank_answer(surgery):
    from app.utils import theatres as theatre

    surgery["sign_in"]().post(
        f"/theatres/operation/{surgery['ids']['case']}/equipment",
        data={}, follow_redirects=True)
    with surgery["app"].app_context():
        assert theatre.equipment_state(_op(surgery)) == "unasked"


def test_an_item_nobody_answered_stays_unchecked(surgery):
    """A form that posts nothing for an item must not write an answer for it:
    "nobody looked" is exactly the state the screen exists to show."""
    from app.utils import theatres as theatre

    with surgery["app"].app_context():
        theatre.set_equipment_needed(_op(surgery), True, user=_boss(surgery))
        surgery["db"].session.commit()
        first = theatre.equipment_for(_op(surgery))[0].id

    surgery["sign_in"]().post(
        f"/theatres/operation/{surgery['ids']['case']}/equipment",
        data={"needed": "yes", f"present_{first}": "yes",
              f"working_{first}": "yes"}, follow_redirects=True)
    with surgery["app"].app_context():
        assert _items(surgery)["منظار ٥ مم"].state == "ready"
        assert _items(surgery)["مصدر إضاءة"].state == "unchecked"
        assert theatre.equipment_state(_op(surgery)) == "checking"


def test_the_columns_are_registered_for_a_clinic_already_running(surgery):
    from app.utils.schema import ADDITIONS

    pairs = {(t, c) for t, c, _ in ADDITIONS}
    assert ("operations", "equipment_needed") in pairs
    assert ("operations", "equipment_checked_by") in pairs
    assert ("operations", "equipment_checked_at") in pairs
    assert ("services", "equipment_list") in pairs
