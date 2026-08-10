"""A one-star rating, in front of somebody who can answer it.

**Measured before building:** ``feedback.py`` held ``doctor_ratings()``,
``summary()`` and the NPS roll-up — every one of them an aggregate. There was
no path at all from a low rating to anybody doing anything. A mother gave one
star, wrote why, and her answer went into a monthly average.

A complaint somebody replies to turns the most annoyed patient into the most
loyal one; a complaint that is only counted gets written on Facebook a week
later. The difference is one person seeing it in time — so it lands in the
inbox the clinic already reads, as a thread that is waiting for an answer,
carrying the family's own words.

**The rules worth testing hardest are the ones about not shouting.** A
complaint label must never overwrite a topic a human chose — least of all
``urgent``, where it would move a child down the list — and a guardian
refreshing the survey page must not fill the inbox with copies.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def survey(clinic):
    """A sent survey for the clinic's child, with a number on file."""
    with clinic["app"].app_context():
        from app.models import Feedback, Patient
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01012345678"
        fb = Feedback(patient_id=clinic["ids"]["child"],
                      visit_id=clinic["ids"]["visit"],
                      doctor_id=clinic["ids"]["doctor"],
                      token="tok-complaint", status="sent")
        clinic["db"].session.add(fb)
        clinic["db"].session.commit()
    return clinic


def _rate(clinic, doctor=5, service=5, nps=10, comment=""):
    """Submit the survey the way a guardian's phone does."""
    return clinic["app"].test_client().post("/f/tok-complaint", data={
        "doctor_rating": str(doctor), "service_rating": str(service),
        "nps": str(nps), "comment": comment,
    }, follow_redirects=True)


def _threads(clinic):
    from app.models import MessageLog
    return MessageLog.query.filter_by(direction="in",
                                      template_type="feedback_complaint").all()


def _conversation(clinic):
    from app.models import Conversation
    return Conversation.query.filter_by(
        thread_key=f"p{clinic['ids']['child']}").first()


# --- it reaches a human at all ---------------------------------------------

def test_a_low_rating_becomes_a_thread_waiting_for_an_answer(survey):
    """The gap: it used to become a number in an average and nothing else."""
    _rate(survey, doctor=1, service=2, nps=2, comment="استنينا ساعتين")

    with survey["app"].app_context():
        rows = _threads(survey)
        assert len(rows) == 1, "a one-star rating reached nobody"
        assert rows[0].direction == "in", (
            "it must sit on the waiting side of the inbox, or nobody answers it")


def test_the_thread_carries_what_they_actually_said(survey):
    """A row reading only "low rating" sends whoever picks it up to another
    screen to find out what about — which is where it stops."""
    _rate(survey, doctor=1, service=2, nps=3, comment="استنينا ساعتين")

    with survey["app"].app_context():
        body = _threads(survey)[0].body
        assert "استنينا ساعتين" in body
        assert "1/5" in body and "2/5" in body


def test_it_is_labelled_a_complaint_so_it_sorts_with_the_others(survey):
    _rate(survey, doctor=1, service=1, nps=0)

    with survey["app"].app_context():
        assert _conversation(survey).topic == "complaint"


def test_a_closed_thread_reopens_for_a_complaint(survey):
    """Same rule an inbound message already follows.

    A family whose thread was closed last week and who has now rated the visit
    one star is waiting for an answer again.
    """
    from datetime import datetime, timedelta

    with survey["app"].app_context():
        from app.utils.inbox import conversation_for
        conv = conversation_for(f"p{survey['ids']['child']}")
        conv.resolved_at = datetime.utcnow() - timedelta(days=7)
        survey["db"].session.commit()

    _rate(survey, doctor=1, service=1, nps=1)

    with survey["app"].app_context():
        assert _conversation(survey).resolved_at is None


# --- and, mostly, it stays quiet -------------------------------------------

def test_a_happy_family_is_not_put_in_the_work_list(survey):
    """Five stars is not a complaint, and an inbox full of them is an inbox
    nobody reads."""
    _rate(survey, doctor=5, service=5, nps=10, comment="شكراً جزيلاً")

    with survey["app"].app_context():
        assert _threads(survey) == []
        conv = _conversation(survey)
        assert conv is None or conv.topic != "complaint"


@pytest.mark.parametrize("doctor,service,nps,expected", [
    (5, 5, 10, False),
    (2, 5, 10, True),    # the doctor scored low — that is specific and useful
    (5, 2, 10, True),    # …and so is the waiting room, on its own
    (5, 5, 6, True),     # a 6 is a detractor however good the stars are
    (5, 5, 7, False),
    (3, 3, 8, False),
])
def test_one_low_score_is_enough_even_when_the_others_are_good(
        survey, doctor, service, nps, expected):
    """Averaging them is how the useful half gets lost.

    A family that rated the doctor five and the waiting room one has told the
    clinic something exact; a comfortable mean of three tells it nothing.
    """
    from app.models import Feedback
    from app.utils.complaints import is_complaint

    with survey["app"].app_context():
        fb = Feedback.query.filter_by(token="tok-complaint").first()
        fb.doctor_rating, fb.service_rating, fb.nps = doctor, service, nps
        fb.status = "submitted"
        assert is_complaint(fb) is expected


def test_an_urgent_thread_is_not_relabelled_a_complaint(survey):
    """The rule that matters most here.

    ``urgent`` is the one topic that changes the *order* of the inbox. A child
    with breathing trouble whose family also rated last week's visit two stars
    must not be moved down the list by this.
    """
    with survey["app"].app_context():
        from app.utils.inbox import conversation_for
        conv = conversation_for(f"p{survey['ids']['child']}")
        conv.topic = "urgent"
        survey["db"].session.commit()

    _rate(survey, doctor=1, service=1, nps=0)

    with survey["app"].app_context():
        assert _conversation(survey).topic == "urgent", (
            "an emergency was relabelled as a complaint")


def test_refreshing_the_survey_page_does_not_fill_the_inbox(survey):
    """Guardians re-open links. Double submissions are already ignored for the
    rating itself; the thread entry has to be just as boring."""
    _rate(survey, doctor=1, service=1, nps=0, comment="مش راضي")
    _rate(survey, doctor=1, service=1, nps=0, comment="مش راضي")
    _rate(survey, doctor=1, service=1, nps=0, comment="مش راضي")

    with survey["app"].app_context():
        assert len(_threads(survey)) == 1


def test_raising_the_same_rating_twice_adds_one_thread(survey):
    """The guard belongs to the function, not to the route above it.

    Through the survey page this can't happen — ``submit`` ignores a second
    submission, so the test above stays green with the guard deleted, which is
    how this one came to be written. But the obvious next caller is a sweep
    over the low ratings already in the database, and that would put every one
    of them in the inbox a second time.
    """
    _rate(survey, doctor=1, service=1, nps=0, comment="مش راضي")

    with survey["app"].app_context():
        from app.models import Feedback
        from app.utils.complaints import raise_from_feedback

        fb = Feedback.query.filter_by(token="tok-complaint").first()
        assert raise_from_feedback(fb) is None, "a second thread was created"
        survey["db"].session.commit()
        assert len(_threads(survey)) == 1


def test_the_clinic_sets_where_the_line_is(survey):
    """Three stars is a complaint in a clinic that expects five, and noise in
    one that does not. Neither is the program's call."""
    from app.models import Feedback, Setting
    from app.utils.complaints import is_complaint

    with survey["app"].app_context():
        fb = Feedback.query.filter_by(token="tok-complaint").first()
        fb.doctor_rating, fb.service_rating, fb.nps = 3, 3, 9
        fb.status = "submitted"
        assert is_complaint(fb) is False

        Setting.set("feedback_complaint_stars", "3")
        survey["db"].session.commit()
        assert is_complaint(fb) is True


def test_a_broken_inbox_never_costs_the_rating(survey, monkeypatch):
    """The guardian is on a phone, on a public page, and has just given the
    clinic something useful.

    Meeting an error there would lose the rating *and* the goodwill, so the
    thread entry is best-effort and the survey submission is not.
    """
    from app.models import Feedback
    from app.utils import complaints

    monkeypatch.setattr(complaints, "raise_from_feedback",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    response = _rate(survey, doctor=1, service=1, nps=0, comment="سيء")
    assert response.status_code == 200

    with survey["app"].app_context():
        fb = Feedback.query.filter_by(token="tok-complaint").first()
        assert fb.status == "submitted", "the rating was lost"
        assert fb.doctor_rating == 1
