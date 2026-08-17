"""The customer-service tab opened in a settings screen.

`MODULE_ENDPOINTS` pointed `messages` at `messages.occasions` — the hub where
the WhatsApp connection and the message templates are configured. So somebody
whose job is answering people all day arrived there every morning. Reported
as: the customer-service tab is almost all settings.

Almost nothing here is new work. Every block on the desk is a question that
already had an answer somewhere in this blueprint; they were spread over five
screens with no front door between them.

The other half is who may do what. A desk answers people, sends the birthday
message and chases a failed delivery; it does not repoint the clinic's
WhatsApp connection or rewrite the text that goes out under the clinic's name
to everybody. That is a capability, not a role — so a small clinic gives
reception the module and nothing changes, and a large one hires a
customer-service desk and separates the two by granting one capability to one
person, rather than rebuilding anything.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's clock, not the machine's. `datetime.date.today()` is UTC
# and the program runs on the clinic's timezone; at 21:00 UTC in Cairo
# those are different days. This file used both, and the full suite
# caught it by running across that boundary: a birthday built for
# "today" read as yesterday's and vanished off the list.
from app.utils.clock import local_today  # noqa: E402

WORK_SCREENS = ["/messages/desk", "/messages/", "/messages/inbox",
                "/messages/service", "/messages/recall", "/messages/roster",
                "/messages/satisfaction", "/messages/quick-replies"]
SETUP_SCREENS = ["/messages/occasions", "/messages/survey"]


def _inbound(clinic, hours_ago=5, body="عندي سؤال عن الجرعة"):
    from app.extensions import db
    from app.models import MessageLog, Patient

    kid = Patient.query.first()
    db.session.add(MessageLog(
        patient_id=kid.id, to_phone=kid.contact_phone or "01000000000",
        direction="in", body=body, status="sent",
        created_at=datetime.utcnow() - timedelta(hours=hours_ago)))
    return kid


# ------------------------------------------------------------ the front door

def test_the_module_opens_on_the_desk_not_on_the_settings(clinic):
    """The one line that caused the complaint.

    Asserted through the sidebar rather than the mapping, because the sidebar
    is what somebody actually presses — a mapping that is right and a link
    that is wrong would pass the other way round.
    """
    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()
    nav = page[page.index('class="sidebar__nav'):]
    nav = nav[:nav.index("</nav>")]

    assert 'href="/messages/desk"' in nav, \
        "the customer-service tab does not lead to the desk"
    assert "/messages/occasions" not in nav, \
        "the customer-service tab still opens in a settings screen"


def test_the_desk_opens_for_the_people_who_sit_at_it(clinic):
    for who in ("desk", "boss"):
        answer = clinic["sign_in"](who).get("/messages/desk")
        assert answer.status_code == 200, f"{who} cannot open the desk"


# ------------------------------------------- doing the job vs setting it up

def test_reception_can_reach_every_working_screen(clinic):
    client = clinic["sign_in"]("desk")

    for url in WORK_SCREENS:
        assert client.get(url).status_code == 200, \
            f"reception is locked out of {url}, which is work, not setup"


def test_reception_cannot_reach_the_settings(clinic):
    """The connection and the templates go out under the clinic's name."""
    client = clinic["sign_in"]("desk")

    for url in SETUP_SCREENS:
        assert client.get(url).status_code == 403, \
            f"reception can configure customer service through {url}"


def test_the_manager_can_reach_both(clinic):
    client = clinic["sign_in"]("boss")

    for url in WORK_SCREENS + SETUP_SCREENS:
        assert client.get(url).status_code == 200, f"the admin is locked out of {url}"


def test_the_capability_is_not_granted_to_reception_by_the_role(clinic):
    from app.models.permissions import CAPABILITIES, role_has_capability

    assert "messages_setup" in CAPABILITIES
    assert role_has_capability("admin", "messages_setup")
    assert not role_has_capability("reception", "messages_setup")
    assert not role_has_capability("doctor", "messages_setup")


def test_the_settings_link_is_hidden_from_whoever_cannot_use_it(clinic):
    """A button that only ever answers 403 is worse than no button."""
    desk_page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()
    boss_page = clinic["sign_in"]("boss").get("/messages/desk").data.decode()

    assert "/messages/occasions" not in desk_page.replace(
        "/messages/occasions/birthday", ""), \
        "reception is shown a link to a screen it cannot open"
    assert "/messages/occasions" in boss_page, \
        "the manager has no way to reach the settings from the desk"


def test_no_working_screen_sends_reception_to_a_wall(clinic):
    """Every link on a screen reception may open has to be one they may follow.

    The hub links on the send log, the inbox and the satisfaction screen all
    pointed at the settings, which reception can no longer open.
    """
    client = clinic["sign_in"]("desk")

    for url in WORK_SCREENS:
        page = client.get(url).data.decode()
        page = page.replace("/messages/occasions/birthday", "")
        assert "/messages/occasions" not in page, \
            f"{url} links reception to the settings hub"


def test_the_birthday_bell_points_at_the_desk(clinic):
    """It pointed at the hub, which reception can no longer open."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.notifications import get_notifications
    from app.models import User

    with clinic["app"].app_context():
        kid = Patient.query.first()
        today = local_today()
        kid.date_of_birth = date(2024, today.month, today.day)
        db.session.commit()
        items = get_notifications(User.query.filter_by(username="desk").first())

    birthdays = [i for i in items if i.get("key") == "birthdays"]
    if birthdays:  # the bell only raises it when there is one
        assert birthdays[0]["endpoint"] == "messages.desk", \
            "the bell still sends reception to a screen it cannot open"


# ------------------------------------------------- what the desk actually says

def test_somebody_waiting_is_the_first_thing_on_it(clinic):
    from app.extensions import db

    with clinic["app"].app_context():
        _inbound(clinic)
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "عندي سؤال عن الجرعة" in page, \
        "a patient waiting for an answer is not on the desk"


def test_an_answered_thread_is_not_on_the_work_list(clinic):
    """The last word being the clinic's is the whole definition of answered."""
    from app.extensions import db
    from app.models import MessageLog

    with clinic["app"].app_context():
        kid = _inbound(clinic)
        db.session.add(MessageLog(
            patient_id=kid.id, to_phone=kid.contact_phone or "01000000000",
            direction="out", body="أهلاً، الجرعة ٥ مل", status="sent",
            created_at=datetime.utcnow()))
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "عندي سؤال عن الجرعة" not in page, \
        "a thread the clinic already answered is still on the work list"


def test_the_queue_puts_the_closing_window_first(clinic):
    """Not longest-waiting alone.

    `inbox` already works out how long the clinic may still answer for free,
    and after that window shuts the reply costs money and can only go out as
    an approved template. A thread with forty minutes left is more urgent than
    one that has waited longer with a day still in hand — so the order is the
    order of what is about to become impossible.
    """
    import inspect

    from app.blueprints.messages import routes

    source = inspect.getsource(routes.desk)
    assert "closing" in source, \
        "the desk sorts on waiting time alone and buries the urgent thread"


def test_todays_numbers_are_on_it(clinic):
    from app.extensions import db
    from app.models import MessageLog, Patient

    with clinic["app"].app_context():
        kid = Patient.query.first()
        db.session.add(MessageLog(patient_id=kid.id, to_phone="01000000000",
                                  direction="out", body="x", status="sent",
                                  sent_at=datetime.utcnow()))
        db.session.add(MessageLog(patient_id=kid.id, to_phone="01000000000",
                                  direction="out", body="y", status="failed",
                                  error="number not on whatsapp",
                                  created_at=datetime.utcnow()))
        db.session.commit()

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "number not on whatsapp" in page, \
        "a failed delivery is not surfaced where somebody would act on it"


def test_this_weeks_birthdays_are_on_it_with_a_way_to_send(clinic):
    from app.extensions import db
    from app.models import Patient

    with clinic["app"].app_context():
        kid = Patient.query.first()
        soon = local_today() + timedelta(days=2)
        kid.date_of_birth = date(2024, soon.month, soon.day)
        db.session.commit()
        name = kid.full_name

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert name in page, "the week's birthdays are not on the desk"
    assert "/messages/occasions/birthday/" in page, \
        "the birthday is listed with no way to send anything"


def test_todays_clinic_is_on_it(clinic):
    """So the desk can answer "how many are ahead of me" without leaving."""
    from app.extensions import db
    from app.models import Appointment, Patient, User

    with clinic["app"].app_context():
        doc = User.query.filter_by(username="doc").first()
        db.session.add(Appointment(patient_id=Patient.query.first().id,
                                   doctor_id=doc.id, appt_date=local_today(),
                                   appt_time=time(10, 0), status="scheduled"))
        db.session.commit()
        doctor_name = doc.full_name

    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert doctor_name in page, "today's clinic is not on the desk"


def test_an_empty_desk_says_so_rather_than_showing_nothing(clinic):
    """A blank panel reads as a broken screen."""
    page = clinic["sign_in"]("desk").get("/messages/desk").data.decode()

    assert "مفيش حد مستني رد" in page or "Nobody is waiting" in page, \
        "a quiet morning renders as an empty box"
