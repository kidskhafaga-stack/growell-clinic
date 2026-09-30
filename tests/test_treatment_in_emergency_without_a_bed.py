"""Treatment in emergency for a child with no bed — and on whose word.

Asked as *«الناس الى داخله الطوارئ تنفذ علاج معين ومش هتاخد اقامة»*, with the
rule in the doctor's words: *«الدكتور لازم يبص على الحالة الاول ولو طبيب من
المستشفى بتنفذ العلاج على طول وتكتب اسم الطبيب ولو طبيب خارجي مش متعاقد مع
المستشفى لازم الطبيب يكتب اوردر ويكتب ويتاكد وانها جايه من دكتور فلان»*, and
on confirming: *«تظهر لو الطبيب موجود فى المستشفى لو مش موجود تبقى موجوده فى
الملف»*. What is held here:

* a child arrives with no bed, from a screen, and a walk-in says so;
* our doctor's order is theirs and is given at once;
* a hospital doctor's paper is given at once in their name, and they are
  asked to confirm only if the rota has them in the building;
* an outside paper is not given until one of our doctors approves it, and
  a nurse cannot approve it;
* nothing is written on a child who has left, and what was given stays;
* a given treatment is the «care provided» the record asks for;
* tests from the attendance land on its own emergency encounter.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er(clinic):
    from app.models import Setting, User

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:emergency", "1")
        nurse = User(username="nurse", full_name="ممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        colleague = User(username="doc2", full_name="د. منى", role="doctor",
                         is_active=True)
        colleague.set_password("secret")
        db.session.add_all([nurse, colleague])
        db.session.commit()
        clinic["ids"].update(nurse=nurse.id, doc2=colleague.id)
    return clinic


@pytest.fixture(autouse=True)
def _nobody_on_the_rota(monkeypatch):
    from app.utils import emergency_orders

    monkeypatch.setattr(emergency_orders, "present_now", lambda: set())


def _arrive(er, who="nurse", **extra):
    resp = er["sign_in"](who).post("/emergency/arrive", data={
        "patient_id": er["ids"]["child"], "arrival": "walk_in", **extra})
    assert resp.status_code == 302
    from app.models import EmergencyVisit

    with er["app"].app_context():
        return EmergencyVisit.query.order_by(EmergencyVisit.id.desc()).first().id


def _write(er, attendance, who="doc", **form):
    data = {"name": "Ceftriaxone", "dose": "500 mg", "route": "im", **form}
    return er["sign_in"](who).post(f"/emergency/attendance/{attendance}/order",
                                   data=data)


def _orders(er, attendance):
    from app.models import EmergencyOrder

    with er["app"].app_context():
        return [(o.id, o.source, o.state, o.prescriber_id, o.outside_doctor,
                 o.confirm_asked)
                for o in EmergencyOrder.query.filter_by(
                    emergency_visit_id=attendance).order_by(EmergencyOrder.id)]


# ============================================================ arriving ===
def test_a_child_arrives_with_no_bed_from_the_register(er):
    page = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert "data-arrive-form" in page and "data-treatment-only" in page
    attendance = _arrive(er, treatment_only="1")
    from app.models import Admission, EmergencyVisit

    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, attendance)
        assert row.treatment_only is True and row.is_open
        assert Admission.query.count() == 0
    listed = er["sign_in"]("nurse").get("/emergency/register").get_data(as_text=True)
    assert "data-walk-in" in listed and "data-to-attendance" in listed


def test_an_ordinary_arrival_is_not_marked_walk_in(er):
    attendance = _arrive(er)
    from app.models import EmergencyVisit

    with er["app"].app_context():
        assert er["db"].session.get(EmergencyVisit, attendance).treatment_only is None


# ============================================================ our doctor ==
def test_our_doctors_order_is_theirs_and_given_at_once(er):
    attendance = _arrive(er)
    assert _write(er, attendance, source="ours").status_code == 302
    [(oid, source, state, prescriber, _, asked)] = _orders(er, attendance)
    assert (source, state, prescriber, asked) == ("ours", "ready", er["ids"]["doctor"], False)
    assert er["sign_in"]("nurse").post(f"/emergency/order/{oid}/give").status_code == 302
    assert _orders(er, attendance)[0][2] == "given"


def test_a_nurse_cannot_write_an_order_of_our_own(er):
    attendance = _arrive(er)
    assert _write(er, attendance, who="nurse", source="ours").status_code == 403
    assert _orders(er, attendance) == []


# ======================================================= a hospital paper ==
def test_a_hospital_doctors_paper_is_given_at_once_in_their_name(er):
    attendance = _arrive(er, treatment_only="1")
    _write(er, attendance, who="nurse", source="hospital_rx",
           prescriber_id=er["ids"]["doc2"])
    [(oid, source, state, prescriber, _, asked)] = _orders(er, attendance)
    assert (source, state, prescriber) == ("hospital_rx", "ready", er["ids"]["doc2"])
    # Not on the rota now: it stays on the file, and nobody is asked.
    assert asked is False
    page = er["sign_in"]("nurse").get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert 'data-source="hospital_rx"' in page and "د. منى" in page
    assert "data-awaiting-confirmation" not in page
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/give")
    assert _orders(er, attendance)[0][2] == "given"


def test_a_paper_needs_a_doctor_of_ours_on_it(er):
    attendance = _arrive(er)
    _write(er, attendance, who="nurse", source="hospital_rx",
           prescriber_id=er["ids"]["nurse"])
    _write(er, attendance, who="nurse", source="hospital_rx")
    assert _orders(er, attendance) == []


def test_the_doctor_in_the_building_is_asked_to_confirm(er, monkeypatch):
    from app.models import User
    from app.utils import emergency_orders
    from app.utils.notifications import get_notifications

    monkeypatch.setattr(emergency_orders, "present_now",
                        lambda: {er["ids"]["doc2"]})
    attendance = _arrive(er)
    _write(er, attendance, who="nurse", source="hospital_rx",
           prescriber_id=er["ids"]["doc2"])
    [(oid, _, state, _, _, asked)] = _orders(er, attendance)
    assert asked is True and state == "ready", "confirming must not hold the dose"

    with er["app"].test_request_context():
        mona = er["db"].session.get(User, er["ids"]["doc2"])
        doc = er["db"].session.get(User, er["ids"]["doctor"])
        assert any(n["key"] == "er_confirm" for n in get_notifications(mona))
        assert not any(n["key"] == "er_confirm" for n in get_notifications(doc))

    # Only the doctor on the paper confirms it.
    assert er["sign_in"]("doc").post(f"/emergency/order/{oid}/confirm").status_code == 403
    mona_client = er["sign_in"]("doc2")
    listed = mona_client.get("/emergency/confirmations").get_data(as_text=True)
    assert f'data-mine-order="{oid}"' in listed
    assert mona_client.post(f"/emergency/order/{oid}/confirm").status_code == 302
    listed = mona_client.get("/emergency/confirmations").get_data(as_text=True)
    assert "data-none-mine" in listed


def test_a_doctor_entering_their_own_paper_is_not_asked(er, monkeypatch):
    from app.utils import emergency_orders

    monkeypatch.setattr(emergency_orders, "present_now",
                        lambda: {er["ids"]["doctor"]})
    attendance = _arrive(er)
    _write(er, attendance, who="doc", source="hospital_rx",
           prescriber_id=er["ids"]["doctor"])
    assert _orders(er, attendance)[0][5] is False


# ======================================================== an outside paper ==
def test_an_outside_paper_waits_for_one_of_our_doctors(er):
    from app.models import User
    from app.utils.notifications import get_notifications

    attendance = _arrive(er, treatment_only="1")
    assert _write(er, attendance, who="nurse", source="outside_rx",
                  outside_doctor="د. خالد (عيادة خاصة)").status_code == 302
    [(oid, source, state, prescriber, outside, _)] = _orders(er, attendance)
    assert (source, state, prescriber) == ("outside_rx", "waiting_doctor", None)
    assert outside == "د. خالد (عيادة خاصة)"

    nurse = er["sign_in"]("nurse")
    nurse.post(f"/emergency/order/{oid}/give")
    assert _orders(er, attendance)[0][2] == "waiting_doctor", "given before a doctor saw the child"
    assert nurse.post(f"/emergency/order/{oid}/approve").status_code == 403

    register = nurse.get("/emergency/register").get_data(as_text=True)
    assert "data-waiting-doctor" in register and "data-outside-waiting" in register
    with er["app"].test_request_context():
        doc = er["db"].session.get(User, er["ids"]["doctor"])
        nurse_user = er["db"].session.get(User, er["ids"]["nurse"])
        assert any(n["key"] == "er_outside" for n in get_notifications(doc))
        assert not any(n["key"] == "er_outside" for n in get_notifications(nurse_user))

    doctor = er["sign_in"]("doc")
    page = doctor.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert "data-approve" in page
    assert doctor.post(f"/emergency/order/{oid}/approve").status_code == 302
    assert _orders(er, attendance)[0][2] == "ready"
    nurse.post(f"/emergency/order/{oid}/give")
    assert _orders(er, attendance)[0][2] == "given"
    page = doctor.get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert "data-approved" in page and "د. خالد" in page


def test_an_outside_paper_needs_the_doctors_name(er):
    attendance = _arrive(er)
    _write(er, attendance, who="nurse", source="outside_rx", outside_doctor=" ")
    assert _orders(er, attendance) == []


# ========================================================= and afterwards ==
def test_nothing_new_on_a_child_who_has_left_and_what_was_given_stays(er):
    attendance = _arrive(er)
    _write(er, attendance, source="ours")
    [(oid, *_)] = _orders(er, attendance)
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/give")
    assert er["sign_in"]("nurse").post(f"/emergency/order/{oid}/cancel").status_code == 302
    assert _orders(er, attendance)[0][2] == "given", "a given dose was cancelled"
    er["sign_in"]("nurse").post(f"/emergency/depart/{attendance}",
                                data={"disposition": "home"})
    _write(er, attendance, source="ours", name="Paracetamol")
    assert len(_orders(er, attendance)) == 1


def test_a_cancelled_line_is_never_given(er):
    attendance = _arrive(er)
    _write(er, attendance, source="ours")
    [(oid, *_)] = _orders(er, attendance)
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/cancel", data={"reason": "غلط"})
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/give")
    assert _orders(er, attendance)[0][2] == "cancelled"


def test_a_given_treatment_is_the_care_the_record_asks_for(er):
    from app.models import EmergencyVisit
    from app.utils import emergency as util

    attendance = _arrive(er)
    with er["app"].app_context():
        assert "care" in util.missing(er["db"].session.get(EmergencyVisit, attendance))
    _write(er, attendance, source="ours")
    [(oid, *_)] = _orders(er, attendance)
    with er["app"].app_context():
        assert "care" in util.missing(er["db"].session.get(EmergencyVisit, attendance)), \
            "written is not given"
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/give")
    with er["app"].app_context():
        assert "care" not in util.missing(er["db"].session.get(EmergencyVisit, attendance))


# ============================================================ the tests ===
def test_a_test_from_the_attendance_lands_on_its_own_encounter(er):
    from app.models import EmergencyVisit, Investigation, Visit, VisitInvestigation

    with er["app"].app_context():
        cbc = Investigation(name_ar="صورة دم", kind="lab", is_active=True)
        er["db"].session.add(cbc)
        er["db"].session.commit()
        cbc_id = cbc.id
    attendance = _arrive(er)
    assert er["sign_in"]("nurse").post(
        f"/emergency/attendance/{attendance}/test",
        data={"investigation_id": cbc_id}).status_code == 403
    resp = er["sign_in"]("doc").post(f"/emergency/attendance/{attendance}/test",
                                     data={"investigation_id": cbc_id})
    assert resp.status_code == 302
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, attendance)
        visit = er["db"].session.get(Visit, row.visit_id)
        assert visit.channel == "emergency" and visit.status == "completed"
        order = VisitInvestigation.query.filter_by(visit_id=visit.id).one()
        assert order.ordered_by == er["ids"]["doctor"] and order.admission_id is None
    # A second test uses the same encounter.
    er["sign_in"]("doc").post(f"/emergency/attendance/{attendance}/test",
                              data={"name": "مزرعة دم"})
    with er["app"].app_context():
        assert Visit.query.filter_by(channel="emergency").count() == 1
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{attendance}").get_data(as_text=True)
    assert page.count("data-er-test=") == 2


# ============================================================ the doors ===
def test_none_of_it_without_the_emergency_module(er):
    from app.models import Setting

    attendance = _arrive(er)
    with er["app"].app_context():
        Setting.set("mod_enabled:emergency", "0")
        er["db"].session.commit()
    client = er["sign_in"]("doc")
    assert client.get(f"/emergency/attendance/{attendance}").status_code == 404
    assert client.get("/emergency/confirmations").status_code == 404
    assert _write(er, attendance, source="ours").status_code == 404


def test_the_order_right_alone_does_not_make_an_admin_a_doctor(er):
    """The fixture's admin holds every right but does not see patients: they
    may not write an order of their own, nor approve an outside paper."""
    attendance = _arrive(er)
    _write(er, attendance, who="boss", source="ours")
    assert _orders(er, attendance) == []
    _write(er, attendance, who="nurse", source="outside_rx", outside_doctor="د. خالد")
    [(oid, *_)] = _orders(er, attendance)
    er["sign_in"]("boss").post(f"/emergency/order/{oid}/approve")
    assert _orders(er, attendance)[0][2] == "waiting_doctor"


def test_in_the_building_means_present_not_on_call(er, monkeypatch):
    """Asked to confirm only if they could walk over and look — a doctor on
    call from home is not."""
    from types import SimpleNamespace

    import app.utils.on_call as on_call
    from app.utils import emergency_orders

    monkeypatch.undo()
    here = SimpleNamespace(doctor_id=11)
    home = SimpleNamespace(doctor_id=22)
    monkeypatch.setattr(on_call, "covering", lambda roles_only=True: [
        {"role": None, "present": [here], "on_call": [home]}])
    with er["app"].app_context():
        assert emergency_orders.present_now() == {11}
