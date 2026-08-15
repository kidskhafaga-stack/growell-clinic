"""Two things a person doing the setup actually hit.

Both were reported from the screen, and both are the same kind of fault: the
program knew the answer and answered something else.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def app_ctx():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _admin():
    from app.extensions import db
    from app.models import User

    user = User(username="boss", full_name="المدير", role="admin",
                is_active=True)
    user.set_password("secret")
    db.session.add(user)
    db.session.commit()
    return user


def _signed_in(app):
    client = app.test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)
    return client


# ------------------------------------------------- saving keeps you in place

def test_saving_answers_on_the_tab_that_was_being_edited(app_ctx):
    """Every tab posts one form, so the server has to be told which one."""
    _admin()
    client = _signed_in(app_ctx)

    answer = client.post("/settings/", data={"active_tab": "eta"})

    assert answer.status_code == 302
    assert answer.headers["Location"].endswith("#eta"), \
        f"saving the tax tab answered with {answer.headers['Location']}"


def test_a_tab_name_that_is_not_a_tab_does_not_reach_the_url(app_ctx):
    """The posted value lands in a redirect, so it is checked, not trusted."""
    _admin()
    client = _signed_in(app_ctx)

    answer = client.post("/settings/", data={
        "active_tab": "https://elsewhere.example/#x"})

    assert answer.status_code == 302
    assert "elsewhere.example" not in answer.headers["Location"]
    assert answer.headers["Location"].endswith("#clinic")


def test_the_screen_reads_the_tab_back_out_of_the_address(app_ctx):
    """The other half: landing on #eta has to open the tax tab."""
    _admin()
    page = _signed_in(app_ctx).get("/settings/").get_data(as_text=True)

    # The tab list the page decides from, and the sync that keeps it there.
    assert "tabs:" in page and '"eta"' in page
    assert "replaceState" in page
    # And the ICD-11 block, which three redirects point at by its own name,
    # has to resolve to the tab it actually lives on.
    assert "icd11" in page and "'ai'" in page


# ------------------------------------------------- the backup step is honest

def test_a_backup_that_exists_satisfies_the_step(app_ctx, tmp_path,
                                                 monkeypatch):
    """Three backups on disk and the checklist still said "missing"."""
    from app.utils import readiness

    monkeypatch.setattr("app.utils.backups.list_backups",
                        lambda: [{"name": "backup-1.zip"},
                                 {"name": "backup-2.zip"}])

    done, detail = readiness._backup()

    assert done is True, "a clinic with two backups was told it had none"
    assert detail == 2


def test_scheduling_a_backup_also_satisfies_the_step(app_ctx, monkeypatch):
    """The original meaning still counts — it was too narrow, not wrong."""
    from app.extensions import db
    from app.models import Setting
    from app.utils import readiness

    monkeypatch.setattr("app.utils.backups.list_backups", lambda: [])
    Setting.set("backup_auto", "1")
    db.session.commit()

    done, _ = readiness._backup()
    assert done is True


def test_no_backup_at_all_is_still_reported_as_missing(app_ctx, monkeypatch):
    """A step that can never fail is not a step."""
    from app.utils import readiness

    monkeypatch.setattr("app.utils.backups.list_backups", lambda: [])

    done, _ = readiness._backup()
    assert done is False


def test_a_broken_backup_folder_does_not_break_the_checklist(app_ctx,
                                                             monkeypatch):
    """The dashboard draws this. It cannot be allowed to raise."""
    from app.utils import readiness

    def explode():
        raise OSError("the backup folder is not readable")

    monkeypatch.setattr("app.utils.backups.list_backups", explode)

    done, _ = readiness._backup()
    assert done is False
