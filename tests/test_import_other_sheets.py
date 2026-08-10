"""The importer against a file it has never seen — which is most files.

The history import was built against one clinic's export, and reviewed with
the note that *not every sheet will look like that one*. So this measures it
against a file with nothing in common: English headers, a different order,
extra columns the program has no field for, and none of the trailing summary
block.

**What the measurement found.** Nine of fourteen columns were recognised, and
the one that was missed was ``service_date`` — a **required** field, headed
"Visit Date", which the alias table did not contain. The import still worked,
because the mapping screen lets any column be pointed at by hand; but the
required field being the one that needed pointing at is the worst possible
place for the gap.

**The fix generalises rather than chasing names.** Adding "visit date" to the
alias list would have fixed this file and not the next one. Each field now
also carries the *words* that mean it, applied only where an exact alias found
nothing, and only to columns nothing else claimed — so a name the program
knows can never be overruled by a guess.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The clinic this was built for.
ARABIC = ["م", "كود المريض", "اسم المريض", "تاريخ الخدمه", "الساعة",
          "كود الطبيب", "اسم الطبيب", "الخدمه", "فئة الخدمه", "نوع الخدمه",
          "التعاقد", "السعر الاجمالي", "نصيب الطبيب", "نقدي", "شركات",
          "الكميه", "ملاحظات"]

# Somebody else's, sharing not one wording or position.
ENGLISH = ["Row #", "MRN", "Patient Name", "Visit Date", "Time",
           "Doctor Name", "Service", "Qty", "Amount", "Doctor Share",
           "Cash", "Insurance", "Remarks", "Ward"]

REQUIRED = ("patient_name", "service_date", "service_name", "price")


def _guess(headers):
    from app.utils.history_import import guess_mapping
    return {k: v for k, v in guess_mapping(headers).items() if v != ""}


def test_the_file_it_was_built_for_still_maps_completely(clinic):
    """The first thing any generalisation has to not break."""
    found = _guess(ARABIC)
    for key in REQUIRED:
        assert key in found, f"{key} was lost from the original export"
    assert found["service_date"] == 3
    assert found["price"] == 11
    assert found["doctor_share"] == 12
    assert len(found) >= 17, "columns the original file mapped are now missed"


def test_a_sheet_with_nothing_in_common_still_maps_its_required_columns(clinic):
    """The point of the review note.

    Before the word pass this recognised nine of fourteen and missed the date
    — the one field the import cannot proceed without.
    """
    found = _guess(ENGLISH)
    for key in REQUIRED:
        assert key in found, f"{key} was not recognised on a differently-worded sheet"
    assert ENGLISH[found["service_date"]] == "Visit Date"
    assert ENGLISH[found["patient_code"]] == "MRN"
    assert ENGLISH[found["notes"]] == "Remarks"


def test_a_column_the_program_has_no_field_for_is_left_alone(clinic):
    """"Ward" is not one of ours. Guessing it into something would be worse
    than ignoring it — an imported column nobody asked for is data in the
    wrong place, and there is no undo at the field level.

    Tested with **no competing column**, because the first version of this
    passed for the wrong reason: "Remarks" sat earlier in the row and claimed
    ``notes`` first, so "Ward" was never even reached. Widening the notes
    pattern to swallow "ward" left the file green.
    """
    from app.utils.history_import import map_headers

    lonely = ["Row #", "Patient Name", "Visit Date", "Service", "Amount",
              "Ward"]
    mapped = map_headers(lonely)
    assert lonely.index("Ward") not in mapped, (
        "an unknown column was claimed when nothing else competed for it")
    # …and the ordinary case still holds.
    assert ENGLISH.index("Ward") not in _guess(ENGLISH).values()


def test_a_name_the_program_knows_is_never_overruled_by_a_guess(clinic):
    """"Doctor Share" contains the word "doctor".

    The word pass runs second and only fills what is still empty, so the
    doctor's *name* can never end up pointing at the doctor's *share* — which
    would put money in a name column and a name in a money column, and both
    would look plausible on the preview.
    """
    found = _guess(ENGLISH)
    assert ENGLISH[found["doctor_name"]] == "Doctor Name"
    assert ENGLISH[found["doctor_share"]] == "Doctor Share"


@pytest.mark.parametrize("header,key", [
    ("Date of service", "service_date"),
    ("تاريخ الكشف", "service_date"),
    ("Patient MRN", "patient_code"),
    ("Total Amount", "price"),
    ("Cash Paid", "paid_cash"),
    ("Insurance Co.", "paid_company"),
    ("Comments", "notes"),
])
def test_the_wordings_a_next_file_is_likely_to_use(clinic, header, key):
    """None of these are in the alias table, and none had to be added.

    That is the difference between fixing this file and fixing the class of
    file — which was the review note.
    """
    from app.utils.history_import import map_headers

    mapped = map_headers([header])
    assert mapped.get(0) == key, f"{header!r} was not recognised as {key}"


def test_rows_come_out_right_on_the_unfamiliar_sheet(clinic):
    """Mapping is only half of it — the values have to survive the parse."""
    from app.utils.history_import import build_rows, guess_mapping

    rows = [["1", "MR-0091", "Omar Hassan", "2023-04-11", "10:30", "Dr. Sara",
             "Consultation", "1", "250", "100", "250", "0", "first visit", ""]]
    records = build_rows(rows, guess_mapping(ENGLISH))

    assert len(records) == 1
    record = records[0]
    assert record["patient_name"] == "Omar Hassan"
    assert record["service_date"].isoformat() == "2023-04-11"
    assert record["service_name"] == "Consultation"
    assert record["price"] == 250
    assert record["doctor_share"] == 100
    assert record["paid_cash"] == 250
    assert record["quantity"] == 1


def test_no_summary_block_is_invented_where_there_is_none(clinic):
    """The trailing "من تاريخ / إلى تاريخ" block is one clinic's habit.

    The detector is written as a general rule — a column that is almost
    entirely empty is not data — so a file without one must produce no false
    positives, or real columns get dropped.
    """
    from app.utils.history_import import summary_columns

    rows = [["1", "MR-0091", "Omar Hassan", "2023-04-11", "10:30", "Dr. Sara",
             "Consultation", "1", "250", "100", "250", "0", "first visit", "A"],
            ["2", "MR-0117", "Lina Adel", "2024-01-20", "09:00", "Dr. Khaled",
             "Vaccination", "2", "900", "0", "900", "0", "", "B"]]
    assert sorted(summary_columns(ENGLISH, rows)) == []
