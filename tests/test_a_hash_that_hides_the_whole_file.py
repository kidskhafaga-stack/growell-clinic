"""A redirect back to a section must land on a page that is still showing.

Reported after signing a consent: *"بعد ما بحفظ التوقيع مش بيرجع على نفس
الصفحة"*. It did come back to the same page. The page then hid all of itself,
which looks the same from the desk and is worse — a file that has just been
written to, showing nothing.

**Why.** The patient file is one page of Alpine tabs, and the tab is taken from
the URL fragment. Saving a consent redirects to `…/patients/<id>#consent`, and
`consent` is not a tab — it is a section *inside* the overview. Nothing matched,
every `x-show="tab==='…'"` was false at once, and the file rendered as a header
with an AI box under it.

The template already carried the fix for one instance of this, `#meds`, in an
``inside`` map written when the medicines block moved into the prescriptions
tab. Three more fragments were in the same state and nobody had noticed:
`#consent`, `#problems` and `#coverage`. A map that has to be kept in step by
hand is a map that will fall out of step, so the page now also falls back to the
overview for anything it does not recognise — a wrong tab costs a scroll, a
blank file costs trust.

This test is the half that can be checked without a browser, and it is the half
that would have caught it: every fragment the server redirects to has to be
either a tab or a section the map places. The fallback itself was checked in
Chromium — `#consent`, `#problems`, `#coverage` and a deliberate `#nonsense` all
render exactly one visible panel.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROFILE = os.path.join(ROOT, "app", "templates", "patients", "profile.html")
ROUTES = os.path.join(ROOT, "app", "blueprints", "patients", "routes.py")


def _template():
    with open(PROFILE, encoding="utf-8") as fh:
        return fh.read()


def _tab_keys():
    """The tab names the profile renders, from the `ns.tabs` tuples."""
    source = _template()
    start = source.index("{% set ns = namespace(tabs=[")
    end = source.index("{% for key, label, icon in ns.tabs %}")
    return set(re.findall(r"\('([a-z_]+)'\s*,", source[start:end]))


def _placed_sections():
    """The `inside` map: section name -> the tab that holds it."""
    source = _template()
    block = source[source.index("inside: {"):]
    block = block[:block.index("}") + 1]
    return dict(re.findall(r"([a-z_]+)\s*:\s*'([a-z_]+)'", block))


def _fragments_the_server_sends_people_to():
    """Every `#…` the patients blueprint redirects the browser to."""
    with open(ROUTES, encoding="utf-8") as fh:
        source = fh.read()
    return set(re.findall(r'patients\.view"[^)]*\)\s*\+\s*"#([a-z_]+)"', source))


def test_the_scan_finds_the_three_things_it_reads():
    """Guarding the guard: any of these coming back empty would make every
    assertion below vacuously true."""
    assert len(_tab_keys()) >= 8, _tab_keys()
    assert "overview" in _tab_keys()
    assert _placed_sections(), "the inside map was not found"
    assert len(_fragments_the_server_sends_people_to()) >= 5


def test_every_fragment_the_server_redirects_to_shows_something():
    """The bug, stated as a rule."""
    tabs = _tab_keys()
    placed = _placed_sections()
    lost = []
    for fragment in sorted(_fragments_the_server_sends_people_to()):
        if fragment in tabs:
            continue
        if placed.get(fragment) in tabs:
            continue
        lost.append(fragment)

    assert not lost, (
        "these are sections rather than tabs, and nothing places them in one, "
        "so a redirect to them renders the file with every panel hidden: "
        + ", ".join("#" + f for f in lost))


def test_the_four_that_were_wrong_are_named():
    """Pinned by name. `#meds` was fixed once and the other three were left,
    which is the argument for the fallback below as well as for the map."""
    placed = _placed_sections()
    assert placed.get("meds") == "prescriptions"
    assert placed.get("consent") == "overview"
    assert placed.get("problems") == "overview"
    assert placed.get("coverage") == "family"


def test_an_unknown_fragment_falls_back_instead_of_hiding_everything():
    """The half that stops the next one. A map kept by hand falls out of step;
    what must not happen when it does is a blank file."""
    source = _template()
    assert "this.known.includes(wanted) ? wanted : 'overview'" in source, \
        "an unrecognised fragment no longer falls back to the overview"
    # And `known` is read off the rendered buttons rather than listed again,
    # because which tabs exist depends on permissions and on this child.
    assert "querySelectorAll('[data-tab]')" in source
    assert 'data-tab="{{ key }}"' in source, \
        "the tab buttons no longer carry the attribute that list is built from"


def test_the_consent_row_uploads_with_a_button_and_not_a_bare_file_field(clinic):
    """*"الزرار ده شكله غريب"* — the browser's own grey "Choose File / No file
    chosen" in a row of the program's buttons. The control uploads the moment a
    file is picked, so the status text is never true for longer than a blink."""
    from app.models import Consent
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        clinic["db"].session.add(Consent(
            patient_id=clinic["ids"]["child"], consent_type="general",
            guardian_name="أم الطفل", guardian_relation="mother",
            statement="نص", signed_date=local_today()))
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)

    assert "input--pick" in page, "the file field is unstyled again"
    # Reachable as well as tidy: hiding the input behind a label would cost the
    # focus ring and the screen reader, so it keeps both.
    assert 'for="sigfile_' in page, "the file field lost its label"

    css = os.path.join(ROOT, "app", "static", "css", "theme.css")
    with open(css, encoding="utf-8") as fh:
        rules = fh.read()
    assert "::file-selector-button" in rules, \
        "nothing styles the browser's own file button any more"
