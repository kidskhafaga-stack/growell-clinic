"""A key the clinic typed once is not handed back to the browser.

Found while looking at the settings screen for something else: every secret on
it was rendered into the page as ``value="…"``.

**`type="password"` is not a secret.** It draws dots. The real string sits in
the HTML — readable in "view source", in the browser's own element inspector,
in a page saved to disk, and in any screenshot of the source somebody sends
when asking for help. Two of the four were not even that: the tax authority's
client secrets were plain text boxes with the key visible on screen.

**And the code already disagreed with itself about this.** ``_ai_form_config``
carries the sentence *"An empty key box means 'use the saved one' rather than
'no key': the field renders blank on a saved password"* — a defence written for
a state the screen never produced, guarding a case that could not happen. It is
true now.

**Blank means keep, so removing one needs its own action.** The box renders
empty every time, so reading blank as a deletion would wipe the AI key whenever
somebody saved the clinic's name from another tab of the same form — and the
first sign of it would be the assistant quietly refusing to answer. Deleting a
credential should take an action, not the absence of one.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

SECRETS = {
    "ai_api_key": "sk-live-must-never-be-rendered",
    "icd11_client_secret": "who-secret-must-never-be-rendered",
    "eta_client_secret": "eta-one-must-never-be-rendered",
    "eta_client_secret2": "eta-two-must-never-be-rendered",
}


@pytest.fixture()
def desk(clinic):
    """A clinic with every secret already set up."""
    from app.extensions import db
    from app.models import Setting

    with clinic["app"].app_context():
        for key, value in SECRETS.items():
            Setting.set(key, value)
        Setting.set("ai_provider", "groq")
        Setting.set("clinic_name", "عيادة")
        db.session.commit()
    return clinic


def _page(desk):
    return desk["sign_in"]("boss").get("/settings/").get_data(as_text=True)


def _saved(desk, key):
    from app.models import Setting

    with desk["app"].app_context():
        return Setting.get(key)


def _save(desk, **form):
    data = {"active_tab": "ai", "clinic_name": "عيادة"}
    data.update(form)
    return desk["sign_in"]("boss").post("/settings/", data=data,
                                        follow_redirects=True)


# ------------------------------------------------ it is not on the page

@pytest.mark.parametrize("key", sorted(SECRETS))
def test_the_secret_is_not_in_the_html(desk, key):
    """The whole finding. `type="password"` draws dots over a value that is
    still sitting in the source of the page."""
    assert SECRETS[key] not in _page(desk), \
        f"{key} was rendered into the settings page"


def test_the_secret_never_reaches_the_template_at_all(desk):
    """Stronger than checking the markup, and the reason it is here: the test
    above only proves *this* template does not print them. Blanking them in the
    route means a field added next year — a second AI provider, another tax
    endpoint — cannot leak one by writing the obvious `values.get(...)`.

    Caught by mutation testing: removing the blanking loop from the route broke
    nothing, because the template happened to be careful. The template being
    careful is not the guarantee worth having."""
    from flask import template_rendered

    seen = {}

    def record(sender, template, context, **extra):
        if template.name == "settings/index.html":
            seen.update(context.get("values") or {})

    template_rendered.connect(record, desk["app"])
    try:
        desk["sign_in"]("boss").get("/settings/")
    finally:
        template_rendered.disconnect(record, desk["app"])

    assert seen, "the settings template was never rendered"
    for key in SECRETS:
        assert not (seen.get(key) or "").strip(), \
            f"{key} was handed to the template, printed or not"


def test_none_of_them_are_plain_text_boxes(desk):
    """Two of the four were. A secret behind dots is at least not readable
    over somebody's shoulder."""
    import re

    page = _page(desk)
    for key in SECRETS:
        box = re.search(rf'<input[^>]*name="{key}"[^>]*>', page)
        assert box, f"{key} has no box on the screen"
        assert 'type="password"' in box.group(0), \
            f"{key} is a plain text box: {box.group(0)}"


def test_the_screen_still_says_a_key_is_there(desk):
    """An empty box with nothing beside it reads as "no key", and somebody
    types a new one over a working setup."""
    page = _page(desk)

    assert page.count("clear_ai_api_key") == 1, \
        "there is no way to tell a saved key from an empty one"


def test_a_clinic_with_no_key_is_not_told_it_has_one(clinic):
    from app.i18n import t  # noqa: F401 — the badge text is checked by key

    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "clear_ai_api_key" not in page, \
        "an empty setup was offered a key to remove"


# --------------------------------------- blank keeps, and a tick removes

def test_saving_another_tab_does_not_wipe_the_key(desk):
    """The reason blank cannot mean "delete". Every tab posts this one form,
    so saving the clinic's name posts an empty AI key box — and the first sign
    of it being read as a deletion is the assistant refusing to answer."""
    _save(desk, active_tab="clinic")

    assert _saved(desk, "ai_api_key") == SECRETS["ai_api_key"]


@pytest.mark.parametrize("key", sorted(SECRETS))
def test_a_blank_box_keeps_every_one_of_them(desk, key):
    _save(desk)

    assert _saved(desk, key) == SECRETS[key]


def test_typing_a_new_key_replaces_it(desk):
    _save(desk, ai_api_key="sk-the-new-one")

    assert _saved(desk, "ai_api_key") == "sk-the-new-one"


def test_a_tick_removes_it(desk):
    """Blank means keep, so without this there would be no way to remove a
    key at all — which is its own kind of trap for a clinic changing hands."""
    _save(desk, clear_ai_api_key="1")

    assert (_saved(desk, "ai_api_key") or "") == ""


def test_the_tick_wins_over_a_typed_value(desk):
    """Somebody who has both typed a key and ticked "remove" has said two
    things. The destructive one is the deliberate one — a tick is an action
    and text left in a box may be a browser's autofill."""
    _save(desk, ai_api_key="sk-typed-anyway", clear_ai_api_key="1")

    assert (_saved(desk, "ai_api_key") or "") == ""


def test_removing_one_leaves_the_others_alone(desk):
    _save(desk, clear_ai_api_key="1")

    assert _saved(desk, "icd11_client_secret") == SECRETS["icd11_client_secret"]
    assert _saved(desk, "eta_client_secret") == SECRETS["eta_client_secret"]


# ------------------------------------------ and the features still work

def test_the_ai_test_button_still_uses_the_saved_key(desk):
    """`_ai_form_config` falls back to the saved key when the box is empty —
    the defence whose comment described a screen that did not exist until now.
    Without it, "test the connection" on a working clinic would report the
    setup broken because the box it read was blank by design."""
    from app.blueprints.settings.routes import _ai_form_config

    with desk["app"].test_request_context("/settings/", method="POST",
                                          data={"ai_provider": "groq",
                                                "ai_api_key": ""}):
        cfg = _ai_form_config()

    assert cfg["api_key"] == SECRETS["ai_api_key"]


def test_the_who_download_still_finds_its_credentials(desk):
    """The ICD-11 download reads the setting directly rather than the form, so
    blanking the *box* must not have blanked the *setting*."""
    from app.utils.icd_who import settings as who_settings

    with desk["app"].app_context():
        assert who_settings()["client_secret"] == SECRETS["icd11_client_secret"]
