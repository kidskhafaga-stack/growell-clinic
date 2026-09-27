"""The urgent first, and a request from the chat — ``BOOKING_APPROVAL_PLAN.md``
stage two.

**The urgent does not wait for a model.** A written rule — the WhatsApp
inbox's own word list, approved for the clinic as it stands — puts a request
whose words say emergency above every other:

* it is the inbox's list, read through one function: an emergency is not
  decided two ways in one clinic;
* it only ever **raises**; a person may say a request is not urgent, or mark
  one urgent that the words missed — and who said it is kept and logged;
* the word the family used is shown marked inside their words, escaped;
* the desk sees the warning while still typing, from the same list;
* it tells the desk; it sends the family nothing.

**From the chat.** A family who asks for an appointment on WhatsApp is taken
from the thread they asked in: the child chosen, their words copied, and the
request then lives on the requests screen like any other — with the same
card, the same approval — while the thread shows where it stands.
"""
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    from app.extensions import db
    from app.models import DoctorSchedule, Setting, Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        doctor_id = db.session.get(Visit, clinic["ids"]["visit"]).doctor_id
        Setting.set("booking_approval", "reception")
        for weekday in range(7):
            db.session.add(DoctorSchedule(
                doctor_id=doctor_id, weekday=weekday, start_time=time(9, 0),
                end_time=time(17, 0), slot_minutes=30, is_active=True))
        db.session.commit()
    clinic["doctor_id"] = doctor_id
    clinic["tomorrow"] = local_today() + timedelta(days=1)
    return clinic


def _take(desk, message, **fields):
    data = {"patient_id": desk["ids"]["child"], "message": message}
    data.update(fields)
    desk["sign_in"]("desk").post("/appointments/requests", data=data)
    from app.models import BookingRequest

    with desk["app"].app_context():
        return BookingRequest.query.order_by(BookingRequest.id.desc()).first().id


def _order(desk):
    from app.utils import booking_requests

    with desk["app"].app_context():
        return [r.id for r in booking_requests.pending()]


def _page(desk, who="desk"):
    reply = desk["sign_in"](who).get("/appointments/requests")
    assert reply.status_code == 200
    return reply.get_data(as_text=True)


def _row(page, rid):
    row = page[page.index(f'data-request="{rid}"'):]
    return row[:row.index("</tr>")]


def _mark(desk, rid, value, who="desk"):
    return desk["sign_in"](who).post(f"/appointments/requests/{rid}/urgent",
                                     data={"urgent": value})


# ------------------------------------------------------------ the rule ----
def test_it_is_the_inboxs_own_list(desk):
    from app.utils import triage

    for word in ("تشنج", "مش بيتنفس", "seizure"):
        assert word in triage.URGENT_WORDS
        assert triage.urgent_word(f"الولد عنده {word} من الصبح") == word
    assert triage.urgent_word("عايزة ميعاد متابعة") is None
    # The inbox's behaviour is unchanged by sharing it.
    assert triage.suggest_topic("الولد عنده تشنجات") == "urgent"
    assert triage.suggest_topic("عايزة احجز ميعاد") == "appointment"


def test_the_urgent_go_first(desk):
    calm = _take(desk, "عايزة ميعاد متابعة")
    urgent = _take(desk, "الولد عنده تشنج من ساعة")
    assert _order(desk) == [urgent, calm]
    page = _page(desk)
    assert 'data-urgent-count="1"' in page
    assert page.index(f'data-request="{urgent}"') < page.index(
        f'data-request="{calm}"')
    row = _row(page, urgent)
    assert "rq-row--urgent" in row and 'data-urgent="yes"' in row
    assert "<mark>تشنج</mark>" in row


def test_the_word_is_marked_inside_escaped_words(desk):
    rid = _take(desk, "<b>تشنج</b> & <script>x</script>")
    row = _row(_page(desk), rid)
    assert "<script>x</script>" not in row
    assert "&lt;b&gt;<mark>تشنج</mark>&lt;/b&gt;" in row


def test_an_english_word_is_found_however_it_is_written(desk):
    rid = _take(desk, "He had a SEIZURE this morning")
    row = _row(_page(desk), rid)
    assert 'data-urgent="yes"' in row and "<mark>SEIZURE</mark>" in row


def test_a_person_says_it_is_not_urgent(desk):
    from app.extensions import db
    from app.models import ActivityLog, BookingRequest

    calm = _take(desk, "عايزة ميعاد متابعة")
    urgent = _take(desk, "بيتنفس بصعوبة")
    _mark(desk, urgent, "no")
    assert _order(desk) == [calm, urgent]
    row = _row(_page(desk), urgent)
    assert 'data-urgent="no"' in row and "rq-row--urgent" not in row
    assert "الاستقبال" in row                      # who said it is shown
    with desk["app"].app_context():
        r = db.session.get(BookingRequest, urgent)
        assert (r.urgent_mark, r.urgent_by) == ("no", desk["ids"]["desk"])
        log = ActivityLog.query.filter_by(action="booking_request.urgent").one()
        assert (log.entity_id, log.detail, log.user_id) == (
            urgent, "no", desk["ids"]["desk"])


def test_a_person_raises_one_the_words_missed(desk):
    first = _take(desk, "عايزة ميعاد")
    second = _take(desk, "الولد تعبان قوي")
    assert _order(desk) == [first, second]
    _mark(desk, second, "yes", who="doc")
    assert _order(desk) == [second, first]
    row = _row(_page(desk), second)
    assert 'data-urgent="yes"' in row and "د. أحمد" in row


def test_the_rule_only_raises(desk):
    """The program's guess puts a request up; it never takes a person's
    "urgent" down, and a person's "not urgent" stands against the words."""
    from app.extensions import db
    from app.models import BookingRequest
    from app.utils import booking_requests

    rid = _take(desk, "تشنج")
    with desk["app"].app_context():
        row = db.session.get(BookingRequest, rid)
        assert booking_requests.is_urgent(row)
        row.message = "عايزة ميعاد"
        row.urgent_mark = "yes"
        assert booking_requests.is_urgent(row)          # the person's word
        row.urgent_mark = None
        assert not booking_requests.is_urgent(row)      # nothing to go on
        row.message = "تشنج"
        row.urgent_mark = "no"
        assert not booking_requests.is_urgent(row)      # the person's word


def test_a_decided_request_is_not_marked(desk):
    from app.extensions import db
    from app.models import BookingRequest

    rid = _take(desk, "عايزة ميعاد")
    desk["sign_in"]("desk").post(f"/appointments/requests/{rid}/decline",
                                 data={"reason": "مفيش مكان"})
    _mark(desk, rid, "yes")
    with desk["app"].app_context():
        assert db.session.get(BookingRequest, rid).urgent_mark is None


def test_only_somebody_who_can_book_marks_one(desk):
    from app.extensions import db
    from app.models import BookingRequest

    rid = _take(desk, "عايزة ميعاد")
    reply = _mark(desk, rid, "yes", who="acct")
    assert reply.status_code in (302, 403)
    with desk["app"].app_context():
        assert db.session.get(BookingRequest, rid).urgent_mark is None


def test_the_doctor_asked_to_approve_sees_the_urgent_first(desk):
    from app.models import Setting

    with desk["app"].app_context():
        Setting.set("booking_approval", "both")
        desk["db"].session.commit()
    calm = _take(desk, "متابعة", doctor_id=desk["doctor_id"])
    urgent = _take(desk, "حرارة 40 ومش بيفوق", doctor_id=desk["doctor_id"])
    for rid in (calm, urgent):
        desk["sign_in"]("desk").post(f"/appointments/requests/{rid}/forward")
    page = _page(desk, who="doc")
    assert page.index(f'data-mine="{urgent}"') < page.index(f'data-mine="{calm}"')


def test_the_desk_is_warned_while_typing(desk):
    page = _page(desk)
    form = page[page.index("data-request-form"):]
    form = form[:form.index("</form>")]
    assert "data-live-urgent" in form and 'x-model="note"' in form
    import json

    from app.utils.triage import URGENT_WORDS

    assert "window.GC_URGENT_WORDS" in page
    # The page carries the same list the server reads, word for word.
    listed = page[page.index("window.GC_URGENT_WORDS = ") + 25:]
    listed = json.loads(listed[:listed.index(";")])
    assert listed == list(URGENT_WORDS)


def test_nothing_is_sent_to_the_family(desk):
    from app.models import MessageLog

    _take(desk, "تشنج")
    with desk["app"].app_context():
        assert MessageLog.query.count() == 0


def test_the_progress_line(desk):
    from app.models import Setting

    rid = _take(desk, "متابعة")
    row = _row(_page(desk), rid)
    assert 'data-steps="taken:current,booked:todo"' in row
    with desk["app"].app_context():
        Setting.set("booking_approval", "both")
        desk["db"].session.commit()
    rid2 = _take(desk, "متابعة", doctor_id=desk["doctor_id"])
    desk["sign_in"]("desk").post(f"/appointments/requests/{rid2}/forward")
    row = _row(_page(desk), rid2)
    assert ('data-steps="taken:done,with_doctor:current,approved:todo,'
            'booked:todo"') in row


# ------------------------------------------------------------ the chat ----
def _chat(desk, phone="01000000001", patient=True, bodies=("عايزة ميعاد",),
          before=()):
    from app.extensions import db
    from app.models import MessageLog

    with desk["app"].app_context():
        at = datetime.utcnow() - timedelta(minutes=30)
        for i, body in enumerate(before):
            db.session.add(MessageLog(
                direction="in", body=body, to_phone=phone, status="received",
                patient_id=desk["ids"]["child"] if patient else None,
                created_at=at - timedelta(minutes=60 - i)))
        db.session.add(MessageLog(direction="out", body="أهلاً بيكم",
                                  to_phone=phone, status="sent",
                                  patient_id=desk["ids"]["child"] if patient else None,
                                  created_at=at))
        for i, body in enumerate(bodies):
            db.session.add(MessageLog(
                direction="in", body=body, to_phone=phone, status="received",
                patient_id=desk["ids"]["child"] if patient else None,
                created_at=at + timedelta(minutes=i + 1)))
        db.session.commit()
    return f"p{desk['ids']['child']}" if patient else phone


def test_the_thread_offers_the_request_already_filled(desk):
    key = _chat(desk, bodies=("السلام عليكم", "عايزة ميعاد للولد بكرة"),
                before=("الكشف بكام؟",))
    page = desk["sign_in"]("desk").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    form = page[page.index("data-from-chat-form"):]
    form = form[:form.index("</form>")]
    assert f'name="conversation" value="{key}"' in form
    assert 'name="source" value="whatsapp"' in form
    assert f'name="patient_id" value="{desk["ids"]["child"]}"' in form
    # The family's words since the desk last wrote, not the whole history —
    # read from what the form opens with, not from the chat beside it.
    import html
    import json

    box = page[page.index("data-from-chat\n"):]
    box = box[box.index("note: ") + 6:]
    note = json.loads(html.unescape(box[:box.index(",\n")]))
    assert note == "السلام عليكم\nعايزة ميعاد للولد بكرة"
    assert "data-type-chips" in form and "data-when-chips" in form


def test_taken_from_the_chat_and_back_to_it(desk):
    from app.models import BookingRequest

    key = _chat(desk)
    reply = desk["sign_in"]("desk").post("/appointments/requests", data={
        "patient_id": desk["ids"]["child"], "message": "عايزة ميعاد",
        "source": "whatsapp", "conversation": key,
        "appt_type": "followup"})
    assert reply.headers["Location"].endswith(f"/messages/inbox/{key}")
    with desk["app"].app_context():
        row = BookingRequest.query.one()
        assert (row.source, row.conversation_key, row.patient_id) == (
            "whatsapp", key, desk["ids"]["child"])
        rid = row.id
    # The thread shows where it stands; the requests screen says where it
    # came from, with the same card as any other.
    thread = desk["sign_in"]("desk").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    assert f'data-conv-request="{rid}"' in thread
    assert 'data-steps="taken:current,booked:todo"' in thread
    row = _row(_page(desk), rid)
    assert 'data-source="whatsapp"' in row
    assert f'data-request-card="{rid}"' in row


def test_an_unknown_number_leaves_a_name_and_that_number(desk):
    from app.models import BookingRequest

    key = _chat(desk, phone="01099999999", patient=False)
    page = desk["sign_in"]("desk").get(f"/messages/inbox/{key}") \
        .get_data(as_text=True)
    form = page[page.index("data-from-chat-form"):]
    assert 'value="01099999999"' in form[:form.index("</form>")]
    desk["sign_in"]("desk").post("/appointments/requests", data={
        "contact_name": "أم يوسف", "contact_phone": "01099999999",
        "message": "تشنج", "source": "whatsapp", "conversation": key})
    with desk["app"].app_context():
        row = BookingRequest.query.one()
        assert (row.contact_name, row.conversation_key) == ("أم يوسف", key)
    # And an urgent word from the chat is urgent on the screen.
    assert 'data-urgent="yes"' in _row(_page(desk), row.id)


def test_a_source_nobody_knows_is_the_desk(desk):
    from app.models import BookingRequest

    desk["sign_in"]("desk").post("/appointments/requests", data={
        "patient_id": desk["ids"]["child"], "source": "carrier-pigeon"})
    with desk["app"].app_context():
        assert BookingRequest.query.one().source == "desk"


def test_the_request_follows_the_number_onto_the_childs_file(desk):
    """Taken while the number was unknown; the number is then put on the
    child's file and the thread becomes the child's — the request is still
    shown on it."""
    from app.models import BookingRequest

    key = _chat(desk, phone="01099999999", patient=False)
    desk["sign_in"]("desk").post("/appointments/requests", data={
        "contact_name": "أم يوسف", "contact_phone": "01099999999",
        "message": "عايزة ميعاد", "source": "whatsapp", "conversation": key})
    with desk["app"].app_context():
        rid = BookingRequest.query.one().id
    desk["sign_in"]("desk").post(f"/messages/inbox/{key}/link",
                                 data={"patient_id": desk["ids"]["child"]})
    thread = desk["sign_in"]("desk").get(
        f"/messages/inbox/p{desk['ids']['child']}").get_data(as_text=True)
    assert f'data-conv-request="{rid}"' in thread
