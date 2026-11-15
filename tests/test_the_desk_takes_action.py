"""Customer service that takes action — through the desk's own door.

``HOSPITAL_PLAN.md`` ٦ «خدمة العملاء بالذكاء الاصطناعي، وهي بتاخد أكشن», on
the rules the plan agreed:

* the program reads what the family asked, says which word it caught, and
  puts the action in front of the person on the conversation — **it
  prepares, a person does**: nothing is cancelled and nothing is sent on its
  own;
* **with that person's permissions**: bookings for whoever reaches the
  appointments, a result's state for whoever reaches the laboratory or the
  medical file, the balance for whoever works the till — and the AI's draft
  is told only what that person could have seen;
* **a result's state, never its value.**
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    """The child with a booking tomorrow, a potassium ordered, and a bill
    with 150 still owed."""
    from app.extensions import db
    from app.models import (Appointment, Invoice, InvoiceItem, Payment,
                            VisitInvestigation)
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        ids = clinic["ids"]
        appt = Appointment(patient_id=ids["child"], doctor_id=ids["doctor"],
                           appt_date=local_today() + timedelta(days=1),
                           appt_time=time(17, 30), appt_type="followup",
                           status="scheduled")
        db.session.add(appt)
        test = VisitInvestigation(visit_id=ids["visit"],
                                  patient_id=ids["child"], kind="lab",
                                  name="بوتاسيوم", status="requested")
        db.session.add(test)
        inv = Invoice(invoice_number="INV-D1", patient_id=ids["child"],
                      invoice_date=local_today())
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=200, quantity=1))
        db.session.add(Payment(invoice_id=inv.id, amount=50, kind="payment",
                               method="cash"))
        db.session.commit()
        clinic["appt"], clinic["test"] = appt.id, test.id
    return clinic


def _chat(c, *bodies, phone="01000000001"):
    from app.extensions import db
    from app.models import MessageLog

    with c["app"].app_context():
        at = datetime.utcnow() - timedelta(minutes=30)
        db.session.add(MessageLog(direction="out", body="أهلاً بيكم",
                                  to_phone=phone, status="sent",
                                  patient_id=c["ids"]["child"], created_at=at))
        for i, body in enumerate(bodies):
            db.session.add(MessageLog(
                direction="in", body=body, to_phone=phone, status="received",
                patient_id=c["ids"]["child"],
                created_at=at + timedelta(minutes=i + 1)))
        db.session.commit()
    return f"p{c['ids']['child']}"


# ------------------------------------------------- reading the words ----
def test_what_the_family_asked_is_read_from_their_words():
    from app.utils.desk_actions import intents

    def names(text):
        return [i for i, _w in intents(text)]

    assert names("لو سمحت عايزة أُلغي الحجز بتاع بكرة") == ["cancel"]
    # «I can't come — another day?» is a move, not a cancellation.
    assert names("مش هقدر آجي بكرة، ممكن ميعاد تاني؟") == ["reschedule"]
    assert names("هي نتيجة التحليل طلعت؟") == ["result"]
    assert names("علينا كام لو سمحت") == ["balance"]
    assert names("صباح الخير") == []
    # The word it caught is said, so the person can see why.
    assert intents("عايزين نلغي")[0] == ("cancel", "نلغي")


# ------------------------------------------- with the person's rights ----
def test_reception_sees_bookings_and_balance_not_results(desk):
    key = _chat(desk, "هي النتيجة طلعت؟ وعلينا كام؟")
    page = desk["sign_in"]("desk").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    assert "data-desk-actions" in page
    assert 'data-desk-asked="result,balance"' in page
    assert f'data-desk-booking="{desk["appt"]}"' in page
    assert 'data-desk-balance="150.0"' in page
    # Reception reaches neither the laboratory nor the medical file.
    assert "data-desk-tests" not in page


def test_whoever_reaches_the_file_sees_the_state_never_the_value(desk):
    from app.extensions import db
    from app.models import VisitInvestigation

    key = _chat(desk, "النتيجة طلعت؟")
    page = desk["sign_in"]("boss").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    assert 'data-desk-test="waiting"' in page
    with desk["app"].app_context():
        test = db.session.get(VisitInvestigation, desk["test"])
        test.result_value, test.result_unit = 7.25, "mmol/L"
        test.status, test.resulted_at = "resulted", datetime.utcnow()
        db.session.commit()
    page = desk["sign_in"]("boss").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    assert 'data-desk-test="with_doctor"' in page
    assert "7.25" not in page
    with desk["app"].app_context():
        test = db.session.get(VisitInvestigation, desk["test"])
        test.doctor_seen_at = datetime.utcnow()
        db.session.commit()
    page = desk["sign_in"]("boss").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    assert 'data-desk-test="ready"' in page and "7.25" not in page


def test_the_panel_is_absent_for_what_you_could_not_do(desk):
    from app.extensions import db
    from app.models import Patient
    from app.utils import desk_actions

    class Nobody:
        is_authenticated = True
        can_collect = False

        def can_access(self, _module):
            return False

        def can(self, _cap):
            return False

    with desk["app"].app_context():
        kid = db.session.get(Patient, desk["ids"]["child"])
        got = desk_actions.panel(Nobody(), [kid], "عايزة ألغي")
        assert (got["bookings"], got["tests"], got["balance"]) == \
            (None, None, None)


# ------------------------------------------------- the person does it ----
def test_cancelling_is_a_press_and_the_reply_is_theirs_to_send(desk):
    from app.extensions import db
    from app.models import Appointment, MessageLog

    key = _chat(desk, "معلش عايزة ألغي ميعاد بكرة")
    with desk["app"].app_context():
        sent_before = MessageLog.query.filter_by(direction="out").count()
    client = desk["sign_in"]("desk")
    resp = client.post(f"/messages/inbox/{key}/cancel/{desk['appt']}",
                       data={"reason": ""})
    assert f"/messages/inbox/{key}" in resp.headers["Location"]
    with desk["app"].app_context():
        appt = db.session.get(Appointment, desk["appt"])
        assert appt.status == "cancelled"
        assert appt.cancel_reason        # «طلب الأهل من المحادثة»
        # Nothing went to the family: the sentence waits in the box.
        assert MessageLog.query.filter_by(direction="out").count() == \
            sent_before
        day = appt.appt_date.isoformat()
    page = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert day in page


def test_only_this_familys_booking(desk):
    from app.extensions import db
    from app.models import Appointment, Patient
    from app.utils.clock import local_today

    with desk["app"].app_context():
        other = Patient(patient_number="P9", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=900))
        db.session.add(other)
        db.session.flush()
        theirs = Appointment(patient_id=other.id,
                             doctor_id=desk["ids"]["doctor"],
                             appt_date=local_today() + timedelta(days=2),
                             appt_time=time(10, 0), appt_type="followup",
                             status="scheduled")
        db.session.add(theirs)
        db.session.commit()
        theirs_id = theirs.id
    key = _chat(desk, "ألغي")
    resp = desk["sign_in"]("desk").post(
        f"/messages/inbox/{key}/cancel/{theirs_id}")
    assert resp.status_code == 404
    with desk["app"].app_context():
        assert db.session.get(Appointment, theirs_id).status == "scheduled"


def test_the_ai_draft_is_told_only_what_the_person_could_see(desk):
    from app.extensions import db
    from app.models import Patient, Setting, User, VisitInvestigation
    from app.utils.service_desk import clinic_facts

    with desk["app"].app_context():
        Setting.set("ai_patient_context", "1")
        test = db.session.get(VisitInvestigation, desk["test"])
        test.result_value, test.status = 7.25, "resulted"
        db.session.commit()
        kid = db.session.get(Patient, desk["ids"]["child"])
        reception = db.session.get(User, desk["ids"]["desk"])
        boss = db.session.get(User, desk["ids"]["admin"])
        seen_by_desk = " ".join(clinic_facts(kid, user=reception))
        seen_by_boss = " ".join(clinic_facts(kid, user=boss))
        nobody = " ".join(clinic_facts(kid))
    assert "owes" in seen_by_desk and "بوتاسيوم" not in seen_by_desk
    assert "بوتاسيوم = with_doctor" in seen_by_boss
    assert "7.25" not in seen_by_boss
    assert "owes" not in nobody and "بوتاسيوم" not in nobody
