"""Two kinds of doctor, and the program only ever knew one.

Asked directly: *"عايز الطبيب يبقى ليه شاشة يشوف فيها العيادة، وفي فرق بين
الطبيب الأدمن والطبيب العادي — الطبيب اللي واخد صلاحيات أدمن كاملة بيشوف
اللي بيحصل في العيادة كلها"*.

``_doctor_home`` is pinned to ``doctor_id == user.id``. That is right for a
doctor and wrong for the person who owns the place: a doctor holding full
admin opened the program to the same four numbers and the same single queue
as the newest locum, with nothing on the screen about the three other عيادات
running down the corridor. An admin who is not a practitioner had it worse —
the panel is conditioned on *being* a doctor, so the manager of a four-doctor
clinic got a dashboard that said nothing about the clinic at all.

**They are two questions, not one bigger one.** "Who is my next patient" and
"what is my clinic doing" have different answers and the same person usually
asks both, so the owner gets both panels rather than one panel that grew.

And the clinic-wide answer is *the board's* answer, reached rather than
rewritten — two screens that must agree about how many children are waiting
eventually do not.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def busy(clinic):
    """Three doctors working: the owner, and two others with their own queues."""
    from app.extensions import db
    from app.models import Appointment, Patient, User
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        owner = User.query.filter_by(username="boss").first()
        owner.is_practitioner = True
        other = User(username="doc2", full_name="د. منى", role="doctor",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.flush()

        today = local_today()
        made = {}
        for who, status, hour in ((owner, "in_progress", 9),
                                  (owner, "waiting", 10),
                                  (other, "waiting", 11),
                                  (other, "completed", 12)):
            child = Patient(patient_number=f"X{hour}", full_name=f"طفل {hour}",
                            gender="male", date_of_birth=date(2023, 1, 1),
                            is_active=True)
            db.session.add(child)
            db.session.flush()
            db.session.add(Appointment(patient_id=child.id, doctor_id=who.id,
                                       appt_date=today, appt_time=time(hour, 0),
                                       status=status))
            made.setdefault(who.username, []).append(child.id)
        db.session.commit()
        clinic["other_id"] = other.id
    return clinic


def _dash(clinic, who="boss"):
    return clinic["sign_in"](who).get("/dashboard").get_data(as_text=True)


# --------------------------------------------- who is shown the whole clinic

def test_the_owner_sees_the_other_doctors_running(busy):
    """The finding, stated as the screen. Before this the answer was on the
    appointments board and only if you went there and cleared the filter."""
    page = _dash(busy)

    assert "د. منى" in page, \
        "the person who runs the clinic cannot see who else is working in it"


def test_the_owner_still_gets_their_own_queue(busy):
    """Both panels, not one. The owner is seeing patients too, and a screen
    that answered only "what is the clinic doing" would have taken away the
    thing they open the program for."""
    page = _dash(busy)

    assert "dashboard.today_clinic" not in page       # rendered, not a raw key
    assert page.count("stat-chip") >= 8, \
        "one of the two panels is missing"


def test_a_plain_doctor_is_not_shown_the_clinic(busy):
    """The other half of the difference asked about. A doctor's dashboard is
    their own day; who else is working is not on it."""
    page = _dash(busy, "doc2")

    assert "clinic today" not in page.lower()
    assert "العيادة النهارده" not in page


def test_a_plain_doctor_still_gets_their_own_queue(busy):
    """Nothing was taken from the doctor this feature is not about."""
    page = _dash(busy, "doc2")

    assert "stat-chip" in page, "the doctor lost their own panel"


def test_reception_is_not_handed_a_clinic_panel(busy):
    """It is the *running the clinic* view, not the "everyone" view. Reception
    has the board, which is built for coordinating across doctors."""
    page = _dash(busy, "desk")

    assert "العيادة النهارده" not in page


# ------------------------------- the manager who never examines anybody

def test_an_admin_who_is_not_a_doctor_gets_it_too(busy):
    """The case that was worst before: the panel above is conditioned on being
    a doctor, so a non-practitioner admin's dashboard said nothing at all
    about the clinic they run."""
    from app.extensions import db
    from app.models import User

    with busy["app"].app_context():
        boss = User.query.filter_by(username="boss").first()
        boss.is_practitioner = False
        db.session.commit()

    page = _dash(busy)

    assert "د. منى" in page, "a non-practitioner admin sees nothing of the clinic"


# --------------------------------------- one answer, reached not rewritten

def test_the_clinic_view_is_the_board_s_own_answer(busy):
    """Both screens call the same function. It used to be private to the
    board's module, so the only way to have it here was a copy — and two
    strips that must agree about how many children are waiting will not."""
    import inspect

    from app.blueprints.appointments import routes as board
    from app.blueprints.main import routes as home
    from app.utils import clinic_now

    assert board._clinics_now is clinic_now._clinics_now, \
        "the board has its own copy of the clinic view again"
    assert "clinic_now" in inspect.getsource(home._clinic_now)


def test_the_strip_is_one_template_too(busy):
    """Same argument, the markup half of it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    board = (root / "app/templates/appointments/board.html").read_text(encoding="utf-8")
    dash = (root / "app/templates/main/dashboard.html").read_text(encoding="utf-8")

    assert "clinics_strip(" in board and "clinics_strip(" in dash
    assert 'class="clinic-card' not in board, \
        "the board still spells the card out; two copies drift"


def test_it_counts_doctors_rather_than_cards(busy):
    """A doctor with an empty day gets no card, so counting the cards would
    answer a different question from "how many doctors are in today"."""
    from app.blueprints.main.routes import _clinic_now
    from app.models import User

    with busy["app"].app_context():
        boss = User.query.filter_by(username="boss").first()
        seen = _clinic_now(boss)

    assert seen["counts"]["doctors"] == 2
    assert seen["counts"]["total"] == 4


def test_a_cancelled_slot_is_not_a_patient_seen(busy):
    """The same rule the board already follows. A no-show counted as a total
    is a clinic told it was busier than it was."""
    from app.blueprints.main.routes import _clinic_now
    from app.extensions import db
    from app.models import Appointment, User

    with busy["app"].app_context():
        appt = Appointment.query.first()
        appt.status = "no_show"
        db.session.commit()

        boss = User.query.filter_by(username="boss").first()
        assert _clinic_now(boss)["counts"]["total"] == 3
