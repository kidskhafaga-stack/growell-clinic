"""Setting a nursing station up, from a screen rather than the database.

The stations themselves worked; there was no way to make one. A feature that
can only be configured with SQL is a feature nobody has, so this is the other
half rather than a nicety.

Two decisions worth stating.

**Clinics are ticked, not typed.** A nurse's screen scoped to the wrong
corridor is worse than one scoped to nothing, and a free-text list of room
numbers is exactly how that happens.

**The screen shows the consequence, not only the setting.** Each station says
how many doctors it actually covers *today*. A station covering nobody is
almost always one whose عيادات were never ticked, and without that line the
mistake is invisible here and only shows up as an empty screen in front of a
nurse.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """Four عيادات, each with a doctor in it today."""
    from app.extensions import db
    from app.models import ClinicRoom, RoomAssignment, User

    with clinic["app"].app_context():
        rooms, docs = [], []
        for i in range(1, 5):
            room = ClinicRoom(code=f"S{i}", name_ar=f"عيادة {i}",
                              sort_order=i, is_active=True)
            doc = User(username=f"sd{i}", full_name=f"د. {i}", role="doctor",
                       is_active=True)
            doc.set_password("secret")
            db.session.add_all([room, doc])
            rooms.append(room)
            docs.append(doc)
        db.session.flush()
        for doc, room in zip(docs, rooms):
            db.session.add(RoomAssignment(on_date=local_today(),
                                          doctor_id=doc.id, room_id=room.id))
        db.session.commit()
        clinic["rooms"] = [r.id for r in rooms]
    return clinic


def _make(ward, name="محطة تمريض ١", rooms=None):
    client = ward["sign_in"]("boss")
    client.post("/appointments/stations/add",
                data={"name_ar": name,
                      "rooms": [str(r) for r in (rooms or ward["rooms"][:2])]},
                follow_redirects=True)
    from app.models import NursingStation
    with ward["app"].app_context():
        return NursingStation.query.filter_by(name_ar=name).first().id


# --------------------------------------------------------------- the screen

def test_the_screen_opens(ward):
    assert ward["sign_in"]("boss").get(
        "/appointments/stations").status_code == 200


def test_a_station_can_be_created_from_it(ward):
    """The half that was missing: stations existed and could not be made."""
    from app.models import NursingStation

    _make(ward)

    with ward["app"].app_context():
        station = NursingStation.query.filter_by(name_ar="محطة تمريض ١").first()
        assert station is not None
        assert len(station.rooms) == 2, "the ticked عيادات were not saved"


def test_the_clinics_are_ticked_not_typed(ward):
    """A free-text room list is how a nurse ends up scoped to the wrong
    corridor."""
    page = ward["sign_in"]("boss").get("/appointments/stations").data.decode()

    assert 'name="rooms"' in page and 'type="checkbox"' in page
    assert "عيادة 1" in page, "the عيادات are not offered on the form"


def test_it_says_how_many_doctors_the_station_covers_today(ward):
    """The consequence of the setting, not only the setting."""
    from app.i18n import t

    _make(ward)
    page = ward["sign_in"]("boss").get("/appointments/stations").data.decode()

    with ward["app"].test_request_context("/"):
        assert t("station.covers_n", n=2) in page, \
            "the screen does not say what the station actually covers"


def test_a_station_with_no_clinics_says_so_loudly(ward):
    """The mistake this line exists to catch: it is invisible otherwise, and
    shows up as an empty screen in front of a nurse."""
    from app.i18n import t

    client = ward["sign_in"]("boss")
    client.post("/appointments/stations/add",
                data={"name_ar": "محطة فاضية"}, follow_redirects=True)

    page = client.get("/appointments/stations").data.decode()
    with ward["app"].test_request_context("/"):
        assert t("station.covers_none") in page


def test_a_station_needs_a_name(ward):
    from app.models import NursingStation

    ward["sign_in"]("boss").post("/appointments/stations/add",
                                 data={"name_ar": "  "}, follow_redirects=True)

    with ward["app"].app_context():
        assert NursingStation.query.count() == 0


# ------------------------------------------------------------ editing it

def test_the_clinics_can_be_changed(ward):
    from app.models import NursingStation

    station_id = _make(ward)
    ward["sign_in"]("boss").post(
        f"/appointments/stations/{station_id}/edit",
        data={"name_ar": "محطة تمريض ١", "is_active": "1",
              "rooms": [str(r) for r in ward["rooms"][:3]]},
        follow_redirects=True)

    with ward["app"].app_context():
        assert len(ward["db"].session.get(NursingStation, station_id).rooms) == 3


def test_unticking_them_all_leaves_it_covering_nobody(ward):
    """Not "unchanged". An empty tick list is a decision, and the station
    covering nobody is the honest reading of it."""
    from app.models import NursingStation

    station_id = _make(ward)
    ward["sign_in"]("boss").post(
        f"/appointments/stations/{station_id}/edit",
        data={"name_ar": "محطة تمريض ١", "is_active": "1"},
        follow_redirects=True)

    with ward["app"].app_context():
        station = ward["db"].session.get(NursingStation, station_id)
        assert station.rooms == []
        assert station.doctor_ids_on(local_today()) == set()


def test_a_station_can_be_switched_off(ward):
    from app.models import NursingStation

    station_id = _make(ward)
    ward["sign_in"]("boss").post(
        f"/appointments/stations/{station_id}/edit",
        data={"name_ar": "محطة تمريض ١"}, follow_redirects=True)

    with ward["app"].app_context():
        assert ward["db"].session.get(NursingStation, station_id).is_active is False


# ----------------------------------------------------------- deleting it

def test_deleting_one_does_not_strand_the_people_who_used_it(ward):
    """A station owns no history, so removing it is safe — but somebody's
    remembered choice still points at it, and a dangling id must fall back to
    the whole clinic rather than to an error.
    """
    from app.extensions import db
    from app.models import NursingStation, User

    station_id = _make(ward)
    with ward["app"].app_context():
        nurse = User.query.filter_by(username="doc").first()
        nurse.nursing_station_id = station_id
        db.session.commit()

    ward["sign_in"]("boss").post(f"/appointments/stations/{station_id}/delete",
                                 follow_redirects=True)

    with ward["app"].app_context():
        assert db.session.get(NursingStation, station_id) is None
        nurse = User.query.filter_by(username="doc").first()
        assert nurse.nursing_station_id is None, \
            "somebody is still pointed at a station that no longer exists"


def test_the_nursing_screen_survives_a_deleted_station(ward):
    """The end-to-end of the above: the screen must still open."""
    from app.extensions import db
    from app.models import User

    # Whoever opens this screen needs the `visits` module; reception has no
    # such thing, which is why the doctor stands in for the nurse here.
    station_id = _make(ward)
    with ward["app"].app_context():
        nurse = User.query.filter_by(username="doc").first()
        nurse.nursing_station_id = station_id
        db.session.commit()
    ward["sign_in"]("boss").post(f"/appointments/stations/{station_id}/delete",
                                 follow_redirects=True)

    answer = ward["sign_in"]("doc").get("/visits/station",
                                        follow_redirects=True)

    assert answer.status_code == 200


# --------------------------------------------------------------- the way in

def test_the_rooms_screen_links_to_it(ward):
    """It reads that screen's rota, so that is where somebody looks for it."""
    page = ward["sign_in"]("boss").get("/appointments/clinics").data.decode()

    assert "/appointments/stations" in page


def test_the_empty_state_explains_itself(ward):
    """A clinic with one station should not think it has to define one."""
    from app.i18n import t

    page = ward["sign_in"]("boss").get("/appointments/stations").data.decode()

    with ward["app"].test_request_context("/"):
        assert t("station.none")[:20] in page
        assert t("station.none_hint")[:25] in page


def test_the_wording_exists_in_both_languages(ward):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    keys = ["title", "subtitle", "explainer", "add", "covers_n", "covers_none",
            "none", "none_hint", "rooms", "all_clinics"]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["station"]
        for key in keys:
            assert key in block, f"{lang} is missing station.{key}"
    assert isinstance(date.today(), date)
