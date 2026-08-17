"""A role a clinic invented could hold no capability at all.

Roles are editable data — a clinic can add its own — but capabilities were
not. ``User.can`` asked ``role_has_capability(self.role, …)``, which reads a
table **in code**, keyed by the five built-in role names. So a clinic that
made its own "front desk" role got a receptionist who could not reach the
till, with nothing on any screen to explain it, and no way to fix it except
granting the capability to each person one at a time, forever.

It surfaced properly when a nursing station needed a role of its own: a new
role is exactly the case that has no entry in that table.

**The union is the part to be careful about.** A clinic upgrading has roles
whose new `capabilities` column is empty. Reading only the column would take
the till away from every receptionist on the morning of the upgrade — the
built-in table has to keep working underneath. Reading only the table is the
bug. So `can` is the union of: the role's own list, the built-in table, and
this person's individual grants.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _role(clinic, name, caps=(), modules=("dashboard",), admin=False):
    from app.extensions import db
    from app.models import Role

    role = Role(name=name, label_ar=name, is_admin=admin)
    role.set_modules(list(modules))
    role.set_capabilities(list(caps))
    db.session.add(role)
    db.session.flush()
    return role


def _user(clinic, username, role):
    from app.extensions import db
    from app.models import User

    user = User(username=username, full_name=username, role=role, is_active=True)
    user.set_password("secret")
    db.session.add(user)
    db.session.flush()
    return user


# ------------------------------------------------------------- the bug

def test_a_role_the_clinic_invented_can_hold_a_capability(clinic):
    """The whole point. A nursing role is a new role, and a new role had
    nothing."""
    with clinic["app"].app_context():
        _role(clinic, "nursing", caps=["patient_medical"],
              modules=["dashboard", "patients", "visits"])
        nurse = _user(clinic, "nur", "nursing")
        clinic["db"].session.commit()

        assert nurse.can("patient_medical") is True, \
            "a role the clinic created still holds nothing"


def test_a_custom_front_desk_can_reach_the_till(clinic):
    """The reported shape of it: reception under a name of the clinic's own."""
    with clinic["app"].app_context():
        _role(clinic, "front_desk", caps=["cashier"],
              modules=["dashboard", "patients", "appointments"])
        _user(clinic, "fd", "front_desk")
        clinic["db"].session.commit()

    client = clinic["app"].test_client()
    client.post("/login", data={"username": "fd", "password": "secret"},
                follow_redirects=True)

    assert client.get("/finance/cashier",
                      follow_redirects=True).status_code == 200


def test_a_capability_not_granted_is_still_refused(clinic):
    """Widening this must not hand everything to everybody."""
    with clinic["app"].app_context():
        _role(clinic, "nursing2", caps=["patient_medical"],
              modules=["dashboard", "visits"])
        nurse = _user(clinic, "nur2", "nursing2")
        clinic["db"].session.commit()

        assert nurse.can("cashier") is False
        assert nurse.can("treasury_move") is False


# ------------------------------------------------- what an upgrade must keep

def test_an_existing_role_with_an_empty_column_keeps_what_it_had(clinic):
    """The migration hazard, and the reason `can` is a union.

    Every role in every clinic gets this column empty. If the column replaced
    the built-in table instead of adding to it, the upgrade would take the
    till away from every receptionist in the country on the same morning.
    """
    from app.extensions import db
    from app.models import Role

    with clinic["app"].app_context():
        role = Role(name="reception2", label_ar="استقبال", is_admin=False)
        role.set_modules(["dashboard", "patients", "appointments"])
        role.capabilities = ""           # exactly what an upgrade leaves
        db.session.add(role)
        user = _user(clinic, "rec2", "reception2")
        db.session.commit()

        assert role.capability_list == []
        # `reception2` is not in the built-in table either, so this one is
        # honestly empty — the built-in *name* is what carries the fallback.
        assert user.can("cashier") is False

    with clinic["app"].app_context():
        plain = db.session.get(type(user), user.id)
        plain.role = "reception"          # the built-in name
        db.session.commit()

        assert plain.can("cashier") is True, \
            "the upgrade stripped the till from a built-in reception role"


def test_the_built_in_roles_are_untouched(clinic):
    """Nothing about the five that ship changes."""
    from app.models.permissions import role_has_capability

    assert role_has_capability("reception", "cashier")
    assert role_has_capability("admin", "messages_setup")
    assert not role_has_capability("doctor", "cashier")


def test_a_personal_grant_still_adds_on_top(clinic):
    """The third source. Grants only ever add — that was already the rule."""
    from app.extensions import db
    from app.models import UserCapability

    with clinic["app"].app_context():
        _role(clinic, "front_desk2", caps=[], modules=["dashboard"])
        user = _user(clinic, "fd2", "front_desk2")
        db.session.commit()

        assert user.can("cashier") is False
        db.session.add(UserCapability(user_id=user.id, capability="cashier"))
        db.session.commit()

        assert user.can("cashier") is True


def test_an_admin_role_holds_everything(clinic):
    from app.models.permissions import CAPABILITIES

    with clinic["app"].app_context():
        role = _role(clinic, "boss_role", caps=[], admin=True)

        assert role.capability_list == list(CAPABILITIES)


# --------------------------------------------------------------- the screen

def test_the_role_editor_offers_the_capabilities(clinic):
    """A column nothing can set is the same bug one layer down."""
    page = clinic["sign_in"]("boss").get("/users/roles").data.decode()

    assert 'name="capabilities"' in page, \
        "the role editor cannot set a capability, so the column is unreachable"
    assert 'value="cashier"' in page


def test_saving_a_role_stores_what_was_ticked(clinic):
    from app.models import Role

    client = clinic["sign_in"]("boss")
    client.post("/users/roles/new",
                data={"name": "nursing3", "label_ar": "تمريض",
                      "modules": ["dashboard", "visits"],
                      "capabilities": ["patient_medical"]},
                follow_redirects=True)

    with clinic["app"].app_context():
        role = Role.query.filter_by(name="nursing3").first()
        assert role is not None, "the role was not created"
        assert role.capability_list == ["patient_medical"]


@pytest.mark.parametrize("cap", ["patient_medical", "cashier", "finance_manage",
                                 "treasury_move", "treasury_adjust",
                                 "messages_setup"])
def test_every_capability_has_a_label(clinic, cap):
    """An unlabelled checkbox reads as a bug on a permissions screen."""
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert cap in json.load(fh)["cap"], f"{lang} has no label for {cap}"


def test_the_column_is_in_the_additive_migration(clinic):
    from app.utils.schema import ADDITIONS

    assert ("roles", "capabilities") in {(t, c) for t, c, _ in ADDITIONS}, \
        "existing clinics would not get the column at all"
