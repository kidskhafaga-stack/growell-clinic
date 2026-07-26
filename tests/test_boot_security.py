"""How the clinic starts up — the two settings that decide who can walk in.

Neither of these is a feature anybody asks for. They are the difference
between a program on a clinic's computer and a program anyone on the clinic's
wifi can take over, and both used to be wrong by *default* — which is the
only way that matters, because a default is what a clinic actually runs.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ----------------------------------------------- the key that signs you in --
def test_a_clinic_gets_its_own_session_key(tmp_path):
    """The fallback key is printed in the open source. Whoever reads it can
    mint a cookie for any user and walk in as the administrator — so every
    clinic gets a key of its own, written down and kept."""
    from app.settings_file import DEFAULT_SECRET, ensure_file, ensure_secret

    root = str(tmp_path)
    ensure_file(root)
    environ = {}
    key = ensure_secret(root, environ)

    assert key and len(key) >= 40
    assert key != DEFAULT_SECRET
    assert environ["SECRET_KEY"] == key
    assert f"SECRET_KEY={key}" in (tmp_path / "clinic.env").read_text(encoding="utf-8")


def test_the_key_survives_a_restart(tmp_path):
    """Generating a new one every start would sign the whole clinic out every
    morning."""
    from app.settings_file import ensure_file, ensure_secret

    root = str(tmp_path)
    ensure_file(root)
    first = ensure_secret(root, {})

    environ = {}
    assert ensure_secret(root, environ) is None      # nothing new written
    assert environ["SECRET_KEY"] == first            # …the old one is loaded


def test_an_install_that_never_had_a_key_gets_one_on_upgrade(tmp_path):
    """The clinics already running are exactly the ones exposed, so the file
    is topped up rather than only written on a fresh install."""
    from app.settings_file import ensure_secret

    env_file = tmp_path / "clinic.env"
    env_file.write_text("PORT=8080\nDEFAULT_LANGUAGE=ar\n", encoding="utf-8")

    key = ensure_secret(str(tmp_path), {})
    assert key
    text = env_file.read_text(encoding="utf-8")
    assert f"SECRET_KEY={key}" in text
    assert "PORT=8080" in text, "the clinic's own settings must survive"


def test_a_key_somebody_set_on_purpose_is_left_alone(tmp_path):
    from app.settings_file import ensure_secret

    (tmp_path / "clinic.env").write_text("PORT=5000\n", encoding="utf-8")
    environ = {"SECRET_KEY": "a-key-the-admin-chose-themselves"}

    assert ensure_secret(str(tmp_path), environ) is None
    assert environ["SECRET_KEY"] == "a-key-the-admin-chose-themselves"
    assert "SECRET_KEY" not in (tmp_path / "clinic.env").read_text(encoding="utf-8")


def test_the_public_default_counts_as_no_key_at_all(tmp_path):
    """Finding the shipped constant in the environment is not "configured"."""
    from app.settings_file import DEFAULT_SECRET, ensure_file, ensure_secret

    root = str(tmp_path)
    ensure_file(root)
    environ = {"SECRET_KEY": DEFAULT_SECRET}

    key = ensure_secret(root, environ)
    assert key and environ["SECRET_KEY"] == key != DEFAULT_SECRET


# --------------------------------------------------- how the server starts --
def test_the_clinic_starts_without_the_debugger(monkeypatch):
    """Flask's debugger puts a Python console on any error page, and this
    server listens on the whole network. It has to be something a developer
    asks for, never something a clinic lands in by leaving a default alone."""
    import run

    monkeypatch.delenv("FLASK_CONFIG", raising=False)
    assert os.environ.get("FLASK_CONFIG") is None
    assert run.app.debug is False


def test_a_developer_can_still_ask_for_it():
    from app import create_app

    assert create_app("development").debug is True


def test_the_session_cookie_is_not_marked_secure_on_a_plain_http_clinic():
    """Marking it secure without TLS means the browser never sends it back
    and nobody can log in — most clinics run this on the practice LAN over
    plain HTTP."""
    from app import create_app

    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True


def test_behind_real_https_the_cookies_tighten(monkeypatch):
    from app import create_app

    monkeypatch.setenv("HTTPS", "1")
    app = create_app("production")
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_SECURE"] is True


# ------------------------------------------- clinic.env has to mean something --
def test_the_settings_file_actually_reaches_the_config(monkeypatch):
    """The config classes read the environment while their class bodies run —
    at import time. run.py imports the app first and reads clinic.env second,
    so everything a clinic wrote in that file was read too late and silently
    ignored: the database location and the session key included.

    Which would also have made generating a key pointless — the app would go
    on signing cookies with the one printed in the source.
    """
    from app import create_app

    monkeypatch.setenv("SECRET_KEY", "the-key-from-clinic-env")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///from_clinic_env.db")
    app = create_app("production")

    assert app.config["SECRET_KEY"] == "the-key-from-clinic-env"
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///from_clinic_env.db"


def test_a_blank_line_in_the_settings_file_overrides_nothing(monkeypatch):
    """`SECRET_KEY=` with nothing after it must not hand the clinic an empty
    key — that is worse than the default, not better."""
    from app import create_app

    monkeypatch.setenv("SECRET_KEY", "   ")
    monkeypatch.setenv("DATABASE_URL", "")
    app = create_app("production")

    assert app.config["SECRET_KEY"].strip()
    assert "from_clinic_env" not in app.config["SQLALCHEMY_DATABASE_URI"]


def test_a_clinic_can_still_sign_in_with_the_production_settings(tmp_path,
                                                                 monkeypatch):
    """The whole hardening is worthless if it locks the clinic out. This is
    the check that says the door still opens."""
    from app import create_app
    from app.extensions import db

    # Pointed at this test's own database through DATABASE_URL — the very
    # mechanism fixed above — and then verified, because running against the
    # developer's real database would create users in it.
    db_file = tmp_path / "p.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    app = create_app("production")
    assert str(db_file) in app.config["SQLALCHEMY_DATABASE_URI"], \
        "refusing to run against a database that isn't this test's"

    with app.app_context():
        db.create_all()
        from app.models import User

        user = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        user.set_password("secret")
        db.session.add(user)
        db.session.commit()

    client = app.test_client()
    signed_in = client.post("/login", data={"username": "boss",
                                            "password": "secret"},
                            follow_redirects=True)
    assert signed_in.status_code == 200
    assert client.get("/patients/").status_code == 200, "the session was dropped"


@pytest.mark.parametrize("name", ["waitress"])
def test_the_real_server_is_actually_installed(name):
    """run.py falls back to the development server with a warning when it
    isn't — a fallback nobody should be relying on."""
    import importlib

    assert importlib.import_module(name)
