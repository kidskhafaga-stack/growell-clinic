"""A nursing station is a place beside certain عيادات, not a person.

A nurse serving three of the clinic's eight rooms was shown all eight, and
had to find their own children in somebody else's list every time.

**The scope belongs to the station.** That decision came from the clinic, not
from me: I proposed remembering a set of rooms per *user* and was corrected —
nursing staff rotate, so a preference stored on the person walks off with them
the day they cover another shift. The station is what stays beside the doors.

**Rooms, not doctors**, for the mirror-image reason. Doctors move between
rooms and the station does not, so a station holds عيادات and the doctors it
covers today are read from the day's room assignments. Nobody has to remember
to update anything when the rota changes — which is the test below that would
never be written if the doctors were stored.
"""
import os
import sys
from datetime import date, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """Five عيادات, five doctors, a child waiting in each, and two stations."""
    from app.extensions import db
    from app.models import (Appointment, ClinicRoom, NursingStation, Patient,
                            RoomAssignment, Role, RoomAssignment as RA, User)

    with clinic["app"].app_context():
        role = Role(name="nursing", label_ar="تمريض", is_admin=False)
        role.set_modules(["dashboard", "patients", "visits"])
        role.set_capabilities(["patient_medical"])
        db.session.add(role)
        nurse = User(username="nur", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        db.session.add(nurse)

        today = local_today()
        rooms, docs = [], []
        for i in range(1, 6):
            room = ClinicRoom(code=f"R{i}", name_ar=f"عيادة {i}",
                              sort_order=i, is_active=True)
            doc = User(username=f"wd{i}", full_name=f"د. {i}", role="doctor",
                       is_active=True)
            doc.set_password("secret")
            db.session.add_all([room, doc])
            rooms.append(room)
            docs.append(doc)
        db.session.flush()

        for doc, room in zip(docs, rooms):
            db.session.add(RA(on_date=today, doctor_id=doc.id, room_id=room.id))
            kid = Patient(patient_number=f"W{room.id}", full_name=f"طفل {room.id}",
                          gender="male", date_of_birth=date(2021, 1, 1),
                          own_phone=f"0100{room.id}", is_active=True)
            db.session.add(kid)
            db.session.flush()
            db.session.add(Appointment(patient_id=kid.id, doctor_id=doc.id,
                                       appt_date=today, appt_time=time(10, 0),
                                       status="waiting"))

        first = NursingStation(name_ar="محطة تمريض ١", sort_order=1)
        first.rooms = rooms[:3]
        second = NursingStation(name_ar="محطة تمريض ٢", sort_order=2)
        second.rooms = rooms[3:]
        db.session.add_all([first, second])
        db.session.commit()

        clinic["first"] = first.id
        clinic["second"] = second.id
        clinic["rooms"] = [r.id for r in rooms]
        clinic["docs"] = [d.id for d in docs]
        assert RoomAssignment is RA
    return clinic


def _nurse(ward):
    client = ward["app"].test_client()
    client.post("/login", data={"username": "nur", "password": "secret"},
                follow_redirects=True)
    return client


def _names(page):
    import re
    return sorted(set(re.findall(r"طفل \d+", page)))


# ------------------------------------------------------------ the scoping

def test_a_station_shows_only_its_own_clinics(ward):
    """The reported problem: three رooms, eight children."""
    client = _nurse(ward)

    page = client.get(f"/visits/station?station={ward['first']}",
                      follow_redirects=True).data.decode()

    assert len(_names(page)) == 3, \
        f"the station is not scoped to its own عيادات: {_names(page)}"


def test_the_other_station_shows_the_others(ward):
    client = _nurse(ward)

    page = client.get(f"/visits/station?station={ward['second']}",
                      follow_redirects=True).data.decode()

    assert len(_names(page)) == 2


def test_without_a_station_the_whole_clinic_is_shown(ward):
    """A small clinic with one station must not have to define one."""
    client = _nurse(ward)

    page = client.get("/visits/station", follow_redirects=True).data.decode()

    assert len(_names(page)) == 5


def test_the_choice_is_remembered(ward):
    """Nobody should re-pick their station every morning."""
    client = _nurse(ward)
    client.get(f"/visits/station?station={ward['second']}", follow_redirects=True)

    page = client.get("/visits/station", follow_redirects=True).data.decode()

    assert len(_names(page)) == 2, "the station was forgotten on the next visit"


def test_switching_station_takes_the_list_with_it(ward):
    """Staff rotate — that is the whole reason the scope is not on the nurse."""
    client = _nurse(ward)
    client.get(f"/visits/station?station={ward['first']}", follow_redirects=True)

    page = client.get(f"/visits/station?station={ward['second']}",
                      follow_redirects=True).data.decode()

    assert len(_names(page)) == 2


# ------------------------------------------- rooms, so the rota can change

def test_a_doctor_moving_room_moves_with_the_room(ward):
    """The test that could not exist if the station stored doctors.

    The rota changes and nobody updates the station. The child follows the
    room, because that is where the nurse is standing.
    """
    from app.extensions import db
    from app.models import RoomAssignment

    with ward["app"].app_context():
        today = local_today()
        # The doctor from عيادة 5 (station two) moves into عيادة 1 today.
        moved = (RoomAssignment.query
                 .filter_by(on_date=today, doctor_id=ward["docs"][4]).first())
        moved.room_id = ward["rooms"][0]
        db.session.commit()

    client = _nurse(ward)
    page = client.get(f"/visits/station?station={ward['first']}",
                      follow_redirects=True).data.decode()

    assert len(_names(page)) == 4, \
        "a doctor who moved room did not move with it — the station stores doctors"


def test_a_station_with_no_rooms_covers_nobody(ward):
    """Not everybody.

    Showing the whole clinic while somebody is halfway through setting a
    station up is how a nurse weighs a child from the other end of the
    corridor.
    """
    from app.extensions import db
    from app.models import NursingStation

    with ward["app"].app_context():
        empty = NursingStation(name_ar="محطة جديدة", sort_order=3)
        db.session.add(empty)
        db.session.commit()
        empty_id = empty.id
        assert empty.doctor_ids_on(local_today()) == set()

    client = _nurse(ward)
    page = client.get(f"/visits/station?station={empty_id}",
                      follow_redirects=True).data.decode()

    assert _names(page) == []


def test_yesterdays_rota_does_not_decide_todays_scope(ward):
    from app.extensions import db
    from app.models import NursingStation

    with ward["app"].app_context():
        station = db.session.get(NursingStation, ward["first"])

        assert len(station.doctor_ids_on(local_today())) == 3
        assert station.doctor_ids_on(local_today() - timedelta(days=1)) == set()


def test_a_room_can_belong_to_two_stations(ward):
    """A corridor with a station at each end is a real layout."""
    from app.extensions import db
    from app.models import ClinicRoom, NursingStation

    with ward["app"].app_context():
        first = db.session.get(NursingStation, ward["first"])
        second = db.session.get(NursingStation, ward["second"])
        shared = db.session.get(ClinicRoom, ward["rooms"][0])
        second.rooms = list(second.rooms) + [shared]
        db.session.commit()

        assert shared.id in first.room_ids and shared.id in second.room_ids
        assert len(second.doctor_ids_on(local_today())) == 3


# ------------------------------------------------------------- the screen

def test_the_switcher_is_on_the_screen(ward):
    """One press to move, or the scope is a setting somebody has to hunt for."""
    page = _nurse(ward).get("/visits/station", follow_redirects=True).data.decode()

    assert 'name="station"' in page, "there is no way to change station"
    assert "محطة تمريض ١" in page and "محطة تمريض ٢" in page


def test_the_nurse_can_still_enter_vitals_for_their_own(ward):
    """Scoping the list must not scope away the thing the screen is for."""
    from app.models import Appointment

    with ward["app"].app_context():
        appt = (Appointment.query
                .filter_by(doctor_id=ward["docs"][0]).first())
        appt_id = appt.id

    client = _nurse(ward)
    client.get(f"/visits/station?station={ward['first']}", follow_redirects=True)
    answer = client.post(f"/visits/station/{appt_id}/vitals",
                         data={"weight": "12.5", "temperature": "37.1"},
                         follow_redirects=True)

    assert answer.status_code == 200


def test_the_column_is_in_the_additive_migration(ward):
    from app.utils.schema import ADDITIONS

    assert ("users", "nursing_station_id") in {(t, c) for t, c, _ in ADDITIONS}
