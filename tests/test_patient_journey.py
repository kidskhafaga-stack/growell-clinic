"""One child, one day, straight through the clinic — and the ways it forks.

A patient does not live inside a module. They are booked at the desk, weighed
at the station, examined in the room, sent out for an X-ray and a blood test,
and then two days later the mother photographs the report at the lab and sends
it on WhatsApp. Every one of those steps is a different part of the program,
and the joins between them are where things fall on the floor: vitals that
never reach the growth chart, an order nobody can find again, a film that
arrives and is filed under nothing.

Each module's own rules are tested elsewhere. What's walked here is the
handover — and the forks a real day takes: the walk-in with no slot left, the
number nobody recognises, the result that arrives before the follow-up, the
test the doctor typed because it isn't in the catalogue.
"""
from datetime import date, timedelta

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 400
PDF = b"%PDF-1.4\n" + b"x" * 400


# --------------------------------------------------------------- helpers --
@pytest.fixture()
def journey(clinic, tmp_path):
    """The shared clinic, plus a mother with a phone and somewhere to write.

    The uploads folder is redirected into the test's own directory: a test
    that files an X-ray must not write into the developer's static folder.
    """
    static = tmp_path / "static"
    (static / "uploads" / "patient_docs").mkdir(parents=True)
    clinic["app"].static_folder = str(static)

    with clinic["app"].app_context():
        from datetime import time

        from app.models import DoctorSchedule, Family, Parent, Patient

        # Clinic hours every day of the week. Without them the doctor has no
        # slots and every booking is refused — correctly, but it would make
        # this whole file a test of the empty-schedule case.
        for weekday in range(7):
            clinic["db"].session.add(DoctorSchedule(
                doctor_id=clinic["ids"]["doctor"], weekday=weekday,
                start_time=time(9, 0), end_time=time(17, 0),
                slot_minutes=15, is_active=True))

        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        family = Family(family_name="عائلة خفاجة")
        clinic["db"].session.add(family)
        clinic["db"].session.flush()
        clinic["db"].session.add(Parent(family_id=family.id, full_name="الأم",
                                        relation="mother", phone="01000000001"))
        child.family_id = family.id
        clinic["db"].session.commit()
    clinic["static"] = static
    return clinic


def _inbound(journey, text, media=True, phone="01000000001", mime="image/png",
             data=PNG):
    """The mother sends a message — with a file on it unless told otherwise."""
    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    original = wa_media.download
    wa_media.download = lambda m, cfg=None: (data, mime)
    try:
        with journey["app"].app_context():
            result = handle_inbound(
                {"from_phone": phone, "text": text,
                 "media": {"id": "m1"} if media else None}, "meta")
            journey["db"].session.commit()
            return result
    finally:
        wa_media.download = original


def _attachments(journey):
    from app.models import PatientAttachment

    with journey["app"].app_context():
        return [{"patient": a.patient_id, "kind": a.kind, "label": a.label,
                 "file": a.filename}
                for a in PatientAttachment.query.order_by(PatientAttachment.id).all()]


def _orders(journey):
    from app.models import VisitInvestigation

    with journey["app"].app_context():
        return [{"id": o.id, "kind": o.kind, "name": o.name,
                 "status": o.status, "result": o.result_text}
                for o in VisitInvestigation.query
                .order_by(VisitInvestigation.id).all()]


def _order(doctor, journey, name="أشعة صدر", kind="imaging", **extra):
    data = {"name_ar": name, "kind": kind}
    data.update(extra)
    return doctor.post(f"/visits/{journey['ids']['visit']}/investigations",
                       data=data, follow_redirects=True)


# ============================================ 1. the desk: getting seen ====
def test_a_booking_puts_the_child_on_the_doctors_day(journey):
    from app.models import Appointment

    desk = journey["sign_in"]("desk")
    desk.post("/appointments/new", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"],
        "appt_date": (date.today() + timedelta(days=1)).isoformat(),
        "appt_time": "10:00", "appt_type": "consultation",
        "reason": "كحة وسخونية"}, follow_redirects=True)
    with journey["app"].app_context():
        appt = Appointment.query.one()
        assert appt.status == "scheduled"
        assert appt.reason == "كحة وسخونية"


def test_a_walk_in_is_seen_today_even_with_no_slot_left(journey):
    """A sick child at the door isn't turned away because the grid is full —
    they're overbooked at the current time and marked waiting."""
    from app.models import Appointment

    desk = journey["sign_in"]("desk")
    desk.post("/appointments/walk-in", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"],
        "appt_type": "consultation"}, follow_redirects=True)
    with journey["app"].app_context():
        appt = Appointment.query.one()
        assert appt.is_walk_in is True
        assert appt.status == "waiting"
        assert appt.appt_date == date.today()


def test_a_paused_clinic_stops_reception_but_not_the_manager(journey):
    """The doctor closed booking. Reception can't push one through; an
    emergency add by an admin still can."""
    from app.models import Appointment, Setting

    with journey["app"].app_context():
        Setting.set("clinic_booking_open", "0")
        journey["db"].session.commit()

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    form = {"patient_id": journey["ids"]["child"],
            "doctor_id": journey["ids"]["doctor"], "appt_date": tomorrow,
            "appt_time": "10:00", "appt_type": "consultation"}

    journey["sign_in"]("desk").post("/appointments/new", data=form,
                                    follow_redirects=True)
    with journey["app"].app_context():
        assert Appointment.query.count() == 0

    journey["sign_in"]("boss").post("/appointments/new", data=form,
                                    follow_redirects=True)
    with journey["app"].app_context():
        assert Appointment.query.count() == 1


# ================================ 2. the station: weighed before the room ==
def test_the_nurses_measurements_reach_the_growth_chart(journey):
    """Weighing a child twice — once for the visit, once for the chart — is
    how the two disagree. The station writes one set of numbers."""
    from app.models import Appointment, GrowthRecord, Visit

    desk = journey["sign_in"]("desk")
    desk.post("/appointments/walk-in", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"],
        "appt_type": "consultation"}, follow_redirects=True)
    with journey["app"].app_context():
        appt_id = Appointment.query.one().id

    nurse = journey["sign_in"]("doc")
    nurse.post(f"/visits/station/{appt_id}/vitals", data={
        "weight_kg": "9.5", "height_cm": "75", "temperature_c": "38.4",
        "pulse_bpm": "120"}, follow_redirects=True)

    with journey["app"].app_context():
        # One encounter, not two: the child already had an open visit, so the
        # station writes into it rather than opening a second one beside it.
        visit = Visit.query.filter_by(patient_id=journey["ids"]["child"],
                                      status="open").one()
        assert visit.vitals.temperature_c == 38.4
        record = GrowthRecord.query.filter_by(visit_id=visit.id).one()
        assert record.weight_kg == 9.5 and record.height_cm == 75.0
        assert record.bmi is not None


def test_correcting_the_weight_corrects_the_chart_too(journey):
    """The scale was misread and re-entered. That must fix the chart point,
    not leave two contradicting dots on the same day."""
    from app.models import Appointment, GrowthRecord

    desk = journey["sign_in"]("desk")
    desk.post("/appointments/walk-in", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"],
        "appt_type": "consultation"}, follow_redirects=True)
    with journey["app"].app_context():
        appt_id = Appointment.query.one().id

    nurse = journey["sign_in"]("doc")
    nurse.post(f"/visits/station/{appt_id}/vitals",
               data={"weight_kg": "19.5"}, follow_redirects=True)
    nurse.post(f"/visits/station/{appt_id}/vitals",
               data={"weight_kg": "9.5"}, follow_redirects=True)

    with journey["app"].app_context():
        records = GrowthRecord.query.all()
        assert len(records) == 1
        assert records[0].weight_kg == 9.5


# ================================= 3. the room: the examination and orders =
def test_the_doctor_orders_an_xray_and_a_blood_test(journey):
    """Both go on the visit as *requested* — an order with no result yet is
    the thing the follow-up has to be able to find."""
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة صدر", "imaging")
    _order(doctor, journey, "صورة دم كاملة", "lab")

    orders = _orders(journey)
    assert [o["kind"] for o in orders] == ["imaging", "lab"]
    assert all(o["status"] == "requested" for o in orders)
    assert all(o["result"] is None for o in orders)


def test_an_order_needs_a_name(journey):
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, name="", kind="lab")
    assert _orders(journey) == []


def test_an_unknown_kind_is_treated_as_a_lab_test(journey):
    """Rather than refusing the order and losing it."""
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "حاجة غريبة", kind="telepathy")
    assert _orders(journey)[0]["kind"] == "lab"


def test_a_test_the_doctor_typed_can_join_the_catalogue(journey):
    """So the next doctor picks it from the list instead of typing it again —
    and typing the same one twice doesn't create two entries."""
    from app.models import Investigation

    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة مقطعية على الصدر", "imaging",
           add_to_catalog="1")
    _order(doctor, journey, "أشعة مقطعية على الصدر", "imaging",
           add_to_catalog="1")

    with journey["app"].app_context():
        rows = Investigation.query.filter_by(name_ar="أشعة مقطعية على الصدر").all()
        assert len(rows) == 1


def test_an_order_can_be_taken_back(journey):
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey)
    order_id = _orders(journey)[0]["id"]
    doctor.post(f"/visits/investigations/{order_id}/delete", follow_redirects=True)
    assert _orders(journey) == []


# =========================== 4. the patient sends the result to the clinic =
def test_the_xray_the_mother_sends_lands_in_the_childs_file(journey):
    """She photographs the report at the lab and sends it on WhatsApp. The
    program used to notice a file had arrived, write "[media]" and throw it
    away."""
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة صدر", "imaging")

    result = _inbound(journey, "أشعة الصدر بتاعت أحمد")
    assert result["matched"] is True
    assert result["attachment"] is True

    filed = _attachments(journey)
    assert len(filed) == 1
    assert filed[0]["patient"] == journey["ids"]["child"]
    assert filed[0]["kind"] == "imaging"


def test_what_she_wrote_decides_which_tab_it_goes_under(journey):
    """Nobody sorts these by hand. "تحليل" is a lab result, "أشعة" is a film,
    and a PDF with neither word is a report."""
    _inbound(journey, "تحليل الدم")
    _inbound(journey, "الأشعة")
    _inbound(journey, "تقرير الدكتور", mime="application/pdf", data=PDF)

    assert [a["kind"] for a in _attachments(journey)] == ["lab", "imaging",
                                                          "report"]


def test_a_number_nobody_recognises_is_not_guessed_onto_a_record(journey):
    """A stranger's file must never be attached to a child. The message is
    kept — somebody can look at it — but no record is touched."""
    from app.models import MessageLog

    result = _inbound(journey, "أشعة", phone="01555555555")
    assert result["matched"] is False
    assert _attachments(journey) == []
    with journey["app"].app_context():
        log = MessageLog.query.order_by(MessageLog.id.desc()).first()
        assert log.patient_id is None
        assert log.image_url, "the file is kept with the message"


def test_a_message_with_no_file_files_nothing(journey):
    result = _inbound(journey, "الدكتور موجود امتى؟", media=False)
    assert result["attachment"] is False
    assert _attachments(journey) == []


def test_a_file_type_nobody_asked_for_is_not_written_to_disk(journey):
    """The documents folder is served over the web. Whatever the sender
    declares, only the handful of types the clinic actually uses are kept."""
    result = _inbound(journey, "أشعة", mime="application/x-msdownload",
                      data=b"MZ" + b"x" * 100)
    assert result["attachment"] is False
    assert _attachments(journey) == []


def test_the_result_arrives_before_anyone_asks_for_it(journey):
    """Parents send things unprompted. It still belongs on the file."""
    result = _inbound(journey, "تحليل الصديد")
    assert result["attachment"] is True
    assert _attachments(journey)[0]["kind"] == "lab"


# ================================ 5. the follow-up: the doctor reads it ====
def test_the_pending_order_is_waiting_at_the_next_visit(journey):
    """Two days later the child comes back. The X-ray ordered last time has
    to be in front of the doctor — an order nobody can find again is an order
    that never happened."""
    from app.models import Visit

    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة صدر", "imaging")

    with journey["app"].app_context():
        follow_up = Visit(patient_id=journey["ids"]["child"],
                          doctor_id=journey["ids"]["doctor"],
                          visit_date=date.today())
        journey["db"].session.add(follow_up)
        journey["db"].session.commit()
        follow_up_id = follow_up.id

    body = doctor.get(f"/visits/{follow_up_id}/record").get_data(as_text=True)
    assert "أشعة صدر" in body


def test_writing_the_result_closes_the_order(journey):
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "صورة دم كاملة", "lab")
    order_id = _orders(journey)[0]["id"]

    doctor.post(f"/visits/investigations/{order_id}/result", data={
        "result_text": "Hb 11.2 — WBC 8.4",
        "result_comment": "طبيعي، مفيش أنيميا"}, follow_redirects=True)

    order = _orders(journey)[0]
    assert order["status"] == "resulted"
    assert "Hb 11.2" in order["result"]


def test_clearing_a_result_reopens_the_order(journey):
    """It was pasted onto the wrong test. Emptying it must put the order back
    on the pending list, not leave it closed and blank."""
    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "صورة دم كاملة", "lab")
    order_id = _orders(journey)[0]["id"]

    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": "Hb 11.2"}, follow_redirects=True)
    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": ""}, follow_redirects=True)

    assert _orders(journey)[0]["status"] == "requested"


def test_a_resulted_order_stops_being_pending(journey):
    """Once it has an answer it comes off the outstanding list — otherwise
    every visit accumulates a longer list of things already dealt with, and
    the doctor stops reading it."""
    from app.models import Visit

    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة صدر", "imaging")
    order_id = _orders(journey)[0]["id"]

    with journey["app"].app_context():
        follow_up = Visit(patient_id=journey["ids"]["child"],
                          doctor_id=journey["ids"]["doctor"],
                          visit_date=date.today())
        journey["db"].session.add(follow_up)
        journey["db"].session.commit()
        follow_up_id = follow_up.id

    before = doctor.get(f"/visits/{follow_up_id}/record").get_data(as_text=True)
    assert "أشعة صدر" in before, "it should be outstanding before it is answered"

    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": "صدر سليم"}, follow_redirects=True)
    after = doctor.get(f"/visits/{follow_up_id}/record").get_data(as_text=True)
    assert "أشعة صدر" not in after


# ================================================ 6. the whole way through =
def test_one_child_from_the_door_to_the_till(journey):
    """The join, end to end: booked, weighed, examined, sent for an X-ray,
    the film arrives on WhatsApp, the doctor reads it, and the visit is paid
    for. Every step is a different module; this is the handover between them.
    """
    from app.models import Appointment, GrowthRecord, Invoice, Visit

    # --- the desk books him in
    desk = journey["sign_in"]("desk")
    desk.post("/appointments/walk-in", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"],
        "appt_type": "consultation", "reason": "كحة"}, follow_redirects=True)
    with journey["app"].app_context():
        appt_id = Appointment.query.one().id

    # --- the station weighs him
    doctor = journey["sign_in"]("doc")
    doctor.post(f"/visits/station/{appt_id}/vitals", data={
        "weight_kg": "9.5", "height_cm": "75", "temperature_c": "38.4"},
        follow_redirects=True)
    with journey["app"].app_context():
        visit_id = Visit.query.filter_by(patient_id=journey["ids"]["child"],
                                         status="open").one().id
        assert GrowthRecord.query.filter_by(visit_id=visit_id).count() == 1

    # --- the room: a procedure and an X-ray order
    doctor.post(f"/visits/{visit_id}/services",
                data={"service_id": journey["ids"]["nebul"], "quantity": "1"},
                follow_redirects=True)
    doctor.post(f"/visits/{visit_id}/investigations",
                data={"name_ar": "أشعة صدر", "kind": "imaging"},
                follow_redirects=True)

    # --- the mother sends the film home
    assert _inbound(journey, "أشعة الصدر")["attachment"] is True
    assert _attachments(journey)[0]["kind"] == "imaging"

    # --- the doctor reads it
    order_id = _orders(journey)[0]["id"]
    doctor.post(f"/visits/investigations/{order_id}/result",
                data={"result_text": "التهاب شعبي"}, follow_redirects=True)
    assert _orders(journey)[0]["status"] == "resulted"

    # --- the till collects, and the procedure is on the bill
    desk.post("/finance/shift/open", data={"opening_float": "0"},
              follow_redirects=True)
    body = desk.get(f"/finance/invoices/new?visit_id={visit_id}").get_data(
        as_text=True)
    assert "تنفس" in body

    desk.post("/finance/invoices/new", data={
        "patient_id": journey["ids"]["child"],
        "doctor_id": journey["ids"]["doctor"], "visit_id": visit_id,
        "line_service_id": [str(journey["ids"]["exam"]),
                            str(journey["ids"]["nebul"])],
        "line_description": ["كشف", "جلسة تنفس"],
        "line_unit_price": ["200", "150"], "line_quantity": ["1", "1"],
        "line_vs_id": ["", ""]}, follow_redirects=True)
    with journey["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.total == 350.0
        desk.post(f"/finance/invoices/{invoice.id}/payment",
                  data={"amount": "350", "method": "cash"},
                  follow_redirects=True)

    with journey["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.status == "paid"
        assert invoice.balance == 0.0


def test_the_file_the_mother_sent_is_readable_from_the_childs_record(journey):
    """Filed and then unreachable is the same as lost."""
    from app.models import PatientAttachment

    _inbound(journey, "أشعة الصدر")
    doctor = journey["sign_in"]("doc")
    body = doctor.get(f"/patients/{journey['ids']['child']}").get_data(as_text=True)
    with journey["app"].app_context():
        stored = PatientAttachment.query.one().filename
    assert stored in body


# ------------------------------------------------------ a known weak join --
@pytest.mark.xfail(strict=True, reason=(
    "Known gap: an inbound result is filed on the patient but not linked to "
    "the order it answers, so the X-ray can arrive while its order still "
    "reads 'requested'. Remove the marker when capture() attaches to a "
    "matching pending investigation."))
def test_the_arriving_result_answers_the_order_that_asked_for_it(journey):
    """The doctor asked for a chest X-ray; the mother sent one. Nothing joins
    the two: the file sits in documents and the order stays pending, so the
    follow-up screen still shows it as outstanding and somebody has to
    remember. Filing the film against the order it answers is the whole point
    of having ordered it in the program."""
    from app.models import PatientAttachment

    doctor = journey["sign_in"]("doc")
    _order(doctor, journey, "أشعة صدر", "imaging")
    _inbound(journey, "أشعة الصدر")

    with journey["app"].app_context():
        attachment = PatientAttachment.query.one()
        assert getattr(attachment, "investigation_id", None) is not None
