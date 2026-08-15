"""The ICD-11 import counted all along and threw the number away.

``icd_who.walk`` takes an ``on_progress`` callback, and its docstring says
why: *"this takes minutes, and a spinner with no number is indistinguishable
from a hang"*. The route then called ``import_all()`` with no callback, so the
count was computed on every entity and discarded, and the screen sat still for
minutes with nothing to say whether it was working or stuck.
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


# ------------------------------------------------------- the count is kept

def test_the_running_count_is_readable_while_it_runs(app_ctx):
    from app.utils import icd_progress

    icd_progress.start()
    icd_progress.note._last = 0            # the throttle, stood down
    icd_progress.note(1200)

    state = icd_progress.status()
    assert state["running"] is True
    assert state["count"] == 1200


def test_the_count_is_not_written_on_every_single_entity(app_ctx):
    """A database write per WHO request would cost more than the request."""
    from app.utils import icd_progress

    icd_progress.start()
    icd_progress.note._last = 0
    icd_progress.note(10)                  # written
    icd_progress.note(11)                  # inside the window, skipped
    icd_progress.note(12)

    assert icd_progress.status()["count"] == 10


# ------------------------------------------------------- honest percentage

def test_the_first_import_reports_no_percentage(app_ctx):
    """There is no denominator yet, and inventing one misinforms.

    A bar reading 90% at the halfway mark is worse than no bar: it does not
    merely fail to inform, it is believed.
    """
    from app.utils import icd_progress

    icd_progress.start()
    icd_progress.note._last = 0
    icd_progress.note(500)

    assert icd_progress.status()["percent"] is None


def test_a_later_import_is_measured_against_the_last_real_total(app_ctx):
    from app.utils import icd_progress

    icd_progress.finish(10000, ok=True)    # a previous, finished import
    icd_progress.start()
    icd_progress.note._last = 0
    icd_progress.note(2500)

    state = icd_progress.status()
    assert state["percent"] == 25
    assert state["estimated_from"] == 10000


def test_a_running_estimate_never_reads_a_hundred(app_ctx):
    """WHO's classification grows, so the estimate can legitimately overshoot.

    A bar that sits at 100% while the work continues is the same lie in the
    other direction.
    """
    from app.utils import icd_progress

    icd_progress.finish(10000, ok=True)
    icd_progress.start()
    icd_progress.note._last = 0
    icd_progress.note(14000)

    assert icd_progress.status()["percent"] == 99


def test_a_failed_import_does_not_become_the_next_denominator(app_ctx):
    from app.models import Setting
    from app.utils import icd_progress

    icd_progress.finish(37, ok=False)

    assert not (Setting.get(icd_progress.TOTAL_KEY) or "").strip()


# ----------------------------------------------------- the wiring itself

def test_the_import_route_actually_passes_the_callback(app_ctx, monkeypatch):
    """The bug in one line: the machinery existed and nothing was connected."""
    from app.utils import icd_who

    seen = {}

    def fake_import_all(cfg=None, requests=None, on_progress=None, limit=None):
        seen["callback"] = on_progress
        if on_progress:
            on_progress(4120)
        return {"ok": True, "codes": 4120}

    monkeypatch.setattr(icd_who, "import_all", fake_import_all)
    _admin()

    _signed_in(app_ctx).post("/settings/icd11/import", follow_redirects=True)

    assert seen.get("callback") is not None, \
        "the import still runs with nowhere to report progress"


def test_the_page_can_ask_how_far_it_has_got(app_ctx):
    from app.utils import icd_progress

    _admin()
    icd_progress.start()
    icd_progress.note._last = 0
    icd_progress.note(777)

    answer = _signed_in(app_ctx).get("/settings/icd11/progress")

    assert answer.status_code == 200
    assert answer.get_json()["count"] == 777


def test_only_an_admin_can_watch_the_import(app_ctx):
    from app.extensions import db
    from app.models import User

    _admin()
    desk = User(username="desk", full_name="الاستقبال", role="reception",
                is_active=True)
    desk.set_password("secret")
    db.session.add(desk)
    db.session.commit()

    client = app_ctx.test_client()
    client.post("/login", data={"username": "desk", "password": "secret"},
                follow_redirects=True)
    answer = client.get("/settings/icd11/progress", follow_redirects=False)

    assert answer.status_code in (302, 403)


def test_a_plain_form_post_still_redirects(app_ctx, monkeypatch):
    """No JavaScript: the import still works, only the counter is lost."""
    from app.utils import icd_who

    monkeypatch.setattr(icd_who, "import_all",
                        lambda **kw: {"ok": True, "codes": 5})
    _admin()

    answer = _signed_in(app_ctx).post("/settings/icd11/import")

    assert answer.status_code == 302
    assert answer.headers["Location"].endswith("#icd11")


def test_the_background_post_answers_in_json(app_ctx, monkeypatch):
    from app.utils import icd_who

    monkeypatch.setattr(icd_who, "import_all",
                        lambda **kw: {"ok": True, "codes": 9})
    _admin()

    answer = _signed_in(app_ctx).post(
        "/settings/icd11/import", headers={"X-Requested-With": "fetch"})

    assert answer.status_code == 200
    assert answer.get_json()["codes"] == 9


def test_a_failure_still_reaches_the_page(app_ctx, monkeypatch):
    """Silence on failure is the state this whole change exists to remove."""
    from app.utils import icd_who

    monkeypatch.setattr(icd_who, "import_all",
                        lambda **kw: {"ok": False, "error": "who_empty"})
    _admin()

    answer = _signed_in(app_ctx).post(
        "/settings/icd11/import", headers={"X-Requested-With": "fetch"})

    body = answer.get_json()
    assert body["ok"] is False
    assert body["message"], "a failed import said nothing at all"


# ------------------------------------------- saying why the option is absent

def test_the_visit_screen_says_why_icd11_is_not_offered(clinic):
    """Hiding a dead option was right. Saying nothing about it was not.

    The clinic entered its WHO credentials, pressed import, and then went
    looking for a picker that was never going to appear — with no way to tell
    "not imported yet" from "this program does not do ICD-11".
    """
    visit_id = clinic["ids"]["visit"]
    page = clinic["sign_in"]("boss").get(
        f"/visits/{visit_id}/record").data.decode()

    assert "#icd11" in page, "no way from the empty picker to the import"


def test_a_doctor_is_not_shown_the_import_link(clinic):
    """There is nothing they could do with it in front of a patient."""
    visit_id = clinic["ids"]["visit"]
    page = clinic["sign_in"]("doc").get(
        f"/visits/{visit_id}/record").data.decode()

    assert "settings/#icd11" not in page
