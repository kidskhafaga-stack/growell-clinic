"""The device studies board: ordered anywhere, booked when they need it, and
answered by the study itself.

Asked as *«الاجهزة الثانية موجوده لانها ممكن تتواجد فى اي عيادة زي … الايكو
قياس التنفس … وultra sound كل ده ممكن تبقى فى عيادة وممكن تجرى فى الاقسام
الداخلية»* and *«رسم المخ الى بيحتاج حجز ونوم»*. What is held here:

* a diagnostic order from a clinic visit and one from a ward bed are both on
  the board, the bed named;
* a study is booked for a day and an hour with what to do before it, and
  today's bookings come first, in time order; a booking is cleared;
* recording it opens the device the test is set to, and the study answers the
  order — performed, resulted, linked, and on the stay when done at a bed;
* the menu door shows only where the clinic does one of these or one is
  waiting — a clinic that does none sees the menu it had;
* the board is the visit's, not the lab's: it works with the lab switched off.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def room(clinic):
    from app.models import DeviceMeasurement, Investigation, MedicalDevice

    with clinic["app"].app_context():
        db = clinic["db"]
        eeg = MedicalDevice(name="جهاز رسم المخ", device_type="eeg", is_active=True)
        db.session.add(eeg)
        db.session.flush()
        db.session.add(DeviceMeasurement(device_id=eeg.id, name="النشاط الخلفي", sort_order=1))
        test = Investigation(name_ar="رسم مخ بعد حرمان من النوم", kind="diagnostic",
                             device_id=eeg.id, needs_booking=True,
                             preparation="ينام متأخر الليلة اللي قبلها", is_active=True)
        db.session.add(test)
        db.session.commit()
        clinic["ids"].update(eeg=eeg.id, eeg_test=test.id)
    return clinic


def _order(c, name="رسم مخ بعد حرمان من النوم", admission_id=None, minutes_ago=30):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = VisitInvestigation(visit_id=c["ids"]["visit"], patient_id=c["ids"]["child"],
                                 investigation_id=c["ids"]["eeg_test"], kind="diagnostic",
                                 name=name, status="requested", admission_id=admission_id,
                                 created_at=datetime.utcnow() - timedelta(minutes=minutes_ago))
        c["db"].session.add(row)
        c["db"].session.commit()
        return row.id


def _get(c, order_id):
    from app.models import VisitInvestigation

    with c["app"].app_context():
        row = c["db"].session.get(VisitInvestigation, order_id)
        return {"status": row.status, "booked": row.booked_for, "note": row.booking_note,
                "performed": row.performed_at is not None, "text": row.result_text,
                "sample": row.sample_code}


def test_ordered_from_a_visit_and_from_a_bed_both_wait_on_the_board(room):
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward

    with room["app"].app_context():
        db = room["db"]
        Setting.set("mod_enabled:beds", "1")
        unit = Unit(name="الداخلي", kind="ward")
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة 1", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="سرير 2", kind="bed")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, room["ids"]["child"]), bed)
        db.session.commit()
        stay_id = stay.id
    clinic_order = _order(room, name="إيكو قلب")
    bed_order = _order(room, admission_id=stay_id)
    page = room["sign_in"]("doc").get("/visits/studies/board").get_data(as_text=True)
    assert f'data-device-order="{clinic_order}"' in page
    assert f'data-device-order="{bed_order}"' in page
    assert "data-device-bed" in page and "سرير 2" in page
    assert "data-needs-booking" in page and "data-preparation" in page


def test_a_study_is_booked_and_todays_bookings_come_first(room):
    from app.utils import device_board
    from app.utils.clock import local_now

    first = _order(room, name="أول", minutes_ago=90)
    second = _order(room, name="تاني", minutes_ago=10)
    doc = room["sign_in"]("doc")
    later_today = (local_now() + timedelta(minutes=5))
    doc.post(f"/visits/studies/order/{second}/book",
             data={"date": later_today.strftime("%Y-%m-%d"),
                   "time": later_today.strftime("%H:%M"), "note": "ينام متأخر"})
    booked = _get(room, second)
    assert booked["booked"] is not None and booked["note"] == "ينام متأخر"
    with room["app"].app_context():
        assert [r.id for r in device_board.rows()][:2] == [second, first]

    doc.post(f"/visits/studies/order/{second}/book", data={"clear": "1"})
    assert _get(room, second)["booked"] is None and _get(room, second)["note"] is None


def test_a_booking_with_no_day_is_refused(room):
    order = _order(room)
    room["sign_in"]("doc").post(f"/visits/studies/order/{order}/book",
                                data={"date": "", "time": "10:00"})
    assert _get(room, order)["booked"] is None


def test_recording_it_opens_the_tests_device_and_answers_the_order(room):
    from app.models import DeviceStudy

    order = _order(room)
    doc = room["sign_in"]("doc")
    page = doc.get(f"/visits/studies/new/{room['ids']['child']}?order_id={order}").get_data(as_text=True)
    assert f'data-answers-order="{order}"' in page and "النشاط الخلفي" in page
    with room["app"].app_context():
        from app.models import DeviceMeasurement
        m = DeviceMeasurement.query.filter_by(device_id=room["ids"]["eeg"]).one()
        mid = m.id
    doc.post(f"/visits/studies/new/{room['ids']['child']}?device_id={room['ids']['eeg']}&order_id={order}",
             data={f"value_{mid}": "طبيعي", "conclusion": "رسم مخ طبيعي",
                   "study_date": datetime.utcnow().strftime("%Y-%m-%d")})
    after = _get(room, order)
    assert after["status"] == "resulted" and after["performed"]
    assert after["text"] == "رسم مخ طبيعي" and after["sample"] is None
    with room["app"].app_context():
        study = DeviceStudy.query.filter_by(order_id=order).one()
        assert study.device_id == room["ids"]["eeg"]
    page = doc.get("/visits/studies/board").get_data(as_text=True)
    assert f'data-device-order="{order}"' not in page


def test_a_study_done_at_a_bed_is_kept_on_the_stay(room):
    from app.models import DeviceStudy, MedicalDevice, Patient
    from app.models.place import Bed, Space, Unit
    from app.utils import beds as ward
    from app.utils import device_board

    with room["app"].app_context():
        db = room["db"]
        unit = Unit(name="الحضانة", kind="nicu")
        db.session.add(unit)
        db.session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        db.session.add(space)
        db.session.flush()
        bed = Bed(space_id=space.id, name="حضانة 1", kind="incubator")
        db.session.add(bed)
        db.session.flush()
        stay = ward.admit(db.session.get(Patient, room["ids"]["child"]), bed)
        db.session.commit()
        stay_id = stay.id
    order = _order(room, admission_id=stay_id)
    with room["app"].app_context():
        from app.models import VisitInvestigation
        db = room["db"]
        row = db.session.get(VisitInvestigation, order)
        study = DeviceStudy(patient_id=row.patient_id, device_id=room["ids"]["eeg"],
                            conclusion="")
        study.device = db.session.get(MedicalDevice, room["ids"]["eeg"])
        db.session.add(study)
        db.session.flush()
        with room["app"].test_request_context():
            device_board.answer(row, study)
        db.session.commit()
        assert study.admission_id == stay_id and study.order_id == order
        assert row.status == "resulted" and row.result_text


def test_the_door_shows_only_where_the_clinic_does_these(room):
    from app.models import Setting

    doc = room["sign_in"]("doc")
    assert "data-nav-devices" not in doc.get("/dashboard").get_data(as_text=True), \
        "a clinic that does none of these got a new menu item on upgrade"
    _order(room)
    assert "data-nav-devices" in doc.get("/dashboard").get_data(as_text=True)


def test_the_door_shows_for_a_clinic_that_said_it_does_echo(room):
    """Ticked in the setup wizard — the same function the wizard saves with."""
    from app.utils import facility

    with room["app"].app_context():
        facility.apply_facility("pediatric_center", None,
                                ["general_consultation", "echo"],
                                ["patients", "visits", "appointments"])
        room["db"].session.commit()
    assert "data-nav-devices" in room["sign_in"]("doc").get("/dashboard").get_data(as_text=True)


def test_the_board_is_the_visits_not_the_labs(room):
    from app.models import Setting

    with room["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        room["db"].session.commit()
    order = _order(room)
    page = room["sign_in"]("doc").get("/visits/studies/board").get_data(as_text=True)
    assert f'data-device-order="{order}"' in page


def test_the_catalogue_sets_a_studys_device_and_booking(room):
    from app.models import Investigation, Setting

    with room["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        row = Investigation(name_ar="إيكو", kind="diagnostic", is_active=True)
        room["db"].session.add(row)
        room["db"].session.commit()
        test_id = row.id
    boss = room["sign_in"]("boss")
    page = boss.get("/visits/studies/catalogue").get_data(as_text=True)
    assert "data-device-pick" in page
    boss.post(f"/visits/studies/catalogue/{test_id}", data={"name_ar": "إيكو", "is_active": "1",
                                               "in_house": "1", "device_id": str(room["ids"]["eeg"]),
                                               "needs_booking": "1"})
    with room["app"].app_context():
        row = room["db"].session.get(Investigation, test_id)
        assert row.device_id == room["ids"]["eeg"] and row.needs_booking is True


# ------------------------------------- what the clinic doctor must not lose --
@pytest.mark.parametrize("kind,name", [("lab", "صورة دم"), ("imaging", "أشعة صدر"),
                                       ("diagnostic", "إيكو قلب")])
def test_the_next_visit_still_shows_what_was_ordered_and_takes_its_result(room, kind, name):
    """«مش عايز افقد ميزة ان الطبيب لو طلب فى عيادة اشعة او تحليل يظهر فى
    الزيارة الى بعدها انه كان طالب … ويكتب النتيجة». With the lab and
    radiology modules both off — a clinic that sends everything out — an
    order from the last visit is on the next visit's screen, and the result
    the doctor types answers it."""
    from app.models import Setting, Visit, VisitInvestigation
    from app.utils.clock import local_today

    with room["app"].app_context():
        db = room["db"]
        Setting.set("mod_enabled:labs", "0")
        Setting.set("mod_enabled:imaging", "0")
        order = VisitInvestigation(visit_id=room["ids"]["visit"], patient_id=room["ids"]["child"],
                                   kind=kind, name=name, status="requested", done_outside=True)
        db.session.add(order)
        db.session.flush()
        later = Visit(patient_id=room["ids"]["child"], doctor_id=room["ids"]["doctor"],
                      visit_date=local_today(), status="open")
        db.session.add(later)
        db.session.commit()
        order_id, later_id = order.id, later.id
    doc = room["sign_in"]("doc")
    page = doc.get(f"/visits/{later_id}/record").get_data(as_text=True)
    assert name in page and f"/visits/investigations/{order_id}/result" in page
    doc.post(f"/visits/investigations/{order_id}/result",
             data={"result_text": "طبيعي", "result_comment": ""})
    with room["app"].app_context():
        row = room["db"].session.get(VisitInvestigation, order_id)
        assert row.status == "resulted" and row.result_text == "طبيعي"
