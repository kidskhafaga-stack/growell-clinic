"""Every button on the readiness screen has to open something.

That screen has exactly one job: take somebody to the thing they still have to
set up. Three of its links did not.

* **Backups → 405 Method Not Allowed.** It pointed at
  ``settings.backup_settings``, which is POST-only — it *saves* the settings,
  it does not show them — so pressing "open" issued a GET and the clinic got
  an error page. Reported from a real screen.
* **AI assistant → the wrong tab.** It pointed at the settings page with no
  anchor, so it landed on "clinic" and left somebody hunting for the section
  they had just asked for. The page already understood ``#ai``; the link never
  sent it.
* **Facility setup → 403.** Found by the sweep below rather than reported.
  That step is owner-only by design, and the checklist offered the button to
  every admin. The fix is different in kind: the door is not going to open
  however long they look at it, so the row says who can open it instead.

The first test is the one that matters. Checking the two reported links would
have left the third, and the next link somebody adds would be the fourth.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SKIP_PREFIXES = ("/static", "/logout", "/lang")


def _admin(clinic, owner=False):
    # The username is held as a plain string: reading it off the model after
    # the context closes detaches the instance.
    username = "setupadmin" + ("o" if owner else "")
    with clinic["app"].app_context():
        from app.models import User
        db = clinic["db"]
        user = User(username=username, full_name="admin", role="admin",
                    is_active=True, is_super_admin=owner)
        user.set_password("secret")
        db.session.add(user)
        db.session.commit()
    client = clinic["app"].test_client()
    client.post("/login", data={"username": username, "password": "secret"},
                follow_redirects=True)
    return client


def _links(body):
    return sorted({href for href in re.findall(r'href="(/[^"]*)"', body)
                   if not href.startswith(SKIP_PREFIXES)})


# --- the sweep -------------------------------------------------------------

def test_every_link_on_the_readiness_screen_opens(clinic):
    """The test that catches the next one too.

    Written as a sweep rather than three assertions, because two of these were
    reported by a person looking at the screen and the third was only found by
    following every link. A checklist whose buttons 404, 405 or 403 is worse
    than no checklist: it teaches the person setting the clinic up that the
    program is broken, on their first morning with it.
    """
    client = _admin(clinic)
    body = client.get("/settings/wizard").data.decode()
    broken = []
    for href in _links(body):
        response = client.get(href.split("#")[0])
        if response.status_code != 200:
            broken.append((response.status_code, href))
    assert broken == [], f"links that do not open: {broken}"


# --- the three, named ------------------------------------------------------

def test_the_backup_step_points_at_a_page_not_a_post_handler(clinic):
    """The 405 as it was met: press "open", get an error page."""
    from app.utils.readiness import STEPS

    step = next(s for s in STEPS if s["key"] == "backup")
    assert step["endpoint"] != "settings.backup_settings", (
        "the backup step points at the POST-only save handler again")

    client = _admin(clinic)
    body = client.get("/settings/wizard").data.decode()
    assert "/settings/data/backup-settings" not in body
    assert client.get("/settings/data").status_code == 200


def test_the_backup_link_lands_on_the_backup_card_not_the_top(clinic):
    """A link to the top of a long data screen has not arrived."""
    client = _admin(clinic)
    body = client.get("/settings/wizard").data.decode()
    assert "/settings/data#backup" in body

    page = client.get("/settings/data").data.decode()
    assert 'id="backup"' in page, "the anchor it points at does not exist"


def test_the_ai_step_opens_the_ai_tab(clinic):
    """The settings page already understood #ai. The link never sent it."""
    client = _admin(clinic)
    body = client.get("/settings/wizard").data.decode()
    assert "/settings/#ai" in body or "/settings/index#ai" in body

    page = client.get("/settings/").data.decode()
    assert "#ai" in page, "the settings page no longer reads the anchor"


def test_an_owner_only_step_says_so_instead_of_handing_over_a_403(clinic):
    """Different in kind from the other two.

    The facility setup reshapes what the whole institution is and a plain
    admin must not. So the row names who can open it rather than offering a
    button that refuses — being refused a door you were just pointed at is
    worse than being told it is not yours.
    """
    plain = _admin(clinic)
    body = plain.get("/settings/wizard").data.decode()
    assert "/settings/setup" not in body, (
        "a plain admin is still offered the owner-only setup")
    assert "المالك بس" in body


def test_the_owner_still_gets_the_button(clinic):
    """The guard must not lock out the one person it is for."""
    owner = _admin(clinic, owner=True)
    body = owner.get("/settings/wizard").data.decode()
    assert "/settings/setup" in body


@pytest.mark.parametrize("key,expected", [
    ("backup", "backup"),
    ("ai", "ai"),
])
def test_the_anchors_are_carried_through_the_data_not_hardcoded(key, expected):
    """The template renders whatever the step declares.

    Hard-coding the two anchors in the template would work today and be
    forgotten the moment a third step needs one.
    """
    from app.utils.readiness import STEPS

    step = next(s for s in STEPS if s["key"] == key)
    assert step.get("anchor") == expected
