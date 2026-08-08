"""Arabic shows Arabic, English shows English.

*"أنا عايز العربي كله يظهر عربي، الإنجليزي يظهر إنجليزي."*

The clinic was seeing both at once, and the cause was not what it looks like.
The two locale files are exactly in step — 4,293 phrases each, not one missing
on either side — so nothing was falling back.

**A doctor's account was created in English.** Whatever language the clinic
runs in, ``role == "doctor"`` set the interface to ``en``, so a doctor signed
in to an English program wrapped around Arabic names, Arabic complaints and
Arabic drug notes. Reception and the accountant saw Arabic; the doctor did
not; and the clinic saw a program that could not make up its mind.

**And one label on the paper never went through the translator at all** —
"License:" was written into the prescription in English, so it printed that
way on an Arabic page, and on the copy sent to the family.

What is *not* a bug, and is checked here so nobody "fixes" it: a child called
"عمر" is called عمر on the English screen too. The program translates its own
words, never the clinic's.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARABIC = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")


def _locale(lang):
    with open(os.path.join(ROOT, "app", "i18n", "locales", f"{lang}.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


def _flat(data, prefix=""):
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _flat(value, prefix + key + ".")
        elif isinstance(value, str):
            yield prefix + key, value


# ============================================== nobody is forced =============
def test_a_new_doctor_is_not_put_into_english(clinic):
    """The cause. A clinic running in Arabic that hires a doctor should not
    have to discover this setting to get an Arabic screen."""
    from app.models import User

    clinic["sign_in"]("boss").post("/users/new", data={
        "username": "newdoc", "full_name": "د. سامي", "role": "doctor",
        "password": "secret123", "is_active": "1", "language": "",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        doctor = User.query.filter_by(username="newdoc").first()
        assert doctor is not None, "the doctor was not created"
        assert doctor.language is None, \
            "a doctor was created in English without anybody choosing it"


def test_a_doctor_who_wants_english_can_still_have_it(clinic):
    """Removing the default must not remove the choice: plenty of doctors
    read medicine in English and want the screen to match."""
    from app.models import User

    clinic["sign_in"]("boss").post("/users/new", data={
        "username": "engdoc", "full_name": "د. ليلى", "role": "doctor",
        "password": "secret123", "is_active": "1", "language": "en",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        assert User.query.filter_by(username="engdoc").first().language == "en"


# ============================================== the two files agree ==========
def test_neither_language_is_missing_a_phrase():
    """A phrase that exists in one file and not the other is English leaking
    into an Arabic screen — silently, because the fallback is English."""
    ar = dict(_flat(_locale("ar")))
    en = dict(_flat(_locale("en")))

    assert not (set(en) - set(ar)), \
        "English-only phrases (they show in English on the Arabic screen): " \
        + ", ".join(sorted(set(en) - set(ar))[:20])
    assert not (set(ar) - set(en)), \
        "Arabic-only phrases: " + ", ".join(sorted(set(ar) - set(en))[:20])


def test_the_arabic_file_is_actually_in_arabic():
    """A phrase filled in with the English text passes every other check and
    still reads as English on an Arabic screen.

    The allowance is for words that have no Arabic: USB, CSV, an API. They are
    listed rather than pattern-matched, so adding one is a decision somebody
    makes on purpose.
    """
    untranslatable = {
        "growth.zscore", "vtype.mRNA", "settings.wa_cloud_api",
        "settings.wa_wapilot", "settings.chip_en_ph",
        "connection_types.usb", "connection_types.wifi",
        "import_modes.csv", "import_modes.xml", "import_modes.hl7",
        "import_modes.sdk", "import_modes.api", "audit.ip",
    }
    english = []
    for key, value in _flat(_locale("ar")):
        if key in untranslatable:
            continue
        if LATIN.search(value) and not ARABIC.search(value):
            english.append(f"{key} = {value!r}")

    assert not english, ("these are English on the Arabic screen: "
                         + ", ".join(english))


# ============================================== the paper ====================
def test_the_prescription_says_licence_in_the_page_language(clinic):
    """It printed "License:" on an Arabic prescription, and on the copy the
    family opens."""
    with open(os.path.join(ROOT, "app", "templates", "prescriptions",
                           "_paper.html"), encoding="utf-8") as fh:
        source = fh.read()

    assert "License:" not in source
    assert "t('rx.license')" in source


# ============================================== what must not change =========
def test_the_clinics_own_words_are_left_alone(clinic):
    """A child called "عمر" is called عمر in English too. The program
    translates its own words and never the clinic's — a screen that
    transliterated a patient's name would be worse than a mixed one."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.full_name = "عمر محمد"
        patient.full_name_en = None
        db.session.commit()
        assert patient.display_name("en") == "عمر محمد"
        assert patient.display_name("ar") == "عمر محمد"


def test_an_english_name_is_used_when_the_clinic_wrote_one(clinic):
    """And where the clinic *did* write both, each screen gets its own."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        patient = db.session.get(Patient, clinic["ids"]["child"])
        patient.full_name = "عمر محمد"
        patient.full_name_en = "Omar Mohamed"
        db.session.commit()
        assert patient.display_name("en") == "Omar Mohamed"
        assert patient.display_name("ar") == "عمر محمد"
