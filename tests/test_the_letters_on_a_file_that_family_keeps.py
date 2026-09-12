"""A file number carries a clinic's initials — and it carried the wrong ones.

``GC-000123``. ``GC`` is Growell Clinic: one customer. Every other copy of
the program handed out file numbers with that clinic's initials on them, and
nobody caught it, because a file number is not read — it is quoted down a
phone and copied onto a card. The letters now come from the name of the
clinic the copy is installed for.

**The rule this whole file exists to hold: a number already issued never
changes.** It is on a card in a mother's handbag, on a folder in a cupboard,
on last January's lab report. So the derivation is only ever a *default*:

* before the first number, the letters follow the clinic's name
* after it, the **numbers already issued** answer instead, so renaming the
  clinic changes nothing

Two mistakes are what most of these tests are actually for, both of them
possible readings of "make it take the clinic's name":

* **recomputing on every allocation** — rename the clinic in March and
  April's files come out with new letters and a sequence restarting at 1,
  while March's keep theirs. Two series, silently.
* **moving a prefix somebody typed** — an admin who deliberately set ``MK``
  loses it the next time the clinic name is saved.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """An empty clinic with a name and no patients — the state before the
    first file number exists, where every derivation is still allowed."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Setting
        Setting.set("clinic_name", "Sunrise Medical Centre")
        Setting.set("clinic_name_ar", "")
        db.session.commit()
    return {"app": app, "db": db}


def _add(app, db, number):
    from app.models import Patient
    with app.app_context():
        db.session.add(Patient(patient_number=number, full_name="طفل",
                               date_of_birth=date(2024, 1, 1), gender="male"))
        db.session.commit()


# --------------------------------------------------------- the derivation --
@pytest.mark.parametrize("name,expected", [
    ("Sunrise Medical Centre", "SM"),      # "Centre" is the third word, unused
    ("Growell Clinic", "GC"),              # the old hard-coded default — but
                                           # now because it is *theirs*
    ("New Cairo Paediatric Centre", "NCP"),
    ("PediaPro", "PP"),                    # one word, two capitals: the join
    ("Growell", "GR"),                     # one word, one capital: two letters
])
def test_a_latin_name_gives_its_own_letters(clinic, name, expected):
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.initials(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("عيادة الأطفال", "AT"),               # عيادة dropped, ال dropped
    ("مركز جرو ويل الطبي", "GW"),
    ("د. أحمد سمير", "AS"),                # the title is not an initial
    ("مستشفى الشفاء", "SF"),
    # **Caught by measurement.** Every Arabic case above reaches the
    # single-word branch, which strips «ال» in its own line — so leaving the
    # article in on the *multi*-word path changed nothing any test could see.
    # This clinic is half the paediatric clinics in the country, and the
    # letters it wants are of نور and أطفال, not of «ال» and «لل».
    ("مركز النور للأطفال", "NA"),
])
def test_an_arabic_name_gives_latin_letters(clinic, name, expected):
    """A file number gets printed, dictated and sometimes barcoded. Letters
    that change direction halfway through are worse than the wrong letters."""
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.initials(name) == expected


@pytest.mark.parametrize("word,bare", [
    ("الأطفال", "أطفال"),
    ("للأطفال", "أطفال"),
    ("نور", "نور"),
    # **The floor.** «ال» alone is all somebody typed; stripping it leaves
    # nothing, and a word stripped to nothing yields no letter at all — so
    # the name would silently contribute none.
    ("ال", "ال"),
    ("لل", "لل"),
])
def test_stripping_never_leaves_a_word_with_nothing_in_it(clinic, word, bare):
    from app.utils.numbering import _bare
    assert _bare(word) == bare


def test_a_name_that_is_only_the_kind_of_place_still_gives_its_own_letters(clinic):
    """«عيادة» alone is all the clinic gave us. Dropping every word and
    falling back to the program's initials would be the old bug again, just
    with a different two letters."""
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.initials("عيادة") == "AY"


def test_a_long_name_stops_at_three_letters(clinic):
    """**Caught by measurement.** No name in this file had four informative
    words, so the cap could have been dropped and every test stayed green. A
    file number is dictated down a phone and copied onto a card by hand;
    ``NCPSC-2026-0001`` is the version somebody gets wrong."""
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.initials(
            "New Cairo Paediatric Surgery Specialist Centre") == "NCP"
        assert numbering.initials("مركز رعاية الأم والطفل والحديثي") == "RAW"


def test_a_name_with_no_letters_at_all_falls_back(clinic):
    from app.models import Setting
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.initials("١٢٣ ٤٥٦") == ""
        Setting.set("clinic_name", "123")
        Setting.set("clinic_name_ar", "")
        assert numbering.suggest() == numbering.FALLBACK_PREFIX


def test_the_arabic_name_is_asked_first(clinic):
    """A clinic that filled in both is an Arabic clinic with a translation."""
    from app.models import Setting
    from app.utils import numbering
    with clinic["app"].app_context():
        Setting.set("clinic_name_ar", "عيادة الأطفال")
        assert numbering.suggest() == "AT"


def test_the_letters_in_force_are_derived_before_anything_is_settled(clinic):
    """**Caught by measurement.** Every other test here goes through
    ``settle``, so ``prefix_for`` — the read the settings screen and every
    display uses — could have returned the fallback for an unsettled clinic
    and stayed green. It would have shown ``PP`` to a clinic called Sunrise.
    """
    from app.models import Setting
    from app.utils import numbering
    with clinic["app"].app_context():
        assert Setting.get("patient_number_prefix") is None
        assert numbering.prefix_for() == "SM"
        assert numbering.prefix_for("fixed") == "SM"
        # And reading it settled nothing — that is the allocator's job.
        assert Setting.get("patient_number_prefix") is None


def test_a_blank_file_number_is_not_a_file_number(clinic):
    """A row imported with the column left empty is not a number handed out.
    Reading it as one freezes the letters for a clinic that has issued
    nothing — and answers ``""`` as the series in force."""
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "")
    with clinic["app"].app_context():
        assert numbering.issued() is False
        assert numbering.in_use() == ""
        assert numbering.prefix_for() == "SM"


def test_a_blank_row_added_last_does_not_hide_the_series(clinic):
    """**Caught by measurement.** With the blank row as the *only* patient,
    skipping it and reading it both answer ``""`` — so the filter could go and
    nothing failed. Put it after a real number and the difference appears:
    the clinic would forget its own letters because of one empty row."""
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "MK-2026-0001")
    _add(clinic["app"], clinic["db"], "")
    with clinic["app"].app_context():
        assert numbering.in_use() == "MK"
        assert numbering.prefix_for() == "MK"


def test_the_latest_number_being_a_paper_one_does_not_invent_letters(clinic):
    """**Also caught by measurement.** An imported paper file comes in as a
    bare ``1234``. Reading its first field as a prefix would have the next
    file number come out ``1234-2026-0001``, and the clinic name — the only
    honest answer left — never consulted."""
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "1234")
    with clinic["app"].app_context():
        assert numbering.in_use() == ""
        assert numbering.prefix_for() == "SM"


def test_an_unknown_scheme_reads_as_the_default_one(clinic):
    from app.utils import numbering
    with clinic["app"].app_context():
        assert numbering.prefix_for("something_else") == \
            numbering.prefix_for("yearly")


# ------------------------------------------------- it is no longer hard-coded --
def test_the_shipped_default_is_not_one_clinics_initials(clinic):
    """The bug, stated as a test. A fresh copy installed for somebody else
    must not issue ``GC-…``."""
    from app.utils.patients import generate_patient_number
    with clinic["app"].app_context():
        assert generate_patient_number().startswith("SM-")


def test_init_db_does_not_write_the_letters_down(clinic):
    """A seeded row is a row this module has to read as the clinic's own
    choice — so seeding ``PM`` meant no derivation could ever fire."""
    from app.cli import DEFAULT_SETTINGS
    assert "patient_number_prefix" not in DEFAULT_SETTINGS
    assert "patient_number_prefix_fixed" not in DEFAULT_SETTINGS
    # The *scheme* is still seeded; only the letters moved.
    assert DEFAULT_SETTINGS["patient_number_scheme"] == "yearly"


def test_both_schemes_use_the_clinics_letters(clinic):
    from app.models import Setting
    from app.utils.patients import generate_patient_number
    with clinic["app"].app_context():
        Setting.set("patient_number_scheme", "fixed")
        assert generate_patient_number(scheme="fixed").startswith("SM-")


# ----------------------------------------------------------- and it settles --
def test_the_next_number_follows_the_last_one_not_the_name(clinic):
    """After the first file number the clinic's name stops being consulted:
    the record answers. That is what makes a rename harmless."""
    from app.models import Setting
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "MK-2026-0007")
    with clinic["app"].app_context():
        assert Setting.get("patient_number_prefix") is None
        assert numbering.in_use() == "MK"
        assert numbering.prefix_for() == "MK"


def test_the_letters_in_use_are_the_latest_not_the_commonest(clinic):
    """A clinic that changed its letters after four hundred patients is
    using the new ones. Counting instead of looking would drag it back."""
    from app.utils import numbering
    for n in range(4):
        _add(clinic["app"], clinic["db"], f"PM-2026-000{n + 1}")
    _add(clinic["app"], clinic["db"], "MK-2026-0001")
    with clinic["app"].app_context():
        assert numbering.in_use() == "MK"


def test_asking_for_the_next_number_writes_nothing(clinic):
    """**The bug this design exists to avoid.** The new-patient form previews
    the next file number before anybody types a name — a read. Settling the
    letters into a settings row there would be a write on a read path, which
    this program has shipped once already."""
    from app.models import Setting
    from app.utils.patients import generate_patient_number
    with clinic["app"].app_context():
        before = {r.key: r.value for r in Setting.query.all()}
        generate_patient_number()
        generate_patient_number(scheme="fixed")
        clinic["db"].session.commit()
        assert {r.key: r.value for r in Setting.query.all()} == before


def test_renaming_the_clinic_does_not_change_next_years_letters(clinic):
    """**The mistake this file was written for.** Recomputing on every
    allocation gives a clinic that renamed itself two series, a sequence that
    restarts at 1, and no warning."""
    from app.models import Setting
    from app.utils.patients import generate_patient_number
    with clinic["app"].app_context():
        first = generate_patient_number()
        clinic["db"].session.commit()
    _add(clinic["app"], clinic["db"], first)

    with clinic["app"].app_context():
        Setting.set("clinic_name", "Al Noor Children Hospital")
        clinic["db"].session.commit()
    with clinic["app"].app_context():
        second = generate_patient_number()
        assert second.startswith("SM-"), "a rename moved a live numbering series"
        assert second != first


def test_a_number_on_file_is_never_rewritten(clinic):
    """The card in the handbag. Nothing in this module touches a stored
    number, whatever the clinic is called now."""
    from app.models import Patient, Setting
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "SM-2026-0001")
    with clinic["app"].app_context():
        Setting.set("clinic_name", "Totally Different Name")
        clinic["db"].session.commit()
        numbering.adopt_clinic_name()
        numbering.prefix_for()
        clinic["db"].session.commit()
        assert Patient.query.first().patient_number == "SM-2026-0001"


# ------------------------------------------------------------- the wizard --
def test_the_wizard_adopts_the_name_it_just_learned(clinic):
    """The wizard is where a fresh copy first hears whose clinic it is —
    later than the settings defaults were written."""
    from app.models import Setting
    from app.utils import facility
    with clinic["app"].app_context():
        facility.apply_facility("clinic", "عيادة الأطفال", ["outpatient"], [])
        clinic["db"].session.commit()
        assert Setting.get("patient_number_prefix") == "AT"
        assert Setting.get("patient_number_prefix_fixed") == "AT"


def test_the_wizard_replaces_the_old_shipped_letters(clinic):
    """A clinic upgrading into this carries ``PM``/``GC`` already — written by
    ``init-db``, chosen by nobody."""
    from app.models import Setting
    from app.utils import numbering
    with clinic["app"].app_context():
        Setting.set("patient_number_prefix", "PM")
        Setting.set("patient_number_prefix_fixed", "GC")
        clinic["db"].session.commit()
        assert numbering.adopt_clinic_name() == "SM"
        assert Setting.get("patient_number_prefix") == "SM"


def test_but_not_letters_somebody_chose(clinic):
    """**The other mistake.** An admin who set ``MK`` on purpose keeps it
    through every rename and every rerun of the wizard."""
    from app.models import Setting
    from app.utils import numbering
    with clinic["app"].app_context():
        Setting.set("patient_number_prefix", "MK")
        Setting.set("patient_number_prefix_fixed", "MK")
        clinic["db"].session.commit()
        assert numbering.adopt_clinic_name() is None
        assert Setting.get("patient_number_prefix") == "MK"


def test_a_prefix_somebody_chose_beats_the_numbers_already_out(clinic):
    """**Caught by measurement.** Nothing here had both a stored prefix and a
    different one already in the files, so the two could have been read in
    either order. An admin who deliberately changes the letters after four
    hundred patients means the next one, not the four hundredth."""
    from app.models import Setting
    from app.utils import numbering
    from app.utils.patients import generate_patient_number
    for n in range(3):
        _add(clinic["app"], clinic["db"], f"PM-2026-000{n + 1}")
    with clinic["app"].app_context():
        Setting.set("patient_number_prefix", "MK")
        clinic["db"].session.commit()
        assert numbering.in_use() == "PM", "the old series is still on file"
        assert numbering.prefix_for() == "MK"
        assert generate_patient_number().startswith("MK-")


def test_the_wizard_declines_once_a_number_exists(clinic):
    from app.models import Setting
    from app.utils import facility
    _add(clinic["app"], clinic["db"], "PM-2026-0001")
    with clinic["app"].app_context():
        Setting.set("patient_number_prefix", "PM")
        clinic["db"].session.commit()
        facility.apply_facility("clinic", "عيادة الأطفال", ["outpatient"], [])
        clinic["db"].session.commit()
        assert Setting.get("patient_number_prefix") == "PM"


# ------------------------------------------- more than one series is a fact --
def test_the_series_on_file_are_listed_commonest_first(clinic):
    """A clinic that changed its letters after nine patients has two series
    and the program reads both. Implying otherwise on the settings screen is
    how somebody concludes the old files were lost."""
    from app.utils import numbering
    for n in range(3):
        _add(clinic["app"], clinic["db"], f"PM-2026-000{n + 1}")
    _add(clinic["app"], clinic["db"], "GC-000001")
    with clinic["app"].app_context():
        assert numbering.series() == [("PM", 3), ("GC", 1)]


def test_a_legacy_number_with_no_prefix_is_not_invented_into_one(clinic):
    """Imported paper files come in as bare numbers. ``1234`` has no series,
    and reporting ``1234`` as one would be the program making something up."""
    from app.utils import numbering
    _add(clinic["app"], clinic["db"], "1234")
    with clinic["app"].app_context():
        assert numbering.series() == []


def test_the_settings_screen_shows_the_letters_and_the_series(clinic):
    """Where somebody actually meets this — and the one screen where the two
    answers differ and both have to be visible: the clinic is *called*
    Sunrise, so ``SM`` is what its name asks for and sits in the box as the
    offer, while ``GC`` is what its files actually carry and is what the next
    one will get."""
    from app.models import User
    with clinic["app"].app_context():
        boss = User(username="boss", full_name="المدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        clinic["db"].session.add(boss)
        clinic["db"].session.commit()
    for n in range(2):
        _add(clinic["app"], clinic["db"], f"PM-2026-000{n + 1}")
    _add(clinic["app"], clinic["db"], "GC-000001")

    client = clinic["app"].test_client()
    client.post("/login", data={"username": "boss", "password": "secret"},
                follow_redirects=True)
    html = client.get("/settings/").get_data(as_text=True)
    assert 'placeholder="SM"' in html, "the derived letters are not offered"
    assert ">GC<" in html, "the letters actually in force are not shown"
    assert "GC" in html and "PM" in html, "the series on file are not shown"
