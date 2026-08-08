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
