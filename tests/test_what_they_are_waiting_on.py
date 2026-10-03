"""What each child in emergency is waiting on — read, never typed.

Asked as *«مش التحاليل المتأخره بس — هو قاعد وملهوش علاج، وخلص جلسة النفس،
او مستنى اشعة، او مستنى الطبيب يكتب روشتة فى الخروج»*. What is held here:

* each state is read off what was written and done, in the order a person
  would ask it: triage, then a doctor, then the nurse, then the lab;
* a timed session that has run out, with nothing written since, asks for a
  reassessment — and a countdown shows while it runs;
* everything done and the child still here is the doctor's move;
* time is flagged only against the department's own limit, and a blank
  limit flags nothing;
* the live board lists the children with no bed, and the beds' own tests.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    from app.models import Service, Setting, User

    with clinic["app"].app_context():
        db = clinic["db"]
        for module in ("emergency", "beds", "labs"):
            Setting.set(f"mod_enabled:{module}", "1")
        nurse = User(username="nurse", full_name="ممرضة", role="nursing", is_active=True)
        nurse.set_password("secret")
        neb = Service(name="جلسة تنفس", category="procedure", service_type="session",
                      price=80, duration_minutes=15, is_active=True)
        db.session.add_all([nurse, neb])
        db.session.commit()
        clinic["ids"].update(nurse=nurse.id, neb=neb.id)
    return clinic


@pytest.fixture(autouse=True)
def _nobody_on_the_rota(monkeypatch):
    from app.utils import emergency_orders

    monkeypatch.setattr(emergency_orders, "present_now", lambda: set())


def _arrive(er, minutes_ago=30, triaged=True):
    from app.models import Patient
    from app.utils import emergency as util

    with er["app"].app_context():
        db = er["db"]
        child = db.session.get(Patient, er["ids"]["child"])
        row = util.arrive(child, at=datetime.utcnow() - timedelta(minutes=minutes_ago))
        db.session.flush()
        if triaged:
            row.triaged_at = row.arrived_at + timedelta(minutes=5)
            row.level = "أصفر"
        db.session.commit()
        return row.id


def _waiting(er, attendance, now=None):
    from app.models import EmergencyVisit
    from app.utils import waiting_on

    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, attendance)
        return waiting_on.for_attendances([row], now=now)[attendance]


def _kinds(w):
    return [i["kind"] for i in w["items"]]


def _write(er, attendance, who="doctor", source="ours", given_ago=None, service=None, **kw):
    from app.models import EmergencyVisit, Service, User
    from app.utils import emergency_orders as eo

    with er["app"].app_context():
        db = er["db"]
        row = db.session.get(EmergencyVisit, attendance)
        order = eo.write(row, db.session.get(User, er["ids"][who]), source=source,
                         name=kw.pop("name", "Salbutamol"),
                         service=db.session.get(Service, er["ids"][service]) if service else None,
                         **kw)
        if given_ago is not None:
            eo.give(order, db.session.get(User, er["ids"]["nurse"]),
                    at=datetime.utcnow() - timedelta(minutes=given_ago))
        db.session.commit()
        return order.id


def _test(er, attendance, kind="lab", collected=False, resulted=False):
    from app.models import EmergencyVisit, User
    from app.utils import emergency_orders as eo

    with er["app"].app_context():
        db = er["db"]
        row = db.session.get(EmergencyVisit, attendance)
        test = eo.order_test(row, db.session.get(User, er["ids"]["doctor"]),
                             name="صورة دم" if kind == "lab" else "أشعة صدر", kind=kind)
        if collected:
            test.collected_at = datetime.utcnow() - timedelta(minutes=5)
            test.status = "collected"
        if resulted:
            test.result_text = "طبيعي"
            test.status = "resulted"
            test.resulted_at = datetime.utcnow()
        db.session.commit()


# ============================================================ the states ==
def test_nobody_triaged_is_waiting_for_triage(er):
    a = _arrive(er, triaged=False)
    assert _kinds(_waiting(er, a)) == ["triage"]


def test_triaged_and_nothing_written_is_waiting_for_a_doctor(er):
    a = _arrive(er)
    w = _waiting(er, a)
    assert _kinds(w) == ["doctor"] and w["top"]["minutes"] >= 20


def test_an_outside_paper_waits_for_our_doctor(er):
    a = _arrive(er)
    _write(er, a, who="nurse", source="outside_rx", outside_doctor="د. خالد")
    assert _kinds(_waiting(er, a)) == ["approval"]


def test_written_and_not_given_is_the_nurses_move(er):
    a = _arrive(er)
    _write(er, a)
    assert _kinds(_waiting(er, a)) == ["treatment"]


def test_a_session_that_ran_out_asks_for_a_look_and_one_running_counts_down(er):
    from app.models import EmergencyOrder
    from app.utils import waiting_on

    a = _arrive(er, minutes_ago=60)
    _write(er, a, service="neb", given_ago=20)
    w = _waiting(er, a)
    assert _kinds(w) == ["reassess"] and 4 <= w["top"]["minutes"] <= 6

    b = _arrive(er, minutes_ago=60)
    _write(er, b, service="neb", given_ago=5)
    assert _kinds(_waiting(er, b)) == ["decision"]
    with er["app"].app_context():
        orders = EmergencyOrder.query.filter_by(emergency_visit_id=b).all()
        running = waiting_on.running_session(orders)
        assert running and 9 <= running["left"] <= 11 and running["total"] == 15


def test_writing_something_after_the_session_answers_it(er):
    a = _arrive(er, minutes_ago=60)
    _write(er, a, service="neb", given_ago=20)
    _write(er, a, name="Dexamethasone")
    assert _kinds(_waiting(er, a)) == ["treatment"]


def test_where_the_tests_are(er):
    a = _arrive(er)
    _test(er, a)
    assert _kinds(_waiting(er, a)) == ["sample"]
    b = _arrive(er)
    _test(er, b, collected=True)
    assert _kinds(_waiting(er, b)) == ["result"]
    c = _arrive(er)
    _test(er, c, kind="imaging")
    assert _kinds(_waiting(er, c)) == ["imaging"]


def test_everything_done_and_still_here_is_the_doctors_decision(er):
    a = _arrive(er)
    _write(er, a, name="Paracetamol", given_ago=10)
    _test(er, a, collected=True, resulted=True)
    assert _kinds(_waiting(er, a)) == ["decision"]


def test_the_worst_comes_first(er):
    a = _arrive(er)
    _write(er, a, who="nurse", source="outside_rx", outside_doctor="د. خالد")
    _write(er, a)
    _test(er, a)
    assert _kinds(_waiting(er, a)) == ["approval", "treatment", "sample"]


# ============================================================== the limit ==
def test_time_is_flagged_only_against_the_units_own_limit(er):
    from app.models.place import Unit

    a = _arrive(er, minutes_ago=90)
    assert _waiting(er, a)["over"] is False, "flagged with no limit set"
    with er["app"].app_context():
        er["db"].session.add(Unit(name="الطوارئ", kind="emergency", max_stay_minutes=60))
        er["db"].session.commit()
    w = _waiting(er, a)
    assert w["over"] is True and w["limit"] == 60
    b = _arrive(er, minutes_ago=30)
    assert _waiting(er, b)["over"] is False


def test_the_limit_is_set_in_hours_and_minutes_and_cleared_by_blank(er):
    from app.models.place import Unit

    with er["app"].app_context():
        unit = Unit(name="الطوارئ", kind="emergency")
        er["db"].session.add(unit)
        er["db"].session.commit()
        uid = unit.id
    boss = er["sign_in"]("boss")
    assert "data-max-stay" in boss.get("/beds/setup").get_data(as_text=True)
    boss.post(f"/beds/unit/{uid}/max-stay", data={"hours": "4", "minutes": "30"})
    with er["app"].app_context():
        assert er["db"].session.get(Unit, uid).max_stay_minutes == 270
    boss.post(f"/beds/unit/{uid}/max-stay", data={"hours": "", "minutes": ""})
    with er["app"].app_context():
        assert er["db"].session.get(Unit, uid).max_stay_minutes is None


# ============================================================= the screens ==
def test_the_screens_say_it(er):
    from app.models.place import Unit

    with er["app"].app_context():
        er["db"].session.add(Unit(name="الطوارئ", kind="emergency", max_stay_minutes=10))
        er["db"].session.commit()
    a = _arrive(er, minutes_ago=40)
    _write(er, a, service="neb", given_ago=3)
    doc = er["sign_in"]("doc")
    board = doc.get("/emergency/").get_data(as_text=True)
    assert f'data-bedless-row="{a}"' in board and "data-over-limit" in board
    register = doc.get("/emergency/register").get_data(as_text=True)
    assert 'data-waiting="decision"' in register
    page = doc.get(f"/emergency/attendance/{a}").get_data(as_text=True)
    assert "data-waiting-box" in page and "data-session" in page


def test_a_child_in_an_emergency_bed_shows_its_tests_and_the_limit(er):
    from app.models import Patient, User
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward
    from app.utils import stay_orders

    with er["app"].app_context():
        db = er["db"]
        unit = Unit(name="الطوارئ", kind="emergency", max_stay_minutes=30)
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="بارتشن 1", kind="partition")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="ترولي 1", kind="trolley")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, er["ids"]["child"]), bed,
                          when=datetime.utcnow() - timedelta(minutes=45))
        db.session.flush()
        stay_orders.order(stay, db.session.get(User, er["ids"]["doctor"]),
                          name="أشعة صدر", kind="imaging")
        db.session.commit()
    board = er["sign_in"]("doc").get("/emergency/").get_data(as_text=True)
    assert 'data-waiting="imaging"' in board and "data-over-limit" in board
