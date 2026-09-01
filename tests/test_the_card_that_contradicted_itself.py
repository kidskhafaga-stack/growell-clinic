"""One card, two answers.

Reported with a screenshot of the update tab. The status badge said **أحدث
إصدار** — you are on the latest version — while the sentence immediately
beside it said **فيه إصدار أجدد — شوف «الجديد» تحت**, there was a newer one,
look at "what's new" below. And there was no «الجديد» anywhere on the screen.

Three faults, one cause. The check updated exactly one sentence. The badge,
the notes and the block that tells you how to install it were all rendered by
the server when the page loaded, and never heard that the answer had changed —
so a check run at 3pm on a page opened at 9am could only ever contradict what
was already on it.

The endpoint had been returning the version and the notes the whole time. The
screen threw them away.

Not fixed by reloading the page, which would have been simpler: every tab on
this screen is one form, and somebody halfway through typing an API key on
another tab must not lose it for having pressed a button on this one.
"""
import pytest


@pytest.fixture
def screen(clinic):
    return clinic["sign_in"]("boss").get(
        "/settings/").get_data(as_text=True)


def _card(page):
    """The update tab only — the rest of the settings screen is not this."""
    start = page.index('id="update"')
    return page[start:page.index("</div>", page.index("update_check"))]


# ------------------------------------------------- the badge is not fixed ---
def test_the_badge_follows_the_live_answer(screen):
    """Both badges are rendered, and which shows is decided at read time.

    A server-rendered badge cannot be right after a check: it was written
    before the question was asked."""
    card = _card(screen)
    assert 'x-show="behind()"' in card
    assert 'x-show="!behind()"' in card


def test_the_badge_is_not_hard_coded_by_the_server(screen):
    """The old shape, and the exact bug. `{% if update_pending %}` around the
    badge means the page's first paint is its last word."""
    card = _card(screen)
    for line in card.splitlines():
        if "update.behind" in line or "update.current_short" in line:
            assert "x-show" in line, (
                "a status badge is still decided once, at page load: " + line)


# ------------------------- the section the sentence points at must exist ----
def test_what_is_new_is_rendered_and_shown_on_demand(screen):
    """«شوف «الجديد» تحت» has to be able to come true. It was a sentence
    pointing at nothing."""
    card = _card(screen)
    assert 'x-for="(line, i) in notes()"' in card
    assert "update.whats_new" not in card, "untranslated key on the screen"


def test_it_says_so_when_there_is_an_update_but_no_notes(screen):
    """GitHub can answer the version and not the commits. Silence there would
    look like the same missing section all over again."""
    card = _card(screen)
    assert 'x-show="behind() && !notes().length"' in card


# ------------------------------- and something to actually do about it ------
def test_the_install_block_appears_on_a_live_check(screen):
    """Announcing a new version with no way to act on it anywhere on the
    screen is the third half of the same bug."""
    card = _card(screen)
    assert 'class="update-do" x-show="behind()"' in card


# ------------------------------------------ what the check does with it -----
def test_the_check_keeps_the_version_and_the_notes(screen):
    """The endpoint has always returned both. This is the line that stopped
    them being discarded."""
    assert "this.live = { behind: true" in screen
    assert "notes: d.notes || []" in screen


def test_being_offline_does_not_overwrite_a_real_answer(screen):
    """A blip in the connection must not turn "there is an update" into
    "you are up to date"."""
    # Sliced from `check()` forward, not from the page — `this.busy = false`
    # appears in other components above this one, and an index taken on the
    # whole page produces a slice that runs backwards and matches nothing.
    start = screen.index("async check()")
    body = screen[start:start + screen[start:].index("this.busy = false;")]
    unreachable = body[body.index("unreachable"):]
    assert "this.live" not in unreachable, (
        "an unreachable check overwrites what a real one found")


# ------------------------------------------------------- and end to end -----
def test_a_check_that_finds_one_returns_what_the_card_needs(
        clinic, monkeypatch):
    """The contract the screen now depends on."""
    from app.utils import updates

    monkeypatch.setattr(updates, "installed_revision", lambda: "a" * 40)
    monkeypatch.setattr(updates, "pending", lambda: {
        "installed": "a" * 40, "latest": "b" * 40,
        "notes": ["A vaccine this clinic does not give"]})

    answer = clinic["sign_in"]("boss").post("/settings/update/check")
    body = answer.get_json()
    assert body["ok"] and body["behind"]
    assert body["latest"] == "b" * 40
    assert body["notes"] == ["A vaccine this clinic does not give"]
