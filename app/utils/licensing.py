"""Whether this copy is licensed, and what happens when it is not.

The program is installed on a clinic's own computer and runs with no
connection to anybody. A licence therefore has to be a **file**: something the
vendor can sign and send over WhatsApp, that the clinic saves once, and that
the program can check on its own with nothing to phone home to. There is no
activation server here, and adding one would mean a clinic in a building with
bad internet cannot open its own patient records.

**What the file says.** Three facts, signed together: which machine it is for,
what date it runs to, and who it was issued to. The signature is Ed25519 over
the exact bytes of the payload — the vendor holds the private key and nothing
in this repository can produce a licence, only recognise one.

**What happens when it is not valid: the program goes read-only.** Every
record stays on the screen — the file, the chart, the statement, the printed
receipt — and nothing new can be written until the licence is renewed. That is
a deliberate choice over the alternative of refusing to start. A clinic whose
licence lapsed on a Thursday still has children in the waiting room and still
has to answer "what is this child allergic to?"; a program that hides that
answer to make a commercial point is one that hurt somebody to get paid.

**Read-only means the writes, not the buttons.** The rule is enforced where
the data changes — in the database session itself — and not by hiding forms.
Eighteen of this program's screens change something on a plain GET (a visit
starts, an appointment is confirmed, a message thread is opened), so a guard
that only refused POST would have been a read-only mode that quietly wrote.

The buttons are *not* hidden. Every screen carries a banner saying the program
is read-only and why, and a blocked write lands on a page that says the same
thing — but the controls themselves still look pressable. Disabling them would
mean touching two hundred templates to state in each one a rule that is
already stated once, and the half of that work that got missed would be the
screen somebody was standing at.

**Nothing is enforced until a vendor key is compiled in.** With no public key
this module is dormant and the program behaves exactly as it always has. That
is what makes the feature safe to ship: a clinic already running keeps
running, and the lock only ever exists in a build that was made to carry it.
"""
import base64
import hashlib
import json
import os
import platform
import subprocess
from datetime import date, timedelta

# --- the vendor's key -------------------------------------------------------
#
# Base64 of a 32-byte Ed25519 public key, filled in when a build is made for
# sale. **Empty here on purpose**, and this is the whole safety property of
# shipping this file: with no key there is nothing to verify against, so
# nothing is ever locked and a clinic running today keeps running.
#
# The matching private key is not in this repository and must never be. It
# lives with whoever signs licences; everything here can do is recognise a
# signature, never make one.
VENDOR_PUBLIC_KEY = ""

# Two fallbacks, consulted in order and only while the constant above is
# empty: the environment (the vendor's own bench and the test suite) and then
# `instance/licence_pubkey.txt`.
#
# The file exists because of how this program is actually updated. A clinic
# updates with `git pull` from this repository, or by downloading its ZIP — so
# a key committed here would be handed to every clinic along with the code,
# and a key that lives only in the source tree would be overwritten by the
# next update. `instance/` is the one folder that is neither published nor
# replaced, so that is where a clinic's copy of the key goes.
#
# **This is bookkeeping between a vendor and a customer, not a lock.** The
# program ships as readable Python: anybody holding the machine can delete
# this file, or delete the check, in about a minute. What the licence buys is
# a date that is visible, a renewal that has to happen, and an installation
# that says out loud when it has lapsed — not resistance to somebody who has
# decided not to pay. Building it as though it were the second thing would
# mean obfuscation, a phone-home, or both, and this program runs in buildings
# with no internet.
_KEY_ENV = "PEDIAPRO_LICENCE_KEY"
PUBKEY_FILENAME = "licence_pubkey.txt"

LICENCE_FILENAME = "licence.lic"
SEEN_FILENAME = ".licence-seen"

# How near the end the screens start saying so. A licence that lapses without
# warning is a clinic locked out on a morning nobody planned for.
WARN_WITHIN_DAYS = 30

# The most the clock is allowed to carry the high-water mark forward in one
# step. See :func:`effective_today`.
MAX_CLOCK_JUMP_DAYS = 31


class LicenceError(ValueError):
    """A licence file that cannot be believed, with a reason worth printing."""


# --- which machine this is --------------------------------------------------
def _raw_machine_id():
    """The operating system's own idea of which computer this is.

    Chosen for **stability**, which is the only property that matters: a
    fingerprint that moves is a clinic locked out of its own records by a
    Windows update. So no MAC address (changes with a docking station), no
    disk serial (changes when the disk is replaced and the image restored),
    no hostname (changes when somebody renames the PC).

    What is left is the identifier the OS installation gives itself and keeps
    until it is reinstalled — which is exactly the event that should count as
    a different machine.
    """
    system = platform.system()
    try:
        if system == "Windows":
            import winreg

            with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography", 0,
                    winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return (value or "").strip() or None
        if system == "Darwin":
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2].strip() or None
            return None
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    value = handle.read().strip()
                if value:
                    return value
    except Exception:  # noqa: BLE001 - an unreadable id is a state, not a crash
        return None
    return None


def machine_fingerprint():
    """This machine, as a number a receptionist can read down the phone.

    The OS identifier is hashed rather than printed. It is a stable handle on
    somebody's computer and there is no reason for it to travel to us in the
    clear when a hash answers the same question — and the clinic sends this
    string to the vendor to get a licence made, so it is going to travel.

    ``None`` when the machine has no readable identifier. That is not treated
    as a licence failure: see :func:`check`.
    """
    raw = _raw_machine_id()
    if not raw:
        return None
    digest = hashlib.sha256(b"pediapro-machine\x00" + raw.encode("utf-8")).hexdigest()
    # Upper case, and the signing tool upper-cases what it is given, so a
    # number read down the phone and typed back in by hand matches whichever
    # way it was typed. The comparison in `check` is exact.
    block = digest[:16].upper()
    return "-".join(block[i:i + 4] for i in range(0, 16, 4))


# --- where the file lives ---------------------------------------------------
def _instance_dir():
    from flask import current_app

    return current_app.instance_path


def licence_path():
    """The licence file. Configurable so the tests are not writing into the
    running clinic's instance folder."""
    from flask import current_app

    configured = current_app.config.get("LICENCE_FILE")
    if configured:
        return str(configured)
    return os.path.join(_instance_dir(), LICENCE_FILENAME)


def _seen_path():
    return os.path.join(os.path.dirname(licence_path()), SEEN_FILENAME)


def read_licence():
    """The file's contents, or ``None`` when there isn't one."""
    try:
        with open(licence_path(), "r", encoding="utf-8") as handle:
            return handle.read().strip() or None
    except OSError:
        return None


def _pubkey_file():
    return os.path.join(os.path.dirname(licence_path()), PUBKEY_FILENAME)


def vendor_public_key():
    """The 32 raw bytes to verify against, or ``None`` when dormant."""
    encoded = (VENDOR_PUBLIC_KEY or "").strip()
    if not encoded:
        encoded = (os.environ.get(_KEY_ENV) or "").strip()
    if not encoded:
        try:
            with open(_pubkey_file(), "r", encoding="utf-8") as handle:
                encoded = handle.read().strip()
        except (OSError, RuntimeError):
            encoded = ""
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:  # noqa: BLE001
        return None
    return raw if len(raw) == 32 else None


# --- the file itself --------------------------------------------------------
def _b64d(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def parse(raw, public_key=None):
    """Read a licence and prove it was signed by the vendor.

    ``payload.signature``, both base64url, in one line. The signature covers
    the payload **as it was written**, not as this program would re-encode it:
    two JSON documents that mean the same thing do not have the same bytes,
    and verifying a re-serialised copy would be verifying something the vendor
    never signed.

    Raises :class:`LicenceError` with a reason. Never returns an unverified
    payload — there is no "parse without checking", because a function that
    returns one is a function somebody will call.
    """
    public_key = public_key if public_key is not None else vendor_public_key()
    if not public_key:
        raise LicenceError("no_vendor_key")
    text = (raw or "").strip()
    if not text or text.count(".") != 1:
        raise LicenceError("malformed")
    encoded_payload, encoded_signature = text.split(".")
    try:
        payload_bytes = _b64d(encoded_payload)
        signature = _b64d(encoded_signature)
    except Exception:  # noqa: BLE001
        raise LicenceError("malformed") from None

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
    except ImportError:  # pragma: no cover - the dependency is pinned
        raise LicenceError("no_crypto") from None

    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, payload_bytes)
    except InvalidSignature:
        raise LicenceError("bad_signature") from None
    except Exception:  # noqa: BLE001 - a malformed key or signature length
        raise LicenceError("bad_signature") from None

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise LicenceError("malformed") from None
    if not isinstance(payload, dict):
        raise LicenceError("malformed")
    return payload


def _payload_date(payload, key):
    value = (payload.get(key) or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# --- what day is it, really -------------------------------------------------
def effective_today():
    """Today, or the latest day this installation has ever seen — whichever is
    later.

    An expiry date checked against a clock the licensee controls is not an
    expiry date. The mark is kept in a small file beside the licence and only
    ever moves forward, so winding the clock back changes nothing.

    It moves forward by at most :data:`MAX_CLOCK_JUMP_DAYS` at a time, and
    that cap is the important half. Without it, one accidental keystroke
    setting the year to 2099 would expire every licence this clinic will ever
    be issued, permanently, with no way back. With it the worst a wild clock
    can do is make the program a month pessimistic about a licence that was
    nearly finished anyway.
    """
    from app.utils.clock import local_today

    today = local_today()
    mark = None
    try:
        with open(_seen_path(), "r", encoding="utf-8") as handle:
            mark = date.fromisoformat(handle.read().strip())
    except (OSError, ValueError):
        mark = None

    if mark is None:
        _write_seen(today)
        return today
    if today > mark:
        capped = min(today, mark + timedelta(days=MAX_CLOCK_JUMP_DAYS))
        _write_seen(capped)
        return max(today, capped)
    return max(today, mark)


def _write_seen(day):
    try:
        os.makedirs(os.path.dirname(_seen_path()), exist_ok=True)
        with open(_seen_path(), "w", encoding="utf-8") as handle:
            handle.write(day.isoformat())
    except OSError:  # noqa: BLE001 - a read-only disk is not a licence failure
        pass


# --- the verdict ------------------------------------------------------------
class Licence:
    """The answer to "is this copy licensed", and why.

    ``state`` is one of:

    ``dormant``       no vendor key compiled in — nothing is enforced
    ``missing``       no licence file
    ``malformed``     a file that is not a licence
    ``bad_signature`` a licence this vendor did not sign
    ``wrong_machine`` a real licence, for a different computer
    ``expired``       a real licence for this computer, past its date
    ``valid``         everything checks out
    """

    def __init__(self, state, payload=None, expires=None, days_left=None):
        self.state = state
        self.payload = payload or {}
        self.expires = expires
        self.days_left = days_left

    # `ok` is the question the screens ask; `locked` is the one the guard asks.
    @property
    def ok(self):
        return self.state == "valid"

    @property
    def enforced(self):
        return self.state != "dormant"

    @property
    def locked(self):
        """Whether the program must refuse to write. Dormant is not locked."""
        return self.enforced and not self.ok

    @property
    def expiring_soon(self):
        return (self.ok and self.days_left is not None
                and self.days_left <= WARN_WITHIN_DAYS)

    @property
    def issued_to(self):
        return (self.payload.get("clinic") or "").strip()

    @property
    def serial(self):
        return (self.payload.get("id") or "").strip()

    def __repr__(self):
        return f"<Licence {self.state} to={self.issued_to!r} till={self.expires}>"


def check(raw=None, public_key=None, today=None):
    """Work out the verdict from a licence's text. Pure, and testable.

    ``raw`` defaults to the installed file. Nothing here touches the database
    or the session, so it can be called from a request, a CLI command, or the
    installer.
    """
    public_key = public_key if public_key is not None else vendor_public_key()
    if not public_key:
        return Licence("dormant")
    if raw is None:
        raw = read_licence()
    if not raw:
        return Licence("missing")

    try:
        payload = parse(raw, public_key)
    except LicenceError as error:
        reason = str(error)
        return Licence(reason if reason in ("malformed", "bad_signature")
                       else "malformed")

    # The machine. A licence may be issued to a site rather than a computer —
    # `"*"` — which is how a clinic whose machine has no readable identifier
    # gets a licence at all. Without that escape the only answer to an
    # unreadable machine id would be "you cannot use the program you bought".
    wanted = (payload.get("machine") or "").strip()
    if wanted and wanted != "*":
        if wanted != (machine_fingerprint() or ""):
            return Licence("wrong_machine", payload)

    expires = _payload_date(payload, "expires")
    if expires is None:
        # No date is a perpetual licence. Deliberate: a vendor who wants to
        # sell one outright should not have to write the year 2099 into a
        # field and hope.
        return Licence("valid", payload, None, None)

    day = today or effective_today()
    days_left = (expires - day).days
    if days_left < 0:
        return Licence("expired", payload, expires, days_left)
    return Licence("valid", payload, expires, days_left)


def status():
    """The verdict for this request, worked out once.

    Every page asks — the banner, the guard, the templates — and a signature
    check per ask is work for nothing.
    """
    from app.utils.request_cache import remember

    return remember("licence:status", check)


def locked():
    """Whether writes must be refused right now."""
    try:
        return status().locked
    except Exception:  # noqa: BLE001 - never lock a clinic out over a bug here
        return False


def looks_like_a_licence(text):
    """Whether this is shaped like a licence, without asking who signed it.

    Only used where there is no key to ask with — see :func:`install`. It
    rejects the paste that went wrong (an empty box, a WhatsApp message, half
    a line) and nothing else; a signature is what says a licence is genuine,
    and this cannot and does not try to say that.
    """
    text = (text or "").strip()
    if text.count(".") != 1:
        return False
    body, signature = text.split(".")
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
        _b64d(signature)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(payload, dict)


# --- how much of the program a licence pays for -----------------------------
#
# Three numbers and a list, all optional. A licence that says nothing about
# them buys the whole program, which is what every licence issued before this
# existed says — so adding this cannot narrow anything already in the field.
#
# **Zero means no limit, and absent means no limit.** Not "none allowed". A
# clinic whose licence forgot to mention doctors must not find it cannot add
# one; the failure of an unspecified field has to fall on the side of the
# clinic keeping working.
COUNTED = ("doctors", "users", "services")


def limit(name):
    """How many of ``name`` this licence allows. ``0`` means no limit.

    The dormant check below is belt to the braces of an invariant rather than
    a live branch: :func:`check` returns before it parses anything when there
    is no vendor key, so a dormant verdict carries an empty payload and this
    would answer 0 regardless. It is kept because the invariant is not
    visible from here, and a later change that gave a dormant verdict a
    payload would otherwise start enforcing limits on builds that enforce
    nothing. The invariant itself is pinned by a test.
    """
    verdict = status()
    if not verdict.enforced:
        return 0
    limits = verdict.payload.get("limits")
    if not isinstance(limits, dict):
        return 0
    try:
        return max(0, int(limits.get(name) or 0))
    except (TypeError, ValueError):
        return 0


def room_for_another(name, current):
    """Whether one more ``name`` may be added, given ``current`` of them.

    **Nothing existing is ever touched.** A clinic running five doctors that
    renews onto a three-doctor licence keeps all five: they are already on the
    rota, already seeing children, and already in last month's figures.
    What it cannot do is add a sixth.

    That is the same shape as read-only, and for the same reason. A commercial
    limit that reached backwards and switched off two doctors would be
    settling a billing question by closing a clinic in the middle of a
    Tuesday.
    """
    allowed = limit(name)
    return allowed == 0 or current < allowed


def licensed_modules():
    """The modules this licence pays for, or ``None`` when it says nothing.

    ``None`` is not "no modules" — it is "this licence does not talk about
    modules", which every licence issued before this field existed does not.
    """
    verdict = status()
    if not verdict.enforced:
        return None
    modules = verdict.payload.get("modules")
    if not isinstance(modules, list):
        return None
    return {str(m) for m in modules}


def module_licensed(module):
    """Whether the licence permits ``module``.

    The licence **narrows**; it never widens. A clinic that has not switched
    dentistry on does not get it because a licence mentions it, and a clinic
    that has switched it on loses it if the licence does not. The two
    questions are asked separately and both have to say yes — see
    ``facility.module_enabled``.
    """
    allowed = licensed_modules()
    return allowed is None or module in allowed


def install(raw):
    """Save a licence, after proving it is one. Returns the verdict.

    Checked before it is written, so a typo or the wrong file cannot replace a
    working licence with a broken one. A licence for another machine or an
    already-expired one is still *saved* — it is genuine, the clinic should be
    able to see what it says, and the screen explains what is wrong with it
    better than a refusal would.

    **A dormant build accepts one too**, and that is not the hole it looks
    like. It exists because of the order a clinic is switched on in. The
    public key is what turns enforcement on, so a build with no key that also
    refused to store a licence could only be licensed key-first — and the
    moment the key lands the clinic is read-only, staying that way until
    somebody gets the licence in after it. On a clinic that is already open
    and working, that window is the middle of a Tuesday.

    Storing it first closes the window: the licence goes in while nothing is
    enforced, the key follows, and the program comes up licensed. Nothing is
    trusted any earlier than before — the file is verified on every single
    read, so an unverifiable one saved now is refused later exactly as it
    would have been. What is skipped here is a check there was no key to
    perform.
    """
    text = (raw or "").strip()
    if not text:
        raise LicenceError("empty")
    verdict = check(text)
    if verdict.state in ("malformed", "bad_signature"):
        raise LicenceError(verdict.state)
    if verdict.state == "dormant" and not looks_like_a_licence(text):
        raise LicenceError("malformed")
    path = licence_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    from app.utils.request_cache import forget

    forget("licence:status")
    return verdict
