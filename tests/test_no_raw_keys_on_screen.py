"""Every phrase a template asks for must exist, in both languages.

Found by opening the program in a browser and looking at it: the medicines
tab of the visit screen — the doctor's main working screen — had two form
labels reading **``rx.dose``** and **``rx.frequency``**. Not a wrong
translation; the raw key, printed at the user, in Arabic and in English
alike, because ``translate()`` falls back to the key when it finds nothing.

That fallback is right — a screen with a key on it is better than a screen
that crashes — but it means a missing phrase is invisible to every test in
this suite and perfectly visible to the clinic. Seven more were in the same
state across the program.

So: read the templates, take every literal key they ask for, and require it
of both locale files. Keys built by concatenation (``t('mv_' ~ kind)``) are
skipped — they cannot be resolved without running the code, and pretending
otherwise would make this test either noisy or wrong.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES = os.path.join(ROOT, "app", "templates")

# ``t('a.b')`` or ``t('a.b', name=…)`` — a literal, closed immediately by a
# comma or a bracket. Anything followed by ``~`` is built at render time.
LITERAL_KEY = re.compile(r"""\bt\(\s*['"]([a-zA-Z0-9_.]+)['"]\s*[),]""")


def _locale(lang):
    with open(os.path.join(ROOT, "app", "i18n", "locales", f"{lang}.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _has(data, key):
    node = data
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return isinstance(node, str)


def _keys_in_templates():
    found = {}
    for folder, _dirs, files in os.walk(TEMPLATES):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                for key in LITERAL_KEY.findall(fh.read()):
                    found.setdefault(key, os.path.relpath(path, ROOT))
    return found


def test_no_template_asks_for_a_phrase_that_does_not_exist():
    """The one that would have caught ``rx.dose``."""
    missing = []
    locales = {lang: _locale(lang) for lang in ("ar", "en")}
    for key, where in sorted(_keys_in_templates().items()):
        for lang, data in locales.items():
            if not _has(data, key):
                missing.append(f"{lang}.{key} ({where})")

    assert not missing, (
        "these templates print the key itself at the user, because nothing "
        "answers to it: " + ", ".join(missing))


def test_the_two_labels_that_were_found_by_looking(clinic):
    """Pinned by name and by screen. Cheap, and the next person to delete them
    will be told which screen they broke."""
    page = clinic["sign_in"]("doc").get(
        f"/visits/{clinic['ids']['visit']}/record").data.decode()
    assert "rx.dose" not in page
    assert "rx.frequency" not in page


def test_the_scan_would_notice_a_missing_key():
    """Guarding the guard: a regex that matched nothing would make this file
    a green light that means nothing at all."""
    keys = _keys_in_templates()
    assert len(keys) > 500, f"the scan only found {len(keys)} keys"
    assert "rx.dose" in keys


# ``t('a.b.' ~ something)`` — the leaf is built at render time, but everything
# before the last dot is a literal and has to exist as a section.
BUILT_PREFIX = re.compile(r"""\bt\(\s*['"]([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*)\.['"]\s*~""")


def _sections_in_templates():
    found = {}
    for folder, _dirs, files in os.walk(TEMPLATES):
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                for section in BUILT_PREFIX.findall(fh.read()):
                    found.setdefault(section, os.path.relpath(path, ROOT))
    return found


def _section_exists(data, key):
    node = data
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return isinstance(node, dict)


def test_a_key_built_at_render_time_still_has_a_section_to_build_it_from():
    """The hole the test above leaves open, and something did fall through it.

    The patient file printed **``parent_relations.father``** at the user, in
    the consent row and again in the relationship dropdown, because the
    section in both locale files is called ``relations``. The check above
    could not see it: `t('parent_relations.' ~ cs.guardian_relation)` is built
    at render time and is skipped, correctly, since nothing here can know
    which leaf it will end up asking for.

    But it can know the **prefix**, which is a literal sitting right there in
    the template — and a prefix that names no section cannot produce a
    translation for any value of the variable. That is not a guess about one
    key; it is every key that expression will ever build, wrong at once.
    """
    missing = []
    locales = {lang: _locale(lang) for lang in ("ar", "en")}
    for section, where in sorted(_sections_in_templates().items()):
        for lang, data in locales.items():
            if not _section_exists(data, section):
                missing.append(f"{lang}.{section}.* ({where})")

    assert not missing, (
        "these templates build a key from a prefix that names no section, so "
        "every value they render prints the key itself: " + ", ".join(missing))


def test_the_relationship_is_named_and_not_keyed(clinic):
    """Pinned to the screen it was seen on, with a consent that has one."""
    from app.models import Consent
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        clinic["db"].session.add(Consent(
            patient_id=clinic["ids"]["child"], consent_type="general",
            guardian_name="أبو الطفل", guardian_relation="father",
            statement="نص", signed_date=local_today()))
        clinic["db"].session.commit()

    page = clinic["sign_in"]("boss").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "parent_relations" not in page
    assert "الأب" in page
