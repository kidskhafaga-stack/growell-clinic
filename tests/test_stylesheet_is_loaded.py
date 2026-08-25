"""A stylesheet that nothing linked.

Asked to make the عيادات counter look better. It turned out not to be a
styling problem: `app/static/css/app.css` was **never loaded by any page**.
Every rule in it — the عيادات cards, the patient and drug pickers, the live
counters — had never once applied.

Two things follow from that, and the second is the one that matters.

The cards rendered as plain lines of text because their stylesheet was not
there, which is exactly what was reported.

And `.lt-amber` / `.lt-red` are defined in that file. `app.js` has been adding
those classes every thirty seconds — deliberately, with a comment explaining
that only a *waiting family* may go red and never a doctor mid-consultation —
to classes no stylesheet defined. **The escalation that tells reception a
family has been waiting too long has been invisible the whole time.** Nobody
would report that: it looks identical to nobody having waited too long.

So the test is not "does the card look nice". It is that every stylesheet in
the folder is actually linked, and that the classes the JS toggles have
somewhere to land.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CSS_DIR = os.path.join(ROOT, "app/static/css")


def _linked_stylesheets():
    """Every css file the templates ask for."""
    found = set()
    for root, _dirs, files in os.walk(os.path.join(ROOT, "app/templates")):
        for name in files:
            if not name.endswith(".html"):
                continue
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                for match in re.findall(r"filename='css/([\w.-]+)'", fh.read()):
                    found.add(match)
    return found


def _css_files():
    return {n for n in os.listdir(CSS_DIR) if n.endswith(".css")}


def test_every_stylesheet_is_actually_linked(clinic):
    """The bug, as a rule rather than as one filename.

    A css file nobody links is not dead code that costs nothing — it is a
    screen that silently renders unstyled, and a set of classes the JS keeps
    toggling into a void.
    """
    stranded = _css_files() - _linked_stylesheets()

    assert not stranded, (
        f"these stylesheets exist and no template links them, so every rule "
        f"in them is inert: {sorted(stranded)}")


def test_the_page_really_asks_for_it(clinic):
    """Asserted through a rendered page, not the template source."""
    page = clinic["sign_in"]("boss").get("/appointments/",
                                         follow_redirects=True).data.decode()

    assert "css/app.css" in page, "the board does not load the component styles"
    assert "css/theme.css" in page


def test_the_escalation_classes_have_somewhere_to_land(clinic):
    """`app.js` toggles these every thirty seconds.

    Without a rule, a family waiting fifty minutes looks exactly like one
    waiting five — and no one would ever report it, because there is nothing
    to see.
    """
    css = ""
    for name in _css_files():
        with open(os.path.join(CSS_DIR, name), encoding="utf-8") as fh:
            css += fh.read()

    with open(os.path.join(ROOT, "app/static/js/app.js"), encoding="utf-8") as fh:
        js = fh.read()

    for cls in re.findall(r"classList\.toggle\('(lt-[\w-]+)'", js):
        assert f".{cls}" in css, \
            f"app.js toggles {cls} and no stylesheet defines it"


def test_the_clinic_cards_are_styled(clinic):
    """The reported symptom, pinned: the markup and the rules must agree.

    A renamed class on either side leaves the card unstyled again, and an
    unstyled card is not an error anybody sees in a log.
    """
    # The strip moved out of the board into a partial when the dashboard
    # needed the same cards. The claim is unchanged — markup and rules must
    # agree — so it follows the markup rather than staying where it was.
    with open(os.path.join(ROOT, "app/templates/_clinics_strip.html"),
              encoding="utf-8") as fh:
        markup = fh.read()
    with open(os.path.join(CSS_DIR, "app.css"), encoding="utf-8") as fh:
        css = fh.read()

    for cls in ("clinic-card", "cl-edge", "cl-orb", "cl-rail", "cl-pips"):
        assert cls in markup, f"the strip no longer uses .{cls}"
        assert f".{cls}" in css, f"nothing styles .{cls}"


def test_the_card_takes_its_state_from_the_timer(clinic):
    """One rule for "this wait is too long", in the place that already owned it.

    `app.js` decides when a wait is amber or red, and applies it only to a
    waiting family — never to a doctor mid-consultation. The card reads that
    decision rather than repeating the thresholds in CSS, so the two cannot
    drift apart.
    """
    with open(os.path.join(CSS_DIR, "app.css"), encoding="utf-8") as fh:
        css = fh.read()

    assert ".clinic-card:has(.lt-red)" in css, \
        "the card does not follow the escalation the timer already computes"
    assert not re.search(r"\.clinic-card[^{]*\{[^}]*\b(20|40)min\b", css), \
        "the thresholds were copied into CSS, where they will drift"


def test_motion_is_kept_for_the_thing_that_needs_somebody(clinic):
    """A tile that pulses all day is one nobody looks at by Thursday.

    The orb animates only for a red wait or an urgent child in the queue — a
    room simply in use is the normal state of a clinic, not an alarm.
    """
    with open(os.path.join(CSS_DIR, "app.css"), encoding="utf-8") as fh:
        css = fh.read()

    block = css[css.index("@keyframes cl-breathe"):]
    block = block[:block.index("\n.cl-alarm")]

    assert "infinite" in block, "the alarm pulse stops after a few seconds"
    assert ":has(.lt-red)" in block or "is-urgent" in block, \
        "the pulse is not tied to anything needing attention"
    # And plainly not on every busy card.
    assert ".clinic-card.is-busy .cl-orb.busy {" not in block.replace(" ", " "), \
        "every room in use pulses, which is every room, all day"
