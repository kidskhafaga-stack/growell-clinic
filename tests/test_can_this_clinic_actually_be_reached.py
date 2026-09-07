"""The round trip that tells an admin whether receiving works.

Setting up inbound WhatsApp is done blind. The clinic types an address, opens
a tunnel, pastes a URL into two dashboards, and waits — and when nothing
arrives there is no way to tell which link broke: the tunnel, the address,
the path, the secret, the switch, or the provider's subscription. So the
whole thing gets abandoned, or believed without evidence.

These tests pin what the check must be able to tell apart, because a checker
that only answers "yes/no" would replace six problems with one useless word.
Chief among them: a **wrong** secret being accepted. That is not a working
connection, it is somebody else's server on the clinic's address collecting
what parents write — and reporting it as success would be worse than
reporting nothing at all.

Nothing here reaches the network. Each test replaces the one call the module
makes with the answer a real server would have given.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

BASE = "https://clinic.example.com"
SECRET = "a-long-enough-webhook-secret-value"
VERIFY = "my-verify-token"


@pytest.fixture()
def clinic():
    """A clinic with an address, a secret, and receiving switched on."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting

        Setting.set("wa_public_base_url", BASE)
        Setting.set("wa_webhook_secret", SECRET)
        Setting.set("wa_meta_verify_token", VERIFY)
        Setting.set("wa_inbound_enabled", "1")

        from app.models import User

        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)
        db.session.commit()

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "client": app.test_client(),
            "sign_in": sign_in}


def answering(monkeypatch, replies):
    """Stand in for the network. ``replies`` is called with the URL."""
    from app.utils import wa_connect

    seen = []

    def fake(url, data=None, timeout=wa_connect.TIMEOUT_SECONDS):
        seen.append(url)
        return replies(url)

    monkeypatch.setattr(wa_connect, "_call", fake)
    return seen


def a_working_server(url):
    """What this program actually answers, on each of its own endpoints."""
    if "/wapilot/" in url:
        return (200, '{"ok": true}') if SECRET in url else (403, "")
    challenge = url.rsplit("hub.challenge=", 1)[-1]
    return (200, challenge) if VERIFY in url else (403, "")


# ------------------------------------------------------------ the good case --
def test_a_working_clinic_reads_as_working(clinic, monkeypatch):
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, a_working_server)
        result = wa_connect.check()
    assert result["wapilot"]["verdict"] == "ok"
    assert result["meta"]["verdict"] == "ok"
    assert result["base"] == BASE


def test_the_wrong_secret_is_tried_before_the_right_one(clinic, monkeypatch):
    """A success from the right secret means nothing until a wrong one has
    been refused — anything can answer 200."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        seen = answering(monkeypatch, a_working_server)
        wa_connect.check_wapilot()
    assert len(seen) == 2
    assert SECRET not in seen[0]
    assert SECRET in seen[1]


def test_the_probe_never_invents_a_message(clinic, monkeypatch):
    """An empty body is what the receiver already answers and files nothing."""
    from app.models import MessageLog
    from app.utils import wa_connect

    sent = []

    def capture(url, data=None, timeout=wa_connect.TIMEOUT_SECONDS):
        sent.append(data)
        return a_working_server(url)

    with clinic["app"].app_context():
        monkeypatch.setattr(wa_connect, "_call", capture)
        wa_connect.check()
        assert MessageLog.query.count() == 0
    for body in [b for b in sent if b is not None]:
        assert json.loads(body) == {}


# ----------------------------------------------- what it has to tell apart --
def test_somebody_else_answering_is_never_called_success(clinic, monkeypatch):
    """The dangerous one: a token that should be refused gets a 200.

    Every message a parent sends is going to that server instead. Calling
    this "reachable" would hand the clinic a false all-clear.
    """
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, lambda url: (200, '{"ok": true}'))
        verdict = wa_connect.check_wapilot()["verdict"]
    assert verdict == "impostor"


def test_switched_off_is_not_the_same_as_working(clinic, monkeypatch):
    """Receiving off answers 200 with an empty body, on purpose, so the
    provider stops retrying. From outside that looks identical to working."""
    from app.utils import wa_connect

    def off(url):
        if "/wapilot/" in url:
            return (200, "") if SECRET in url else (403, "")
        return a_working_server(url)

    with clinic["app"].app_context():
        answering(monkeypatch, off)
        assert wa_connect.check_wapilot()["verdict"] == "off"


def test_nothing_answering_is_its_own_answer(clinic, monkeypatch):
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, lambda url: (None, "URLError"))
        assert wa_connect.check_wapilot()["verdict"] == "unreachable"
        assert wa_connect.check_meta()["verdict"] == "unreachable"


def test_reaching_the_wrong_server_is_not_unreachable(clinic, monkeypatch):
    """A 404 means DNS and the tunnel worked and the path did not — which is
    a different afternoon's work from nothing answering."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, lambda url: (404, "Not Found"))
        assert wa_connect.check_wapilot()["verdict"] == "wrong_place"
        assert wa_connect.check_meta()["verdict"] == "wrong_place"


def test_the_right_secret_refused_says_so(clinic, monkeypatch):
    """What a stale deployment looks like: the settings and the running copy
    hold different secrets."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, lambda url: (403, ""))
        assert wa_connect.check_wapilot()["verdict"] == "refused"


def test_meta_must_echo_the_challenge_unchanged(clinic, monkeypatch):
    """A 200 carrying anything else is an agreeable stranger, and Meta's own
    dashboard would reject it."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        answering(monkeypatch, lambda url: (200, "sure thing"))
        assert wa_connect.check_meta()["verdict"] == "impostor"


def test_the_challenge_is_different_every_time(clinic, monkeypatch):
    """Otherwise a server that once echoed it could just remember it."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        seen = answering(monkeypatch, a_working_server)
        wa_connect.check_meta()
        wa_connect.check_meta()
    assert seen[0] != seen[1]


# ------------------------------------------------------ nothing set up yet --
def test_with_no_address_there_is_nothing_to_test(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import wa_connect

    with clinic["app"].app_context():
        Setting.set("wa_public_base_url", "")
        clinic["db"].session.commit()
        calls = answering(monkeypatch, a_working_server)
        result = wa_connect.check()
    assert result["wapilot"]["verdict"] == "not_set"
    assert result["meta"]["verdict"] == "not_set"
    assert calls == []          # and it does not go looking


def test_meta_with_no_verify_token_is_not_a_failure(clinic, monkeypatch):
    """A clinic on WaPilot alone has no Meta token, and is not broken."""
    from app.models import Setting
    from app.utils import wa_connect

    with clinic["app"].app_context():
        Setting.set("wa_meta_verify_token", "")
        clinic["db"].session.commit()
        answering(monkeypatch, a_working_server)
        assert wa_connect.check_meta()["verdict"] == "not_set"
        assert wa_connect.check_wapilot()["verdict"] == "ok"


# -------------------------------------------------------------- the URLs --
def test_the_url_offered_is_the_url_tested(clinic):
    """The screen shows one address and the check must probe that same one,
    or a pass proves nothing about what was pasted into the dashboard."""
    from app.utils import wa_connect

    with clinic["app"].app_context():
        assert wa_connect.wapilot_url() == f"{BASE}/wa/webhook/wapilot/{SECRET}"
        assert wa_connect.meta_url() == f"{BASE}/wa/webhook/meta"


def test_a_trailing_slash_does_not_double_up(clinic):
    from app.models import Setting
    from app.utils import wa_connect

    with clinic["app"].app_context():
        Setting.set("wa_public_base_url", BASE + "/")
        clinic["db"].session.commit()
        assert "//wa/webhook" not in wa_connect.meta_url()


# ------------------------------------------------------------- the route --
def test_the_check_is_admin_only(clinic):
    """It makes the clinic's server open an outbound connection. That is not
    something an unauthenticated link gets to trigger."""
    assert clinic["client"].post("/messages/connection/test").status_code in (302, 401, 403)


def test_an_admin_gets_the_verdicts_back(clinic, monkeypatch):
    from app.utils import wa_connect

    monkeypatch.setattr(wa_connect, "check",
                        lambda: {"base": BASE, "inbound_on": True,
                                 "wapilot": {"verdict": "ok", "detail": None},
                                 "meta": {"verdict": "off", "detail": None}})
    body = clinic["sign_in"]().post("/messages/connection/test").get_json()
    assert body["wapilot"]["verdict"] == "ok"
    assert body["meta"]["verdict"] == "off"


# --------------------------------------------------- the steps on screen --
def test_the_steps_carry_this_clinics_own_values(clinic):
    """An admin reading a manual has to translate every placeholder into
    their own address and secret, and that translation is where the mistakes
    live. The screen prints the real thing so there is nothing to translate.
    """
    page = clinic["sign_in"]().get("/messages/occasions")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f"{BASE}/wa/webhook/wapilot/{SECRET}" in html
    assert f"{BASE}/wa/webhook/meta" in html
    assert VERIFY in html            # Meta's verify token, ready to copy


def test_the_url_in_the_steps_is_the_one_that_gets_tested(clinic, monkeypatch):
    """Otherwise a pass upstairs says nothing about what was pasted below."""
    from app.utils import wa_connect

    html = clinic["sign_in"]().get("/messages/occasions").get_data(as_text=True)
    with clinic["app"].app_context():
        assert wa_connect.wapilot_url() in html
        assert wa_connect.meta_url() in html


def test_the_steps_say_to_leave_the_broader_event_off(clinic):
    """``message.any`` includes the clinic's own sends, so subscribing to it
    files the clinic's outgoing messages as if parents had written them."""
    html = clinic["sign_in"]().get("/messages/occasions").get_data(as_text=True)
    assert "message.any" in html


def test_with_no_verify_token_the_step_asks_for_one(clinic):
    """Rather than printing an empty box beside "put this in Verify Token"."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("wa_meta_verify_token", "")
        clinic["db"].session.commit()
    html = clinic["sign_in"]().get("/messages/occasions").get_data(as_text=True)
    # Read from the locale file: ``t()`` needs a request context, and this
    # test is outside one.
    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        assert json.load(fh)["crm"]["steps_meta_missing"] in html


# --------------------------------------------------------- the vocabulary --
def test_every_verdict_the_checks_produce_is_declared(clinic, monkeypatch):
    """The screen renders from ``VERDICTS``; one missing from it renders as
    nothing, which is how a real failure turns into an empty box.

    Every server behaviour worth telling apart is driven through both checks
    here, and what comes out has to be a word the screen knows.
    """
    from app.utils import wa_connect

    servers = [
        a_working_server,
        lambda url: (200, '{"ok": true}'),      # accepts anything
        lambda url: (200, "") if SECRET in url else (403, ""),
        lambda url: (None, "URLError"),
        lambda url: (404, "Not Found"),
        lambda url: (403, ""),
        lambda url: (500, "boom"),
        lambda url: (200, "sure thing"),
    ]
    produced = set()
    with clinic["app"].app_context():
        for server in servers:
            answering(monkeypatch, server)
            produced.add(wa_connect.check_wapilot()["verdict"])
            produced.add(wa_connect.check_meta()["verdict"])
        from app.models import Setting

        Setting.set("wa_public_base_url", "")
        clinic["db"].session.commit()
        produced.add(wa_connect.check_wapilot()["verdict"])

    assert produced <= set(wa_connect.VERDICTS), produced - set(wa_connect.VERDICTS)
    # And nothing is declared that nothing can ever produce.
    assert set(wa_connect.VERDICTS) == produced
