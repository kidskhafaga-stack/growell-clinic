"""Turning backup encryption off was the one thing here that needed no proof.

Asked for: a way to lock and unlock future backups, where unlocking asks for
the passphrase — and a "forgotten it" door that takes the owner's own password
instead.

What that uncovered is worth stating plainly: unlocking was already possible
and already unguarded. Submitting the passphrase box **empty** cleared it, so
anybody who could reach this screen could silently stop every future backup
from being encrypted, without knowing the current passphrase and with nothing
on the page marking it as a decision.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def locked(clinic, monkeypatch, tmp_path):
    """A clinic already taking encrypted backups."""
    from app import settings_file

    clinic["app"].config["BACKUP_PASSWORD"] = "the-real-passphrase"
    # Never write to the machine's own clinic.env from a test.
    monkeypatch.setattr(settings_file, "set_value", lambda *a, **kw: True)
    return clinic


def _post(clinic, who="boss", **fields):
    data = {"backup_password": ""}
    data.update(fields)
    return clinic["sign_in"](who).post("/settings/data/backup-password",
                                       data=data, follow_redirects=True)


def _still_locked(clinic):
    return bool(clinic["app"].config.get("BACKUP_PASSWORD"))


# ------------------------------------------------------- it is not free now

def test_an_empty_box_alone_no_longer_unlocks(locked):
    """The hole this change closes."""
    _post(locked)

    assert _still_locked(locked), \
        "encryption was switched off without proving anything"


def test_a_wrong_passphrase_does_not_unlock(locked):
    _post(locked, current_password="not-it")

    assert _still_locked(locked)


# ------------------------------------------------------------ the two doors

def test_the_passphrase_unlocks(locked):
    _post(locked, current_password="the-real-passphrase")

    assert not _still_locked(locked)


def test_the_owners_own_password_unlocks_when_the_passphrase_is_lost(locked):
    """The case the request was actually about: nobody remembers it."""
    _post(locked, owner_password="secret")

    assert not _still_locked(locked)


def test_somebody_elses_password_does_not(locked):
    _post(locked, owner_password="wrong")

    assert _still_locked(locked)


def test_a_receptionist_never_reaches_the_unlock_at_all(locked):
    """Named for what it proves, which is not what I first called it.

    The second door is "a correct password from somebody who can already open
    this screen". A receptionist's correct password is not one, and the reason
    is the route being admin-only — not anything inside the handler. Written
    against the endpoint, because that is where the guarantee is: I put an
    ``is_admin`` check inside the handler too and then took it out, since
    nothing that reaches that line can fail it.
    """
    answer = _post(locked, who="desk", owner_password="secret")

    assert _still_locked(locked)
    assert b"unlock" not in answer.data.lower() or _still_locked(locked)


# ------------------------------------------------------- setting one is free

def test_setting_a_passphrase_still_needs_no_old_one(locked):
    """Locking is the safe direction, and asking for proof to *increase*
    protection would only make people leave it off."""
    _post(locked, backup_password="a-brand-new-one",
          backup_password_confirm="a-brand-new-one")

    assert locked["app"].config["BACKUP_PASSWORD"] == "a-brand-new-one"


def test_a_clinic_with_no_passphrase_is_unaffected(clinic, monkeypatch):
    """Nothing to prove when there is nothing locked."""
    from app import settings_file

    monkeypatch.setattr(settings_file, "set_value", lambda *a, **kw: True)
    clinic["app"].config["BACKUP_PASSWORD"] = ""

    _post(clinic)

    assert not clinic["app"].config.get("BACKUP_PASSWORD")


# ------------------------------------------------------------- it is written

def test_an_unlock_is_recorded_and_says_which_door(locked):
    """A year later, "who turned this off" has to have an answer."""
    from app.models import ActivityLog

    _post(locked, owner_password="secret")

    with locked["app"].app_context():
        row = (ActivityLog.query.filter_by(action="backup.unlock")
               .order_by(ActivityLog.id.desc()).first())
        assert row is not None, "unlocking left no trace"
        assert row.detail == "owner_password"


def test_the_passphrase_itself_never_reaches_the_log(locked):
    from app.models import ActivityLog

    _post(locked, current_password="the-real-passphrase")

    with locked["app"].app_context():
        for row in ActivityLog.query.all():
            assert "the-real-passphrase" not in (row.detail or "")
