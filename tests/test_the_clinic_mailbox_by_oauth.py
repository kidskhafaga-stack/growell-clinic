"""صندوق إيميل بيطلب تسجيل دخول Google أو Microsoft — من توثيقهم.

* **الربط**: رابط الدخول فيه ``state`` و PKCE (S256)، ولـ Google
  ``access_type=offline`` و ``prompt=consent``؛ الرجوع بـ state غلط ما
  بيحفظش حاجة، والـ ``code_verifier`` اللي بيتبعت هو اللي اتعمل منه الـ
  challenge؛ ولو الشخص شال صلاحية Gmail الربط بيترفض؛
* **الدخول**: IMAP بـ ``AUTHENTICATE XOAUTH2`` و SMTP بـ ``AUTH XOAUTH2``
  بالصيغة ``user=…^Aauth=Bearer …^A^A``، وبعد تحدي الخطأ سطر فاضي؛
* **التجديد**: المفتاح بيتجدد لما يقرب يخلص، و Microsoft لو رجّع مفتاح تجديد
  جديد بيتحفظ مكان القديم؛ ولو التجديد اترفض الشاشة بتقول «اربطه تاني».
"""
import base64
import hashlib
import os
import sys
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

USER = "clinic@clinic.example"


@pytest.fixture()
def box(clinic, monkeypatch):
    from app.models import Setting
    from app.utils import channels, social

    with clinic["app"].app_context():
        for k, v in (("mail_auth", "google"), ("mail_oauth_client_id", "cid.apps"),
                     ("mail_oauth_client_secret", "csecret"),
                     ("mail_oauth_client_id_was", "cid.apps"),
                     ("mail_user", USER), ("mail_address", USER),
                     ("mail_imap_host", "imap.gmail.com"),
                     ("mail_smtp_host", "smtp.gmail.com")):
            Setting.set(k, v)
        channels.set_enabled(["whatsapp", "email"])
        clinic["db"].session.commit()
    calls = []
    answer = {"data": {"access_token": "AT1", "expires_in": 3599,
                       "refresh_token": "RT1", "scope": "https://mail.google.com/",
                       "token_type": "Bearer"}}

    def fake_form(url, fields):
        calls.append((url, dict(fields)))
        return 200, dict(answer["data"])
    monkeypatch.setattr(social, "_post_form", fake_form)
    clinic["calls"], clinic["answer"] = calls, answer
    return clinic


def _connect(boss, code="C1"):
    start = boss.get("/messages/channels/mail-oauth/start")
    assert start.status_code == 302
    with boss.session_transaction() as sess:
        state, verifier = sess["mail_oauth_state"], sess["mail_oauth_verifier"]
    boss.get(f"/messages/channels/mail-oauth/callback?code={code}&state={state}")
    return start.headers["Location"], verifier


def test_connecting_google_checks_state_pkce_and_the_scope(box):
    from app.models import Setting

    boss = box["sign_in"]()
    page = boss.get("/messages/channels").get_data(as_text=True)
    assert "data-mail-oauth-fields" in page and "csecret" not in page
    assert 'data-mail-oauth-state="off"' in page and "data-mail-oauth-start" in page
    boss.get("/messages/channels/mail-oauth/start")
    boss.get("/messages/channels/mail-oauth/callback?code=C&state=forged")
    with box["app"].app_context():
        assert not Setting.get("mail_oauth_refresh"), "a forged return stores nothing"
    loc, verifier = _connect(boss)
    url = urllib.parse.urlparse(loc)
    q = dict(urllib.parse.parse_qsl(url.query))
    assert url.netloc == "accounts.google.com" and url.path == "/o/oauth2/v2/auth"
    assert q["scope"] == "https://mail.google.com/" and q["access_type"] == "offline"
    assert q["prompt"] == "consent" and q["code_challenge_method"] == "S256"
    assert q["login_hint"] == USER and q["redirect_uri"].endswith("/messages/channels/mail-oauth/callback")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == challenge
    token_url, sent = box["calls"][-1]
    assert token_url == "https://oauth2.googleapis.com/token"
    assert sent["grant_type"] == "authorization_code" and sent["code_verifier"] == verifier
    assert sent["client_secret"] == "csecret" and sent["redirect_uri"] == q["redirect_uri"]
    with box["app"].app_context():
        assert Setting.get("mail_oauth_refresh") == "RT1"
        from app.utils import mail_channel
        assert mail_channel.ready()
    assert 'data-mail-oauth-state="on"' in boss.get("/messages/channels").get_data(as_text=True)
    # The person unticked the Gmail permission: nothing is kept.
    with box["app"].app_context():
        Setting.set("mail_oauth_refresh", "")
        box["db"].session.commit()
    box["answer"]["data"] = {**box["answer"]["data"], "scope": "openid email"}
    _connect(boss, code="C2")
    with box["app"].app_context():
        assert not Setting.get("mail_oauth_refresh")
    assert box["sign_in"]("desk").get("/messages/channels/mail-oauth/start").status_code in (302, 403)


def test_the_box_signs_in_with_xoauth2_and_a_failure_says_connect_again(box, monkeypatch):
    from app.models import Setting
    from app.utils import mail_channel

    with box["app"].app_context():
        for k, v in (("mail_auth", "microsoft"), ("mail_oauth_tenant", "contoso.example"),
                     ("mail_oauth_refresh", "RT1"), ("mail_oauth_access", "OLD"),
                     ("mail_oauth_until", (datetime.utcnow() + timedelta(minutes=2)).isoformat()),
                     ("mail_last_uid", "5"), ("mail_uidvalidity", "77")):
            Setting.set(k, v)
        box["db"].session.commit()
    box["answer"]["data"] = {"access_token": "AT2", "expires_in": 3599, "refresh_token": "RT2"}
    seen = {}

    class FakeIMAP:
        def __init__(self, host, port, ssl_context=None, timeout=None):
            assert ssl_context is not None, "TLS is verified"

        def authenticate(self, mech, callback):
            seen["mech"] = mech
            seen["first"] = callback(b"")
            seen["after_error"] = callback(b'{"status":"401"}')
            return "OK", [b"done"]

        def login(self, *a):
            raise AssertionError("no password on an OAuth box")

        def select(self, name, readonly=False):
            return "OK", [b"5"]

        def response(self, code):
            return code, [b"77"]

        def uid(self, cmd, *args):
            return "OK", [b"5"]

        def logout(self):
            pass
    monkeypatch.setattr(mail_channel.imaplib, "IMAP4_SSL", FakeIMAP)
    with box["app"].app_context():
        assert mail_channel.poll() == (0, None)
        assert seen["mech"] == "XOAUTH2"
        assert seen["first"] == f"user={USER}\x01auth=Bearer AT2\x01\x01".encode()
        assert seen["after_error"] == b""
        url, sent = box["calls"][-1]
        assert url == "https://login.microsoftonline.com/contoso.example/oauth2/v2.0/token"
        assert sent["grant_type"] == "refresh_token" and sent["refresh_token"] == "RT1"
        assert "offline_access" in sent["scope"]
        assert Setting.get("mail_oauth_refresh") == "RT2", "Microsoft's new refresh token is kept"
        # The refresh token stops working: the screen says so.
        Setting.set("mail_oauth_until", datetime.utcnow().isoformat())
        box["db"].session.commit()
        box["answer"]["data"] = {"error": "invalid_grant"}
        assert mail_channel.poll() == (0, "oauth: invalid_grant")
    page = box["sign_in"]().get("/messages/channels").get_data(as_text=True)
    assert 'data-mail-oauth-state="error"' in page


def test_a_reply_goes_out_with_smtp_xoauth2(box, monkeypatch):
    from app.models import Setting
    from app.utils import mail_channel

    with box["app"].app_context():
        Setting.set("mail_oauth_refresh", "RT1")
        Setting.set("mail_oauth_access", "AT9")
        Setting.set("mail_oauth_until", (datetime.utcnow() + timedelta(hours=1)).isoformat())
        box["db"].session.commit()
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            seen["host"] = (host, port)

        def starttls(self, context=None):
            assert context is not None

        def ehlo(self):
            pass

        def auth(self, mech, authobject):
            seen["mech"], seen["first"] = mech, authobject()
            seen["after_error"] = authobject("err")

        def login(self, *a):
            raise AssertionError("no password on an OAuth box")

        def send_message(self, msg):
            seen["to"] = msg["To"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(mail_channel.smtplib, "SMTP", FakeSMTP)
    with box["app"].app_context():
        ok, _, err = mail_channel.send("mona@example.com", "تمام")
    assert ok and err is None and seen["host"] == ("smtp.gmail.com", 587)
    assert seen["mech"] == "XOAUTH2" and seen["first"] == f"user={USER}\x01auth=Bearer AT9\x01\x01"
    assert seen["after_error"] == "" and seen["to"] == "mona@example.com"
    assert not box["calls"], "a live token is not renewed"


def test_choosing_a_provider_fills_its_servers_and_a_change_forgets_old_tokens(box):
    from app.models import Setting

    with box["app"].app_context():
        Setting.set("mail_oauth_refresh", "RT1")
        Setting.set("mail_imap_host", "")
        Setting.set("mail_smtp_host", "")
        box["db"].session.commit()
    boss = box["sign_in"]()
    form = {"mail_auth": "microsoft", "mail_oauth_client_id": "cid.apps",
            "mail_user": USER, "mail_address": USER}
    boss.post("/messages/channels/connect", data=form)
    with box["app"].app_context():
        assert Setting.get("mail_imap_host") == "outlook.office365.com"
        assert Setting.get("mail_smtp_host") == "smtp.office365.com"
        assert not Setting.get("mail_oauth_refresh"), "Google's token is not Microsoft's"
        Setting.set("mail_oauth_refresh", "RT5")
        box["db"].session.commit()
    boss.post("/messages/channels/connect", data={
        **form, "mail_imap_host": "outlook.office365.com",
        "mail_smtp_host": "smtp.office365.com"})
    with box["app"].app_context():
        assert Setting.get("mail_oauth_refresh") == "RT5", "saving again keeps the connection"
