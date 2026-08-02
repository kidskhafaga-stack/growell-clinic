"""A POST has to have come from one of our own screens.

Without this, any page anywhere can make a logged-in member of staff's browser
submit a form here — the session cookie goes along by itself. A refund, a
deleted patient, a permission change: the member of staff sees nothing, and
the audit log records *them* doing it.

The rest of the suite runs with the check off (``TestingConfig``) so that
tests can post plainly. This file turns it **on**, which is the only way to
find out whether the forms actually carry the token — a protection that
rejects the clinic's own screens is an outage, not a defence.
"""
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def guarded(tmp_path, monkeypatch):
    """A signed-in clinic with the protection switched on."""
    from app import create_app
    from app.extensions import db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/csrf.db")
    app = create_app("testing")
    app.config.update(WTF_CSRF_ENABLED=True, TESTING=True)
    assert str(tmp_path) in app.config["SQLALCHEMY_DATABASE_URI"]

    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, User

        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)
        db.session.add(Service(name="كشف", category="consultation", price=200,
                               is_active=True))
        db.session.add(Patient(patient_number="P1", full_name="طفل",
                               gender="male", date_of_birth=date(2025, 1, 1),
                               is_active=True))
        db.session.commit()

    client = app.test_client()
    page = client.get("/login").get_data(as_text=True)
    client.post("/login", data={"username": "boss", "password": "secret",
                                "csrf_token": _token(page)},
                follow_redirects=True)
    return {"app": app, "db": db, "client": client}


def _token(html):
    """The token as a screen actually renders it."""
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return match.group(1) if match else None


def _services(guarded):
    from app.models import Service

    with guarded["app"].app_context():
        return Service.query.count()


# --------------------------------------------------------- the protection --
def test_a_post_from_nowhere_is_refused(guarded):
    """The whole attack in one test: a form on somebody else's page, posting
    into the clinic with the staff member's own session."""
    before = _services(guarded)
    resp = guarded["client"].post("/finance/services/new",
                                  data={"name": "خدمة مزوّرة", "price": "500"})
    assert resp.status_code == 400
    assert _services(guarded) == before


def test_a_stolen_looking_token_is_refused(guarded):
    before = _services(guarded)
    resp = guarded["client"].post("/finance/services/new",
                                  data={"name": "خدمة", "price": "500",
                                        "csrf_token": "not-a-real-token"})
    assert resp.status_code == 400
    assert _services(guarded) == before


def test_the_clinics_own_screen_still_works(guarded):
    """The half that gets forgotten. A check that rejects the clinic's own
    forms is an outage wearing a security badge."""
    page = guarded["client"].get("/finance/services").get_data(as_text=True)
    token = _token(page)
    assert token, "the services screen renders no token"

    before = _services(guarded)
    resp = guarded["client"].post("/finance/services/new",
                                  data={"name": "خدمة جديدة", "price": "150",
                                        "csrf_token": token},
                                  follow_redirects=True)
    assert resp.status_code == 200
    assert _services(guarded) == before + 1


def test_a_screen_can_post_by_script(guarded):
    """Some screens post with fetch() rather than a form. base.html adds the
    token as a header for those."""
    page = guarded["client"].get("/finance/services").get_data(as_text=True)
    resp = guarded["client"].post("/finance/services/new",
                                  data={"name": "خدمة سكربت", "price": "10"},
                                  headers={"X-CSRFToken": _token(page)},
                                  follow_redirects=True)
    assert resp.status_code == 200


def test_signing_in_is_itself_protected(guarded):
    """The login form is a form. Left out, it is a place to point a browser
    at with someone else's credentials."""
    fresh = guarded["app"].test_client()
    assert fresh.post("/login", data={"username": "boss",
                                      "password": "secret"}).status_code == 400


# ------------------------------------------------ the doors that must stay --
def test_the_providers_can_still_deliver(guarded):
    """A webhook cannot know a token of ours. It proves itself by signature,
    so the check must not apply to it — otherwise turning CSRF on silently
    stops every inbound WhatsApp message."""
    import hashlib
    import hmac
    import json

    from app.models import Setting

    secret = "app-secret-for-this-test"
    with guarded["app"].app_context():
        Setting.set("wa_inbound_enabled", "1")
        Setting.set("wa_meta_app_secret", secret)
        guarded["db"].session.commit()

    body = json.dumps({"entry": []}).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body,
                                     hashlib.sha256).hexdigest()
    resp = guarded["client"].post(
        "/wa/webhook/meta", data=body,
        headers={"Content-Type": "application/json",
                 "X-Hub-Signature-256": signature})
    assert resp.status_code == 200, "the token check swallowed a real delivery"


def test_an_unsigned_delivery_is_still_refused(guarded):
    """Exempt from the token check is not exempt from proving itself."""
    resp = guarded["client"].post("/wa/webhook/meta", json={"entry": []})
    assert resp.status_code == 403


# ------------------------------------------------------- every form has it --
def test_the_login_page_carries_a_token(guarded):
    """Checked with a signed-out browser — a signed-in one is redirected away
    from it, which would have quietly skipped the most important form."""
    body = guarded["app"].test_client().get("/login").get_data(as_text=True)
    assert 'method="post"' in body.lower()
    assert _token(body), "the login form posts without a token"


@pytest.mark.parametrize("path", [
    "/patients/new",
    "/finance/services",
    "/finance/collect/1",   # the checkout — the invoice builder it replaced
    "/prescriptions/drugs",
    "/settings/",
])
def test_the_screens_render_a_token(guarded, path):
    """218 forms had to be given one. A screen that renders a form without a
    token is a screen nobody can submit — this is the check that says the
    edit reached everywhere it needed to."""
    body = guarded["client"].get(path, follow_redirects=True).get_data(as_text=True)
    assert 'method="post"' in body.lower(), f"{path} rendered no form to check"
    assert _token(body), f"{path} posts without a token"


def test_no_template_was_missed():
    """Read the templates rather than trusting the run above to have covered
    them: a form added later without a token fails here, not in a clinic."""
    import pathlib

    missing = []
    for template in sorted(pathlib.Path("app/templates").rglob("*.html")):
        text = template.read_text(encoding="utf-8")
        for match in re.finditer(r"<form\b[^>]*>", text, re.I):
            if 'method="post"' not in match.group(0).lower():
                continue
            following = text[match.end():match.end() + 200]
            if "csrf_token" not in following:
                missing.append(f"{template}:{text[:match.start()].count(chr(10)) + 1}")
    assert not missing, "POST forms with no CSRF token:\n" + "\n".join(missing)
