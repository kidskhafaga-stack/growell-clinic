"""Suggesting a diagnosis, and never suggesting a code.

Asked as *"يقترح تشخيصات للطبيب للتسهيل"*, then narrowed to what it is
actually for: *"لو الدكتور مش حافظ الاكواد او التشخيص مظبوط فا يقترح هو"*.

The whole design turns on one split. **The model names the diagnosis; the
program owns the code.** A model asked for `J06.9` will produce one, and it
will sometimes be a code that means something else — and a wrong code does not
stop at the screen, it goes into the file, the report and the claim. So the
prompt forbids codes, and — because a prompt is a request, not a guarantee —
:func:`strip_codes` removes any that arrive anyway, and the code on the screen
comes from the clinic's own ICD table via the same search the manual box uses.

The tests below are mostly about the ways that split can quietly stop holding.
"""
import pytest

from app.utils import ai_suggest


# ------------------------------------------------------- the brief we send ---
@pytest.fixture
def visit(clinic):
    from app.models import Visit

    with clinic["app"].app_context():
        row = Visit.query.get(clinic["ids"]["visit"])
        row.chief_complaint = "سخونية ٣ أيام وطفح"
        row.clinical_exam = "لوزتين محتقنتين، الصدر سليم"
        clinic["db"].session.commit()
        yield row


def test_the_brief_carries_what_the_doctor_wrote(clinic, visit):
    with clinic["app"].app_context():
        brief = ai_suggest.case_brief(visit)
    assert "سخونية ٣ أيام وطفح" in brief
    assert "لوزتين محتقنتين" in brief


def test_the_brief_never_carries_the_child_s_name(clinic, visit):
    """Not "anonymised when the setting is on" — it simply never has the name.

    A differential turns on age, sex and findings. Sending a name would be
    sending something the feature has no use for, and this route deliberately
    does not sit behind the patient-context switch precisely because it sends
    no file."""
    with clinic["app"].app_context():
        brief = ai_suggest.case_brief(visit)
        assert visit.patient.full_name not in brief
        assert visit.patient.patient_number not in brief
    assert "Age:" in brief


def test_what_is_typed_now_beats_what_was_saved(clinic, visit):
    """The doctor presses the button while still writing.

    A brief built only from the saved row would reason about the previous
    state of the screen — and to the doctor who just typed three lines it
    would look like a model that ignored them."""
    with clinic["app"].app_context():
        brief = ai_suggest.case_brief(
            visit, typed={"cc": "كحة وزلة نفس من ساعتين"})
    assert "كحة وزلة نفس" in brief
    assert "سخونية ٣ أيام" not in brief          # the stored one stepped aside
    assert "لوزتين محتقنتين" in brief             # and the untyped one stayed


def test_an_empty_typed_field_does_not_erase_the_saved_one(clinic, visit):
    """The screen sends all three fields every time, most of them blank."""
    with clinic["app"].app_context():
        brief = ai_suggest.case_brief(
            visit, typed={"cc": "", "exam": "", "notes": ""})
    assert "سخونية ٣ أيام وطفح" in brief


def test_it_refuses_to_ask_about_an_empty_screen(clinic):
    """Not an error — a refusal to spend money finding out that a model will
    describe a plausible child from no information at all."""
    from app.models import Visit

    with clinic["app"].app_context():
        row = Visit.query.get(clinic["ids"]["visit"])
        row.chief_complaint = None
        row.clinical_exam = None
        row.notes = None
        clinic["db"].session.commit()
        brief = ai_suggest.case_brief(row)
        assert not ai_suggest.enough_to_ask(brief)

        called = []
        result = ai_suggest.suggest(
            row, chat=lambda *a, **k: called.append(1) or {"ok": True})
    assert result == {"ok": False, "error": "too_thin"}
    assert called == [], "it asked the model about an empty screen"


def test_the_age_lines_alone_are_not_enough_to_ask(clinic):
    """The guard has to measure the doctor's contribution, not the brief.

    The header the program writes itself — `Age: 3y 2m`, `Sex: male` — is
    already longer than the minimum, so a naive length check on the whole
    brief passes on a completely empty visit."""
    from app.models import Visit

    with clinic["app"].app_context():
        row = Visit.query.get(clinic["ids"]["visit"])
        row.chief_complaint = None
        row.clinical_exam = None
        row.notes = None
        clinic["db"].session.commit()
        brief = ai_suggest.case_brief(row)
        assert len(brief) > ai_suggest.MIN_CHARS      # the trap
        assert not ai_suggest.enough_to_ask(brief)    # the check that matters


# ------------------------------------------------------ reading the reply ---
def test_it_reads_a_plain_json_reply():
    found = ai_suggest.parse(
        '{"suggestions":[{"ar":"التهاب لوزتين حاد","en":"Acute tonsillitis",'
        '"why":"لوزتين محتقنتين","danger":false}]}')
    assert len(found) == 1
    assert found[0]["ar"] == "التهاب لوزتين حاد"
    assert found[0]["en"] == "Acute tonsillitis"
    assert found[0]["danger"] is False


def test_it_reads_a_reply_wrapped_in_a_code_fence():
    """Models fence JSON however firmly they are told not to."""
    found = ai_suggest.parse(
        '```json\n{"suggestions":[{"ar":"نزلة برد","en":"Common cold"}]}\n```')
    assert [item["en"] for item in found] == ["Common cold"]


def test_it_reads_a_reply_with_prose_around_it():
    found = ai_suggest.parse(
        'Here are my thoughts:\n{"suggestions":[{"ar":"نزلة برد",'
        '"en":"Common cold"}]}\nHope that helps.')
    assert [item["en"] for item in found] == ["Common cold"]


@pytest.mark.parametrize("reply", [
    "", "   ", "I cannot help with that.", "{", "[1,2,3]", "null",
    '{"suggestions": "not a list"}',
])
def test_an_unreadable_reply_is_no_suggestions_and_never_a_crash(reply):
    """A consultation screen must not show a stack trace because a provider
    answered in prose."""
    assert ai_suggest.parse(reply) == []


def test_it_does_not_flood_the_screen():
    many = ",".join('{"ar":"س","en":"x%d"}' % i for i in range(20))
    found = ai_suggest.parse('{"suggestions":[%s]}' % many)
    assert len(found) == ai_suggest.MAX_SUGGESTIONS


def test_an_entry_with_no_name_at_all_is_dropped():
    found = ai_suggest.parse(
        '{"suggestions":[{"why":"because"},{"ar":"نزلة برد","en":"Cold"}]}')
    assert [item["ar"] for item in found] == ["نزلة برد"]


# ------------------------------------------ the codes it must never state ---
@pytest.mark.parametrize("text,gone", [
    ("Acute tonsillitis (J03.9)", "J03.9"),
    ("J069 upper respiratory infection", "J069"),
    ("Bronchiolitis — ICD 1A00", "1A00"),
])
def test_a_code_the_model_produced_never_reaches_the_screen(text, gone):
    """The prompt forbids codes. This makes the prompt's compliance
    irrelevant, because a code beside a diagnosis reads as *the* code for it
    and the one thing worse than not knowing the code is being shown a wrong
    one by your own program."""
    cleaned = ai_suggest.strip_codes(
        [{"ar": text, "en": text, "why": text, "danger": False}])
    for field in ("ar", "en", "why"):
        assert gone not in cleaned[0][field]


def test_stripping_a_code_does_not_throw_away_the_diagnosis():
    """The name is the part the doctor needs. A strip that took it too would
    turn every code-happy reply into an empty list."""
    cleaned = ai_suggest.strip_codes(
        [{"ar": "التهاب لوزتين حاد J03.9", "en": "Acute tonsillitis J03.9",
          "why": "", "danger": False}])
    assert cleaned[0]["ar"] == "التهاب لوزتين حاد"
    assert cleaned[0]["en"] == "Acute tonsillitis"


# ------------------------------------------- the code the program does own --
def test_the_code_comes_from_the_clinic_s_own_table(clinic):
    """Searched, not trusted: whatever code appears is one this machine holds
    and can look back up."""
    from app.utils.icd import lookup_icd

    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "أنيميا نقص حديد", "en": "Iron deficiency anaemia",
              "why": "", "danger": False}])
        assert found[0]["code"], "nothing matched a diagnosis this table has"
        assert lookup_icd(found[0]["code"]) is not None


def test_a_diagnosis_the_table_does_not_have_arrives_with_no_code(clinic):
    """Not hidden, and not given somebody else's code. The doctor still has
    the term, and the search box is right there."""
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "حاجة مش موجودة", "en": "Zzzqqx nonexistent condition",
              "why": "", "danger": False}])
    assert found[0]["code"] == ""
    assert found[0]["ar"] == "حاجة مش موجودة"


def test_the_version_recorded_is_the_matched_code_s_own(clinic):
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "أنيميا نقص حديد", "en": "Iron deficiency anaemia",
              "why": "", "danger": False}])
        from app.utils.icd import lookup_icd
        entry = lookup_icd(found[0]["code"])
    assert found[0]["icd_version"] == entry["version"]


# --------------------------------------------------------- the whole path ---
def test_end_to_end_a_reply_becomes_a_coded_suggestion(clinic, visit):
    reply = ('{"suggestions":[{"ar":"أنيميا نقص حديد",'
             '"en":"Iron deficiency anaemia J06.9","why":"شحوب",'
             '"danger":false}]}')
    with clinic["app"].app_context():
        result = ai_suggest.suggest(
            visit, chat=lambda *a, **k: {"ok": True, "text": reply})
    assert result["ok"]
    item = result["suggestions"][0]
    assert "J06.9" not in item["en"], "the model's own code survived the path"
    assert item["code"], "the program did not attach its own code"


def test_a_provider_failure_is_passed_through_untouched(clinic, visit):
    with clinic["app"].app_context():
        result = ai_suggest.suggest(
            visit,
            chat=lambda *a, **k: {"ok": False,
                                  "error": "not_configured"})
    assert result == {"ok": False, "error": "not_configured"}


def test_it_is_metered_under_its_own_name(clinic, visit):
    """So a clinic reading the usage screen can see what this costs, apart
    from the summaries and the discussion."""
    seen = {}

    def fake(messages, system=None, feature=None):
        seen["feature"] = feature
        return {"ok": True, "text": '{"suggestions":[]}'}

    with clinic["app"].app_context():
        ai_suggest.suggest(visit, chat=fake)
    assert seen["feature"] == "dx_suggest"


# ------------------------------------- the spelling the table does not use ---
@pytest.mark.parametrize("british,american", [
    ("Iron deficiency anaemia", "anemia"),
    ("Acute diarrhoea", "diarrhea"),
    ("Reflux oesophagitis", "esophagitis"),
])
def test_a_british_spelling_still_finds_the_code(clinic, british, american):
    """Found while testing this, and it is not a small one.

    The classification bundled with the program is the US clinical
    modification. Searching it for "anaemia" or "diarrhoea" returns **nothing
    at all** — and diarrhoea in a paediatric clinic is not an edge case. Worse,
    "tonsillitis" and most others match fine, so the table looks like it is
    working while failing silently on a whole class of terms."""
    from app.utils.icd import search_icd

    with clinic["app"].app_context():
        assert not search_icd(british, limit=1), (
            "the premise no longer holds — this table now has British "
            "spellings and the fallback may be unnecessary")
        found = ai_suggest.resolve(
            [{"ar": "س", "en": british, "why": "", "danger": False}])
        assert found[0]["code"], f"'{british}' still resolves to no code"
        assert american in found[0]["icd_title"].lower()


def test_the_fallback_cannot_change_a_search_that_already_worked(clinic):
    """It is a second attempt, not a rewrite. A rule that mangles a word costs
    an already-empty search nothing; one that fired on a working search could
    swap a correct code for another."""
    from app.utils.icd import search_icd

    with clinic["app"].app_context():
        direct = search_icd("Acute tonsillitis", limit=1)[0]["code"]
        found = ai_suggest.resolve(
            [{"ar": "س", "en": "Acute tonsillitis", "why": "",
              "danger": False}])
    assert found[0]["code"] == direct


@pytest.mark.parametrize("nonsense", [
    "Zzzqqx nonexistent condition",
    "Made up thing disease",
    "Imaginary paediatric syndrome",
])
def test_a_generic_last_word_never_drags_in_an_unrelated_code(
        clinic, nonsense):
    """The head-noun fallback's own failure mode, and it is a bad one.

    "Zzzqqx nonexistent condition" fell through to searching "condition" and
    came back **A51.49 — other secondary syphilitic conditions**. Nothing
    about that would have looked wrong on the screen: a real code, a real row,
    beside a diagnosis nobody wrote."""
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "س", "en": nonsense, "why": "", "danger": False}])
    assert found[0]["code"] == "", (
        f"'{nonsense}' picked up {found[0]['code']} "
        f"({found[0]['icd_title']})")


def test_the_matched_title_travels_with_the_code(clinic):
    """The screen shows it beside the code, and that is the check on every
    fallback above: a match that reached too far is visible before anybody
    clicks it."""
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "التهاب لوزتين حاد", "en": "Acute tonsillitis",
              "why": "", "danger": False}])
    assert "tonsillitis" in found[0]["icd_title"].lower()


def test_a_word_matched_inside_another_word_is_not_a_match(clinic):
    """"Made up thing disease" fell through to the word "thing" and matched
    **K00.7, Teething syndrome** — because the picker matches any substring,
    which is right for a doctor typing "diarr" and watching the list, and
    wrong for a fallback nobody is watching."""
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "س", "en": "Made up thing disease", "why": "",
              "danger": False}])
    assert found[0]["code"] == "", found[0]["icd_title"]


def test_the_specific_word_is_tried_before_the_last_one(clinic):
    """The table titles it *"Mucocutaneous lymph node syndrome [Kawasaki]"* —
    so the phrase matches nothing, and the last word is the empty one. A
    fallback that only looked at the end would lose a diagnosis no
    paediatrician can afford to have go uncoded."""
    with clinic["app"].app_context():
        found = ai_suggest.resolve(
            [{"ar": "مرض كاواساكي", "en": "Kawasaki disease", "why": "",
              "danger": True}])
    assert found[0]["code"] == "M30.3"
