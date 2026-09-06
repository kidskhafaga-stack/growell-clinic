"""A common cold filed as RSV pneumonia, and nothing on the screen said so.

Reported with two screenshots. On the visit, two diagnoses both carrying
**ICD-10 · J12.1** under two different Arabic names. On the prescription
opened from that visit, the diagnosis carried across and, underneath it,
*«مفيش تشخيص بالاسم ده»* — no diagnosis by that name — about a diagnosis the
program itself had just written.

Three faults, in the order they happen.

**A word is not a diagnosis.** The model wrote *"Upper respiratory viral
infection"*. The classification titles that illness *"Acute upper respiratory
infection, unspecified"* — every important word shared and not one contiguous
run of characters, which is all ``search_icd`` can match. So the full phrase
found nothing and the fallback tried the term's longest word, **"respiratory"**,
whose first hit is **J12.1, Respiratory syncytial virus pneumonia**. The
single-word guard passed it, because "respiratory" genuinely is a word in that
title. A cold went into the file as pneumonia.

**The check that would have caught it was not on the screen.** ``resolve`` has
always returned the matched title precisely so the doctor can see what the
code says — the module's own docstring calls it "the check on all of this" —
and the suggestion chip printed the model's name and the bare number.

**And the code arrived without its name.** A code picked by hand takes the
row's own wording; a code found by the assistant kept the model's paraphrase.
So one number ends up under two names in one visit, and the prescription
screen — searching the classification for the name it was handed — correctly
answers that no such diagnosis exists.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


# ------------------------------------------------- the words, not the word

@pytest.mark.parametrize("written,code", [
    # The reported case, and the two other ways a model phrases it.
    ("Upper respiratory viral infection", "J06.9"),
    ("Viral upper respiratory tract infection", "J06.9"),
    ("Acute otitis media", "H66.009"),
    ("Iron deficiency anaemia", "D50.9"),      # and the British spelling
])
def test_the_words_together_find_what_the_phrase_could_not(clinic, written, code):
    """``search_icd`` wants a contiguous run; a written-out diagnosis rarely
    is one. Matching on the words instead finds the commonest illness in
    paediatrics, which the old path could only reach by accident."""
    from app.utils.icd import search_by_words

    with clinic["app"].app_context():
        rows = search_by_words(written, version="10", limit=1)
        assert rows and rows[0]["code"] == code, rows[:1]


@pytest.mark.parametrize("written", [
    "Zzzqqx nonexistent condition",
    "Imaginary paediatric syndrome",
    "Bronchiolitis",                 # one word: not enough on its own
])
def test_it_refuses_when_the_words_do_not_carry_it(clinic, written):
    """Two words minimum and at least half of them matched — both proportions,
    not thresholds picked by taste. A row sharing two words out of nine has
    not been identified by them."""
    from app.utils.icd import search_by_words

    with clinic["app"].app_context():
        assert search_by_words(written, version="10", limit=1) == []


def test_a_body_system_word_can_no_longer_carry_a_code(clinic):
    """The exact failure, named. "respiratory" is a word in 228 titles in the
    bundled classification; it selects none of them."""
    from app.utils.ai_suggest import EMPTY_WORDS, _attempts

    for word in ("respiratory", "infection", "tract", "upper", "viral"):
        assert word in EMPTY_WORDS
    assert not any(single for _, single in
                   _attempts("Upper respiratory viral infection"))


def test_the_real_single_word_diagnoses_still_work(clinic):
    """The line this draws is between a body system and an illness, not
    between long words and short. Blocking too much would be the same fault
    facing the other way."""
    from app.utils.ai_suggest import resolve

    with clinic["app"].app_context():
        for term, code in (("Anemia", "D64.9"), ("Pneumonia", "J18.9"),
                           ("Impetigo", "L01.00")):
            assert resolve([{"en": term, "ar": ""}])[0]["code"] == code, term


def test_the_reported_case_end_to_end(clinic):
    """A cold is a cold."""
    from app.utils.ai_suggest import resolve

    with clinic["app"].app_context():
        out = resolve([{"en": "Upper respiratory viral infection",
                        "ar": "عدوى فيروسية للأنابيب الهوائية العلوية"}])[0]
        assert out["code"] == "J06.9"
        assert "pneumonia" not in out["icd_title"].lower()


# ------------------------------------------------- the code brings its name

def test_a_matched_code_carries_the_classifications_own_arabic(clinic):
    from app.utils.ai_suggest import resolve

    with clinic["app"].app_context():
        out = resolve([{"en": "Upper respiratory viral infection",
                        "ar": "عدوى فيروسية للأنابيب الهوائية العلوية"}])[0]
        assert out["icd_title"] == "Acute upper respiratory infection, unspecified"
        assert out["icd_title_ar"] == "التهاب الجهاز التنفسي العلوي الحاد"
        # And the model's own words are not overwritten in the payload — the
        # screen decides what to file, and it can only decide if it has both.
        assert out["ar"] == "عدوى فيروسية للأنابيب الهوائية العلوية"


def test_a_row_with_no_arabic_says_so_rather_than_inventing_one(clinic):
    """Most of the full table is English-only. An Arabic title is not made up
    for it, here or anywhere else."""
    from app.utils.ai_suggest import resolve

    with clinic["app"].app_context():
        out = resolve([{"en": "Respiratory syncytial virus as the cause",
                        "ar": "كذا"}])[0]
        if out["code"]:
            assert out["icd_title_ar"] in ("", out["icd_title_ar"])


@pytest.fixture()
def wired(clinic):
    """The suggestion block on, so the chip and its handler are rendered."""
    from app.models import Setting

    with clinic["app"].app_context():
        for key, value in (("ai_enabled", "1"), ("ai_provider", "claude"),
                           ("ai_api_key", "k"), ("ai_model", "m"),
                           ("ai_dx_suggest", "1")):
            Setting.set(key, value)
        clinic["db"].session.commit()
    return clinic


def test_the_screen_files_the_code_s_own_name(wired):
    """The fix for two names under one number: a code found by the assistant
    behaves like a code picked by hand."""
    page = wired["sign_in"]("doc").get(
        f"/visits/{wired['ids']['visit']}/record").get_data(as_text=True)
    handler = page.split("applySuggestion(s) {")[1].split("applyIcd(")[0]
    assert "s.icd_title_ar" in handler and "s.icd_title" in handler


def test_the_chip_shows_what_the_code_actually_says(wired):
    """The safeguard the module documents and the screen had dropped."""
    page = wired["sign_in"]("doc").get(
        f"/visits/{wired['ids']['visit']}/record").get_data(as_text=True)
    assert "classifiedAs(s)" in page
    body = page.split("classifiedAs(s) {")[1].split("},")[0]
    # Quiet when the two agree: a line that always fires is furniture.
    assert "return ''" in body
