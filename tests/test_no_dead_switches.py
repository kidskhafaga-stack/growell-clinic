"""A switch that is saved, shown, and read by nothing.

`small_clinic_mode` was a checkbox on the settings screen labelled "reception
runs the till". It was stored, and injected into the template context of every
page in the program, and **nothing ever read it** — not a route, not a
decorator, not a template. Ticking it did nothing at all.

Found while answering "why isn't it applying?", which is the only way a switch
like this is ever found: somebody tries to use it.

It is removed rather than wired up, because the thing it promised already
works and works better. Reception collecting money is the ``cashier``
capability, which the role holds by default and which can be granted to one
person without inventing a role — per-user and per-role, where this was one
global flag for the whole clinic.

**The test is not about this one setting.** It is the third dead promise found
in a day: the `settings` module checkbox, the `users` one, and this. So it
checks the shape of the class — every switch the settings screen saves is read
somewhere — rather than naming the one that has already been removed.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Keys whose only consumer is the settings form itself — they are read back
# into the same screen to redraw it, which is a real use.
FORM_ONLY = set()


def _sources():
    """Every file that could read a setting."""
    out = []
    for base in ("app",):
        for root, _dirs, files in os.walk(os.path.join(ROOT, base)):
            if "__pycache__" in root:
                continue
            for name in files:
                if name.endswith((".py", ".html")):
                    out.append(os.path.join(root, name))
    return out


def _toggle_keys():
    """The switches the settings screen stores."""
    with open(os.path.join(ROOT, "app/blueprints/settings/routes.py"),
              encoding="utf-8") as fh:
        src = fh.read()
    block = src[src.index("TOGGLE_KEYS"):]
    block = block[:block.index("]") + 1]
    return [k for k in re.findall(r'"(\w+)"', block) if k != "TOGGLE_KEYS"]


def test_the_dead_switch_is_gone(clinic):
    """Named once, so the removal itself is recorded."""
    for path in _sources():
        with open(path, encoding="utf-8") as fh:
            assert "small_clinic_mode" not in fh.read(), \
                f"the removed switch came back in {os.path.relpath(path, ROOT)}"

    for lang in ("ar", "en"):
        with open(os.path.join(ROOT, "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert "small_clinic_mode" not in json.load(fh)["settings"], \
                f"its wording is still in {lang}.json"


def test_every_switch_the_settings_screen_saves_is_read_somewhere(clinic):
    """The shape of the bug, not the one instance of it.

    A switch nobody reads is a promise the program does not keep, and the
    only way anybody finds out is by ticking it and waiting for something to
    happen.
    """
    keys = _toggle_keys()
    assert len(keys) > 3, f"the TOGGLE_KEYS scan found only {keys}"

    sources = _sources()
    unread = []
    for key in keys:
        if key in FORM_ONLY:
            continue
        seen = 0
        for path in sources:
            if path.endswith("blueprints/settings/routes.py"):
                continue                      # the screen that saves it
            if path.endswith("templates/settings/index.html"):
                continue                      # the form that draws it
            with open(path, encoding="utf-8") as fh:
                if key in fh.read():
                    seen += 1
        if seen == 0:
            unread.append(key)

    assert not unread, (
        "these settings are saved and shown and nothing reads them, so "
        f"ticking them does nothing: {unread}")


def test_the_settings_screen_still_works_without_it(clinic):
    """Removing a field from a form is the sort of change that 500s."""
    client = clinic["sign_in"]("boss")

    assert client.get("/settings/").status_code == 200
    answer = client.post("/settings/", data={"active_tab": "policies",
                                             "clinic_name": "عيادة"},
                         follow_redirects=True)
    assert answer.status_code == 200


def test_the_capability_still_does_the_job_it_promised(clinic):
    """It is removed because the thing it offered already works properly.

    Reception collects money through the `cashier` capability — per role and
    per person, rather than one flag for the whole clinic.
    """
    from app.models import User

    with clinic["app"].app_context():
        rec = User.query.filter_by(username="desk").first()

        assert rec.can("cashier") is True
        assert rec.can_collect is True

    assert clinic["sign_in"]("desk").get(
        "/finance/cashier", follow_redirects=True).status_code == 200
