"""Choosing a drug: one list, and one that can actually be read.

Reported: *"the drug search looks strange and it's hard to choose"*. Three
faults sat behind that, and only the third is cosmetic.

**A field that was never sent.** The prescription writer printed
``'(' + s.strength + ') ' + s.generic`` on every row, and its endpoint did not
return ``strength`` at all. ``undefined`` is falsy, ``s.form`` was not, so the
condition took the branch that prints the brackets: every row read
**"() باراسيتامول"**. That is the "strange look", and no amount of reading the
Python would have found it — the server was not the one printing it.

**A stylesheet in another file.** The visit room's list used the classes
``patient-results`` / ``patient-result``, whose CSS was written inside
`appointments/form.html`. So in the consulting room the drug list rendered with
no background, no border and no shadow: bare buttons over whatever was beneath
them. Each file was individually fine.

**And two endpoints for one question.** The visit room's returned the Arabic
name, the strength and the ingredient; the prescription writer's returned the
Latin trade name and neither of the others. Same question, two answers,
depending on which screen the doctor was standing on.

What made it *hard to choose* rather than merely ugly: nothing distinguished
two rows of the same brand at different strengths, the order was alphabetical
so an exact match landed wherever the alphabet put it, there was no keyboard —
mouse only, for every line of a prescription — and a search matching nothing
showed an empty box, which looks the same as still loading and the same as
broken.

The last of those is the one that could hurt somebody: with no guard, a slow
reply for "para" lands after "paracetamol" and repaints the list. On a list
screen you read the wrong rows. Here you *click* one.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def pharmacy(clinic):
    """A shelf with the traps on it: one brand at three strengths, an Arabic
    name, a name that merely contains the search text, and an ingredient no
    brand on file carries."""
    from app.models import Drug, GenericDrug

    with clinic["app"].app_context():
        para = GenericDrug(name_ar="باراسيتامول", name_en="Paracetamol",
                           is_active=True)
        lonely = GenericDrug(name_ar="أزيثرومايسين", name_en="Azithromycin",
                             is_active=True)
        clinic["db"].session.add_all([para, lonely])
        clinic["db"].session.flush()

        clinic["db"].session.add_all([
            Drug(trade_name="Panadol", trade_name_ar="بانادول",
                 generic_name="Paracetamol", generic_id=para.id,
                 strength="120 mg/5 ml", form="شراب", is_active=True,
                 default_dose="5 ml", default_frequency="كل 6 ساعات"),
            Drug(trade_name="Panadol", trade_name_ar="بانادول",
                 generic_name="Paracetamol", generic_id=para.id,
                 strength="250 mg/5 ml", form="شراب", is_active=True),
            Drug(trade_name="Panadol Extra", trade_name_ar="بانادول إكسترا",
                 generic_name="Paracetamol", generic_id=para.id,
                 strength="500 mg", form="أقراص", is_active=True),
            # Contains "panadol" nowhere — it matches on the ingredient only.
            Drug(trade_name="Adol", trade_name_ar="أدول",
                 generic_name="Paracetamol", generic_id=para.id,
                 strength="125 mg", form="لبوس", is_active=True),
            Drug(trade_name="Panadol Old", trade_name_ar="بانادول قديم",
                 generic_name="Paracetamol", strength="100 mg",
                 is_active=False),
        ])
        clinic["db"].session.commit()
    return clinic


def _search(app, q, **kw):
    from app.utils.drug_search import search_drugs

    with app.test_request_context("/"):
        return search_drugs(q, **kw)


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ================================================= the field that wasn't sent
def test_the_search_returns_the_strength_the_screen_prints(pharmacy):
    """The reported bug at its source. The template printed s.strength and the
    endpoint never sent it, so every row showed an empty pair of brackets."""
    rows = _search(pharmacy["app"], "panadol")
    assert rows
    assert all("strength" in r for r in rows)
    assert any(r["strength"] for r in rows)


def test_the_prescription_writer_no_longer_prints_empty_brackets(pharmacy):
    """Belt and braces on the template itself: the expression that produced
    "()" is gone, not merely fed better data."""
    body = _read("app", "templates", "prescriptions", "new.html")
    assert "'('+(s.strength||'')+') '" not in body
    assert "s.strength||s.form?" not in body


def test_both_screens_get_the_same_answer(pharmacy):
    """The two endpoints were hand-written separately and drifted. A doctor
    should not get a different list for standing on a different screen."""
    rx = pharmacy["sign_in"]("doc")
    a = rx.get("/prescriptions/drugs/search", query_string={"q": "panadol"})
    b = rx.get("/visits/drugs/search", query_string={"q": "panadol"})
    assert a.status_code == b.status_code == 200
    first_a, first_b = a.get_json(), b.get_json()
    assert first_a and first_b
    assert set(first_a[0]) == set(first_b[0]), "the payloads drifted again"


# ========================================================== hard to choose ==
def test_two_strengths_of_one_brand_are_told_apart(pharmacy):
    """Three rows reading "Panadol" and nothing else is a choice made blind."""
    rows = [r for r in _search(pharmacy["app"], "بانادول")
            if r["trade"].startswith("بانادول") and not r["trade"].endswith("إكسترا")]
    strengths = {r["strength"] for r in rows}
    assert len(strengths) >= 2, "the rows are indistinguishable"


def test_the_exact_match_comes_first(pharmacy):
    """Alphabetical order put what you typed wherever the alphabet happened to
    place it — with "Panadol Extra" landing above "Panadol"."""
    rows = _search(pharmacy["app"], "بانادول")
    assert rows[0]["trade"] == "بانادول"


def test_a_starts_with_match_beats_a_contains_match(pharmacy):
    rows = _search(pharmacy["app"], "panadol", lang="en")
    names = [r["latin"] for r in rows if r["latin"]]
    assert names[0].lower().startswith("panadol")


def test_the_arabic_name_is_what_comes_back_in_arabic(pharmacy):
    """It is what the parent reads off the box and what the doctor types. The
    prescription writer searched it and then showed the Latin name, so you
    could not tell which row was the one you had typed."""
    rows = _search(pharmacy["app"], "بانادول", lang="ar")
    assert rows[0]["trade"] == "بانادول"
    assert rows[0]["alt"] == "Panadol", "the other spelling is gone"


def test_the_picked_name_carries_the_strength(pharmacy):
    """"Panadol" on its own is not a prescription — and it is the only thing
    that tells the 120 from the 250 once the list has closed."""
    rows = _search(pharmacy["app"], "بانادول")
    assert any(r["strength"] and r["strength"] in r["name"] for r in rows)


def test_an_ingredient_with_no_brand_is_still_offered(pharmacy):
    """The visit room did this and the prescription writer did not, so a drug
    the clinic has never stocked was writable on one screen only."""
    rows = _search(pharmacy["app"], "أزيثرو")
    assert any(r.get("is_ingredient") for r in rows)


def test_an_inactive_drug_is_not_offered(pharmacy):
    rows = _search(pharmacy["app"], "بانادول")
    assert not any("قديم" in r["trade"] for r in rows)


def test_an_empty_search_asks_for_nothing(pharmacy):
    assert _search(pharmacy["app"], "") == []
    assert _search(pharmacy["app"], "   ") == []


def test_the_limit_is_respected(pharmacy):
    rows = _search(pharmacy["app"], "بانادول", limit=2, include_generics=False)
    assert len(rows) == 2


def test_ranking_never_drops_the_exact_match_off_the_end(pharmacy):
    """The database orders alphabetically and the ranking happens after, so
    cutting at the limit before ranking would throw the best answer away."""
    rows = _search(pharmacy["app"], "بانادول", limit=1, include_generics=False)
    assert rows[0]["trade"] == "بانادول"


# ================================================== the list you look at ====
def test_the_list_is_styled_where_every_screen_can_see_it(pharmacy):
    """The visit room used class names whose CSS lived inside another
    template, so its drug list had no background at all. Each file read fine
    on its own — which is why nobody found it by reading one."""
    css = _read("app", "static", "css", "app.css")
    for rule in (".gc-picker", ".gc-picker-item", ".gc-picker-empty"):
        assert rule in css, rule


def test_the_list_follows_the_theme(pharmacy):
    """The old hover handler wrote background='#fff' onto the row, so in dark
    mode it went white under white text."""
    css = _read("app", "static", "css", "app.css")
    block = css[css.index(".gc-picker {"):]
    assert "var(--card" in block and "var(--line" in block
    for screen in ("prescriptions/new.html", "visits/record.html"):
        body = _read("app", "templates", *screen.split("/"))
        assert "$el.style.background='#fff'" not in body


def test_both_screens_render_the_same_list(pharmacy):
    """One macro, so the two cannot drift into three states of repair again."""
    for screen in ("prescriptions/new.html", "visits/record.html"):
        body = _read("app", "templates", *screen.split("/"))
        assert 'from "_picker.html" import drug_list' in body
        assert "drug_list(" in body


def test_a_search_that_matches_nothing_says_so(pharmacy):
    """An empty box looks the same as still loading and the same as broken."""
    macro = _read("app", "templates", "_picker.html")
    assert "gc-picker-empty" in macro
    assert "searched" in macro, "the empty state must wait for a reply"


# ========================================================== the keyboard ====
@pytest.mark.parametrize("screen", ["prescriptions/new.html", "visits/record.html"])
def test_the_list_can_be_driven_from_the_keyboard(pharmacy, screen):
    """Mouse-only meant reaching for it on every line of a prescription."""
    body = _read("app", "templates", *screen.split("/"))
    for key in ("keydown.arrow-down", "keydown.arrow-up",
                "keydown.enter", "keydown.escape"):
        assert key in body, f"{screen}: {key}"


@pytest.mark.parametrize("screen", ["prescriptions/new.html", "visits/record.html"])
def test_the_highlighted_row_is_announced(pharmacy, screen):
    body = _read("app", "templates", *screen.split("/"))
    assert 'role="combobox"' in body
    assert "aria-expanded" in body
    macro = _read("app", "templates", "_picker.html")
    assert 'role="listbox"' in macro and 'role="option"' in macro
    assert "aria-selected" in macro


# =================================================== the correctness rule ===
def test_a_stale_reply_can_never_paint_over_a_newer_one():
    """The one rule that is not taste. Type "para" then "paracetamol": if the
    first reply is slower it lands last and the list shows the wrong drugs —
    and here you then *click* one."""
    js = _read("app", "static", "js", "app.js")
    block = js[js.index("window.gcPicker"):]
    assert "_seq" in block and "mine !== this._seq" in block


def test_an_overtaken_request_is_abandoned():
    js = _read("app", "static", "js", "app.js")
    block = js[js.index("window.gcPicker"):]
    assert "AbortController" in block and ".abort()" in block


def test_an_aborted_request_does_not_blank_the_list():
    """Aborting is normal here — it happens on every keystroke. Treating it as
    a failure would clear the list the newer request is about to fill."""
    js = _read("app", "static", "js", "app.js")
    block = js[js.index("window.gcPicker"):]
    assert 'err.name === "AbortError"' in block


def test_the_picker_never_writes_to_the_screens_data():
    """It used to be handed a callback that closed over the caller's object —
    which is the *raw* object, not Alpine's proxy. The drug would be chosen
    and the field would sit there empty, on a screen where an empty dose field
    is not a cosmetic problem. It hands the row back instead."""
    js = _read("app", "static", "js", "app.js")
    block = js[js.index("window.gcPicker"):]
    assert "onPick" not in block
    assert "take()" in block


# ======================================================= still works ========
def test_the_prescription_screen_still_opens(pharmacy):
    doc = pharmacy["sign_in"]("doc")
    assert doc.get("/prescriptions/new").status_code == 200


def test_the_visit_screen_still_opens(pharmacy):
    doc = pharmacy["sign_in"]("doc")
    visit_id = pharmacy["ids"]["visit"]
    assert doc.get(f"/visits/{visit_id}/record").status_code == 200


def test_the_search_endpoints_still_answer(pharmacy):
    doc = pharmacy["sign_in"]("doc")
    for url in ("/prescriptions/drugs/search", "/visits/drugs/search"):
        reply = doc.get(url, query_string={"q": "بانادول"})
        assert reply.status_code == 200
        assert reply.get_json()
        assert doc.get(url, query_string={"q": ""}).get_json() == []


# =============================================== the other lists on the screen
def test_the_diagnosis_search_answers_in_one_shape(pharmacy):
    """The same drift, one screen over: the visit room's ICD search wrapped
    its list in {"results": [...]} and the prescription writer's returned the
    list. One question, two shapes, and a picker that has to know which screen
    it is on is a picker that will be wrong on the third.

    **The third screen arrived** — the patient file's problem list, which had
    no search at all — and the two shapes were made one by making the two
    endpoints one. So this now asserts what it always wanted: a single
    address, answering with a bare list. Two shapes are no longer something a
    test has to watch for; they are no longer possible.
    """
    doc = pharmacy["sign_in"]("doc")
    reply = doc.get("/icd-search", query_string={"q": "fever"})

    assert reply.status_code == 200
    assert isinstance(reply.get_json(), list)

    # And the two it replaced are gone rather than quietly still there.
    for retired in ("/visits/icd", "/prescriptions/icd/search"):
        assert doc.get(retired, query_string={"q": "fever"}).status_code == 404, \
            f"{retired} still answers; there are two shapes again"


def test_no_dropdown_on_these_screens_is_painted_white(pharmacy):
    """`background:#fff` on a panel is invisible in light mode and unreadable
    in dark — white under light text. Every list on these two screens goes
    through the themed classes now."""
    for screen in ("prescriptions/new.html", "visits/record.html"):
        body = _read("app", "templates", *screen.split("/"))
        # `#fff` as a whole colour, not any colour starting with it: the
        # warning banners on these screens are legitimately #fff8e6.
        assert not re.search(r"background:\s*#fff\b(?![0-9a-fA-F])", body), screen
        assert "style.background='#fff'" not in body, screen
        assert ".icd-dropdown" not in body, screen


@pytest.mark.parametrize("screen", ["prescriptions/new.html", "visits/record.html"])
def test_every_list_on_the_screen_behaves_the_same(pharmacy, screen):
    """Drugs, investigations and diagnoses sit next to each other. Fixing one
    and leaving the others is how somebody learns that arrow keys work here
    and not there — which is worse than none of them working."""
    body = _read("app", "templates", *screen.split("/"))
    assert body.count("gc-picker") >= 2

    # The banned thing is a hand-rolled **type-ahead**: an Alpine component
    # holding its own `suggestions: []` beside its own `open`, filled as
    # somebody types, with no keyboard, no debounce and no guard against a
    # slow reply for "para" landing after "paracetamol" and repainting the
    # list under a doctor who is about to click a row.
    #
    # This used to be asserted as the word "suggestions" appearing anywhere in
    # the file, which is a proxy and not the pattern. It caught the diagnosis
    # suggestion panel, which is none of those things: one request, fired by a
    # button that disables itself while it is in flight, rendering a short list
    # of plain <button>s that Tab and Enter already reach. There is no typing
    # to race and no row to repaint under a cursor.
    #
    # So the two markers of the real pattern are checked instead.
    assert not re.search(r"x-for=\"[^\"]*\bin suggestions\b", body), \
        "a hand-rolled type-ahead list is still in here"
    assert not re.search(r"\bsuggestions:\s*\[\]", body), \
        "a component still holds its own type-ahead state"
