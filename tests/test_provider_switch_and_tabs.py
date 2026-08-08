"""Two bugs a clinic hit every day, and neither was where it looked.

**"The AI provider doesn't save — it stays on the first one."** The provider
saved perfectly. What did not change was the address: ``ai_base_url`` is a
free-text box holding whichever endpoint was put there first, and
``get_config()`` prefers a saved value over the selected provider's default.
So a clinic that set up Claude and later picked Gemini posted a Gemini key to
``api.anthropic.com`` — the screen said one thing and the program did another,
which from a chair is indistinguishable from the choice being ignored.

**"Adding a drug throws me back to the first tab."** Not the fragment: the
server's redirect carries ``#meds`` correctly. The screen's own hash-to-tab
lookup was two hand-written lists, and both were missing ``meds`` and
``consent``, so ``#meds`` fell through to the default. A doctor mid-
consultation, every single time they added a medicine.

Both are the same shape of mistake — a hand-maintained list that has to agree
with something else — which is why the fixes remove the lists rather than add
the missing entries.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

RECORD = os.path.join(os.path.dirname(__file__), "..", "app", "templates",
                      "visits", "record.html")


# ============================================== the provider that "wouldn't save"
def _save_ai(client, **fields):
    return client.post("/settings/", data=fields, follow_redirects=True)


def test_switching_provider_stops_talking_to_the_old_one(clinic):
    """The bug itself, in the order a clinic performs it.

    Set up one provider, come back later and choose another. Before the fix
    the program kept calling the first provider's endpoint — for ever, since
    nothing on the screen ever rewrote that box.
    """
    from app.utils.ai import AI_PROVIDERS, get_config

    client = clinic["sign_in"]("boss")
    with clinic["app"].app_context():
        first, second = AI_PROVIDERS["claude"], AI_PROVIDERS["gemini"]

    _save_ai(client, ai_provider="claude", ai_enabled="1",
             ai_model=first["default_model"], ai_base_url=first["base_url"])
    _save_ai(client, ai_provider="gemini", ai_enabled="1",
             ai_model=second["default_model"], ai_base_url=first["base_url"])

    with clinic["app"].app_context():
        cfg = get_config()
        assert cfg["provider"] == "gemini"
        assert cfg["base_url"] == second["base_url"], (
            "the new provider's key would have gone to the old provider's URL")


def test_a_url_typed_for_the_new_provider_is_kept(clinic):
    """The other half. A clinic behind its own proxy types an address *while*
    switching, and throwing that away would be its own bug."""
    from app.utils.ai import AI_PROVIDERS, get_config

    client = clinic["sign_in"]("boss")
    with clinic["app"].app_context():
        first = AI_PROVIDERS["claude"]

    _save_ai(client, ai_provider="claude", ai_enabled="1",
             ai_model=first["default_model"], ai_base_url=first["base_url"])
    _save_ai(client, ai_provider="openai", ai_enabled="1", ai_model="gpt-4o",
             ai_base_url="https://proxy.clinic.local/v1")

    with clinic["app"].app_context():
        assert get_config()["base_url"] == "https://proxy.clinic.local/v1"


def test_the_custom_provider_keeps_its_address(clinic):
    """For ``custom`` the address is the entire point of the provider —
    clearing it on the switch would make the option unusable."""
    from app.utils.ai import get_config

    client = clinic["sign_in"]("boss")
    _save_ai(client, ai_provider="custom", ai_enabled="1", ai_model="local-1",
             ai_base_url="http://10.0.0.9:8080/v1/chat/completions")
    # Save again without touching anything, the way a clinic edits some other
    # field on the same screen.
    _save_ai(client, ai_provider="custom", ai_enabled="1", ai_model="local-1",
             ai_base_url="http://10.0.0.9:8080/v1/chat/completions")

    with clinic["app"].app_context():
        assert get_config()["base_url"] == "http://10.0.0.9:8080/v1/chat/completions"


def test_saving_the_same_provider_twice_changes_nothing(clinic):
    """Guarding the guard: a fixup that fired on every save would wipe a
    deliberate address the next time somebody edited the clinic's phone
    number."""
    from app.utils.ai import get_config

    client = clinic["sign_in"]("boss")
    _save_ai(client, ai_provider="openai", ai_enabled="1", ai_model="gpt-4o",
             ai_base_url="https://proxy.clinic.local/v1")
    _save_ai(client, ai_provider="openai", ai_enabled="1", ai_model="gpt-4o",
             ai_base_url="https://proxy.clinic.local/v1")

    with clinic["app"].app_context():
        assert get_config()["base_url"] == "https://proxy.clinic.local/v1"
        assert get_config()["model"] == "gpt-4o"


# ============================================== "not ready" while it works ==
def test_the_page_names_what_is_missing_instead_of_just_saying_no(clinic):
    """Reported as *"it says not ready while it is connected and working"*.

    Usually nothing is wrong with the key at all — the assistant is simply
    switched off, or the settings that tested fine were never saved. A grey
    badge cannot tell anybody that, and four different causes rendering as one
    word is what turned a two-second fix into a bug report.
    """
    from app.models import Setting
    from app.utils.ai import why_not_ready

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("ai_provider", "gemini")
        Setting.set("ai_api_key", "a-real-key")
        Setting.set("ai_enabled", "0")
        db.session.commit()
        assert why_not_ready() == ["disabled"]

    page = clinic["sign_in"]("boss").get("/ai/").data.decode()
    from app.i18n import t
    with clinic["app"].test_request_context():
        assert t("ai.missing_disabled") in page
        assert t("ai.fix_disabled") in page


def test_a_key_that_was_never_saved_is_named_as_the_reason(clinic):
    from app.models import Setting
    from app.utils.ai import why_not_ready

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("ai_provider", "gemini")
        Setting.set("ai_enabled", "1")
        Setting.set("ai_api_key", "")
        db.session.commit()
        assert why_not_ready() == ["no_key"]


def test_a_local_provider_needs_no_key_to_be_ready(clinic):
    """Ollama runs on the clinic's own machine. Demanding a key would report a
    working offline setup as broken."""
    from app.models import Setting
    from app.utils.ai import is_ready, why_not_ready

    db = clinic["db"]
    with clinic["app"].app_context():
        Setting.set("ai_provider", "ollama")
        Setting.set("ai_enabled", "1")
        Setting.set("ai_api_key", "")
        db.session.commit()
        assert why_not_ready() == []
        assert is_ready()


def test_a_successful_test_on_unsaved_settings_says_so(clinic):
    """The trap of our own making. The test button reads the *form* on
    purpose, so somebody can try a key before committing it — which means a
    green "it works" can be followed by a page that still says "not ready"."""
    from app.utils.ai import same_as_saved

    with clinic["app"].test_request_context():
        from app.utils.ai import get_config

        saved = get_config()
        assert same_as_saved(saved)
        assert not same_as_saved(dict(saved, api_key="typed-just-now"))


# ============================================== the tab that kept resetting =
def _record_source():
    with open(RECORD, encoding="utf-8") as fh:
        return fh.read()


def test_every_tab_can_be_restored_from_its_hash(clinic):
    """The actual defect, pinned against the source.

    The panels' ids and the redirect fragments are the same strings, so the
    check is that no tab is missing from whatever the screen restores from —
    which is what went wrong when it was a hand-written map.
    """
    import re

    source = _record_source()
    panels = set(re.findall(r"""x-show="tab==='(\w+)'""", source))
    listed = re.search(r"TABS:\s*\[([^\]]+)\]", source)
    assert listed, "the tab list is gone; restore() cannot validate a hash"
    known = set(re.findall(r"'(\w+)'", listed.group(1)))

    assert panels <= known, (
        "these tabs exist on the screen but cannot be restored from a hash, "
        "so an add that redirects to them lands on the first tab: "
        + ", ".join(sorted(panels - known)))


def test_the_medications_tab_is_among_them(clinic):
    """Named, because it is the one that was missing and the one a doctor uses
    most: every added drug threw them back to the first tab."""
    import re

    listed = re.search(r"TABS:\s*\[([^\]]+)\]", _record_source())
    known = set(re.findall(r"'(\w+)'", listed.group(1)))
    assert {"meds", "consent"} <= known


def test_the_server_sends_the_doctor_back_to_the_right_tab(clinic):
    """The other side of the same journey — the redirect really does carry the
    fragment, so the screen has something correct to restore from."""
    from app.models import Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    response = clinic["sign_in"]("doc").post(
        f"/visits/{visit_id}/medications",
        data={"drug_name": "Augmentin", "dose": "5 ml", "frequency": "×2"})
    assert response.headers.get("Location", "").endswith("#meds")


def test_the_add_form_is_marked_so_the_doctor_lands_on_it(clinic):
    """After the reload the next action is almost always another one of what
    they just added, so the form is scrolled to rather than left below the
    fold of a panel they have to find again."""
    source = _record_source()
    assert source.count("data-add-form") >= 4
    assert "scrollIntoView" in source


# ============================================== adding without a page reload
def test_every_panel_that_adds_something_can_be_updated_in_place(clinic):
    """The contract the inline-add script relies on, checked in the template.

    It works by posting the form, letting the redirect render the page as it
    always did, and lifting one list out of that response. So each panel needs
    three things: an id to find it by, a marked list to replace, and a form
    marked as inline. Miss any one and the script silently falls back to a
    full reload — which is the exact behaviour we set out to remove, and it
    would come back without anything failing.
    """
    import re

    source = _record_source()
    panels = re.findall(
        r'<div class="card[^"]*" data-add-panel id="(\w+)"', source)
    assert len(panels) >= 4, "the inline-add panels lost their markers"

    for pid in panels:
        block = source.split(f'data-add-panel id="{pid}"', 1)[1]
        block = block.split("data-add-panel", 1)[0]
        assert "data-add-list" in block, f"#{pid} has no list to swap"
        assert "data-inline" in block, f"#{pid}'s form would still reload"
        assert f'data-count-for="{pid}"' in source, f"#{pid} has no tab badge"


def test_the_tab_badge_exists_even_when_the_list_is_empty(clinic):
    """It has to be in the page to count up from nothing to one. Rendered
    always and hidden at zero, rather than conditionally rendered — otherwise
    the first drug added leaves the tab showing no number until a reload."""
    source = _record_source()
    assert 'data-count-for="meds"{% if not visit.medications %} hidden{% endif %}' \
        in source


def test_the_response_to_an_add_still_contains_the_list_to_lift(clinic):
    """End to end on the server side: the POST redirects, the redirect renders
    the page, and the page carries the updated list. If that ever stopped
    being true the script would fall back to reloading — quietly."""
    from app.models import Visit

    db = clinic["db"]
    with clinic["app"].app_context():
        visit_id = db.session.get(Visit, clinic["ids"]["visit"]).id

    page = clinic["sign_in"]("doc").post(
        f"/visits/{visit_id}/medications",
        data={"name": "Augmentin 156", "dose": "5 ml", "frequency": "×2"},
        follow_redirects=True).data.decode()

    assert "data-add-list" in page
    assert "Augmentin 156" in page
    # And it landed in the medications panel, not somewhere else on the page.
    meds = page.split('id="meds"', 1)[1].split("data-add-panel", 1)[0]
    assert "Augmentin 156" in meds


def test_a_failed_inline_submit_falls_back_to_a_normal_one(clinic):
    """A visit record that quietly fails to record something is far worse than
    one that blinks. Pinned in the script, because "it worked when I tried it"
    is not a guarantee about the clinic's network."""
    source = open(os.path.join(os.path.dirname(__file__), "..", "app",
                               "static", "js", "app.js"), encoding="utf-8").read()
    block = source.split("inline add / remove", 1)[1]
    assert "catch" in block and "form.submit()" in block
    assert "removeAttribute('data-inline')" in block, (
        "the fallback would re-enter the handler and loop")
