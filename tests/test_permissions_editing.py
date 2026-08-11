"""The permissions screen, and the one person allowed one extra thing.

Reported by pointing at the matrix: *"why isn't this editable?"* — and the
answer the screen gave was to go somewhere else. A grid showing somebody
exactly what they want to change, with a note sending them to another screen
to change it, is a screen that has failed at its own job.

**The matrix is the editor now, and there is still only one of them.** Role
management keeps what only it can do — creating, naming and deleting roles —
so "who reaches what" has exactly one place it is written. Two editors of one
list is how they come to disagree.

**And deliberately not view/edit/add/delete per screen.** The clinic asked for
a professional expansion *without* it becoming something nobody can follow: 14
modules × 5 roles is 70 boxes and each row reads as one sentence; times four
it is 280 and the row needs studying. The fine-grained layer already exists
and already reads as sentences — the sensitive capabilities — so growth
belongs there, as more sentences, not as a bigger grid.

**The exception is a grant, never a revocation.** One person can be allowed
one thing their role is not: *"the reception does certain things in finance"*,
without handing every receptionist the capability and without a role called
"reception+" that has to be explained to each new employee. It cannot take a
capability away, because a role whose own list did not mean what it said would
have to be checked holder by holder — and the way to stop somebody is to
change their role, out where the whole clinic's permissions are drawn.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _seed_roles(clinic):
    """The editable Role rows.

    A real install has them (``_ensure_default_roles`` runs at setup); the
    test fixture does not, and without them the screen has nothing to draw —
    the permission model falls back to the static table. Seeding here keeps
    the tests about the editing rather than about the fixture.
    """
    with clinic["app"].app_context():
        from app.cli import _ensure_default_roles
        _ensure_default_roles()
        clinic["db"].session.commit()


def _role_id(clinic, name):
    """The id as a plain int — a Role read outside its context is detached."""
    with clinic["app"].app_context():
        from app.models import Role
        row = Role.query.filter_by(name=name).first()
        return row.id if row else None


def _modules_of(clinic, name):
    with clinic["app"].app_context():
        from app.models import Role
        return sorted(Role.query.filter_by(name=name).first().module_list)


# --- the matrix edits -----------------------------------------------------

def test_the_matrix_offers_a_box_for_every_role_and_module(clinic):
    """The save reads "every box ticked", so a partial form silently strips.

    Anything the form does not draw is absent from the POST, and absent means
    removed. That is only safe while the grid is complete, so this is the
    test holding the save honest rather than a check on the markup.
    """
    from app.models.permissions import MODULES

    _seed_roles(clinic)
    admin = clinic["sign_in"]("boss")
    body = admin.get("/users/permissions").get_data(as_text=True)

    with clinic["app"].app_context():
        from app.models import Role
        roles = [r for r in Role.query.all() if not r.is_admin]

    missing = [f"mod_{r.id}_{m}" for r in roles for m in MODULES
               if f'name="mod_{r.id}_{m}"' not in body]
    assert missing == [], f"boxes the form never draws: {missing[:6]}"


def test_ticking_a_box_gives_the_role_the_module(clinic):
    from app.models.permissions import MODULES

    _seed_roles(clinic)
    role_id = _role_id(clinic, "reception")
    before = _modules_of(clinic, "reception")
    target = next(m for m in MODULES if m not in before)

    admin = clinic["sign_in"]("boss")
    data = {f"role_present_{role_id}": "1"}
    data.update({f"mod_{role_id}_{m}": "1" for m in before})
    data[f"mod_{role_id}_{target}"] = "1"
    admin.post("/users/permissions", data=data, follow_redirects=True)

    assert target in _modules_of(clinic, "reception")


def test_unticking_takes_it_away(clinic):
    _seed_roles(clinic)
    role_id = _role_id(clinic, "reception")
    before = _modules_of(clinic, "reception")
    assert before, "the fixture role has no modules to remove"
    dropped = before[0]

    admin = clinic["sign_in"]("boss")
    data = {f"role_present_{role_id}": "1"}
    data.update({f"mod_{role_id}_{m}": "1"
                 for m in before if m != dropped})
    admin.post("/users/permissions", data=data, follow_redirects=True)

    assert dropped not in _modules_of(clinic, "reception")


def test_saving_one_role_does_not_wipe_another(clinic):
    """The form posts every role at once; a save must not read an absent role
    as "this role now reaches nothing"."""
    _seed_roles(clinic)
    doctor_before = _modules_of(clinic, "doctor")
    reception_id = _role_id(clinic, "reception")

    admin = clinic["sign_in"]("boss")
    admin.post("/users/permissions",
               data={f"role_present_{reception_id}": "1",
                     **{f"mod_{reception_id}_{m}": "1"
                        for m in _modules_of(clinic, "reception")}},
               follow_redirects=True)

    assert _modules_of(clinic, "doctor") == doctor_before, (
        "saving the matrix emptied a role nobody touched")


def test_an_admin_role_cannot_be_stripped(clinic):
    """A screen that lets somebody untick their own administrator is not
    permissions — it is how you lock yourself out of your own program.

    Two separate things hold this, and they are worth telling apart because
    writing the test taught me which one is load-bearing:

    * ``Role.module_list`` returns every module for an admin role **whatever
      is stored on it**. That is the real guarantee, it predates this screen,
      and no request can get past it.
    * the save skipping admin roles, which stops the stored value being
      scribbled on. Belt and braces — but it is the only one a crafted
      request can reach, so it is the one asserted on the row itself.
    """
    _seed_roles(clinic)
    with clinic["app"].app_context():
        from app.models import Role
        admin_role = Role.query.filter_by(is_admin=True).first()
        assert admin_role is not None
        before = sorted(admin_role.module_list)
        stored_before = admin_role.modules
        role_id, role_name = admin_role.id, admin_role.name

    body = clinic["sign_in"]("boss").get("/users/permissions").get_data(as_text=True)
    assert f'name="mod_{role_id}_' not in body, "an admin role is offered as editable"

    # And a **crafted** post — one that supplies the marker and a single
    # module by hand — must not strip it either. Posting nothing would pass
    # against a version with no admin guard at all, since a role the form did
    # not draw is skipped anyway; this is the request that tells the two
    # apart.
    clinic["sign_in"]("boss").post(
        "/users/permissions",
        data={f"role_present_{role_id}": "1", f"mod_{role_id}_dashboard": "1"},
        follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import Role
        after = Role.query.filter_by(name=role_name).first()
        assert sorted(after.module_list) == before, (
            "an administrator stopped reaching everything")
        assert after.modules == stored_before, (
            "a hand-made request rewrote the stored modules of an admin role")


def test_only_an_admin_can_save_the_matrix(clinic):
    response = clinic["sign_in"]("desk").post("/users/permissions", data={})
    assert response.status_code in (302, 403)


def test_the_screen_no_longer_sends_people_elsewhere_to_edit(clinic):
    body = clinic["sign_in"]("boss").get("/users/permissions").get_data(as_text=True)
    assert "للمراجعة فقط" not in body, "the read-only note is still there"
    assert 'action="/users/permissions"' in body


# --- the per-user exception -----------------------------------------------

def test_a_receptionist_can_be_given_one_finance_capability(clinic):
    """The clinic's own case, end to end."""
    admin = clinic["sign_in"]("boss")
    desk_id = clinic["ids"]["desk"]

    with clinic["app"].app_context():
        from app.models import User
        assert clinic["db"].session.get(User, desk_id).can("finance_manage") is False

    admin.post(f"/users/{desk_id}/capabilities",
               data={"capability": "finance_manage", "reason": "بتغطي الخزنة الجمعة"},
               follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import User
        assert clinic["db"].session.get(User, desk_id).can("finance_manage") is True


def test_the_grant_is_to_the_person_not_the_role(clinic):
    """The whole reason this is not a role change."""
    admin = clinic["sign_in"]("boss")
    admin.post(f"/users/{clinic['ids']['desk']}/capabilities",
               data={"capability": "finance_manage"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import User
        db = clinic["db"]
        other = User(username="desk2", full_name="استقبال ٢", role="reception",
                     is_active=True)
        other.set_password("secret")
        db.session.add(other)
        db.session.commit()
        assert other.can("finance_manage") is False, (
            "granting one receptionist gave it to the whole role")


def test_who_granted_it_and_when_is_recorded(clinic):
    """What keeps an exception legible a year later."""
    admin = clinic["sign_in"]("boss")
    admin.post(f"/users/{clinic['ids']['desk']}/capabilities",
               data={"capability": "finance_manage", "reason": "تغطية الجمعة"},
               follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import UserCapability
        row = UserCapability.query.filter_by(
            user_id=clinic["ids"]["desk"]).first()
        assert row.granted_by == clinic["ids"]["admin"]
        assert row.granted_at is not None
        assert row.reason == "تغطية الجمعة"


def test_revoking_leaves_the_role_alone(clinic):
    _seed_roles(clinic)
    admin = clinic["sign_in"]("boss")
    desk_id = clinic["ids"]["desk"]
    admin.post(f"/users/{desk_id}/capabilities",
               data={"capability": "finance_manage"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import UserCapability
        grant_id = UserCapability.query.filter_by(user_id=desk_id).first().id

    admin.post(f"/users/capabilities/{grant_id}/revoke", follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import Role, User
        assert clinic["db"].session.get(User, desk_id).can("finance_manage") is False
        assert Role.query.filter_by(name="reception").first() is not None


def test_granting_twice_does_not_duplicate(clinic):
    admin = clinic["sign_in"]("boss")
    for _ in range(2):
        admin.post(f"/users/{clinic['ids']['desk']}/capabilities",
                   data={"capability": "finance_manage"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import UserCapability
        assert UserCapability.query.filter_by(
            user_id=clinic["ids"]["desk"], capability="finance_manage").count() == 1


def test_an_unknown_capability_is_refused(clinic):
    """A typed or stale name must not become a permission nobody can read."""
    admin = clinic["sign_in"]("boss")
    admin.post(f"/users/{clinic['ids']['desk']}/capabilities",
               data={"capability": "become_god"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import UserCapability
        assert UserCapability.query.count() == 0


def test_only_an_admin_can_grant(clinic):
    """A capability anyone holding it can pass on spreads until the matrix
    stops describing the clinic."""
    response = clinic["sign_in"]("desk").post(
        f"/users/{clinic['ids']['desk']}/capabilities",
        data={"capability": "finance_manage"})
    assert response.status_code in (302, 403)

    with clinic["app"].app_context():
        from app.models import UserCapability
        assert UserCapability.query.count() == 0


def test_grants_cannot_take_a_capability_away(clinic):
    """There is no revocation, on purpose — see the module docstring."""
    from app.models import UserCapability

    columns = {c.name for c in UserCapability.__table__.columns}
    assert "allow" not in columns and "deny" not in columns, (
        "a deny flag would make a role's own list unreadable")


def test_the_exception_shows_on_the_users_screen(clinic):
    admin = clinic["sign_in"]("boss")
    desk_id = clinic["ids"]["desk"]
    admin.post(f"/users/{desk_id}/capabilities",
               data={"capability": "finance_manage", "reason": "تغطية الجمعة"},
               follow_redirects=True)

    body = admin.get(f"/users/{desk_id}/edit").get_data(as_text=True)
    assert "الإدارة المالية الكاملة" in body
    assert "تغطية الجمعة" in body


@pytest.mark.parametrize("capability", ["cashier", "finance_manage"])
def test_a_capability_the_role_already_has_is_not_offered(clinic, capability):
    """Granting somebody something they already have would sit on the screen
    as a decision forever and mean nothing."""
    body = clinic["sign_in"]("boss").get(
        f"/users/{clinic['ids']['accountant']}/edit").get_data(as_text=True)

    with clinic["app"].app_context():
        from app.models import User
        from app.models.permissions import role_capabilities
        user = clinic["db"].session.get(User, clinic["ids"]["accountant"])
        if capability in role_capabilities(user.role):
            assert f'<option value="{capability}"' not in body
