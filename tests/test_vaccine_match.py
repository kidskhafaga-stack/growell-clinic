"""Recognising a vaccine in whatever the old program called it, and which dose.

Both halves are measured against the real export's 27 distinct service names.

**The name.** A vaccine is one free-text field with the brand, the Arabic name
and the abbreviation run together, and not always in the same order — the same
product appears as ``'BEXSERO - meningitis B - الحمى الشوكية B'`` and as
``'الحمى الشوكية B - BEXSERO - meningitis B'``. So order carries no
information: the name is split and each piece scored on its own.

Nothing here decides anything. It proposes with a confidence and the clinic
confirms 27 rows — because the failure mode of a matcher that wrote its own
guesses is a child recorded as having had a vaccine they did not.

**The dose.** There is no dose column at all, so the number is inferred from
the dates — and the obvious way is wrong. Patient 1080 in the real file had
Synflorix (PCV 10) three times and then Prevenar (PCV 13): the same vaccine in
two brands. Numbered per brand that fourth dose is "dose 1", and the schedule
then chases the child for doses they have already had.
"""
import os
import sys
from datetime import date, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# Every distinct service name in the real export.
REAL_NAMES = [
    "كشف", "إستشارة", "تطعيم",
    "Synflorix - مكورات رئوية - PCV 10", "Rota-rix - فيروس الروتا",
    "Varivax-جديرى مائى", "Vaxigrip - الأنفلونزا الموسمية",
    "HAV-rix - كبدي (أ)", "Prevenar - مكورات رؤية - PCV 13",
    "Menactra - الالتهاب السحائى", "Influvac - أنفلونزا موسمية",
    "Varilrix - جديري مائي", "HAV-rix - كبدي (أ) [جديد]",
    "Mencevax - الحمى الشوكية - 10", "HEXAXIM - سداسي لا خلوي",
    "الحمى الشوكية B - BEXSERO - meningitis B", "Mencevax - الحمى الشوكية",
    "OPV - تطعيم شلل الاطفال", "Rota-teq - فيروس الروتا",
    "Hib - انفلونزا بكتيرية", "MMR - حصبة - ألماني - النكاف",
    "BEXSERO - meningitis B - الحمى الشوكية B", "Nimenrix - الالتهاب السحائى",
    "HBV - كبدى (ب) وبائي", "خماسى خلوى-(Quinvaxem (DTwP-HBV-Hib",
    "DT - ثنائي", "Gardasil",
]


@pytest.fixture()
def catalogue(clinic):
    """The clinic's real vaccine catalogue.

    The shared fixture carries two vaccines, which is right for the billing
    tests and useless here: the whole question is whether 24 free-text names
    from somebody else's program find their way into the catalogue this program
    ships with.
    """
    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        clinic["db"].session.commit()
    return clinic


def _suggest(catalogue, name):
    from app.utils.vaccine_match import suggest

    with catalogue["app"].app_context():
        return suggest(name)


# ===================================================== splitting the name ===
def test_the_pieces_are_taken_apart_however_they_were_joined(clinic):
    from app.utils.vaccine_match import pieces

    assert "synflorix" in pieces("Synflorix - مكورات رئوية - PCV 10")
    assert "bexsero" in pieces("الحمى الشوكية B - BEXSERO - meningitis B")


def test_brackets_are_separators_not_part_of_the_name(clinic):
    """"[جديد]" is a note somebody added beside the name."""
    from app.utils.vaccine_match import pieces

    assert pieces("HAV-rix - كبدي (أ)") == pieces("HAV-rix - كبدي (أ) [جديد]")


def test_a_bare_number_is_not_a_piece(clinic):
    """"Mencevax - الحمى الشوكية - 10" carries a 10 that identifies nothing."""
    from app.utils.vaccine_match import pieces

    assert "10" not in pieces("Mencevax - الحمى الشوكية - 10")


def test_arabic_spelling_is_folded(clinic):
    from app.utils.vaccine_match import pieces

    assert pieces("جديرى مائى") == pieces("جديري مائي")


# ==================================================== order carries nothing =
def test_the_same_name_reordered_gives_the_same_answer(catalogue):
    """Both spellings are in the file, for one product."""
    a = _suggest(catalogue, "الحمى الشوكية B - BEXSERO - meningitis B")
    b = _suggest(catalogue, "BEXSERO - meningitis B - الحمى الشوكية B")
    assert a and b
    assert a[0]["brand_id"] == b[0]["brand_id"]


def test_a_note_on_the_end_does_not_change_the_answer(catalogue):
    a = _suggest(catalogue, "HAV-rix - كبدي (أ)")
    b = _suggest(catalogue, "HAV-rix - كبدي (أ) [جديد]")
    assert a and b
    assert a[0]["brand_id"] == b[0]["brand_id"]


def test_a_hyphen_inside_a_brand_name_is_survivable(catalogue):
    """The file writes "Rota-rix"; the catalogue holds "RotaRix". The hyphen is
    also the separator, so the pieces have to be compared de-hyphenated too."""
    found = _suggest(catalogue, "Rota-rix - فيروس الروتا")
    assert found and "rota" in found[0]["label"].lower()


# ================================================ the brand is what matters =
def test_two_brands_of_one_vaccine_are_told_apart(catalogue):
    """Synflorix and Prevenar are both pneumococcal — and different products at
    different prices. Matching only the vaccine would offer them
    interchangeably."""
    pcv10 = _suggest(catalogue, "Synflorix - مكورات رئوية - PCV 10")
    pcv13 = _suggest(catalogue, "Prevenar - مكورات رؤية - PCV 13")
    assert pcv10 and pcv13
    assert pcv10[0]["brand_id"] != pcv13[0]["brand_id"]


def test_a_typo_in_the_arabic_does_not_lose_the_brand(catalogue):
    """The file says "مكورات رؤية" where it means "رئوية". The brand name is
    what carries it."""
    found = _suggest(catalogue, "Prevenar - مكورات رؤية - PCV 13")
    assert found and "prevenar" in found[0]["label"].lower()


# ===================================================== nothing is decided ===
def test_an_unknown_name_proposes_nothing_rather_than_guessing(catalogue):
    """The one case that must not happen is a child recorded as having had a
    vaccine they did not."""
    assert _suggest(catalogue, "حاجة مش موجودة خالص فى الكتالوج") == []


def test_a_plain_service_is_not_matched_to_a_vaccine(catalogue):
    """"كشف" and "إستشارة" are 7,476 of the file's rows. Offering a vaccine for
    them would put a candidate in front of the clinic 27 times for nothing."""
    for name in ("كشف", "إستشارة"):
        assert _suggest(catalogue, name) == [], name


def test_a_tie_is_never_reported_as_high_confidence(catalogue):
    """Two candidates scoring alike is the case that most needs a person."""
    from app.utils.vaccine_match import suggest

    with catalogue["app"].app_context():
        for name in REAL_NAMES:
            found = suggest(name)
            if len(found) > 1 and found[0]["score"] == found[1]["score"]:
                assert found[0]["confidence"] != "high", name


def test_every_candidate_carries_a_confidence(catalogue):
    from app.utils.vaccine_match import suggest_all

    with catalogue["app"].app_context():
        for _name, found in suggest_all(REAL_NAMES).items():
            for candidate in found:
                assert candidate["confidence"] in ("high", "medium", "low")


def test_the_real_file_is_mostly_recognised(catalogue):
    """Measured, not hoped for: of the 24 vaccine names in the export, most
    should arrive with a candidate already chosen so the clinic is confirming
    rather than searching."""
    from app.utils.vaccine_match import suggest_all

    vaccines = [n for n in REAL_NAMES if n not in ("كشف", "إستشارة", "تطعيم")]
    with catalogue["app"].app_context():
        found = suggest_all(vaccines)
    matched = sum(1 for name in vaccines if found[name])
    assert matched == len(vaccines), (
        f"only {matched} of {len(vaccines)} were recognised")


def test_the_confidence_still_tells_the_clinic_something(catalogue):
    """Indexing the catalogue word by word made many more entries score
    *something*, and the first version of the confidence — "more than one
    candidate means medium" — collapsed to medium for almost every name. A
    confidence that is always the same is not a confidence.
    """
    from app.utils.vaccine_match import suggest_all

    vaccines = [n for n in REAL_NAMES if n not in ("كشف", "إستشارة", "تطعيم")]
    with catalogue["app"].app_context():
        found = suggest_all(vaccines)
    levels = {name: rows[0]["confidence"] for name, rows in found.items() if rows}
    assert len(set(levels.values())) > 1, "every name came back the same"
    assert sum(1 for v in levels.values() if v == "high") >= 12


def test_the_messiest_name_in_the_file_finds_the_right_vaccine(catalogue):
    """'خماسى خلوى-(Quinvaxem (DTwP-HBV-Hib' is a brand, a description and an
    ingredient list in one field. Comparing whole phrases, the only piece that
    hit anything was the "HBV" buried in the ingredients — so it was matched to
    hepatitis B. Its words are indexed now."""
    found = _suggest(catalogue, "خماسى خلوى-(Quinvaxem (DTwP-HBV-Hib")
    assert found and "خماسي" in found[0]["label"]


def test_the_two_that_were_missing_are_in_the_catalogue_now(catalogue):
    """Mencevax and DT were in the clinic's ten years of history and in nobody
    else's list. Mencevax is a *brand* of the meningococcal ACWY vaccine rather
    than a vaccine of its own, so a child who had Mencevax and later Menactra
    is one course — which is what per-vaccine dose numbering depends on."""
    mencevax = _suggest(catalogue, "Mencevax - الحمى الشوكية")
    menactra = _suggest(catalogue, "Menactra - الالتهاب السحائى")
    assert mencevax and menactra
    assert mencevax[0]["vaccine_id"] == menactra[0]["vaccine_id"], "same course"
    assert mencevax[0]["brand_id"] != menactra[0]["brand_id"], "different product"

    assert _suggest(catalogue, "DT - ثنائي")


def test_the_definite_article_does_not_hide_a_match(catalogue):
    """The catalogue writes "الخماسي"; the file writes "خماسى خلوى"."""
    from app.utils.vaccine_match import _score

    assert _score("خماسي", "الخماسي") == 2


def test_the_catalogue_is_built_once_for_a_whole_file(clinic):
    """27 names must not mean 27 sets of queries."""
    import inspect

    from app.utils import vaccine_match

    source = inspect.getsource(vaccine_match.suggest_all)
    assert "catalogue()" in source
    assert source.count("catalogue()") == 1


# ======================================================== the dose number ===
def _rows(*specs):
    """``(patient, vaccine, date)`` triples as import rows."""
    return [{"patient_id": p, "vaccine_id": v, "service_date": d,
             "service_time": None, "source_row": str(i)}
            for i, (p, v, d) in enumerate(specs)]


def test_doses_are_numbered_by_date(clinic):
    from app.utils.dose_infer import number_doses

    rows = number_doses(_rows((1, 7, date(2023, 5, 27)),
                              (1, 7, date(2023, 3, 20)),
                              (1, 7, date(2023, 7, 22))))
    by_date = {r["service_date"]: r["dose_number"] for r in rows}
    assert by_date == {date(2023, 3, 20): 1, date(2023, 5, 27): 2,
                       date(2023, 7, 22): 3}


def test_a_different_brand_of_the_same_vaccine_continues_the_course(clinic):
    """The finding that shaped this. Patient 1080 had Synflorix (PCV 10) three
    times and then Prevenar (PCV 13) — the same vaccine, a different brand.
    Numbered per brand, that fourth dose becomes "dose 1" and the schedule
    chases the child for doses they have already had."""
    from app.utils.dose_infer import number_doses

    rows = _rows((1080, 7, date(2023, 3, 20)),
                 (1080, 7, date(2023, 5, 27)),
                 (1080, 7, date(2023, 7, 22)),
                 (1080, 7, date(2024, 2, 21)))     # the other brand, same vaccine
    rows[3]["brand_id"] = 99
    number_doses(rows)
    assert rows[3]["dose_number"] == 4


def test_two_patients_do_not_share_a_course(clinic):
    from app.utils.dose_infer import number_doses

    rows = number_doses(_rows((1, 7, date(2023, 3, 20)),
                              (2, 7, date(2023, 5, 27))))
    assert [r["dose_number"] for r in rows] == [1, 1]


def test_two_vaccines_do_not_share_a_course(clinic):
    from app.utils.dose_infer import number_doses

    rows = number_doses(_rows((1, 7, date(2023, 3, 20)),
                              (1, 9, date(2023, 5, 27))))
    assert [r["dose_number"] for r in rows] == [1, 1]


def test_two_doses_on_one_day_are_ordered_stably(clinic):
    """Common in the file, and a re-import must produce the same numbers rather
    than a reshuffle."""
    from app.utils.dose_infer import number_doses

    rows = [{"patient_id": 1, "vaccine_id": 7, "service_date": date(2023, 3, 20),
             "service_time": time(17, 0), "source_row": "2"},
            {"patient_id": 1, "vaccine_id": 7, "service_date": date(2023, 3, 20),
             "service_time": time(9, 0), "source_row": "1"}]
    number_doses(rows)
    assert rows[1]["dose_number"] == 1 and rows[0]["dose_number"] == 2


def test_a_row_with_no_vaccine_gets_no_dose_number(clinic):
    """A consultation has no dose. Putting a number on it would mean nothing."""
    from app.utils.dose_infer import number_doses

    rows = [{"patient_id": 1, "vaccine_id": None,
             "service_date": date(2023, 3, 20), "service_time": None,
             "source_row": "1"}]
    number_doses(rows)
    assert "dose_number" not in rows[0]


def test_a_booster_beyond_the_schedule_is_flagged_not_dropped(clinic):
    """A boosted child is a real child. An importer that dropped the fourth
    dose of a three-dose schedule would be deleting history to protect a
    table."""
    from app.utils.dose_infer import beyond_schedule, number_doses

    rows = number_doses(_rows((1, 7, date(2023, 1, 1)),
                              (1, 7, date(2023, 3, 1)),
                              (1, 7, date(2023, 5, 1)),
                              (1, 7, date(2024, 5, 1))))
    flagged = beyond_schedule(rows, {7: 3})
    assert len(rows) == 4
    assert len(flagged) == 1 and flagged[0]["dose_number"] == 4


def test_a_vaccine_with_no_schedule_flags_nothing(clinic):
    from app.utils.dose_infer import beyond_schedule, number_doses

    rows = number_doses(_rows((1, 7, date(2023, 1, 1)),
                              (1, 7, date(2023, 3, 1))))
    assert beyond_schedule(rows, {}) == []


def test_the_longest_schedule_is_the_one_measured_against(clinic):
    """A vaccine can carry several templates — a catch-up schedule has fewer
    doses than the routine one — and a dose is only beyond the schedule if it
    is beyond every schedule the vaccine has."""
    from app.models import Vaccine, VaccineScheduleDose, VaccineScheduleTemplate
    from app.utils.dose_infer import schedule_lengths

    with clinic["app"].app_context():
        db = clinic["db"]
        vaccine = Vaccine(code="TEST-SCH", name_ar="اختبار")
        db.session.add(vaccine)
        db.session.flush()
        for name, doses in (("قصير", 2), ("كامل", 4)):
            template = VaccineScheduleTemplate(vaccine_id=vaccine.id, code=name)
            db.session.add(template)
            db.session.flush()
            for number in range(1, doses + 1):
                db.session.add(VaccineScheduleDose(template_id=template.id,
                                                   dose_number=number))
        db.session.commit()
        assert schedule_lengths()[vaccine.id] == 4
