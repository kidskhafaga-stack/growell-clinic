"""Modules the program offered and then refused to open.

Reported from a running clinic with a screenshot: seven cards on the home
screen — الحضّانات، الرعاية المركزة، الأقسام، العمليات، المعمل، الصيدلية،
جدول المناوبات — every one of them **404**.

They are opt-in modules this clinic never switched on, and the routes were
right to refuse: ``module_required`` answers 404 for a module the clinic does
not run, which is a different sentence from the 403 it answers for a role
without the permission. **Two facts, and they must stay two** — "it is not
here" and "it is here and not yours" are not the same thing to read.

The bug was on the drawing side, in three places that each asked only the
permission half:

* the home screen's module cards — a card that 404s
* the "page to open after login" dropdown — offers a module that 404s
* and, through that stored choice, **the login redirect itself** — an admin
  who once picked one of these signs in and lands on a 404 *every time*

The sidebar had asked both all along, which is why the same install shows a
clean sidebar beside a grid of dead cards. That is the tell: one rule, written
out in four places, and three of the copies were wrong.

So the pair now has a name — ``User.can_open`` — and every place that *offers*
a module asks that. What must not follow from this fix is a program that hides
a module the clinic actually runs, so that is asserted here at least as hard
as the hiding is.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

#: Every one of these is opt-in: off until somebody switches it on.
CIRCLED_IN_RED = ("nicu", "icu", "ward", "theatres", "labs", "pharmacy", "duty")


@pytest.fixture()
def clinic():
    """An admin — the role that can reach everything — at a clinic that has
    switched none of the opt-in modules on. The permission half says yes to
    all of them, which is exactly what made the bug invisible."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import User

        user = User(username="admin", full_name="مدير", role="admin",
                    is_active=True)
        user.set_password("secret")
        db.session.add(user)
        # And somebody who is not an admin. The bug hid behind the admin: a
        # role that may reach everything makes the permission half of the rule
        # invisible, so half a rule passes every test written with only one.
        desk = User(username="desk", full_name="استقبال", role="reception",
                    is_active=True)
        desk.set_password("secret")
        db.session.add(desk)
        db.session.commit()

    def sign_in(username="admin"):
        client = app.test_client()
        client.post("/login", data={"username": username, "password": "secret"},
                    follow_redirects=True)
        return client

    def switch_on(module):
        """Switch an opt-in module on, from anywhere — the callers below are a
        mix of inside and outside an app context."""
        from app.models import Setting

        with app.app_context():
            Setting.set(f"mod_enabled:{module}", "1")
            db.session.commit()

    return {"app": app, "db": db, "sign_in": sign_in, "switch_on": switch_on}


def _admin(clinic):
    from app.models import User

    return User.query.filter_by(username="admin").first()


# ------------------------------------------------- the rule, said once --
def test_permission_alone_is_not_enough_to_open_a_module(clinic):
    """The two halves, and why one of them was never asked."""
    with clinic["app"].app_context():
        admin = _admin(clinic)
        for module in CIRCLED_IN_RED:
            assert admin.can_access(module) is True    # the role may
            assert admin.can_open(module) is False     # the clinic does not run it


def test_switching_one_on_opens_it(clinic):
    """**The half that matters more.** A fix that hid every module would pass
    every test above it and lose the clinic its screens."""
    with clinic["app"].app_context():
        clinic["switch_on"]("labs")
        admin = _admin(clinic)
        assert admin.can_open("labs") is True
        assert admin.can_open("nicu") is False


# --------------------------------------------------- 1) the home screen --
def test_no_card_is_drawn_for_a_module_that_would_404(clinic):
    html = clinic["sign_in"]().get("/", follow_redirects=True).get_data(as_text=True)
    for module in CIRCLED_IN_RED:
        assert f'href="/{module}/"' not in html, f"{module} card still drawn"


def test_every_card_that_is_drawn_actually_opens(clinic):
    """Said as the promise rather than as a list: whatever the grid offers,
    pressing it must not be a 404. This is the assertion that would have
    caught the original bug without anybody knowing which seven to name."""
    import re

    clinic["switch_on"]("labs")
    client = clinic["sign_in"]()
    html = client.get("/", follow_redirects=True).get_data(as_text=True)
    grid = html.split("module-card")
    hrefs = {m for chunk in grid[1:]
             for m in re.findall(r'href="(/[a-z-]+/?)"', chunk)[:1]}
    assert hrefs, "no module cards drawn at all — the grid is empty"
    for href in hrefs:
        assert client.get(href).status_code != 404, f"{href} is a card that 404s"


def test_the_lab_this_clinic_runs_is_still_on_the_home_screen(clinic):
    clinic["switch_on"]("labs")
    html = clinic["sign_in"]().get("/", follow_redirects=True).get_data(as_text=True)
    assert 'href="/labs/"' in html


# ------------------------------------------------ 2) the landing choice --
def test_a_switched_off_module_is_not_offered_as_a_landing_page(clinic):
    html = clinic["sign_in"]().get("/profile",
                                   follow_redirects=True).get_data(as_text=True)
    for module in CIRCLED_IN_RED:
        assert f'value="{module}"' not in html, f"{module} offered as a landing page"


def test_one_that_is_switched_on_is_offered(clinic):
    clinic["switch_on"]("labs")
    html = clinic["sign_in"]().get("/profile",
                                   follow_redirects=True).get_data(as_text=True)
    assert 'value="labs"' in html


# ------------------------------------------- 3) the worst one: the login --
def test_signing_in_does_not_land_on_a_page_that_does_not_exist(clinic):
    """The stored choice was made the day the module was on. Switching it off
    later left the preference behind, and `can_access` plus a URL that builds
    fine sent them there anyway — **every sign-in, forever**."""
    with clinic["app"].app_context():
        _admin(clinic).default_landing = "nicu"
        clinic["db"].session.commit()

    resp = clinic["sign_in"]().get("/", follow_redirects=True)
    assert resp.status_code == 200

    client = clinic["app"].test_client()
    landed = client.post("/login",
                         data={"username": "admin", "password": "secret"},
                         follow_redirects=True)
    assert landed.status_code == 200


def test_the_stored_choice_is_not_erased_by_being_skipped(clinic):
    """Skipping it is not the same as forgetting it. Switching the module back
    on has to give the person the home screen they picked, or the fix quietly
    costs them a setting to repair the 404."""
    with clinic["app"].app_context():
        _admin(clinic).default_landing = "nicu"
        clinic["db"].session.commit()

    clinic["sign_in"]()
    with clinic["app"].app_context():
        assert _admin(clinic).default_landing == "nicu"
        clinic["switch_on"]("nicu")
        assert _admin(clinic).can_open("nicu") is True


def test_a_landing_page_that_is_on_is_still_honoured(clinic):
    """The feature still works — this is the reason it exists."""
    clinic["switch_on"]("labs")
    with clinic["app"].app_context():
        _admin(clinic).default_landing = "labs"
        clinic["db"].session.commit()

    client = clinic["app"].test_client()
    resp = client.post("/login", data={"username": "admin", "password": "secret"})
    assert "/labs" in resp.headers.get("Location", "")


def test_a_switched_off_module_cannot_be_saved_as_a_landing_page(clinic):
    """The dropdown no longer offers it; the door behind the dropdown has to
    refuse it too, or a typed form value walks straight past the screen."""
    client = clinic["sign_in"]()
    client.post("/profile", data={"default_landing": "nicu"},
                follow_redirects=True)
    with clinic["app"].app_context():
        assert _admin(clinic).default_landing is None


# ------------------------------------------------- the sidebar's version --
def test_the_sidebar_and_the_home_screen_now_agree(clinic):
    """They disagreed on the same page, in the same render, for the same
    person — the sidebar clean and the grid full of dead cards. That is what
    one rule written out four times looks like from the outside."""
    clinic["switch_on"]("labs")
    html = clinic["sign_in"]().get("/", follow_redirects=True).get_data(as_text=True)
    for module in CIRCLED_IN_RED:
        drawn = f'href="/{module}/"' in html
        assert drawn == (module == "labs"), f"{module}: sidebar and grid disagree"


# ------------------------------------------------- and the other half --
def test_a_module_the_clinic_runs_is_still_not_everybodys(clinic):
    """**The half a test written only with an admin cannot see.**

    Caught by measurement, not by reading: reverting ``can_open`` to ask the
    switch *alone* left all twelve tests above green, because an admin reaches
    every module and the permission half never had to be true. A receptionist
    is what makes it visible — the lab is switched on, it is simply not theirs.
    """
    clinic["switch_on"]("labs")
    with clinic["app"].app_context():
        from app.models import User

        desk = User.query.filter_by(username="desk").first()
        assert desk.can_access("labs") is False     # not this role's
        assert desk.can_open("labs") is False       # so it is not offered

        admin = _admin(clinic)
        assert admin.can_open("labs") is True       # and still is, for one who may


def test_reception_is_not_shown_a_card_that_would_say_403(clinic):
    """The 404 was the reported bug; this is the same mistake wearing the
    other status code. A drawn card that answers "not yours" is the same wasted
    press as one that answers "not here"."""
    clinic["switch_on"]("labs")
    html = clinic["sign_in"]("desk").get("/", follow_redirects=True).get_data(as_text=True)
    assert 'href="/labs/"' not in html
    assert 'href="/appointments/"' in html, "reception lost a screen that is theirs"
