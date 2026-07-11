"""Smoke tests: the app builds and core public routes respond sensibly.

Kept dependency-light (pytest + the app) so CI stays fast. These also give
`pytest` something to collect (an empty run exits non-zero).
"""
import pytest


@pytest.fixture()
def client():
    from app.extensions import db
    from run import app

    app.config.update(TESTING=True)
    with app.app_context():
        db.create_all()
    return app.test_client()


def test_app_builds(client):
    # Unauthenticated root should respond (login page or a redirect to it).
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code < 500


def test_login_page_loads(client):
    resp = client.get("/login")
    assert resp.status_code == 200


def test_meta_webhook_verify_rejects_without_token(client):
    # No verify token configured/passed → must not leak a challenge.
    resp = client.get("/wa/webhook/meta?hub.mode=subscribe&hub.challenge=x")
    assert resp.status_code == 403


def test_wapilot_webhook_rejects_bad_secret(client):
    resp = client.post("/wa/webhook/wapilot/not-a-real-secret", json={})
    assert resp.status_code == 403
