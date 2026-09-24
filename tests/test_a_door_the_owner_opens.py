"""The developer's account — a door the owner opens.

Asked for as «يوزر للمبرمج ده يعمل أي شيء في البرنامج … والأمان مهم». An
account that can do anything in a running hospital is the most dangerous
thing the program could hold, so it is not an account that is always there:

* it cannot sign in unless the owner opened a window for it;
* inside the window it holds the owner's powers;
* the window ends on time or when the owner closes it, and the account is
  signed out on its next click;
* every request inside is written down, in tables a data reset keeps;
* staff accounts, the data reset, restoring a backup, the licence and the
  door itself stay the owner's alone — each is a way to leave without a trace
  or to come back without a door.
"""
from datetime import datetime, timedelta

import pytest

PASSWORD = "dev-pass-123"


@pytest.fixture()
def door(clinic):
    from app.models import User
    from app.utils import support_access

    with clinic["app"].app_context():
        db = clinic["db"]
        boss = db.session.get(User, clinic["ids"]["admin"])
        boss.is_super_admin = True
        # A second administrator who is not the owner.
        it = User(username="it", full_name="الآي تي", role="admin",
                  is_active=True)
        it.set_password("secret")
        db.session.add(it)
        vendor = support_access.make_vendor(boss, "dev", "المطوّر", PASSWORD)
        db.session.commit()
        clinic["ids"].update(vendor=vendor.id, it=it.id)
    return clinic


def _get(door, key):
    from app.models import User

    return door["db"].session.get(User, door["ids"][key])


def _open(door, hours=4, reason="تفعيل مديول العمليات"):
    from app.utils import support_access

    with door["app"].app_context():
        row = support_access.open_for(_get(door, "admin"), _get(door, "vendor"),
                                      hours, reason)
        door["db"].session.commit()
        return row.id


def _developer(door):
    client = door["app"].test_client()
    reply = client.post("/login", data={"username": "dev",
                                        "password": PASSWORD})
    return client, reply


def _actions(door):
    from app.models import SupportAction

    with door["app"].app_context():
        return [(a.method, a.endpoint, a.path, a.refused)
                for a in SupportAction.query.order_by(SupportAction.id)]


# ------------------------------------------------------- the door shut ----
def test_the_right_password_with_the_door_shut_is_refused_and_logged(door):
    from app.models import ActivityLog

    _, reply = _developer(door)
    assert reply.status_code == 403
    with door["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="login_support_closed").count() == 1


def test_outside_a_window_the_account_holds_nothing(door):
    with door["app"].app_context():
        dev = _get(door, "vendor")
        assert not dev.is_admin and not dev.is_owner
        assert not dev.can_access("patients") and not dev.can("cashier")


# ------------------------------------------------------ who opens it ----
@pytest.mark.parametrize("who", ["it", "vendor"])
def test_only_the_owner_in_person_opens_or_makes(door, who):
    from app.utils import support_access

    with door["app"].app_context():
        with pytest.raises(PermissionError):
            support_access.open_for(_get(door, who), _get(door, "vendor"), 4,
                                    "سبب")
        with pytest.raises(PermissionError):
            support_access.make_vendor(_get(door, who), "dev2", "تاني",
                                       "password-99")


@pytest.mark.parametrize("hours, reason", [(4, "  "), (3, "سبب"),
                                           (100, "سبب"), ("x", "سبب")])
def test_a_window_needs_a_listed_length_and_a_reason(door, hours, reason):
    from app.utils import support_access

    with door["app"].app_context(), pytest.raises(ValueError):
        support_access.open_for(_get(door, "admin"), _get(door, "vendor"),
                                hours, reason)


def test_one_window_at_a_time(door):
    from app.utils import support_access

    _open(door)
    with door["app"].app_context(), pytest.raises(ValueError):
        support_access.open_for(_get(door, "admin"), _get(door, "vendor"), 1,
                                "تاني")


def test_a_window_is_for_a_developer_account_only(door):
    from app.utils import support_access

    with door["app"].app_context(), pytest.raises(ValueError):
        support_access.open_for(_get(door, "admin"), _get(door, "it"), 4,
                                "سبب")


# ------------------------------------------------------ inside it ----
def test_inside_the_window_it_holds_the_owners_powers(door):
    _open(door)
    client, reply = _developer(door)
    assert reply.status_code in (200, 302)
    with door["app"].app_context():
        assert _get(door, "vendor").is_owner
    assert client.get("/settings/licence").status_code == 200


def test_every_request_is_written_down_without_the_search_words(door):
    _open(door)
    client, _ = _developer(door)
    client.get("/patients/?q=محمد أحمد")
    rows = _actions(door)
    assert ("GET", "patients.index", "/patients/", False) in rows
    assert not any("محمد" in (r[2] or "") for r in rows)


@pytest.mark.parametrize("url, data", [
    ("/users/new", {"username": "backdoor", "full_name": "باب",
                       "password": "secret-123", "role": "admin"}),
    ("/settings/data/reset", {"confirm": "RESET"}),
    ("/settings/support", {"action": "close", "window_id": "1"}),
])
def test_the_owners_own_things_are_refused_and_logged(door, url, data):
    from app.models import User

    _open(door)
    client, _ = _developer(door)
    assert client.post(url, data=data).status_code == 403
    assert any(r[3] for r in _actions(door))
    with door["app"].app_context():
        assert User.query.filter_by(username="backdoor").first() is None
        assert _get(door, "vendor") is not None


def test_the_door_itself_is_not_even_readable_from_inside(door):
    _open(door)
    client, _ = _developer(door)
    assert client.get("/settings/support").status_code == 403


def test_a_backup_cannot_be_restored_from_inside(door):
    _open(door)
    client, _ = _developer(door)
    reply = client.post("/settings/data/backup/x.db/restore",
                        data={"confirm": "RESTORE"})
    assert reply.status_code == 403


# ------------------------------------------------------ it closes ----
def test_when_the_time_runs_out_the_next_click_signs_it_out(door):
    from app.models import ActivityLog, SupportWindow

    wid = _open(door)
    client, _ = _developer(door)
    assert client.get("/settings/licence").status_code == 200
    with door["app"].app_context():
        row = door["db"].session.get(SupportWindow, wid)
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        door["db"].session.commit()
    reply = client.get("/settings/licence")
    assert reply.status_code == 302 and "/login" in reply.headers["Location"]
    with door["app"].app_context():
        assert ActivityLog.query.filter_by(action="support_signed_out").count() == 1
    # And it stays out.
    assert client.get("/settings/licence").status_code == 302


def test_the_owner_closes_it_early(door):
    boss = door["sign_in"]("boss")
    wid = _open(door)
    client, _ = _developer(door)
    boss.post("/settings/support", data={"action": "close", "window_id": wid})
    reply = client.get("/settings/licence")
    assert reply.status_code == 302


def test_the_screen_opens_a_window_with_the_owner_named(door):
    from app.models import SupportWindow

    boss = door["sign_in"]("boss")
    boss.post("/settings/support", data={"action": "open",
                                         "user_id": door["ids"]["vendor"],
                                         "hours": "1", "reason": "تحديث"})
    with door["app"].app_context():
        row = SupportWindow.query.one()
        assert row.opened_by == door["ids"]["admin"]
        assert row.expires_at - row.opened_at == timedelta(hours=1)
    page = boss.get("/settings/support").get_data(as_text=True)
    assert 'data-door="open"' in page
    assert "data-support-open" in page     # the banner


# -------------------------------------------- the account is the owner's ----
def test_another_administrator_cannot_touch_the_developers_account(door):
    it = door["app"].test_client()
    it.post("/login", data={"username": "it", "password": "secret"})
    vid = door["ids"]["vendor"]
    assert it.get(f"/users/{vid}/edit").status_code == 403
    assert it.post(f"/users/{vid}/delete").status_code == 403
    assert it.get("/settings/support").status_code == 403
    with door["app"].app_context():
        assert _get(door, "vendor") is not None


def test_only_the_owner_resets_its_password(door):
    boss = door["sign_in"]("boss")
    boss.post("/settings/support", data={"action": "password",
                                         "user_id": door["ids"]["vendor"],
                                         "password": "new-pass-456"})
    with door["app"].app_context():
        assert _get(door, "vendor").check_password("new-pass-456")


def test_the_record_outlives_a_data_reset(door):
    from app.utils import wipe

    assert {"support_windows", "support_actions"} <= wipe.KEEP


# -------------------------------------------- nothing else changes ----
def test_the_owner_and_the_other_administrator_are_as_they_were(door):
    with door["app"].app_context():
        boss, it = _get(door, "admin"), _get(door, "it")
        assert boss.is_owner and boss.is_owner_in_person
        assert it.is_admin and not it.is_owner
    assert door["sign_in"]("doc").get("/settings/support").status_code == 403


# ------------------------------------------ inside is never "in person" ----
def test_inside_a_window_the_developer_is_still_not_the_owner_in_person(door):
    """The powers, never the owner's own acts: a developer inside a window
    cannot open another window or make another developer."""
    from app.utils import support_access

    _open(door)
    with door["app"].app_context():
        dev = _get(door, "vendor")
        assert dev.is_owner and not dev.is_owner_in_person
        with pytest.raises(PermissionError):
            support_access.make_vendor(dev, "dev2", "تاني", "password-99")
        with pytest.raises(PermissionError):
            support_access.close(dev, None)


def test_inside_a_window_it_cannot_read_its_own_account_form(door):
    from app.models import Setting

    with door["app"].app_context():
        # Past the first-run wizard, which would otherwise answer first.
        Setting.set("facility_configured", "1")
        door["db"].session.commit()
    _open(door)
    client, _ = _developer(door)
    assert client.get(f"/users/{door['ids']['vendor']}/edit").status_code == 403


@pytest.mark.parametrize("endpoint, method, refused", [
    ("settings.support", "GET", True),
    ("settings.support", "POST", True),
    ("users.edit", "GET", False),
    ("users.edit", "POST", True),
    ("settings.reset_data", "POST", True),
    ("settings.backup_restore", "POST", True),
    ("settings.backup_upload", "POST", True),
    ("settings.licence_install", "POST", True),
    ("settings.setup", "POST", False),
    ("patients.index", "GET", False),
])
def test_what_stays_the_owners_alone(endpoint, method, refused):
    from app.utils import support_access

    assert support_access.owner_only(endpoint, method) is refused


def test_the_developer_account_is_never_minted_an_owner(door):
    with door["app"].app_context():
        dev = _get(door, "vendor")
        assert dev.is_vendor and not dev.is_super_admin


@pytest.mark.parametrize("password", ["", "short77"])
def test_a_developer_password_is_eight_characters_at_least(door, password):
    from app.utils import support_access

    with door["app"].app_context():
        with pytest.raises(ValueError):
            support_access.make_vendor(_get(door, "admin"), "dev3", "تالت",
                                       password)
        with pytest.raises(ValueError):
            support_access.set_vendor_password(_get(door, "admin"),
                                               _get(door, "vendor"), password)


def test_a_closed_window_is_not_open_whatever_its_hour(door):
    from app.models import SupportWindow
    from app.utils import support_access

    wid = _open(door)
    with door["app"].app_context():
        row = door["db"].session.get(SupportWindow, wid)
        support_access.close(_get(door, "admin"), row)
        door["db"].session.commit()
        assert row.expires_at > datetime.utcnow()
        assert not row.open_at()
