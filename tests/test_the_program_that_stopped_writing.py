"""A licence that ran out, and a clinic that could still read its own files.

The program is installed on a clinic's own computer with nothing to phone home
to, so a licence has to be a signed file: three facts — which machine, until
when, issued to whom — with the vendor's signature over them. Nothing in this
repository can make one. These tests make their own throwaway key pair in
memory and sign with that, which is the only way to test a verifier at all;
the key exists for the length of one test and could not validate a licence
against any shipped build.

**What being unlicensed does is stop writing, not stop working.** A clinic
whose licence lapsed on a Thursday still has children in the waiting room and
still has to answer "what is this child allergic to?". So the file, the chart,
the statement and the printed receipt all stay; adding and editing stop.

**And that promise is only worth what it is enforced with.** The obvious guard
refuses POST and calls it read-only. It is not: eighteen screens in this
program change something on a plain GET — a visit starts, an appointment is
confirmed — and every one of them would have gone through a method check
untouched. The rule is stated on the database session instead, which is why
there is a test below that starts a visit with a GET.

The other half of the story is what happens with **no vendor key at all**,
which is how this ships. Nothing is enforced, and a clinic already running
keeps running. That test is the first one here, and it is the one that would
matter most if it broke.
"""
import base64
import json
from datetime import date, timedelta

import pytest


# What "add a child" is on the form the reception desk uses.
_NEW_CHILD = {"full_name": "طفل جديد", "date_of_birth": "2024-01-01",
              "gender": "male", "auto_number": "1"}


# --------------------------------------------------------------- a key pair --
def _keypair():
    """A vendor key that exists for one test.

    The private half never leaves this function's frame and is not written
    anywhere. The repository holds no key that can sign a real licence and
    must not; this is the throwaway one a verifier has to be given to be
    tested at all.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def _sign(private, payload):
    body = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")

    def b64(raw):
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{b64(body)}.{b64(private.sign(body))}"


@pytest.fixture
def vendor(monkeypatch):
    """A signing key, installed as this build's vendor key."""
    private, public = _keypair()
    monkeypatch.setenv("PEDIAPRO_LICENCE_KEY", public)
    return private


@pytest.fixture
def licensed(clinic, tmp_path):
    """A clinic whose licence file is somewhere the tests may write."""
    clinic["app"].config["LICENCE_FILE"] = str(tmp_path / "licence.lic")
    return clinic


def _install(clinic, text):
    with open(clinic["app"].config["LICENCE_FILE"], "w", encoding="utf-8") as f:
        f.write(text)


def _machine(clinic):
    from app.utils import licensing

    with clinic["app"].app_context():
        return licensing.machine_fingerprint() or "*"


def _for_this_machine(clinic, days=365, **extra):
    payload = {"v": 1, "clinic": "عيادة النمو", "id": "GC-0007",
               "machine": _machine(clinic),
               "expires": (date.today() + timedelta(days=days)).isoformat()}
    payload.update(extra)
    return payload


# ------------------------------------------------- shipping this is safe ----
def test_with_no_vendor_key_nothing_is_enforced(clinic, monkeypatch):
    """The property that makes this feature safe to merge at all.

    The published source carries no vendor key, so every clinic already
    running this program keeps running it. If this test ever fails, merging
    licensing locked a working clinic out of its own records.
    """
    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    from app.utils import licensing

    with clinic["app"].app_context():
        monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY", "")
        verdict = licensing.check()
    assert verdict.state == "dormant"
    assert verdict.locked is False


def test_a_dormant_build_still_writes(clinic, monkeypatch):
    """Stated through a screen, not only through the verdict object."""
    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    boss = clinic["sign_in"]("boss")
    before = _patient_count(clinic)
    boss.post("/patients/new", data=_NEW_CHILD,
              follow_redirects=True)
    assert _patient_count(clinic) == before + 1


def _patient_count(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        return Patient.query.count()


# ------------------------------------------------------- reading the file ---
def test_a_licence_signed_by_the_vendor_is_accepted(licensed, vendor):
    from app.utils import licensing

    text = _sign(vendor, _for_this_machine(licensed))
    with licensed["app"].app_context():
        verdict = licensing.check(text)
    assert verdict.state == "valid"
    assert verdict.issued_to == "عيادة النمو"
    assert verdict.serial == "GC-0007"


def test_a_licence_somebody_edited_is_refused(licensed, vendor):
    """The date is the field worth changing, so it is the field tested.

    The signature covers the payload's exact bytes, so moving the year forward
    breaks it — which is the only thing standing between an expiry date and a
    text editor.
    """
    from app.utils import licensing

    payload = _for_this_machine(licensed, days=-1)
    text = _sign(vendor, payload)
    body, signature = text.split(".")
    forged = payload | {"expires": "2099-01-01"}
    swapped = base64.urlsafe_b64encode(
        json.dumps(forged, ensure_ascii=False,
                   separators=(",", ":")).encode()).decode().rstrip("=")
    with licensed["app"].app_context():
        assert licensing.check(f"{swapped}.{signature}").state == "bad_signature"


def test_a_licence_signed_by_somebody_else_is_refused(licensed, vendor):
    """Anybody can generate a key pair. Only one of them is this vendor's."""
    from app.utils import licensing

    other, _ = _keypair()
    text = _sign(other, _for_this_machine(licensed))
    with licensed["app"].app_context():
        assert licensing.check(text).state == "bad_signature"


def test_rubbish_is_a_state_and_not_a_crash(licensed, vendor):
    """It arrives by being pasted into a box, so it arrives wrong."""
    from app.utils import licensing

    with licensed["app"].app_context():
        for junk in ("", "hello", "a.b", "....", "eyJ9.zzz", "a." * 300):
            assert licensing.check(junk).state in ("missing", "malformed",
                                                   "bad_signature")


# -------------------------------------------------------- which machine -----
def test_a_licence_for_another_computer_is_refused(licensed, vendor):
    """The copy that was sent to a colleague."""
    from app.utils import licensing

    payload = _for_this_machine(licensed)
    payload["machine"] = "0000-1111-2222-3333"
    with licensed["app"].app_context():
        verdict = licensing.check(_sign(vendor, payload))
    assert verdict.state == "wrong_machine"
    assert verdict.locked is True


def test_a_clinic_licence_runs_on_any_machine(licensed, vendor):
    """The escape hatch, and it earns its place.

    Some machines have no readable identifier at all — a locked-down Windows
    image, a container, a stripped Linux install. Without a licence that is
    not bound to one, the only answer this program could give those clinics is
    "you cannot use what you bought".
    """
    from app.utils import licensing

    payload = _for_this_machine(licensed)
    payload["machine"] = "*"
    with licensed["app"].app_context():
        assert licensing.check(_sign(vendor, payload)).state == "valid"


def test_the_machine_number_is_steady(licensed):
    """Asked twice, the same answer. A fingerprint that drifts is a clinic
    locked out by a reboot."""
    from app.utils import licensing

    with licensed["app"].app_context():
        first = licensing.machine_fingerprint()
        second = licensing.machine_fingerprint()
    assert first == second


def test_the_machine_number_cannot_be_turned_back_into_the_machine_id(
        licensed, monkeypatch):
    """It is read down a phone to the vendor, so it travels — and what travels
    must not be a stable handle on somebody's computer.

    Asserted by trying to undo it, not by looking for the id inside the
    string. A first attempt checked "the raw id is not a substring of what is
    shown", and mutation testing walked straight through it: replacing the
    hash with a plain hex encoding of the same bytes passed that test while
    printing the machine id in another alphabet. Reading the hex back gives
    the id; reading a hash back gives noise.
    """
    from app.utils import licensing

    raw = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(licensing, "_raw_machine_id", lambda: raw)
    with licensed["app"].app_context():
        shown = licensing.machine_fingerprint()

    undone = bytes.fromhex(shown.replace("-", "")).decode("latin-1")
    assert undone not in raw, f"the machine id decodes out of {shown}"
    assert raw not in shown


# ------------------------------------------------------------- the date -----
def test_a_licence_past_its_date_is_expired(licensed, vendor):
    from app.utils import licensing

    text = _sign(vendor, _for_this_machine(licensed, days=-1))
    with licensed["app"].app_context():
        verdict = licensing.check(text)
    assert verdict.state == "expired"
    assert verdict.locked is True


def test_the_last_day_still_works(licensed, vendor):
    """Off-by-one on the day a clinic is standing in the building."""
    from app.utils import licensing

    text = _sign(vendor, _for_this_machine(licensed, days=0))
    with licensed["app"].app_context():
        assert licensing.check(text).state == "valid"


def test_it_says_so_before_it_stops(licensed, vendor):
    """A licence that lapses without warning is a clinic locked out on a
    morning nobody planned for."""
    from app.utils import licensing

    text = _sign(vendor, _for_this_machine(licensed, days=10))
    with licensed["app"].app_context():
        verdict = licensing.check(text)
    assert verdict.ok
    assert verdict.expiring_soon
    assert verdict.days_left == 10


def test_a_licence_with_plenty_left_says_nothing(licensed, vendor):
    from app.utils import licensing

    text = _sign(vendor, _for_this_machine(licensed, days=300))
    with licensed["app"].app_context():
        assert licensing.check(text).expiring_soon is False


def test_a_licence_with_no_date_never_runs_out(licensed, vendor):
    """A vendor selling one outright should not have to type 2099 and hope."""
    from app.utils import licensing

    payload = _for_this_machine(licensed)
    payload.pop("expires")
    with licensed["app"].app_context():
        verdict = licensing.check(_sign(vendor, payload))
    assert verdict.state == "valid"
    assert verdict.expires is None


# ------------------------------------------------------------- the clock ----
def _clock(monkeypatch, day):
    """What the machine's clock reads."""
    import app.utils.clock as clock

    monkeypatch.setattr(clock, "local_today", lambda: day)


def test_winding_the_clock_back_does_not_revive_a_licence(licensed, vendor,
                                                          monkeypatch):
    """An expiry date checked against a clock the licensee owns is not an
    expiry date.

    The latest day this installation has ever seen is kept in a file beside
    the licence and only ever moves forward, so setting the machine back to
    2020 changes nothing about whether a licence has run out.
    """
    from app.utils import licensing

    today = date.today()
    text = _sign(vendor, _for_this_machine(licensed, days=-1))
    with licensed["app"].app_context():
        licensing.effective_today()          # a year of ordinary use
        _clock(monkeypatch, date(2020, 1, 1))
        assert licensing.effective_today() >= today
        assert licensing.check(text).state == "expired"


def test_a_wild_clock_cannot_expire_a_licence_for_ever(licensed, vendor,
                                                       monkeypatch):
    """The half of that mechanism that matters more.

    One mistyped year — 2099 for 2026 — would otherwise write itself into the
    high-water mark and expire every licence this clinic is ever issued,
    permanently, with no way back and nothing on screen to explain it. The
    mark moves forward by at most a month at a time, so the worst a wild clock
    can do is leave the program briefly pessimistic about a licence that was
    nearly finished anyway.
    """
    from app.utils import licensing

    today = date.today()
    with licensed["app"].app_context():
        licensing.effective_today()
        _clock(monkeypatch, today + timedelta(days=26000))   # the year 2097
        licensing.effective_today()
        _clock(monkeypatch, today)                           # and corrected
        assert licensing.effective_today() <= today + timedelta(
            days=licensing.MAX_CLOCK_JUMP_DAYS)


def test_the_mark_keeps_up_with_ordinary_use(licensed, monkeypatch):
    """The cap must not make the mark lag behind a clinic that simply ran the
    program every day — a mark stuck in the past is a clock guard that guards
    nothing."""
    from app.utils import licensing

    today = date.today()
    with licensed["app"].app_context():
        licensing.effective_today()
        for step in (5, 10, 20, 25):
            _clock(monkeypatch, today + timedelta(days=step))
            assert licensing.effective_today() == today + timedelta(days=step)


# --------------------------------------------- what read-only actually is ---
@pytest.fixture
def locked_out(licensed, vendor):
    """A clinic whose licence ran out yesterday."""
    _install(licensed, _sign(vendor, _for_this_machine(licensed, days=-1)))
    return licensed


def test_a_write_is_refused(locked_out):
    boss = locked_out["sign_in"]("boss")
    before = _patient_count(locked_out)
    response = boss.post("/patients/new", data=_NEW_CHILD)
    assert response.status_code == 403
    assert _patient_count(locked_out) == before


def test_a_write_hidden_behind_a_get_is_refused_too(locked_out):
    """The reason the guard is on the session and not on the request method.

    Starting a visit is a GET in this program — press the child's name on the
    board and the visit exists. So are confirming an appointment and opening a
    message thread. A read-only mode built on "refuse POST" would have let
    every one of them write, and would have passed a test suite that only
    tried forms.
    """
    from app.models import Visit

    boss = locked_out["sign_in"]("boss")
    with locked_out["app"].app_context():
        before = Visit.query.count()
    boss.get(f"/visits/start/{locked_out['ids']['child']}",
             follow_redirects=True)
    with locked_out["app"].app_context():
        assert Visit.query.count() == before


def test_reading_still_works(locked_out):
    """The whole argument for read-only over refusing to start. A child's
    allergies do not stop mattering because an invoice went unpaid."""
    boss = locked_out["sign_in"]("boss")
    page = boss.get(f"/patients/{locked_out['ids']['child']}")
    assert page.status_code == 200


def test_signing_in_still_works(locked_out):
    """Sign-in writes an audit row and a timestamp. Blocked, nobody could
    reach the data the promise is about — or the screen that fixes it."""
    from app.models import User

    client = locked_out["app"].test_client()
    response = client.post("/login", data={"username": "boss",
                                           "password": "secret"},
                           follow_redirects=True)
    assert response.status_code == 200
    with locked_out["app"].app_context():
        assert User.query.filter_by(
            username="boss").first().last_login_at is not None


def test_every_page_says_why(locked_out):
    """A save button that does nothing, with nothing on screen explaining it,
    is the failure this program keeps having."""
    boss = locked_out["sign_in"]("boss")
    page = boss.get(f"/patients/{locked_out['ids']['child']}").get_data(
        as_text=True)
    assert "licence-bar--stop" in page


# ------------------------------------------------------- the way back out ---
@pytest.fixture
def owner(locked_out):
    from app.models import User

    with locked_out["app"].app_context():
        user = User.query.filter_by(username="boss").first()
        user.is_super_admin = True
        locked_out["db"].session.commit()
    return locked_out["sign_in"]("boss")


def test_the_licence_screen_opens_while_locked(locked_out, owner):
    """The way out of read-only must not itself be read-only."""
    page = owner.get("/settings/licence")
    assert page.status_code == 200


def test_installing_a_licence_unlocks_the_program(locked_out, owner, vendor):
    """The whole point, end to end: a renewal arrives, is pasted in, and the
    clinic can write again."""
    fresh = _sign(vendor, _for_this_machine(locked_out, days=365))
    owner.post("/settings/licence/install", data={"licence": fresh},
               follow_redirects=True)

    # Written by the desk rather than the owner: the owner of a clinic that
    # has not finished the setup wizard is redirected to it, and a test that
    # missed that would be reporting on the wizard while claiming to report on
    # the licence.
    desk = locked_out["sign_in"]("desk")
    before = _patient_count(locked_out)
    desk.post("/patients/new", data=_NEW_CHILD, follow_redirects=True)
    assert _patient_count(locked_out) == before + 1


def test_the_licence_screen_can_still_write_while_locked(
        locked_out, owner, vendor):
    """The whole area is exempt, not just the reads in it.

    Saving a licence writes an audit row — who replaced the licence and when,
    which is the record that answers "why did this clinic stop working in
    March". Mutation testing found this: the exemption for the licence screens
    was never exercised, because the route was carrying its own escape hatch
    and the screen's only other act was writing a file.
    """
    from app.models import ActivityLog

    # A licence that does *not* fix anything — genuine, signed, and for
    # another computer, which is what a vendor's mistake looks like. It is
    # saved, so the owner can read on screen what is wrong with it, and the
    # program is still locked while the audit row is written.
    #
    # Installing a *working* licence would not have tested this: it unlocks
    # the program before the row is written, and the exemption is never
    # needed. Mutation testing survived the first version of this test for
    # exactly that reason.
    payload = _for_this_machine(locked_out, days=365)
    payload["machine"] = "0000-1111-2222-3333"
    response = owner.post("/settings/licence/install",
                          data={"licence": _sign(vendor, payload)},
                          follow_redirects=True)
    assert response.status_code == 200
    with locked_out["app"].app_context():
        assert ActivityLog.query.filter_by(action="settings.licence").count() == 1


def test_a_forged_licence_does_not_replace_a_working_one(licensed, vendor):
    """Checked before it is written, so the wrong file pasted into the box
    cannot cost a clinic the licence it already had."""
    from app.models import User
    from app.utils import licensing

    good = _sign(vendor, _for_this_machine(licensed, days=365))
    _install(licensed, good)
    with licensed["app"].app_context():
        user = User.query.filter_by(username="boss").first()
        user.is_super_admin = True
        licensed["db"].session.commit()
    owner = licensed["sign_in"]("boss")

    other, _ = _keypair()
    owner.post("/settings/licence/install",
               data={"licence": _sign(other, _for_this_machine(licensed))},
               follow_redirects=True)
    with licensed["app"].app_context():
        assert licensing.read_licence().strip() == good
        assert licensing.check().state == "valid"


def test_the_screen_shows_this_machine(licensed, vendor):
    """The number a receptionist reads down the phone to get a licence made.
    Missing, the clinic cannot start the conversation at all."""
    from app.models import User
    from app.utils import licensing

    with licensed["app"].app_context():
        user = User.query.filter_by(username="boss").first()
        user.is_super_admin = True
        licensed["db"].session.commit()
        fingerprint = licensing.machine_fingerprint()
    if not fingerprint:
        pytest.skip("this machine has no readable identifier")
    page = licensed["sign_in"]("boss").get("/settings/licence").get_data(
        as_text=True)
    assert fingerprint in page


# ------------------------------------------------- the guard's own limits ---
def test_a_bug_in_the_licence_check_does_not_lock_the_clinic(licensed,
                                                             monkeypatch):
    """The last line of defence, and the one worth having.

    Everything above is about refusing to write when the licence says so.
    This is about what happens when the licence code itself throws — an
    unreadable disk, a corrupt file, a mistake in this module. The answer has
    to be *keep working*: a clinic locked out of its own records by a bug in
    the part of the program that exists to collect money is the worst thing
    this feature could do.
    """
    from app.utils import licensing

    def explode():
        raise RuntimeError("something in here is broken")

    with licensed["app"].app_context():
        monkeypatch.setattr(licensing, "check", explode)
        assert licensing.locked() is False


def test_touching_a_row_without_changing_it_is_not_a_write(locked_out):
    """``Session.dirty`` is optimistic: assigning an attribute the value it
    already had puts an object in it. A guard that read it straight would
    refuse pages that changed nothing, and the report would be a 403 nobody
    could reproduce."""
    from app.models import Patient
    from app.utils.read_only import _blocked

    with locked_out["app"].app_context():
        child = locked_out["db"].session.get(
            Patient, locked_out["ids"]["child"])
        child.full_name = child.full_name
        assert child in locked_out["db"].session.dirty
        assert _blocked(locked_out["db"].session) is False


def test_a_licence_about_to_run_out_says_so_on_every_screen(licensed, vendor):
    """The warning is the difference between renewing and being locked out.
    Shown on the page, not only in the verdict object — a countdown nobody is
    looking at is not a warning."""
    _install(licensed, _sign(vendor, _for_this_machine(licensed, days=9)))
    page = licensed["sign_in"]("boss").get(
        f"/patients/{licensed['ids']['child']}").get_data(as_text=True)
    assert "licence-bar--warn" in page
    assert "licence-bar--stop" not in page


def test_the_key_can_live_in_the_clinics_own_folder(licensed, tmp_path,
                                                    monkeypatch):
    """Where the vendor key actually has to sit, given how updates work.

    A clinic updates with ``git pull`` from this repository or by downloading
    its ZIP. A key committed here would be published to every clinic with the
    code; a key living only in the source tree would be wiped by the next
    update. ``instance/`` is neither published nor replaced, so that is where
    it goes — and this is the test that it is read from there at all.
    """
    from app.utils import licensing

    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    private, public = _keypair()
    with open(tmp_path / licensing.PUBKEY_FILENAME, "w",
              encoding="utf-8") as handle:
        handle.write(public + "\n")

    text = _sign(private, _for_this_machine(licensed))
    with licensed["app"].app_context():
        assert licensing.check(text).state == "valid"


def test_the_compiled_in_key_cannot_be_overridden_from_that_folder(
        licensed, tmp_path, monkeypatch):
    """A build made for sale carries its key in the source. Nothing a clinic
    drops in its own folder replaces it — otherwise the fallback above would
    *be* the licence."""
    from app.utils import licensing

    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    theirs, their_public = _keypair()
    _, ours = _keypair()
    monkeypatch.setattr(licensing, "VENDOR_PUBLIC_KEY", ours)
    with open(tmp_path / licensing.PUBKEY_FILENAME, "w",
              encoding="utf-8") as handle:
        handle.write(their_public + "\n")

    text = _sign(theirs, _for_this_machine(licensed))
    with licensed["app"].app_context():
        assert licensing.check(text).state == "bad_signature"


def test_installing_a_licence_changes_the_answer_immediately(licensed, vendor):
    """The verdict is worked out once per request and remembered, because
    every page asks. Saving a licence is a write against that answer, so it
    has to drop it — a caller that installs a licence and then asks what the
    licence says must not be told what the old one said."""
    from app.utils import licensing

    _install(licensed, _sign(vendor, _for_this_machine(licensed, days=-1)))
    with licensed["app"].test_request_context("/"):
        assert licensing.status().state == "expired"
        licensing.install(_sign(vendor, _for_this_machine(licensed, days=365)))
        assert licensing.status().state == "valid"
