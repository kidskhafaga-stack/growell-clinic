"""Asking whether a child can be anaesthetised, while the answer still matters.

The WHO checklist this module already runs has the question in it —
``anaesthesia_check`` and ``consent``, in the sign-in — and the sign-in is
ticked **with the child in the room**. A case that should never have been
listed is then discovered on the table, which is the most expensive possible
moment to discover it, and the reason a pre-operative assessment exists as its
own thing in every hospital that has one.

So this is not a second checklist. It is the same question moved to where the
answer can still change something, and the queue is what makes that workable:
the anaesthetist opens one screen, sees who has not been looked at, and clears
them on a day when nobody is waiting.

**The decision this file mostly exists to hold is that it does not refuse.**

``start()`` has the one hard stop in this module and keeps it. A bleeding child
does not wait for a form, and a program that blocked an emergency operation
would be dangerous in the other direction — it would be the same failure as a
missing checklist, pointing the other way. What a review does instead is what
``finish()`` does about a missing sign-out: say the gap is there, loudly, every
time. A gap that is visible is worth more than a refusal that gets worked
around, because the refusal that gets worked around also teaches everybody to
work around the refusals that matter.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def hospital():
    """A theatre, a child, and a case on the list."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Setting, User
        from app.models.theatre import Operation, Theatre

        Setting.set("mod_enabled:theatres", "1")
        ids = {}
        for username, name, role in (("boss", "مدير", "admin"),
                                     ("gas", "د. المخدِّر", "doctor")):
            u = User(username=username, full_name=name, role=role,
                     is_active=True)
            u.set_password("secret")
            db.session.add(u)
            db.session.flush()
            ids[username] = u.id

        child = Patient(patient_number="P1", full_name="طفل",
                        date_of_birth=date(2022, 1, 1), gender="male")
        room = Theatre(name="غرفة ١")
        db.session.add_all([child, room])
        db.session.flush()
        op = Operation(patient_id=child.id, theatre_id=room.id,
                       procedure="لوز", on_date=date.today() + timedelta(days=3),
                       status="scheduled")
        db.session.add(op)
        db.session.commit()
        ids["op"] = op.id
        ids["patient"] = child.id
        ids["room"] = room.id

    def sign_in(username="boss"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _op(hospital):
    from app.models.theatre import Operation

    return Operation.query.get(hospital["ids"]["op"])


# ------------------------------------------- the decision that matters most --
def test_an_unfit_review_does_not_stop_the_case(hospital):
    """**The whole design, in one test.**

    A bleeding child does not wait for a form. Blocking here would be the same
    failure as a missing checklist pointing the other way, and the refusal that
    gets worked around teaches people to work around the ones that matter.
    """
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "anaesthesia", "unfit", note="التهاب صدر")
        theatre.sign(op, "sign_in", items=["identity"])
        hospital["db"].session.commit()

        theatre.start(op)               # does not raise
        assert op.status == "in_theatre"


def test_but_it_is_said_where_the_start_button_is(hospital):
    """The trade for not refusing: nobody can say afterwards they were not
    told. Read off the rendered case screen, because a warning that exists in
    a function and not on the page is not a warning."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.review(_op(hospital), "anaesthesia", "unfit", note="التهاب صدر")
        hospital["db"].session.commit()

    html = hospital["sign_in"]().get(
        f"/theatres/operation/{hospital['ids']['op']}").get_data(as_text=True)
    assert "data-preop-blocks" in html
    assert "التهاب صدر" in html


def test_the_one_real_refusal_is_untouched(hospital):
    """``start`` still refuses an unsigned sign-in. Adding a second soft
    warning must not have softened the hard one."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "anaesthesia", "fit")
        hospital["db"].session.commit()
        with pytest.raises(theatre.NotSafeYet):
            theatre.start(op)


# --------------------------------------------------------------- the record --
def test_two_people_two_answers(hospital):
    """The surgeon confirms the operation is still right; the anaesthetist
    confirms the child can be given an anaesthetic. One signature standing for
    both is the thing a merged screen would have allowed."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "surgeon", "fit")
        hospital["db"].session.commit()
        done = theatre.reviews(op)
        assert "surgeon" in done and "anaesthesia" not in done


def test_reviewing_again_replaces_rather_than_stacks(hospital):
    """A child seen again once the chest cleared has **one** current answer.
    Two rows would leave the list showing an "unfit" that stopped being true a
    week ago."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "anaesthesia", "unfit", note="التهاب صدر")
        hospital["db"].session.commit()
        theatre.review(op, "anaesthesia", "fit")
        hospital["db"].session.commit()
        assert len(op.reviews) == 1
        assert theatre.reviews(op)["anaesthesia"].verdict == "fit"


def test_not_fit_must_say_why(hospital):
    """"Not fit" with nothing after it stops a list and tells the next person
    nothing — they have to ring somebody to learn what the program knew."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        with pytest.raises(ValueError):
            theatre.review(_op(hospital), "anaesthesia", "unfit")


def test_fit_with_conditions_is_its_own_answer(hospital):
    """The answer that actually happens — "yes, once the chest is clear".
    Fit/unfit alone forces it into one of the two and loses the condition."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "anaesthesia", "conditions", note="لو الصدر نضيف")
        hospital["db"].session.commit()
        assert theatre.reviews(op)["anaesthesia"].verdict == "conditions"
        assert theatre.blocking(op) == []       # a condition is not a refusal


def test_fit_needs_no_reason(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.review(_op(hospital), "surgeon", "fit")
        hospital["db"].session.commit()


def test_a_made_up_verdict_is_refused(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        with pytest.raises(ValueError):
            theatre.review(_op(hospital), "surgeon", "probably", note="x")


def test_it_records_who_and_when(hospital):
    """Superseded answers stay attributable, which is the reason a row and not
    a flag."""
    from app.models import User
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        gas = User.query.filter_by(username="gas").first()
        op = _op(hospital)
        theatre.review(op, "anaesthesia", "fit", user=gas)
        hospital["db"].session.commit()
        row = theatre.reviews(op)["anaesthesia"]
        assert row.by_id == gas.id and row.at is not None


# ---------------------------------------------------------------- the queue --
def test_a_case_nobody_has_seen_is_on_the_queue(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        assert hospital["ids"]["op"] in {o.id for o in theatre.unreviewed()}


def test_it_leaves_the_queue_once_both_have_answered(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        theatre.review(op, "surgeon", "fit")
        theatre.review(op, "anaesthesia", "fit")
        hospital["db"].session.commit()
        assert theatre.unreviewed() == []


def test_one_persons_queue_is_not_the_others(hospital):
    """They are answering different questions, so a surgeon clearing a case
    must not take it off the anaesthetist's list."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        theatre.review(_op(hospital), "surgeon", "fit")
        hospital["db"].session.commit()
        assert theatre.unreviewed(kind="surgeon") == []
        assert len(theatre.unreviewed(kind="anaesthesia")) == 1


def test_a_cancelled_case_is_not_waiting_for_anybody(hospital):
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        op.status = "cancelled"
        hospital["db"].session.commit()
        assert theatre.unreviewed() == []


def test_yesterdays_list_is_not_a_queue(hospital):
    """The queue is work still worth doing. A case whose day has passed is not
    reviewed retrospectively — it is either done or it was cancelled."""
    from app.utils import theatres as theatre

    with hospital["app"].app_context():
        op = _op(hospital)
        op.on_date = date.today() - timedelta(days=2)
        hospital["db"].session.commit()
        assert theatre.unreviewed() == []


# --------------------------------------------------------------- the doors --
def test_the_queue_screen_opens_and_lists_the_case(hospital):
    body = hospital["sign_in"]().get("/theatres/preop").get_data(as_text=True)
    assert "لوز" in body


def test_the_day_links_to_the_queue(hospital):
    """A screen nobody can reach is a screen that does not exist — and the
    person the queue is for is reading the day list, not the settings."""
    body = hospital["sign_in"]().get("/theatres/").get_data(as_text=True)
    assert "/theatres/preop" in body


def test_recording_through_the_route_works(hospital):
    from app.utils import theatres as theatre

    hospital["sign_in"]("gas").post(
        f"/theatres/operation/{hospital['ids']['op']}/review",
        data={"kind": "anaesthesia", "verdict": "fit"}, follow_redirects=True)
    with hospital["app"].app_context():
        assert "anaesthesia" in theatre.reviews(_op(hospital))


def test_the_route_refuses_a_reasonless_refusal_too(hospital):
    """The screen and the door agree — a rule enforced in one and not the
    other is a rule a typed form walks straight past."""
    from app.utils import theatres as theatre

    hospital["sign_in"]().post(
        f"/theatres/operation/{hospital['ids']['op']}/review",
        data={"kind": "anaesthesia", "verdict": "unfit"}, follow_redirects=True)
    with hospital["app"].app_context():
        assert theatre.reviews(_op(hospital)) == {}


def test_the_screen_is_absent_when_the_module_is_off(hospital):
    """A module off is a module absent, everywhere."""
    from app.models import Setting

    with hospital["app"].app_context():
        Setting.set("mod_enabled:theatres", "0")
        hospital["db"].session.commit()
    assert hospital["sign_in"]().get("/theatres/preop").status_code == 404
