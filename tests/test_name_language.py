"""One person, one name, whatever screen you are on.

Reported: the visit screen showed the guardian's Arabic name while the patient
file beside it showed the English one. Two code paths for the same fact — one
language-aware, one not:

    consent.py          guardian.full_name            # always Arabic
    patients/profile    g.display_name(current_lang)  # English when English

Every model here already has ``display_name(lang)``. Reading ``full_name``
directly is not a shortcut to it, it is a different answer.

And this one is not cosmetic in the way it looks. The guardian's name goes onto
a **signed consent**. Which name a document carries is not a formatting detail,
and a file where the same person appears under two names is a file somebody has
to explain later.

The last test is the one that matters most: it walks the templates and refuses
the pattern anywhere it would be *displayed*, because this is a class of bug
rather than a place. Editing forms are exempt on purpose — an input bound to
the Arabic column must show the Arabic column, or saving the form would
overwrite the Arabic name with the English one.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def guarded(clinic):
    """A child whose guardian has a name in both languages."""
    from app.models import Family, Parent, Patient

    with clinic["app"].app_context():
        fam = Family(family_name="عائلة قنديل")
        clinic["db"].session.add(fam)
        clinic["db"].session.flush()
        clinic["db"].session.add(Parent(
            family_id=fam.id, full_name="محمد قنديل",
            full_name_en="Mohamed Kandil", relation="father",
            national_id="28001011234567", is_primary_contact=True))
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.family_id = fam.id
        clinic["db"].session.commit()
    return clinic


def _guardian(guarded, lang=None):
    from app.models import Patient
    from app.utils.consent import default_guardian

    with guarded["app"].app_context():
        child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
        return default_guardian(child, lang)


# ------------------------------------------------------- the guardian ------
def test_the_arabic_name_is_offered_in_arabic(guarded):
    assert _guardian(guarded, "ar")["name"] == "محمد قنديل"


def test_the_english_name_is_offered_in_english(guarded):
    """The reported mismatch: this used to give the Arabic name while the
    patient file gave the English one."""
    assert _guardian(guarded, "en")["name"] == "Mohamed Kandil"


def test_it_matches_what_the_patient_file_would_show(guarded):
    """Stated as the rule rather than the value: the two paths have to agree,
    whatever the answer is."""
    from app.models import Patient

    for lang in ("ar", "en"):
        with guarded["app"].app_context():
            child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
            expected = child.primary_guardian.display_name(lang)
        assert _guardian(guarded, lang)["name"] == expected


def test_a_guardian_with_no_english_name_falls_back(guarded):
    """Most guardians will only ever have the Arabic name. English must show
    that rather than a blank."""
    from app.models import Patient

    with guarded["app"].app_context():
        child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
        child.primary_guardian.full_name_en = None
        guarded["db"].session.commit()
    assert _guardian(guarded, "en")["name"] == "محمد قنديل"


def test_a_child_with_no_guardian_gives_blanks_not_an_error(guarded):
    from app.models import Patient

    with guarded["app"].app_context():
        child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
        child.family_id = None
        guarded["db"].session.commit()
    assert _guardian(guarded, "ar") == {"name": "", "relation": "", "id_no": ""}


def test_the_rest_of_the_guardian_is_untouched(guarded):
    """Only the name was language-dependent; a national id has no language and
    must not have acquired one."""
    row = _guardian(guarded, "en")
    assert row["relation"] == "father"
    assert row["id_no"] == "28001011234567"


def test_no_language_asked_for_uses_the_pages_own(guarded):
    """Callers that have no opinion get the same answer as the page around
    them, rather than a hard-coded Arabic."""
    from app.models import Patient
    from app.utils.consent import default_guardian

    with guarded["app"].test_request_context("/?lang=en"):
        from flask import g

        g.lang = "en"
        child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
        assert default_guardian(child)["name"] == "Mohamed Kandil"


# ------------------------------------------------- on the screen itself ----
# A correction to an earlier note in this file, which claimed the consent block
# only renders when a visit "calls for consent" and that an end-to-end test
# could not prove anything. Both halves were wrong: `needed_for_visit` always
# returns at least a general consent, and the block is hidden with Alpine's
# `x-show`, which is CSS — the HTML is rendered either way. The real reason the
# first attempt found nothing is duller: `/visits/<id>` renders `view.html`,
# and the consent form lives in `record.html`, behind `/visits/<id>/record`.
def _record_page(guarded, lang="ar"):
    doc = guarded["sign_in"]("doc")
    if lang != "ar":
        doc.get(f"/lang/{lang}", follow_redirects=True)
    return doc.get(f"/visits/{guarded['ids']['visit']}/record").get_data(
        as_text=True)


def test_the_visit_screen_shows_the_arabic_name_in_arabic(guarded):
    assert 'value="محمد قنديل"' in _record_page(guarded, "ar")


def test_the_visit_screen_shows_the_english_name_in_english(guarded):
    """The reported bug, on the reported screen. Before the fix this box held
    the Arabic name while the patient file beside it held the English one."""
    assert 'value="Mohamed Kandil"' in _record_page(guarded, "en")


def test_the_two_screens_agree_in_english(guarded):
    """The actual complaint was not either name on its own — it was that the
    two screens disagreed. So assert on the pair."""
    from app.models import Patient

    with guarded["app"].app_context():
        child = guarded["db"].session.get(Patient, guarded["ids"]["child"])
        expected = child.primary_guardian.display_name("en")

    doc = guarded["sign_in"]("doc")
    doc.get("/lang/en", follow_redirects=True)
    visit = doc.get(f"/visits/{guarded['ids']['visit']}/record").get_data(
        as_text=True)
    profile = doc.get(f"/patients/{guarded['ids']['child']}").get_data(
        as_text=True)
    assert f'value="{expected}"' in visit
    assert expected in profile


# --------------------------------------------------- the class of bug ------
# Rendering a raw name column for display. `name="…"` and `value="…"` inside a
# form are exempt: an input bound to the Arabic column must show the Arabic
# column, or saving would overwrite it with the English one.
_DISPLAYED = re.compile(r"\{\{\s*[\w.]+\.full_name\s*(\||\}\})")


def _templates():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".html"):
                yield os.path.join(folder, name)


def test_no_template_displays_a_raw_name_column():
    """The rule, across every template — because this is a class of bug rather
    than a place, and the next screen to get it wrong has not been written yet.

    If a hit here really is an edit field, it belongs inside `value="…"`, which
    this deliberately does not match.
    """
    offenders = []
    for path in _templates():
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, start=1):
                if 'value="' in line or "name=\"full_name\"" in line:
                    continue                     # binding, not displaying
                if _DISPLAYED.search(line):
                    offenders.append(f"{os.path.basename(path)}:{number}")
    assert not offenders, (
        "these print a name column directly, which ignores the interface "
        "language — use display_name(current_lang): " + ", ".join(offenders))
