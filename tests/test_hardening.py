"""The open doors: how fast strangers may knock, and what they may leave.

Three routes in this program answer people who are not signed in — the login
form, the two WhatsApp webhooks, and the satisfaction survey — and one folder
takes files from inside it and serves them back over the web.

The login form already refuses a *username* after five bad passwords. That
does nothing about one machine trying a thousand different usernames, because
every one of them is on its first attempt. And a file's name was deciding what
the browser would treat it as, in a folder on the clinic's own origin.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def guarded(clinic):
    """The clinic with the ceiling switched on, and the counters empty."""
    from app.utils import rate_limit

    rate_limit.reset()
    clinic["app"].config["RATELIMIT_ENABLED"] = True
    yield clinic
    rate_limit.reset()
    clinic["app"].config["RATELIMIT_ENABLED"] = False


def _try_login(client, n, password="wrong"):
    """Post the login form n times, each with a different username.

    Different names on purpose: the per-username lockout is a separate guard
    that also answers 429, and a test that can't tell which one fired is
    testing neither.
    """
    return [client.post("/login",
                        data={"username": f"guess{i}", "password": password}
                        ).status_code for i in range(n)]


# ------------------------------------------------------------ the counter ---
def test_the_first_requests_are_allowed_and_the_rest_are_not():
    from app.utils.rate_limit import hit, reset

    reset()
    assert all(hit("b", "1.2.3.4", 3, 60)[0] for _ in range(3))
    allowed, retry_after = hit("b", "1.2.3.4", 3, 60)
    assert allowed is False
    assert 0 < retry_after <= 61


def test_one_callers_spending_does_not_touch_another():
    """Otherwise the first attacker locks out the whole clinic — a denial of
    service delivered by the thing meant to prevent one."""
    from app.utils.rate_limit import hit, reset

    reset()
    for _ in range(5):
        hit("b", "attacker", 3, 60)
    assert hit("b", "receptionist", 3, 60)[0] is True


def test_separate_buckets_are_counted_separately():
    from app.utils.rate_limit import hit, reset

    reset()
    for _ in range(5):
        hit("login", "1.2.3.4", 3, 60)
    assert hit("survey", "1.2.3.4", 3, 60)[0] is True


def test_the_window_expires(monkeypatch):
    from app.utils import rate_limit

    rate_limit.reset()
    for _ in range(3):
        rate_limit.hit("b", "k", 3, 60, now=1000.0)
    assert rate_limit.hit("b", "k", 3, 60, now=1030.0)[0] is False
    assert rate_limit.hit("b", "k", 3, 60, now=1061.0)[0] is True


def test_the_table_does_not_grow_without_end():
    """Somebody rotating addresses would otherwise fill memory until the
    process died."""
    from app.utils import rate_limit

    rate_limit.reset()
    for i in range(rate_limit._SWEEP_AT + 50):
        rate_limit.hit("b", f"addr-{i}", 5, 60, now=1000.0)
    # One request a window later, and the expired ones are gone.
    rate_limit.hit("b", "later", 5, 60, now=2000.0)
    assert len(rate_limit._hits) < rate_limit._SWEEP_AT


# ------------------------------------------------------------- the login ----
def test_a_thousand_usernames_from_one_machine_is_stopped(guarded):
    """The per-username lockout never sees this: every name is on its first
    attempt."""
    from app.utils.rate_limit import LOGIN_PER_MINUTE

    client = guarded["app"].test_client()
    codes = [client.post("/login",
                         data={"username": f"user{i}", "password": "x"}
                         ).status_code
             for i in range(LOGIN_PER_MINUTE + 3)]

    assert 429 in codes
    assert codes[0] == 401, "the honest first attempt still gets answered"


def test_the_refusal_says_when_to_come_back(guarded):
    from app.utils.rate_limit import LOGIN_PER_MINUTE

    client = guarded["app"].test_client()
    _try_login(client, LOGIN_PER_MINUTE + 1)
    resp = client.post("/login", data={"username": "x", "password": "y"})

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


def test_the_refusal_gives_nothing_away(guarded):
    """"Too many attempts" on the login screen tells you a real username was
    found. This one has to read the same for a guess, a forgery and a scrape."""
    from app.utils.rate_limit import LOGIN_PER_MINUTE

    client = guarded["app"].test_client()
    _try_login(client, LOGIN_PER_MINUTE + 1)
    body = client.post("/login",
                       data={"username": "boss", "password": "secret"}
                       ).get_data(as_text=True)

    assert "boss" not in body


def test_opening_the_login_page_is_not_an_attempt(guarded):
    """A receptionist who refreshes twenty times has done nothing wrong."""
    client = guarded["app"].test_client()

    codes = [client.get("/login").status_code for _ in range(30)]

    assert 429 not in codes


def test_signing_in_normally_still_works(guarded):
    """The ceiling has to sit above what the clinic actually does."""
    client = guarded["app"].test_client()

    resp = client.post("/login",
                       data={"username": "boss", "password": "secret"},
                       follow_redirects=True)

    assert resp.status_code == 200


# ----------------------------------------------------------- the webhook ----
def test_the_webhook_is_capped_too(guarded):
    from app.utils.rate_limit import WEBHOOK_PER_MINUTE

    client = guarded["app"].test_client()
    codes = [client.post("/wa/webhook/meta", json={}).status_code
             for _ in range(WEBHOOK_PER_MINUTE + 2)]

    assert codes[0] == 403, "an unsigned delivery is still refused on merit"
    assert codes[-1] == 429


def test_the_webhook_ceiling_is_far_above_a_busy_clinic(guarded):
    """Dropping a patient's message to slow an attacker who is already being
    turned away by the signature check would be the wrong trade."""
    from app.utils.rate_limit import WEBHOOK_PER_MINUTE

    assert WEBHOOK_PER_MINUTE >= 100


# ------------------------------------------------------------ the survey ----
def test_the_survey_link_cannot_be_hammered(guarded):
    from app.utils.rate_limit import SURVEY_PER_MINUTE

    client = guarded["app"].test_client()
    codes = [client.get("/f/nosuchtoken").status_code
             for _ in range(SURVEY_PER_MINUTE + 2)]

    assert codes[0] == 404
    assert codes[-1] == 429


# ------------------------------------------------------- off unless asked ---
def test_the_suite_is_not_fighting_the_guard(clinic):
    """A test file that signs in forty times is not an attack, and a limiter
    that made the suite flaky would be turned off for real soon after."""
    assert clinic["app"].config["RATELIMIT_ENABLED"] is False
    client = clinic["app"].test_client()
    # Distinct names, so the only thing that could return 429 here is the
    # per-caller ceiling — the per-username lockout is a different guard and
    # is meant to fire.
    codes = [client.post("/login", data={"username": f"u{i}", "password": "x"}
                         ).status_code for i in range(25)]
    assert 429 not in codes


# ---------------------------------------------------------- what is stored --
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF = b"%PDF-1.7\n" + b"\x00" * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _upload(clinic, data, filename):
    from app.utils.uploads import save_document
    from werkzeug.datastructures import FileStorage

    with clinic["app"].app_context():
        return save_document(FileStorage(stream=io.BytesIO(data),
                                         filename=filename))


def test_a_real_image_is_stored(clinic):
    assert (_upload(clinic, PNG, "xray.png") or "").endswith(".png")


def test_a_pdf_report_is_stored(clinic):
    assert (_upload(clinic, PDF, "report.pdf") or "").endswith(".pdf")


def test_a_script_wearing_a_png_name_is_refused(clinic):
    """This folder is served from the clinic's own origin. A file the browser
    decides is markup runs with the session of whoever opened it — so the
    name does not get to decide what it is."""
    assert _upload(clinic, SVG, "xray.png") is None


def test_the_extension_comes_from_the_bytes_not_the_name(clinic):
    """A PDF sent as .png is stored as a PDF, because that is what it is."""
    assert (_upload(clinic, PDF, "report.png") or "").endswith(".pdf")


def test_an_empty_file_is_not_a_document(clinic):
    assert _upload(clinic, b"", "empty.png") is None


def test_something_too_large_is_refused_before_it_lands(clinic):
    from app.utils.uploads import MAX_UPLOAD_BYTES

    huge = PNG + b"\x00" * (MAX_UPLOAD_BYTES + 1)
    assert _upload(clinic, huge, "big.png") is None


def test_a_name_nobody_should_be_uploading_is_refused(clinic):
    assert _upload(clinic, SVG, "payload.svg") is None
    assert _upload(clinic, b"<html>x</html>", "page.html") is None


def test_the_drug_leaflet_folder_follows_the_same_rule(clinic):
    """A leaflet is no safer a place to smuggle a script than an X-ray."""
    from app.utils.uploads import save_drug_media
    from werkzeug.datastructures import FileStorage

    with clinic["app"].app_context():
        assert save_drug_media(FileStorage(stream=io.BytesIO(SVG),
                                           filename="box.png")) is None
        assert save_drug_media(FileStorage(stream=io.BytesIO(PNG),
                                           filename="box.png"))


def test_sniffing_knows_the_types_the_clinic_keeps():
    from app.utils.uploads import sniff_ext

    assert sniff_ext(PNG) == "png"
    assert sniff_ext(PDF) == "pdf"
    assert sniff_ext(b"\xff\xd8\xff\xe0") == "jpg"
    assert sniff_ext(b"GIF89a....") == "gif"
    assert sniff_ext(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"
    assert sniff_ext(SVG) is None
    assert sniff_ext(b"") is None


# --------------------------------------------------------------- headers ----
def test_the_browser_is_told_not_to_second_guess_a_stored_file(clinic):
    resp = clinic["app"].test_client().get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_the_clinic_is_not_loadable_inside_someone_elses_page(clinic):
    resp = clinic["app"].test_client().get("/login")
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"


# ---------------------------------------------------------- the cookies -----
def test_the_remember_cookie_is_protected_everywhere_not_only_in_production():
    """It signs you in without the session, lives longer than it, and is the
    more valuable of the two to steal. It used to be hardened in
    ProductionConfig alone."""
    from config import config

    for name in ("default", "development", "production"):
        cfg = config[name]
        assert cfg.REMEMBER_COOKIE_HTTPONLY is True, name
        assert cfg.REMEMBER_COOKIE_SAMESITE == "Lax", name
