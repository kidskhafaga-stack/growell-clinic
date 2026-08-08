"""A second upload adds the increment, not a second register.

*"استيراد المرضى يراعي عدم التكرار وياخد الزيادة بس — زي ما عملنا في استيراد
التاريخ بالظبط."*

The import wrote every row it was given, so re-uploading a sheet gave every
child a second file number, a second vaccination card and a second history —
and the second file is the one the next receptionist finds. Clinics re-upload
constantly: because they added a few months, because they fixed something in
the old program, or because they cannot remember whether they already did.

The hard part is deciding what makes two rows the same person, and these tests
are mostly about that: the old program's file number, the national ID, and
name-with-date-of-birth — which is how a human decides, and which needs *both*
halves, because "محمد أحمد" is a quarter of Egypt.

Nothing is updated. The request was the increment, not a merge — a matching
row is left exactly as it is, because overwriting a file somebody has since
corrected by hand is a worse failure than importing nothing.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _row(name, dob="2020-01-01", gender="male", **extra):
    row = {"full_name": name, "gender": gender, "date_of_birth": dob}
    row.update(extra)
    return row


def _import(clinic, rows):
    from app.blueprints.patients.routes import _process_import

    result = _process_import(rows)
    clinic["db"].session.commit()
    return result


def _count(clinic):
    from app.models import Patient

    return Patient.query.count()


# ============================================== the same sheet twice ========
def test_uploading_the_same_sheet_twice_adds_nobody(clinic):
    """The bug, in one test."""
    sheet = [_row("زياد محمود سعيد"), _row("مريم محمود سعيد", gender="female")]

    with clinic["app"].app_context():
        first = _import(clinic, sheet)
        before = _count(clinic)

        second = _import(clinic, sheet)
        assert first["created"] == 2
        assert second["created"] == 0, "the register doubled"
        assert _count(clinic) == before
        assert len(second["skipped"]) == 2


def test_the_second_upload_takes_the_new_rows(clinic):
    """"وياخد الزيادة بس" — the point of re-uploading at all."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود سعيد")])
        result = _import(clinic, [_row("زياد محمود سعيد"),
                                  _row("عمر محمود سعيد")])

        assert result["created"] == 1
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["name"] == "زياد محمود سعيد"


def test_a_skipped_row_names_the_file_it_matched(clinic):
    """So somebody can open it and check the program was right."""
    from app.models import Patient

    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود سعيد")])
        existing = Patient.query.filter_by(full_name="زياد محمود سعيد").one()

        result = _import(clinic, [_row("زياد محمود سعيد")])
        assert result["skipped"][0]["patient_id"] == existing.id


# ============================================== what makes two rows one =====
def test_the_old_programs_file_number_is_enough(clinic):
    """It is the only key meant to be unique, and it survives a name being
    retyped or corrected between the two exports."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود", reference_number="OLD-7")])
        result = _import(clinic, [_row("زياد محمود سعيد أحمد",
                                       dob="2019-05-05",
                                       reference_number="OLD-7")])
        assert result["created"] == 0


def test_the_national_id_is_enough(clinic):
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود", national_id="29001011234567")])
        result = _import(clinic, [_row("زياد محمود سعيد",
                                       national_id="29001011234567")])
        assert result["created"] == 0


def test_the_name_alone_is_not_enough(clinic):
    """Two children called "محمد أحمد" walk into an Egyptian clinic every
    week. Merging them on the name would lose one child's whole history."""
    with clinic["app"].app_context():
        _import(clinic, [_row("محمد أحمد", dob="2020-01-01")])
        result = _import(clinic, [_row("محمد أحمد", dob="2018-07-03")])
        assert result["created"] == 1


def test_the_birthday_alone_is_not_enough(clinic):
    """A clinic sees several children born on the same day."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود", dob="2020-01-01")])
        result = _import(clinic, [_row("حسن إبراهيم", dob="2020-01-01")])
        assert result["created"] == 1


def test_the_hamza_does_not_make_a_second_file(clinic):
    """"أحمد" and "احمد" are one child and two strings — whichever keyboard
    the typist had must not decide whether a file is duplicated."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد أحمد سعيد")])
        result = _import(clinic, [_row("زياد احمد سعيد")])
        assert result["created"] == 0


def test_a_file_number_is_not_matched_against_a_national_id(clinic):
    """The keys are namespaced. A clinic whose file numbers are long digits
    must not have one collide with somebody's national ID."""
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود", reference_number="29001011234567")])
        result = _import(clinic, [_row("حسن إبراهيم",
                                       national_id="29001011234567")])
        assert result["created"] == 1


# ============================================== twice in one file ===========
def test_a_child_listed_twice_in_one_sheet_is_imported_once(clinic):
    """The commoner half of the problem: an export from an old program often
    gives a row per visit rather than a row per child."""
    with clinic["app"].app_context():
        before = _count(clinic)          # the fixture's own child
        result = _import(clinic, [_row("زياد محمود سعيد"),
                                  _row("زياد محمود سعيد"),
                                  _row("زياد محمود سعيد")])
        assert result["created"] == 1
        assert _count(clinic) == before + 1
        assert [s["twin"] for s in result["skipped"]] == [2, 2], \
            "the duplicate rows do not say which line they repeat"


# ============================================== before it runs ==============
def test_the_preview_says_which_rows_are_already_here(clinic):
    """Counting afterwards is too late: somebody about to import 900 rows
    needs to know that 850 of them are already in the register."""
    from app.blueprints.patients.routes import _analyze_rows

    # ``_analyze_rows`` writes its reasons in the user's language, so it needs
    # a request to read the language from.
    with clinic["app"].test_request_context("/"):
        _import(clinic, [_row("زياد محمود سعيد")])

        preview, valid = _analyze_rows([_row("زياد محمود سعيد"),
                                        _row("عمر محمود سعيد")])
        assert valid == 1, "the preview still counts the existing row as new"
        assert preview[0]["duplicate"] is True
        assert preview[0]["ok"] is False
        assert preview[1]["duplicate"] is False


def test_the_preview_catches_a_repeat_inside_the_file(clinic):
    from app.blueprints.patients.routes import _analyze_rows

    # ``_analyze_rows`` writes its reasons in the user's language, so it needs
    # a request to read the language from.
    with clinic["app"].test_request_context("/"):
        preview, valid = _analyze_rows([_row("زياد محمود سعيد"),
                                        _row("زياد محمود سعيد")])
        assert valid == 1
        assert [p["duplicate"] for p in preview] == [False, True]


def test_a_broken_row_is_still_an_error_not_a_duplicate(clinic):
    """The two reasons a row is skipped are not the same thing, and a sheet
    with no dates of birth must not read as "all already here"."""
    from app.blueprints.patients.routes import _analyze_rows

    # ``_analyze_rows`` writes its reasons in the user's language, so it needs
    # a request to read the language from.
    with clinic["app"].test_request_context("/"):
        preview, valid = _analyze_rows([{"full_name": "زياد", "gender": "male"}])
        assert valid == 0
        assert preview[0]["duplicate"] is False
        assert preview[0]["reason"]


# ============================================== and nothing is overwritten ==
def test_an_existing_file_is_left_exactly_as_it_is(clinic):
    """A clinic corrects a name in the program, then re-uploads the old sheet.
    The correction must survive."""
    from app.models import Patient

    db = clinic["db"]
    with clinic["app"].app_context():
        _import(clinic, [_row("زياد محمود", reference_number="OLD-7")])
        patient = Patient.query.filter_by(reference_number="OLD-7").one()
        patient.notes = "حساسية بنسلين"
        db.session.commit()

        _import(clinic, [_row("زياد محمود", reference_number="OLD-7",
                              notes="")])
        assert Patient.query.filter_by(reference_number="OLD-7").one().notes \
            == "حساسية بنسلين"
