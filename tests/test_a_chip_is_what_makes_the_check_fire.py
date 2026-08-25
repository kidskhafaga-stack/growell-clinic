"""One-click allergies — and for the drug ones, that is not the point of them.

Asked for as a convenience: *"نحط الحساسية المشهورة عند الأطفال يقدر يدوس
عليها والأمراض المزمنة برده"*. It is one. But the allergies on a child's file
are not decoration — ``app/utils/allergy.py`` reads them every time a medicine
is written, and matches three ways: the ingredient, the brand, and the **drug
family**. A child recorded as allergic to penicillin is caught when amoxicillin
is prescribed.

That matcher normalises hard, because parents say "بنسلين" and "حساسية من
البنسلين" and "Augmentin". It is good; it is not a mind reader. A mother says
*"حساسيه من البنسلن"* and the check may never fire.

**So a chip is what makes the check fire — and a chip the matcher does not
recognise is worse than free text.** It looks like the allergy was recorded
properly, and then no prescription is ever compared against it. Somebody would
find out when a child was handed the thing they react to.

Which is why the drug chips are generated from the families themselves rather
than typed into a list beside the form, and why this file exists: every chip
the screen offers is fed back through the matcher here, as a real patient
allergy against a real drug from that family.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# One medicine per family, in the words a doctor would actually write.
A_DRUG_FROM = {
    "penicillin": "أموكسيسيللين",
    "cephalosporin": "سيفيكسيم",
    "macrolide": "أزيثروميسين",
    "sulfa": "سبترين",
    "nsaid": "إيبوبروفين",
    "paracetamol": "باراسيتامول",
}


class _Child:
    """Just the attribute the matcher reads."""

    def __init__(self, allergies):
        self.allergies = allergies


def _families():
    from app.utils.allergy import FAMILIES

    return FAMILIES


# ------------------------------------- the chip and the matcher are one thing

@pytest.mark.parametrize("family", sorted(A_DRUG_FROM))
def test_every_drug_chip_actually_catches_its_family(clinic, family):
    """The test the whole design exists for. Click the chip, write the drug,
    get caught."""
    from app.utils.allergy import check_drug

    chip = _families()[family]["chip_ar"]
    hit = check_drug(_Child(chip), name=A_DRUG_FROM[family])

    assert hit is not None, \
        f"the chip «{chip}» records an allergy that {A_DRUG_FROM[family]} " \
        "is never checked against"
    assert hit["level"] in ("match", "caution")


def test_the_chips_come_from_the_families_and_are_not_a_second_list(clinic):
    """Two lists that have to agree eventually do not. The screen's drug chips
    and the matcher's families must be the same data, not a copy."""
    from app.utils import patient_chips

    offered = {ar for ar, _en in patient_chips.drug_allergy_chips()}
    known = {spec["chip_ar"] for spec in _families().values()}

    assert offered == known


def test_a_family_without_a_chip_is_a_family_nobody_can_click(clinic):
    """Adding a family should add its chip. Without this, a new family is
    recognised when somebody types it and invisible on the screen — which is
    the half-wired shape this program keeps finding in itself."""
    for name, spec in _families().items():
        assert spec.get("chip_ar"), f"the {name} family has no chip"


def test_the_english_chip_finds_it_too(clinic):
    """A clinic running the program in English clicks the English chip, and
    the file it writes must be read by the same matcher."""
    from app.utils.allergy import check_drug

    hit = check_drug(_Child("Penicillin"), name="أموكسيسيللين")

    assert hit is not None


# ---------------------------------------------- foods are honestly different

def test_a_food_chip_is_only_a_shared_spelling(clinic):
    """Nobody prescribes egg, so these chips cannot make a check fire and are
    not pretending to. What they buy is one spelling: a file that says "لبن
    بقري" in one place and "حساسية ألبان" in another cannot be searched,
    counted, or handed to a locum."""
    from app.utils import patient_chips
    from app.utils.allergy import FAMILIES

    foods = {ar for ar, _en in patient_chips.NON_DRUG_ALLERGIES}
    drug_words = {w for spec in FAMILIES.values() for w in spec["words"]}

    assert foods, "the food list is empty"
    assert not (foods & drug_words), \
        "a medicine is sitting in the food list, where nothing derives it"


def test_the_food_chips_do_not_flag_medicines(clinic):
    """A false alarm teaches people to click past alarms, which is how a real
    one gets clicked past too."""
    from app.utils.allergy import check_drug

    assert check_drug(_Child("البيض، الفراولة"), name="أموكسيسيللين") is None


# ------------------------------------------------------- the long illnesses

def test_the_g6pd_entry_is_there_and_names_itself_both_ways(clinic):
    """In Egypt this is common, and it is a contraindication list rather than
    a label — fava beans and a named set of drugs. A clinic searching its
    files for it has to find one spelling, and the English name is what a
    locum or a referral letter will use."""
    from app.utils import patient_chips

    with clinic["app"].app_context():
        rows = patient_chips.chips("chronic")
    g6pd = [r for r in rows if "G6PD" in (r["ar"] + r["en"])]

    assert g6pd, "أنيميا الفول is not on the list"
    assert "الفول" in g6pd[0]["ar"] and "G6PD" in g6pd[0]["en"]


def test_the_asthma_family_is_there(clinic):
    """The commonest long illness in a paediatric clinic. A list that made a
    doctor type it is a list they would stop using."""
    from app.utils import patient_chips

    with clinic["app"].app_context():
        ar = " ".join(r["ar"] for r in patient_chips.chips("chronic"))

    for illness in ("الربو", "الأكزيما", "الصرع", "السكري"):
        assert illness in ar, f"{illness} is not offered"


# ------------------------------------------------- the clinic owns the list
#
# ...the half of it that is theirs to own. The drug chips are not: they are the
# matcher's vocabulary wearing a button.

def test_a_clinic_cannot_edit_the_drug_chips_away(clinic):
    """The rule the split exists for. A settings editor stores what it was
    shown, so an editor holding the drug chips would freeze a copy the first
    time anybody pressed save — and the screen and the matcher would be two
    lists that have to agree. A clinic that saved a list without penicillin in
    it would lose the button, not the allergy, and every child who reacts to
    amoxicillin would depend on somebody spelling it right by hand."""
    from app.extensions import db
    from app.utils import patient_chips

    with clinic["app"].app_context():
        patient_chips.save("allergy", [{"code": "", "ar": "غبار المصنع",
                                        "en": "Factory dust"}])
        db.session.commit()

        offered = {r["ar"] for r in patient_chips.chips("allergy")}

    assert "غبار المصنع" in offered, "the clinic's own allergy was not kept"
    assert "بنسلين" in offered, \
        "a clinic edited away the chip the prescription check depends on"


def test_the_editor_is_only_ever_shown_the_clinic_half(clinic):
    """The other side of the same rule, at the source: whatever the settings
    screen renders is what it will save back, so the drug chips must never
    reach it."""
    from app.utils import patient_chips

    with clinic["app"].app_context():
        shown = {r["ar"] for r in patient_chips.editable("allergy")}

    assert "البيض" in shown, "the foods are not editable"
    assert "بنسلين" not in shown, \
        "the editor was handed a chip it would freeze a copy of on save"


def test_a_clinic_can_replace_the_list(clinic):
    """Same promise as the visit phrases: the program's list is where a clinic
    starts, not what they are stuck with."""
    from app.extensions import db
    from app.utils import patient_chips

    with clinic["app"].app_context():
        patient_chips.save("chronic", [{"code": "", "ar": "مرض العيادة دي",
                                        "en": "Local thing"}])
        db.session.commit()

        rows = patient_chips.chips("chronic")

    assert [r["ar"] for r in rows] == ["مرض العيادة دي"]


def test_clearing_it_puts_the_defaults_back(clinic):
    """Blank means "use yours" rather than "I have none" — the same rule the
    doctor's own phrases already follow, so nothing new is learned here."""
    from app.extensions import db
    from app.utils import patient_chips

    with clinic["app"].app_context():
        patient_chips.save("chronic", [])
        db.session.commit()

        assert len(patient_chips.chips("chronic")) > 5


def test_an_unknown_list_answers_with_nothing(clinic):
    from app.utils import patient_chips

    with clinic["app"].app_context():
        assert patient_chips.chips("orthopaedics") == []


def test_a_list_this_module_does_not_know_is_not_written(clinic):
    """Found by mutation testing, which is the only reason it is here: the
    guard in ``chips`` turned out to change no outcome, and the one in ``save``
    was never tested. It is the one that matters. A typo in a caller would
    otherwise store the clinic's edited list under a key no screen reads —
    saved, gone, and no error to say so."""
    from app.extensions import db
    from app.models import Setting
    from app.utils import patient_chips

    with clinic["app"].app_context():
        patient_chips.save("orthopaedics", [{"code": "", "ar": "كسر", "en": ""}])
        db.session.commit()

        assert Setting.get("patient_orthopaedics_chips") is None, \
            "an edit was written somewhere nothing will ever read it"


# ------------------------------------------------------------- the screen

@pytest.mark.parametrize("path", ["/patients/new"])
def test_the_chips_are_on_the_form(clinic, path):
    page = clinic["sign_in"]("boss").get(path).get_data(as_text=True)

    assert "بنسلين" in page, "the drug chips are not on the screen"
    assert "الربو" in page, "the chronic chips are not on the screen"


def test_they_are_on_the_edit_screen_too(clinic):
    """The create screen and the edit screen are the same template rendered
    from four places. A helper that reached only the first is how a feature
    ends up existing on half the paths that show it."""
    page = (clinic["sign_in"]("boss")
            .get(f"/patients/{clinic['ids']['child']}/edit").get_data(as_text=True))

    assert "بنسلين" in page and "الربو" in page


def test_the_chips_survive_a_form_that_came_back_with_an_error(clinic):
    """The template is rendered from four places and two of them are the
    "you left something out" paths — the ones a receptionist hits most. They
    are also the ones nothing was covering: the first version of this feature
    passed the chips in *twice* on exactly those two lines, which is a
    ``TypeError`` at call time, and every test still went green because none of
    them had ever submitted an invalid form."""
    page = clinic["sign_in"]("boss").post(
        "/patients/new", data={"first_name": "", "last_name": ""},
        follow_redirects=True).get_data(as_text=True)

    assert "بنسلين" in page and "الربو" in page, \
        "the chips vanished from the form when it came back with an error"


def test_clicking_the_same_chip_twice_does_not_say_it_twice(clinic):
    """A file that reads "بنسلين، بنسلين" is a file somebody stopped trusting.
    The de-duplication is in the page, so this checks it is there rather than
    that it ran."""
    page = clinic["sign_in"]("boss").get("/patients/new").get_data(as_text=True)

    assert "parts.includes(text)" in page, \
        "a chip clicked twice would write the allergy twice"


# ------------------------------------------- and the clinic edits it there

def test_both_lists_have_an_editor_on_the_settings_screen(clinic):
    """Asked for alongside the chips themselves: *"الاتنين قابلين للتعديل من
    الإعدادات زي شيبس الزيارة بالظبط"*. Same tab, same editor, same stored
    format — a clinic that has edited the visit phrases learns nothing new."""
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert 'name="patient_allergy_chips"' in page
    assert 'name="patient_chronic_chips"' in page


def test_the_settings_screen_never_renders_a_drug_chip_into_the_editor(clinic):
    """The rule again, this time where it would actually go wrong. The editor
    posts back whatever it holds, so a drug chip inside one would be saved as
    a copy — and a copy is a thing that can be edited into words the matcher
    does not know.

    **The payload is parsed rather than searched, and that is not tidiness.**
    The first version of this grepped the rendered `x-data` for "بنسلين" — and
    `tojson` escapes non-ASCII, so the string it looked for could not appear
    there whatever the route did. Handing the editor the full list left it
    green. A test that cannot fail is worse than no test: this one is here
    precisely because that mutant walked past it.
    """
    import html
    import json
    import re

    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    editors = re.findall(
        r'x-data="chipEditor\(([^"]*)\)"\s*>\s*<input type="hidden" '
        r'name="(patient_\w+)"', page)

    assert editors, "the patient chip editors are not on the screen"
    for payload, name in editors:
        rows = json.loads(html.unescape(payload))
        assert rows, f"{name} was rendered empty"
        words = {r.get("ar", "") for r in rows}
        assert "بنسلين" not in words, \
            f"{name} was rendered holding a derived drug chip"


def test_the_drug_chips_are_still_visible_there(clinic):
    """Not editable is not the same as hidden. A clinic looking at this screen
    should see what the file can already record, and read why that half is not
    theirs to change."""
    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)

    assert "بنسلين" in page, "the drug chips are invisible in settings"


def test_editing_the_clinic_half_reaches_the_patient_form(clinic):
    """End to end, because every half of this has been wired up and unwired
    before in this program: save on the settings screen, look at the form."""
    boss = clinic["sign_in"]("boss")
    boss.post("/settings/", data={"active_tab": "phrases",
                                  "clinic_name": "عيادة",
                                  "patient_chronic_chips": "التليف الكبدي|Cirrhosis"},
              follow_redirects=True)

    page = boss.get("/patients/new").get_data(as_text=True)

    assert "التليف الكبدي" in page, "the clinic's edit never reached the form"
    assert "بنسلين" in page, "saving a list took the drug chips off the form"


# --------------------------------------------- and the chips are drawn at all

def test_the_chip_style_is_shared_and_not_one_screen_s_secret(clinic):
    """Found by rendering the page, not by reading it.

    `.chip` was defined inside the `<style>` block of `visits/record.html`,
    which was fine while the visit screen was the only screen with chips. The
    patient file's arrived unstyled — and an unstyled `<button>` is a native
    control, light grey with dark text in *both* themes, so it looked correct
    in daylight by luck and became a row of white pills on a dark card at
    night. A screen cannot inherit another screen's stylesheet."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    shared = (root / "app/static/css/theme.css").read_text(encoding="utf-8")
    visit = (root / "app/templates/visits/record.html").read_text(encoding="utf-8")

    assert ".chip {" in shared, "the chip primitive is not in the shared stylesheet"
    assert ".chip {" not in visit, \
        "the visit screen defines .chip again; two copies drift"


def test_a_checked_chip_is_drawn_differently_from_a_peanut(clinic):
    """The distinction the file argues for, carried onto the screen. One of
    these makes a prescription warning fire and the other is a shared spelling;
    identical buttons say they are the same kind of thing."""
    import re

    page = clinic["sign_in"]("boss").get("/patients/new").get_data(as_text=True)
    penicillin = re.search(r'<button[^>]*>\s*بنسلين\s*</button>', page, re.S)
    egg = re.search(r'<button[^>]*>\s*البيض\s*</button>', page, re.S)

    assert penicillin and egg, "the chips are not both on the screen"
    assert "chip--checked" in penicillin.group(0)
    assert "chip--checked" not in egg.group(0)
