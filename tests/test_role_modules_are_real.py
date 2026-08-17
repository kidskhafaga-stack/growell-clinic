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

Filtered on save as well as in the form. A checkbox removed only from the page
is a permission a hand-posted request can still store, and a stored permission
that does nothing is the same bug with one more step to reach it.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def test_the_two_admin_only_modules_are_named(clinic):
    from app.models.permissions import ADMIN_ONLY_MODULES, MODULES

    assert set(ADMIN_ONLY_MODULES) == {"users", "settings"}
    assert all(m in MODULES for m in ADMIN_ONLY_MODULES), \
        "an admin-only module that is not a module at all"


def test_they_are_not_offered_as_role_checkboxes(clinic):
    from app.models.permissions import ADMIN_ONLY_MODULES, GRANTABLE_MODULES

    for module in ADMIN_ONLY_MODULES:
        assert module not in GRANTABLE_MODULES, \
            f"the role editor still offers {module}, which no route honours"


def test_everything_else_is_still_offered(clinic):
    """The fix must not quietly shrink what a clinic can delegate."""
    from app.models.permissions import GRANTABLE_MODULES, MODULES

    assert len(GRANTABLE_MODULES) == len(MODULES) - 2
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
