"""A permission checkbox that grants nothing.

Reported as: *"I gave the doctor the settings screen and it gives me 404."*

The role editor offered a tick for every module. The sidebar honoured it —
`can_access` reads the role's module list — and every route behind `settings`
asks `is_admin` instead. So the doctor got a Settings link that answered 403,
and a genuine 404 on any address underneath it that does not exist.

**Measured rather than assumed.** A test role was granted all fourteen modules
and each one's landing screen opened in turn: `users` and `settings` were the
only two that refused. So the fix is not "remove the settings checkbox" — it
is "stop offering the checkboxes that cannot be honoured", and there were two.

`panels` joined them later, and by design rather than by accident: its screen
says which specialty panels this clinic has and which doctors work them, which
is a setup question and not a consulting-room one, so the route is
`admin_required` on purpose. The rule these tests hold is the one that
matters — a module the routes refuse to a role must not be offered to a role —
so the list is read rather than restated, and the count follows it.

Filtered on save as well as in the form. A checkbox removed only from the page
is a permission a hand-posted request can still store, and a stored permission
that does nothing is the same bug with one more step to reach it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def test_the_admin_only_modules_are_named(clinic):
    from app.models.permissions import ADMIN_ONLY_MODULES, MODULES

    assert {"users", "settings"} <= set(ADMIN_ONLY_MODULES)
    assert all(m in MODULES for m in ADMIN_ONLY_MODULES), \
        "an admin-only module that is not a module at all"


def test_every_admin_only_module_really_refuses_a_role(clinic):
    """The measurement, kept. A name on this list means nothing unless the
    route behind it actually turns a non-admin away — that is the whole bug
    this file was written for, and adding a name without checking is how it
    would come back.

    The refusal is measured through the worst case that can actually be built:
    every module involved switched on (a module nobody enabled answers 404,
    which would let any name onto this list unmeasured), and the doctor's role
    holding the module in its stored CSV — written directly, because that is
    precisely what `set_modules` exists to prevent and what a hand-posted
    request would otherwise achieve.

    It is worth being exact about which guard then fires, because the answer
    is not the obvious one: `Role.module_list` drops admin-only modules out of
    a non-admin's list even when the CSV names them, so the doctor is turned
    away by the permission check before `admin_required` is ever reached.
    Removing `admin_required` from one of these views therefore does *not*
    make this test fail — checked, not assumed. That is a second lock rather
    than a reason to skip this one: what a clinic is owed is that a doctor
    cannot open these screens, and this is the test that says so end to end.
    """
    from flask import url_for

    from app.models import Setting, User
    from app.models.permissions import ADMIN_ONLY_MODULES

    with clinic["app"].app_context():
        for module in ADMIN_ONLY_MODULES:
            Setting.set(f"mod_enabled:{module}", "1")
        from app.models import Role

        doctor = User.query.filter_by(username="doc").first()
        assert not doctor.is_admin, "this is not a test of a non-admin"
        role = Role.query.filter_by(name=doctor.role).first()
        if role is None:                       # a static role with no row yet
            role = Role(name=doctor.role, label_ar=doctor.role, is_admin=False)
            clinic["db"].session.add(role)
        role.modules = ",".join(["dashboard"] + list(ADMIN_ONLY_MODULES))
        clinic["db"].session.commit()

    client = clinic["sign_in"]("doc")          # signed in, and not an admin
    for module in ADMIN_ONLY_MODULES:
        with clinic["app"].test_request_context():
            endpoint = "main.dashboard" if module == "dashboard" else f"{module}.index"
            if endpoint not in clinic["app"].view_functions:
                continue
            url = url_for(endpoint)
        assert client.get(url).status_code in (302, 403), \
            f"{module} is on the admin-only list but lets a doctor in"


def test_everything_else_is_still_offered(clinic):
    """The fix must not quietly shrink what a clinic can delegate."""
    from app.models.permissions import GRANTABLE_MODULES, MODULES

    from app.models.permissions import ADMIN_ONLY_MODULES

    assert len(GRANTABLE_MODULES) == len(MODULES) - len(ADMIN_ONLY_MODULES)
    for module in ("patients", "finance", "messages", "reports", "prescriptions"):
        assert module in GRANTABLE_MODULES


@pytest.mark.parametrize("module", ["settings", "users"])
def test_saving_one_by_hand_does_not_store_it(clinic, module):
    """The half that a removed checkbox does not cover."""
    from app.extensions import db
    from app.models import Role

    with clinic["app"].app_context():
        role = Role(name="tester", label_ar="تجربة", is_admin=False)
        role.set_modules(["dashboard", "patients", module])
        db.session.add(role)
        db.session.commit()

        assert module not in role.module_list, \
            f"{module} was stored on a role, where it will render a dead link"
        assert "patients" in role.module_list, "the real modules were lost too"


@pytest.mark.parametrize("module", ["settings", "users"])
def test_a_role_saved_before_this_rule_stops_showing_the_dead_link(clinic, module):
    """Existing clinics have roles with the tick already stored.

    Filtering only on save would leave those showing a sidebar link that has
    never once opened, until somebody happened to re-save the role.
    """
    from app.extensions import db
    from app.models import Role

    with clinic["app"].app_context():
        role = Role(name="legacy", label_ar="قديم", is_admin=False)
        # Written straight to the column, the way an older version stored it.
        role.modules = f"dashboard,patients,{module}"
        db.session.add(role)
        db.session.commit()

        assert module not in role.module_list


def test_an_admin_role_still_reaches_everything(clinic):
    """Admins do open both screens — the filter is about *granting*, not about
    who may go there."""
    from app.models import Role
    from app.models.permissions import MODULES

    role = Role(name="boss_role", label_ar="مدير", is_admin=True)

    assert role.module_list == list(MODULES)


def test_the_admin_still_opens_both_screens(clinic):
    client = clinic["sign_in"]("boss")

    for url in ("/settings/", "/users/"):
        assert client.get(url).status_code == 200, \
            f"the admin lost {url} to a permissions change"


def test_a_doctor_is_still_refused_both(clinic):
    client = clinic["sign_in"]("doc")

    for url in ("/settings/", "/users/"):
        assert client.get(url).status_code == 403


def test_the_role_editor_page_does_not_draw_them(clinic):
    page = clinic["sign_in"]("boss").get("/users/roles").data.decode()

    for module in ("settings", "users"):
        assert f'value="{module}"' not in page, \
            f"the role editor still draws a {module} checkbox"
    assert 'value="patients"' in page, "the editor lost its real checkboxes"
