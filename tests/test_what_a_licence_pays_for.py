"""A licence that says three doctors, and a clinic that already has five.

A licence can now carry what it was sold as: how many doctors, how many
users, how many services, and which modules. All four are optional, and a
licence that says nothing about them buys the whole program — which is what
every licence issued before these fields existed says, so adding them cannot
narrow anything already in the field.

**Zero means no limit, and absent means no limit.** Not "none allowed". A
clinic whose licence forgot to mention doctors must not discover it cannot
add one; an unspecified field has to fail on the side of the clinic keeping
working.

**And nothing already there is ever switched off.** A practice running five
doctors that renews onto a three-doctor licence keeps all five: they are on
the rota, they are seeing children, they are in last month's figures. What it
cannot do is add a sixth. That is the same shape as read-only and for the
same reason — a commercial limit that reached backwards and disabled two
doctors would be settling a billing question by closing a clinic in the
middle of a Tuesday.
"""
import base64
import json
from datetime import date, timedelta

import pytest


def _keypair():
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
    private, public = _keypair()
    monkeypatch.setenv("PEDIAPRO_LICENCE_KEY", public)
    return private


@pytest.fixture
def licensed(clinic, tmp_path):
    clinic["app"].config["LICENCE_FILE"] = str(tmp_path / "licence.lic")
    return clinic


def _install(clinic, vendor, **extra):
    payload = {"v": 1, "clinic": "عيادة", "id": "GC-0001", "machine": "*",
               "expires": (date.today() + timedelta(days=365)).isoformat()}
    payload.update(extra)
    with open(clinic["app"].config["LICENCE_FILE"], "w", encoding="utf-8") as f:
        f.write(_sign(vendor, payload))


def _admin(clinic):
    """Signed in as the admin, deliberately **not** as the owner.

    Making boss a super-admin trips the first-run wizard, which redirects an
    owner away from every screen until the facility is configured — so a test
    that promoted him would be reporting on the wizard while claiming to
    report on the licence. Adding users and services only needs admin anyway.
    """
    return clinic["sign_in"]("boss")


def _add_user(client, username, doctor=False, active=True):
    data = {"username": username, "full_name": "شخص",
            "role": "doctor" if doctor else "reception",
            "password": "secret123"}
    if active:
        data["is_active"] = "1"
    return client.post("/users/new", data=data, follow_redirects=True)


def _doctor_seats(clinic):
    """Everyone who consults — the thing a licence is sold by.

    Not `is_practitioner` alone: that flag exists so a *non-doctor* role can
    join the pickers without every admin counting as a doctor. The clinic's
    actual doctors carry `role == "doctor"` and no flag at all, so a count on
    the flag would have found none of them.
    """
    from app.models import User

    with clinic["app"].app_context():
        return User.query.filter(
            User.is_active.is_(True),
            (User.role == "doctor") | (User.is_practitioner.is_(True))).count()


def _count(clinic, **filters):
    from app.models import User

    with clinic["app"].app_context():
        return User.query.filter_by(**filters).count()


# --------------------------------------------- a licence that says nothing --
def test_a_licence_with_no_limits_buys_the_whole_program(licensed, vendor):
    """Every licence issued before these fields existed. If this fails, adding
    limits narrowed licences that were sold without any."""
    from app.utils import licensing

    _install(licensed, vendor)
    with licensed["app"].app_context():
        assert licensing.limit("doctors") == 0
        assert licensing.room_for_another("doctors", 500) is True
        assert licensing.licensed_modules() is None
        assert licensing.module_licensed("dentistry") is True


def test_zero_means_no_limit_not_none_allowed(licensed, vendor):
    """The reading that would lock a clinic out of its own program. A field
    left at zero is "not counted", never "you may have none"."""
    from app.utils import licensing

    _install(licensed, vendor, limits={"doctors": 0, "users": 0})
    with licensed["app"].app_context():
        assert licensing.room_for_another("doctors", 99) is True
        assert licensing.room_for_another("users", 99) is True


def test_a_dormant_build_counts_nothing(licensed, vendor, monkeypatch):
    """No vendor key, no enforcement — of expiry, and of this."""
    from app.utils import licensing

    _install(licensed, vendor, limits={"doctors": 1})
    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    with licensed["app"].app_context():
        assert licensing.limit("doctors") == 0
        assert licensing.room_for_another("doctors", 50) is True


def test_a_limit_that_is_not_a_number_is_ignored(licensed, vendor):
    """It arrives in a signed file somebody typed. A junk value must read as
    "unlimited", not crash the screen a clinic adds staff on."""
    from app.utils import licensing

    _install(licensed, vendor, limits={"doctors": "كتير", "users": None})
    with licensed["app"].app_context():
        assert licensing.limit("doctors") == 0
        assert licensing.room_for_another("users", 40) is True


# ------------------------------------------------------- counting people ----
def test_a_sixth_user_is_refused_when_the_licence_pays_for_five(licensed,
                                                                vendor):
    _install(licensed, vendor, limits={"users": 5})
    admin = _admin(licensed)
    before = _count(licensed, is_active=True)
    assert before == 4                       # the fixture's own four staff
    _add_user(admin, "khamsa")
    assert _count(licensed, is_active=True) == 5
    _add_user(admin, "setta")
    assert _count(licensed, is_active=True) == 5, "the sixth user got in"


def test_the_five_already_there_keep_working(licensed, vendor):
    """The promise this whole feature stands on.

    A clinic renewing onto a smaller licence does not lose people. They are on
    the rota and seeing children; a billing question must not close a clinic
    in the middle of a Tuesday.
    """
    from app.models import User

    _install(licensed, vendor, limits={"users": 1, "doctors": 0})
    assert _count(licensed, is_active=True) == 4
    with licensed["app"].app_context():
        assert all(u.is_active for u in User.query.all())
    # And they can still sign in and work.
    assert licensed["sign_in"]("desk").get("/patients/").status_code == 200


def test_an_existing_user_can_still_be_edited_over_the_limit(licensed, vendor):
    """A clinic sitting on or past its limit has to be able to fix a phone
    number. Only the transition that *adds* somebody is refused."""
    from app.models import User

    _install(licensed, vendor, limits={"users": 1})
    admin = _admin(licensed)
    with licensed["app"].app_context():
        desk = User.query.filter_by(username="desk").first()
        desk_id, role = desk.id, desk.role
    admin.post(f"/users/{desk_id}/edit",
               data={"username": "desk", "full_name": "الاستقبال الجديد",
                     "role": role, "is_active": "1", "phone": "01000000000"},
               follow_redirects=True)
    with licensed["app"].app_context():
        assert licensed["db"].session.get(User, desk_id).full_name == "الاستقبال الجديد"


def test_switching_a_disabled_account_back_on_counts_as_adding(licensed,
                                                               vendor):
    """The way round this that a create-only check would have left open.

    Turning a disabled account back on is one more person on the clinic's
    payroll as far as a licence is concerned, and it happens on a screen
    nobody thinks of as adding anybody.
    """
    from app.models import User

    admin = _admin(licensed)
    with licensed["app"].app_context():
        sleeper = User(username="raged", full_name="راجع", role="reception",
                       is_active=False)
        sleeper.set_password("secret123")
        licensed["db"].session.add(sleeper)
        licensed["db"].session.commit()
        sleeper_id, role = sleeper.id, sleeper.role

    _install(licensed, vendor, limits={"users": 4})   # exactly the four active
    admin.post(f"/users/{sleeper_id}/edit",
               data={"username": "raged", "full_name": "راجع", "role": role,
                     "is_active": "1"}, follow_redirects=True)
    with licensed["app"].app_context():
        assert licensed["db"].session.get(User, sleeper_id).is_active is False, \
            "a disabled account was switched on past the licence"


def test_promoting_somebody_to_doctor_counts_as_adding_a_doctor(licensed,
                                                                vendor):
    """The other way round it. Ticking "practitioner" on a receptionist who
    is already an active user adds no user at all — and adds a doctor."""
    from app.models import User

    _install(licensed, vendor, limits={"doctors": 1})
    admin = _admin(licensed)
    with licensed["app"].app_context():
        desk = User.query.filter_by(username="desk").first()
        desk_id, role = desk.id, desk.role
    assert _doctor_seats(licensed) == 1
    admin.post(f"/users/{desk_id}/edit",
               data={"username": "desk", "full_name": "الاستقبال", "role": role,
                     "is_active": "1", "is_practitioner": "1"},
               follow_redirects=True)
    with licensed["app"].app_context():
        assert licensed["db"].session.get(User, desk_id).is_practitioner is not True, \
            "a second doctor arrived on a one-doctor licence"


def test_a_doctor_is_refused_while_a_plain_user_is_not(licensed, vendor):
    """The two numbers are separate. A clinic sold five seats and one doctor
    can still hire a receptionist."""
    _install(licensed, vendor, limits={"users": 8, "doctors": 1})
    admin = _admin(licensed)
    _add_user(admin, "doctor2", doctor=True)
    assert _doctor_seats(licensed) == 1, "a second doctor got in"
    _add_user(admin, "desk2")
    assert _count(licensed, is_active=True) == 5


# ---------------------------------------------------------------- services --
def test_a_service_beyond_the_licence_is_refused(licensed, vendor):
    from app.models import Service

    with licensed["app"].app_context():
        before = Service.query.count()
    _install(licensed, vendor, limits={"services": before})
    admin = _admin(licensed)
    admin.post("/finance/services/new",
               data={"name": "خدمة زيادة", "price": "100"},
               follow_redirects=True)
    with licensed["app"].app_context():
        assert Service.query.count() == before


def test_the_price_list_it_already_has_is_untouched(licensed, vendor):
    """A catalogue that shrank over a billing question is a clinic that cannot
    charge for work it does."""
    from app.models import Service

    with licensed["app"].app_context():
        before = Service.query.count()
    _install(licensed, vendor, limits={"services": 1})
    admin = _admin(licensed)
    assert admin.get("/finance/services").status_code == 200
    with licensed["app"].app_context():
        assert Service.query.count() == before


# ----------------------------------------------------------------- modules --
def test_a_module_the_licence_does_not_pay_for_is_off(licensed, vendor):
    """Even when the clinic has switched it on."""
    from app.models import Setting
    from app.utils.facility import module_enabled

    with licensed["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        licensed["db"].session.commit()
    _install(licensed, vendor, modules=["patients", "finance"])
    with licensed["app"].app_context():
        assert module_enabled("dentistry") is False


def test_the_licence_narrows_and_never_widens(licensed, vendor):
    """A licence that pays for dentistry does not switch it on. The clinic
    asks for a specialty; the licence only says whether it may have it."""
    from app.utils.facility import module_enabled

    _install(licensed, vendor, modules=["dentistry"])
    with licensed["app"].app_context():
        assert module_enabled("dentistry") is False


def test_a_licence_silent_about_modules_permits_them_all(licensed, vendor):
    from app.models import Setting
    from app.utils.facility import module_enabled

    with licensed["app"].app_context():
        Setting.set("mod_enabled:dentistry", "1")
        licensed["db"].session.commit()
    _install(licensed, vendor)
    with licensed["app"].app_context():
        assert module_enabled("dentistry") is True


def test_a_dormant_verdict_carries_nothing(licensed, vendor, monkeypatch):
    """The invariant the dormant guards rest on.

    With no vendor key, `check` returns before it parses anything — so a
    dormant verdict has an empty payload, and every question asked of that
    payload answers "no limit" without a branch for it. Mutation testing
    showed those branches surviving deletion, which is exactly what a
    redundant guard does.

    They are kept, because the invariant is not visible from where they sit
    and a later change that gave a dormant verdict a payload would start
    enforcing limits on builds that enforce nothing. This test is what would
    notice that change.
    """
    from app.utils import licensing

    _install(licensed, vendor, limits={"doctors": 1, "users": 1},
             modules=["patients"])
    monkeypatch.delenv("PEDIAPRO_LICENCE_KEY", raising=False)
    with licensed["app"].app_context():
        verdict = licensing.check()
        assert verdict.state == "dormant"
        assert verdict.payload == {}, \
            "a dormant verdict now carries a payload; the guards in limit() " \
            "and licensed_modules() are live branches and need their own tests"
