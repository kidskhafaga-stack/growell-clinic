"""Sending the failed ones again — and refusing the ones that would do harm.

**Measured before building:** the failures panel has counted "12 failed" since
it was written, and there is no ``resend`` or ``requeue`` anywhere in the routes
or the templates. The only remedy was to find each message and send it by hand,
which nobody does twelve times.

**Most of this file is about what the button refuses.** Sending a message
again is the one action here that can do damage on purpose: a skip is the
clinic's own decision and re-sending an opt-out messages a family that asked
not to be messaged — the single unrecoverable mistake in this module. And a
reminder for yesterday's appointment is worse arriving late than never
arriving at all.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def sending(clinic):
    """A clinic that sends through an API, with the provider stubbed."""
    with clinic["app"].app_context():
        from app.models import Patient, Setting
        Setting.set("crm_mode", "automatic")
        Setting.set("wa_provider", "cloud_api")
        Setting.set("wa_cloud_token", "tok")
        Setting.set("wa_cloud_phone_id", "1")
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.own_phone = "01012345678"
        clinic["db"].session.commit()
    return clinic


def _failure(clinic, error="http_500", ttype="vaccine_due", appointment_id=None,
             days_ago=0, phone="201012345678"):
    from app.models import MessageLog
    row = MessageLog(
        patient_id=clinic["ids"]["child"], to_phone=phone, body="نص",
        provider="cloud_api", direction="out", status="failed", error=error,
        template_type=ttype, appointment_id=appointment_id,
        created_at=datetime.utcnow() - timedelta(days=days_ago))
    clinic["db"].session.add(row)
    clinic["db"].session.commit()
    return row


def _stub_provider(monkeypatch, ok=True):
    from app.utils import whatsapp as wa
    monkeypatch.setattr(wa, "_post_json", lambda *a, **k: (
        (200, '{"messages":[{"id":"wamid.retry"}]}') if ok else (500, "{}")))


# --- it does something at all ----------------------------------------------

def test_a_failed_message_can_be_sent_again(sending, monkeypatch):
    """The gap: the board counted failures and offered nothing to do."""
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.models import MessageLog
        from app.utils.resend import resend_all

        original = _failure(sending)
        result = resend_all()

        assert result["resent"] == 1
        fresh = MessageLog.query.filter_by(retry_of=original.id).first()
        assert fresh is not None and fresh.status == "sent"


def test_the_failure_is_kept_rather_than_rewritten(sending, monkeypatch):
    """The failure is the record of what happened.

    Flipping the old row back to "scheduled" would erase it — and with it the
    only evidence of how often this number fails.
    """
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.utils.resend import resend_all

        original = _failure(sending)
        original_id = original.id
        resend_all()

        from app.models import MessageLog
        again = sending["db"].session.get(MessageLog, original_id)
        assert again.status == "failed", "the failure was overwritten"


def test_the_button_is_offered_only_when_there_is_something_to_press_it_for(
        sending, monkeypatch):
    """A button that does nothing teaches people the screen is broken."""
    boss = sending["sign_in"]("boss")
    assert "resend-failed" not in boss.get("/messages/").data.decode()

    with sending["app"].app_context():
        _failure(sending)
    assert "resend-failed" in boss.get("/messages/").data.decode()


# --- and, mostly, it refuses -----------------------------------------------

@pytest.mark.parametrize("reason", ["opted_out", "missing_phone", "type_off"])
def test_a_skip_is_never_resent(sending, monkeypatch, reason):
    """These are the clinic's own states, not delivery failures.

    Re-sending an opt-out messages a family that asked not to be messaged,
    which is the one mistake in this module that cannot be taken back.
    """
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.utils.resend import retryable

        row = _failure(sending, error=reason)
        assert row not in retryable()
        assert retryable() == []


def test_a_reminder_for_an_appointment_that_has_passed_is_not_resent(
        sending, monkeypatch):
    """Worse late than never.

    A reminder arriving the morning after tells a family to come to something
    they have already missed, and it is the clinic that looks like it has lost
    track.
    """
    with sending["app"].app_context():
        from app.models import Appointment
        db = sending["db"]
        gone = Appointment(patient_id=sending["ids"]["child"],
                           doctor_id=sending["ids"]["doctor"],
                           appt_date=date.today() - timedelta(days=2),
                           appt_time=time(10, 0), duration_minutes=15,
                           status="no_show")
        db.session.add(gone)
        db.session.flush()
        _failure(sending, ttype="appointment_reminder", appointment_id=gone.id)

        from app.utils.resend import retryable
        assert retryable() == [], "a stale reminder was queued for resending"


def test_a_reminder_for_an_appointment_still_ahead_is_resent(sending, monkeypatch):
    """The other side of the same rule — or it would refuse everything."""
    with sending["app"].app_context():
        from app.models import Appointment
        db = sending["db"]
        soon = Appointment(patient_id=sending["ids"]["child"],
                           doctor_id=sending["ids"]["doctor"],
                           appt_date=date.today() + timedelta(days=2),
                           appt_time=time(10, 0), duration_minutes=15,
                           status="scheduled")
        db.session.add(soon)
        db.session.flush()
        _failure(sending, ttype="appointment_reminder", appointment_id=soon.id)

        from app.utils.resend import retryable
        assert len(retryable()) == 1


def test_pressing_it_twice_does_not_send_twice(sending, monkeypatch):
    """A number that is wrong is wrong.

    Retrying it on every press turns one dead number into a daily habit — and
    the second press is what an impatient person does when the first gave no
    obvious result.
    """
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.models import MessageLog
        from app.utils.resend import resend_all

        original = _failure(sending)
        assert resend_all()["resent"] == 1
        assert resend_all()["resent"] == 0
        assert MessageLog.query.filter_by(retry_of=original.id).count() == 1


def test_last_months_failures_are_not_all_sent_at_once(sending, monkeypatch):
    """Nobody wants a month of reminders arriving together.

    Old enough is history, and a retry that far behind is a message the family
    will read as a mistake — because it is one.
    """
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.utils.resend import retryable

        _failure(sending, days_ago=30)
        assert retryable() == []


def test_a_family_that_opted_out_since_is_still_not_messaged(sending, monkeypatch):
    """The retry goes through the ordinary send path, so every guard applies.

    Writing the row directly would have been shorter and would have messaged
    somebody who asked not to be — the opt-out, the sending window and the
    daily cap all live in ``wa.send``.
    """
    with sending["app"].app_context():
        _stub_provider(monkeypatch)
        from app.models import MessageLog, Patient
        from app.utils.resend import resend_all
        db = sending["db"]

        original = _failure(sending)
        child = db.session.get(Patient, sending["ids"]["child"])
        child.wa_opt_out = True
        db.session.commit()

        resend_all()
        fresh = MessageLog.query.filter_by(retry_of=original.id).first()
        assert fresh is not None
        assert fresh.status == "skipped" and fresh.error == "opted_out", (
            "a family that opted out was messaged by the retry")


def test_the_new_column_reaches_clinics_that_already_have_the_program():
    """``retry_of`` on an existing table exists only if the migration knows.

    Without the line, "already retried" silently becomes unknowable on every
    clinic running since June, and the button would re-send on every press.
    """
    from app.utils.schema import ADDITIONS

    assert ("message_logs", "retry_of", "INTEGER") in ADDITIONS
