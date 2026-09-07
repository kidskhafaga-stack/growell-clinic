"""Telling a doctor their money moved, without becoming noise.

A doctor's share follows the money: a refund of half an invoice takes half
their share with it. ``RefundNotice`` exists to tell them the same day — and
it was told in one place, «عيادتي», a screen nobody opens on a busy morning.

So there are three layers now, and they say different things:

* the pop-up  — "this happened just now"; an interruption, and it goes
* the bell    — "there are things that concern you"; a count, and it stays
* «عيادتي»    — the detail and the objection; the record

The rule these tests exist to hold is the one that makes the "don't show me
this again" button safe to offer at all:

    **switching off the pop-up must not change the bell.**

A doctor turning off an interruption has not said they no longer want to know
about money coming off their own account. If muting emptied the count too,
the button would quietly cost them the thing it was meant to spare them from
— and there would be no way to find that out except by missing a refund.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """Two doctors, and a refund on the first one's work."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Invoice, Patient, RefundNotice, User)
        from app.utils.finance import generate_invoice_number

        ids = {}
        for username, name in (("doc", "د. أحمد"), ("doc2", "د. منى")):
            user = User(username=username, full_name=name, role="doctor",
                        is_active=True)
            user.set_password("secret")
            db.session.add(user)
            db.session.flush()
            ids[username] = user.id

        child = Patient(patient_number="P1", full_name="طفل",
                        date_of_birth=date(2023, 1, 1), gender="male")
        db.session.add(child)
        db.session.flush()
        invoice = Invoice(invoice_number=generate_invoice_number(),
                          patient_id=child.id, doctor_id=ids["doc"])
        db.session.add(invoice)
        db.session.flush()
        notice = RefundNotice(invoice_id=invoice.id, doctor_id=ids["doc"],
                              amount=50, scope="partial")
        db.session.add(notice)
        db.session.commit()
        ids["notice"] = notice.id

    def sign_in(username="doc"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _user(clinic, username="doc"):
    from app.models import User

    return User.query.filter_by(username=username).first()


# ------------------------------------------------------------ the nudge --
def test_a_refund_pops_up_for_the_doctor_it_took_from(clinic):
    from app.utils import popups

    with clinic["app"].app_context():
        assert len(popups.for_user(_user(clinic))) == 1


def test_it_does_not_pop_up_for_anybody_else(clinic):
    """One doctor's money is not another's notice."""
    from app.utils import popups

    with clinic["app"].app_context():
        assert popups.for_user(_user(clinic, "doc2")) == []


def test_once_shown_it_stops_interrupting(clinic):
    """Stamped on the notice's own ``seen_at``, so what stops it appearing is
    the record's existing fact rather than a second one kept beside it."""
    from app.utils import popups

    with clinic["app"].app_context():
        doc = _user(clinic)
        popups.mark_seen(doc, clinic["ids"]["notice"])
        clinic["db"].session.commit()
        assert popups.for_user(doc) == []


def test_a_notice_cannot_be_marked_read_by_someone_else(clinic):
    from app.utils import popups

    with clinic["app"].app_context():
        assert popups.mark_seen(_user(clinic, "doc2"),
                                clinic["ids"]["notice"]) is False


# ----------------------------------------------- the rule that matters --
def test_muting_the_popup_does_not_empty_the_bell(clinic):
    """**The whole reason the button is safe to offer.**

    Somebody switching off an interruption has not said they no longer want
    to know that money came off their account.
    """
    from app.utils import popups

    with clinic["app"].app_context():
        doc = _user(clinic)
        before = popups.pending_count(doc)
        doc.mute_popup("refund")
        clinic["db"].session.commit()
        assert popups.for_user(doc) == []          # the knock stops
        assert popups.pending_count(doc) == before  # the room is not empty
        assert before == 1


def test_the_bell_still_carries_it_after_muting(clinic):
    """Read through the bell's own builder, not the counter underneath it —
    the count reaching the screen is what a doctor actually relies on."""
    from app.utils.notifications import get_notifications

    with clinic["app"].app_context():
        doc = _user(clinic)
        doc.mute_popup("refund")
        clinic["db"].session.commit()
        keys = {i["key"] for i in get_notifications(doc)}
    assert "refund_notices" in keys


def test_the_bell_carries_it_before_muting_too(clinic):
    from app.utils.notifications import get_notifications

    with clinic["app"].app_context():
        keys = {i["key"] for i in get_notifications(_user(clinic))}
    assert "refund_notices" in keys


def test_muting_is_one_doctors_own_choice(clinic):
    """A doctor silencing their own pop-up does not silence a colleague's."""
    from app.models import Invoice, RefundNotice
    from app.utils import popups

    with clinic["app"].app_context():
        invoice = Invoice.query.first()
        clinic["db"].session.add(RefundNotice(
            invoice_id=invoice.id, doctor_id=clinic["ids"]["doc2"],
            amount=20, scope="partial"))
        _user(clinic).mute_popup("refund")
        clinic["db"].session.commit()
        assert popups.for_user(_user(clinic)) == []
        assert len(popups.for_user(_user(clinic, "doc2"))) == 1


def test_muting_one_kind_leaves_the_others_alone(clinic):
    """It is per kind, so a future pop-up is not switched off by a decision
    somebody made about refunds."""
    with clinic["app"].app_context():
        doc = _user(clinic)
        doc.mute_popup("refund")
        assert doc.mutes_popup("refund") is True
        assert doc.mutes_popup("something_else") is False


def test_muting_twice_does_not_grow_the_list(clinic):
    with clinic["app"].app_context():
        doc = _user(clinic)
        doc.mute_popup("refund")
        assert doc.mute_popup("refund") is False
        assert doc.muted_popups == "refund"


def test_a_clinic_that_has_never_muted_anything_is_not_muted(clinic):
    """The column is empty on every existing install, and empty must read as
    "nothing switched off" rather than as a value nobody can parse."""
    with clinic["app"].app_context():
        doc = _user(clinic)
        assert doc.muted_popups is None
        assert doc.mutes_popup("refund") is False


# ------------------------------------------------------------ the doors --
def test_the_mute_route_only_accepts_a_kind_that_exists(clinic):
    """Otherwise anything posted here becomes a stored string nobody reads."""
    resp = clinic["sign_in"]().post("/popup/mute", data={"kind": "whatever"})
    assert resp.status_code == 400
    with clinic["app"].app_context():
        assert _user(clinic).muted_popups is None


def test_muting_through_the_route_says_where_they_went(clinic):
    """Somebody switching a thing off is owed the sentence that says it did
    not disappear."""
    body = clinic["sign_in"]().post("/popup/mute",
                                    data={"kind": "refund"}).get_json()
    assert body["ok"] is True
    assert body["where"]
    with clinic["app"].app_context():
        assert _user(clinic).mutes_popup("refund") is True


def test_marking_seen_through_the_route_stamps_it(clinic):
    from app.models import RefundNotice

    body = clinic["sign_in"]().post(
        "/popup/seen", data={"notice_id": clinic["ids"]["notice"]}).get_json()
    assert body["ok"] is True
    with clinic["app"].app_context():
        assert RefundNotice.query.get(clinic["ids"]["notice"]).seen_at is not None


def test_a_stranger_cannot_mark_it_seen(clinic):
    from app.models import RefundNotice

    clinic["sign_in"]("doc2").post("/popup/seen",
                                   data={"notice_id": clinic["ids"]["notice"]})
    with clinic["app"].app_context():
        assert RefundNotice.query.get(clinic["ids"]["notice"]).seen_at is None


def test_the_popup_reaches_the_page(clinic):
    """It has to be on whatever screen the doctor is already looking at —
    a nudge that only appears where they were going anyway is no nudge."""
    html = clinic["sign_in"]().get("/", follow_redirects=True).get_data(as_text=True)
    assert 'class="popup-stack"' in html
    assert "popupStack()" in html


def test_the_page_is_clean_once_there_is_nothing_to_say(clinic):
    """Checked on the element, not the word: the stylesheet ships on every
    page, so a bare substring is true whether or not anything popped up."""
    html = clinic["sign_in"]("doc2").get("/", follow_redirects=True).get_data(as_text=True)
    assert 'class="popup-stack"' not in html


# ------------------------------------------------------------- the cost --
def test_the_bell_and_the_popup_share_one_read(clinic):
    """It started as two — a count for the bell and rows for the pop-up, the
    same filter read twice on every page anybody opens. CI caught it as a
    query budget going from 41 to 43.

    They are one read now, kept on ``g`` for the request. Asserted rather than
    remembered, because the two callers sit in different context processors
    and neither one looks like it is paying for the other.
    """
    from sqlalchemy import event

    from app.extensions import db
    from app.utils import popups

    seen = []
    with clinic["app"].test_request_context("/"):
        doc = _user(clinic)

        def record(conn, cursor, statement, *a):
            if "refund_notices" in statement:
                seen.append(statement)

        event.listen(db.engine, "before_cursor_execute", record)
        try:
            popups.pending_count(doc)   # what the bell asks
            popups.for_user(doc)        # what the pop-up asks
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
    assert len(seen) == 1, f"{len(seen)} reads of refund_notices in one request"


def test_a_doctor_with_a_pile_of_them_is_still_counted_right(clinic):
    """The shortcut is "the rows I read are all there were". Past the handful
    the pop-up shows, that stops being true and the count is asked for
    properly — a bell that under-reports money is worse than a query."""
    from app.models import Invoice, RefundNotice
    from app.utils import popups

    with clinic["app"].app_context():
        invoice = Invoice.query.first()
        for _ in range(6):
            clinic["db"].session.add(RefundNotice(
                invoice_id=invoice.id, doctor_id=clinic["ids"]["doc"],
                amount=10, scope="partial"))
        clinic["db"].session.commit()
        doc = _user(clinic)
        assert popups.pending_count(doc) == 7          # 6 + the fixture's one
        assert len(popups.for_user(doc)) == popups.SHOWN
