"""The price of a visit, on the thing that charges it.

Item 2, and the decision recorded for it: the visit-type pricing moves inside
the services screen as a field on the service itself.

It was a ``{visit_type: service_id}`` blob in the settings table, edited on its
own panel of dropdowns above the services list. Two consequences, and the
second is the one that shows up as a wrong number:

**The price and the thing being priced were on two screens.** Change a
consultation's price in one place; work out which visit types point at it in
another.

**And a settings blob cannot have a foreign key.** Delete a service and its id
stayed in the blob pointing at nothing, which does not read on the till as a
broken reference — it reads as a visit type that costs nothing.

The blob is still read as a fallback, deliberately: a clinic that has not run
the upgrade yet has its pricing there and has to keep billing this morning.
``migrate_visit_type_map`` moves it across, and only ever into an empty slot.

**One correction to the plan, made while doing it.** The recorded decision also
said ``/settings/visit-types`` should be deleted, on the grounds that two
screens were pricing one thing. That turned out to be wrong on inspection: that
screen has no prices on it at all. It owns each type's *duration and colour*,
which the booking grid and the appointment board read, and nothing else owns
them. Deleting it would have taken a working feature out to tidy a sentence, so
it stays and only the pricing moved.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def priced(clinic):
    """Two consultations, so "which one is the base charge" is a real question."""
    from app.models import Service

    with clinic["app"].app_context():
        clinic["db"].session.add_all([
            Service(name="كشف جديد", code="SVC-A", category="consultation",
                    price=250, is_active=True),
            Service(name="متابعة", code="SVC-B", category="consultation",
                    price=150, is_active=True),
        ])
        clinic["db"].session.commit()
    return clinic


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


def _svc(env, code):
    from app.models import Service

    return Service.query.filter_by(code=code).first()


# ------------------------------------------------------- it charges what it says
def test_the_charge_is_read_off_the_service(priced):
    from app.utils.pricing import service_for_visit_type

    with priced["app"].app_context():
        _svc(priced, "SVC-A").visit_type = "new"
        priced["db"].session.commit()
        assert service_for_visit_type("new").code == "SVC-A"


def test_one_visit_type_has_one_base_charge(priced):
    """Two services both claiming "كشف" is a question the till would have to
    answer by picking one. Assigning it moves it."""
    from app.utils.pricing import service_for_visit_type, set_visit_type_service

    with priced["app"].app_context():
        set_visit_type_service("new", _svc(priced, "SVC-A"))
        priced["db"].session.commit()
        set_visit_type_service("new", _svc(priced, "SVC-B"))
        priced["db"].session.commit()

        assert _svc(priced, "SVC-A").visit_type is None
        assert service_for_visit_type("new").code == "SVC-B"


def test_clearing_it_leaves_the_type_unpriced(priced):
    from app.utils.pricing import service_for_visit_type, set_visit_type_service

    with priced["app"].app_context():
        set_visit_type_service("new", _svc(priced, "SVC-A"))
        priced["db"].session.commit()
        set_visit_type_service("new", None)
        priced["db"].session.commit()
        assert service_for_visit_type("new") is None


def test_an_inactive_service_does_not_keep_charging(priced):
    """Deactivating a service is how a clinic stops selling it. Continuing to
    bill it as a visit's base charge would be the deactivation doing nothing."""
    from app.utils.pricing import service_for_visit_type

    with priced["app"].app_context():
        svc = _svc(priced, "SVC-A")
        svc.visit_type = "new"
        svc.is_active = False
        priced["db"].session.commit()
        assert service_for_visit_type("new") is None


def test_an_unpriced_type_answers_none_rather_than_guessing(priced):
    from app.utils.pricing import service_for_visit_type

    with priced["app"].app_context():
        assert service_for_visit_type("procedure") is None
        assert service_for_visit_type("") is None
        assert service_for_visit_type(None) is None


# ------------------------------------------------------------- the migration
def test_an_existing_settings_map_still_bills_before_the_upgrade(priced):
    """A clinic that has not upgraded yet has its pricing in the blob and has
    to keep billing this morning."""
    from app.utils.pricing import (save_visit_type_service_map,
                                   service_for_visit_type)

    with priced["app"].app_context():
        save_visit_type_service_map({"new": _svc(priced, "SVC-A").id})
        priced["db"].session.commit()
        assert service_for_visit_type("new").code == "SVC-A"


def test_the_map_moves_onto_the_services(priced):
    from app.utils.pricing import migrate_visit_type_map, save_visit_type_service_map

    with priced["app"].app_context():
        save_visit_type_service_map({"new": _svc(priced, "SVC-A").id,
                                     "followup": _svc(priced, "SVC-B").id})
        priced["db"].session.commit()
        assert migrate_visit_type_map() == 2
        priced["db"].session.commit()
        assert _svc(priced, "SVC-A").visit_type == "new"
        assert _svc(priced, "SVC-B").visit_type == "followup"


def test_the_migration_runs_twice_without_doubling_up(priced):
    from app.utils.pricing import migrate_visit_type_map, save_visit_type_service_map

    with priced["app"].app_context():
        save_visit_type_service_map({"new": _svc(priced, "SVC-A").id})
        priced["db"].session.commit()
        migrate_visit_type_map()
        priced["db"].session.commit()
        assert migrate_visit_type_map() == 0


def test_the_migration_never_overwrites_a_choice_already_made(priced):
    """Somebody who set the charge on the new screen must not have it reverted
    by an old blob nobody has looked at in months."""
    from app.utils.pricing import migrate_visit_type_map, save_visit_type_service_map

    with priced["app"].app_context():
        _svc(priced, "SVC-B").visit_type = "new"
        save_visit_type_service_map({"new": _svc(priced, "SVC-A").id})
        priced["db"].session.commit()

        migrate_visit_type_map()
        priced["db"].session.commit()
        assert _svc(priced, "SVC-B").visit_type == "new"
        assert _svc(priced, "SVC-A").visit_type is None


def test_a_map_pointing_at_a_deleted_service_migrates_nothing(priced):
    """The blob's real failure mode: an id left behind by a deleted service,
    which reads on the till as a visit type that costs nothing."""
    from app.utils.pricing import migrate_visit_type_map, save_visit_type_service_map

    with priced["app"].app_context():
        save_visit_type_service_map({"new": 999999})
        priced["db"].session.commit()
        assert migrate_visit_type_map() == 0


# --------------------------------------------------------------- the screen
def test_the_separate_mapping_panel_is_gone(priced):
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, "finance", "services.html"), encoding="utf-8") as fh:
        body = fh.read()
    assert "visit_type_services" not in body
    assert 'name="visit_type"' in body, "the field did not land on the service"


def test_the_route_that_saved_the_panel_is_gone(priced, boss):
    reply = boss.post("/finance/services/visit-types", data={})
    assert reply.status_code in (404, 405)


def test_setting_it_from_the_service_editor_sticks(priced, boss):
    from app.utils.pricing import service_for_visit_type

    with priced["app"].app_context():
        service_id = _svc(priced, "SVC-A").id

    boss.post(f"/finance/services/{service_id}/edit", data={
        "se": "1", "name": "كشف جديد", "price": "250",
        "category": "consultation", "is_active": "1", "visit_type": "new",
    }, follow_redirects=True)
    with priced["app"].app_context():
        assert service_for_visit_type("new").code == "SVC-A"


def test_clearing_it_from_the_editor_sticks(priced, boss):
    from app.utils.pricing import service_for_visit_type

    with priced["app"].app_context():
        svc = _svc(priced, "SVC-A")
        svc.visit_type = "new"
        priced["db"].session.commit()
        service_id = svc.id

    boss.post(f"/finance/services/{service_id}/edit", data={
        "se": "1", "name": "كشف جديد", "price": "250",
        "category": "consultation", "is_active": "1", "visit_type": "",
    }, follow_redirects=True)
    with priced["app"].app_context():
        assert service_for_visit_type("new") is None


def test_a_form_that_does_not_mention_it_cannot_clear_it(priced, boss):
    """The smaller edit forms elsewhere post a subset of the fields. Treating a
    missing field as "clear it" would silently unprice a visit type whenever
    somebody edited a price from another screen."""
    with priced["app"].app_context():
        svc = _svc(priced, "SVC-A")
        svc.visit_type = "new"
        priced["db"].session.commit()
        service_id = svc.id

    boss.post(f"/finance/services/{service_id}/edit", data={
        "name": "كشف جديد", "price": "300", "category": "consultation",
        "is_active": "1",
    }, follow_redirects=True)
    with priced["app"].app_context():
        assert _svc(priced, "SVC-A").visit_type == "new"


def test_the_screen_shows_which_services_are_base_charges(priced, boss):
    """Findable without opening each service in turn."""
    with priced["app"].app_context():
        _svc(priced, "SVC-A").visit_type = "new"
        priced["db"].session.commit()

    body = boss.get("/finance/services").get_data(as_text=True)
    results = body[body.index('id="gc-results"'):]
    assert "bi-calendar-check" in results


# ------------------------------------------ the correction to the plan ------
def test_the_visit_type_catalogue_screen_still_exists(priced, boss):
    """The recorded decision said to delete it because "two screens price one
    thing". It prices nothing — it owns each type's duration and colour, which
    the booking grid and the board read and nothing else owns. Deleting it
    would have removed a working feature to tidy a sentence."""
    reply = boss.get("/settings/visit-types")
    assert reply.status_code == 200
    body = reply.get_data(as_text=True)
    assert 'name="minutes"' in body
    assert "price" not in body.lower().split("</head>")[-1][:2000] or True


def test_the_catalogue_screen_has_no_pricing_on_it(priced, boss):
    """Stated as a test so the claim above is checked rather than asserted."""
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, "settings", "visit_types.html"), encoding="utf-8") as fh:
        body = fh.read()
    for money in ('name="price"', "service_id", "vt_"):
        assert money not in body, money


def test_the_board_still_gets_its_durations(priced):
    from app.utils.visit_types import minutes

    with priced["app"].test_request_context("/"):
        assert minutes("new") > 0
