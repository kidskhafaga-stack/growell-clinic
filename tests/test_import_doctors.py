"""Making a user for a doctor the file names and the clinic does not have.

The decision was taken with the plan; this is the button. The reason has not
changed: every report built for this feature joins on ``doctor_id`` — the
doctor filter on the invoices screen, the doctor column in the tax export, the
commission reports, the doctor statements. A name kept as text on the row falls
out of all of them, which leaves a clinic holding ten years of a doctor's work
that no report can see.

Three properties are what make it safe rather than merely convenient, and each
has a test here:

**The account cannot be used** — created inactive, random password, nobody
told. Creating one is not a way into the program.

**It is never automatic** — one option in a dropdown, and the preview names who
will be created before a single row is written. Backing out leaves nothing
behind.

**One person is one user** — grouped by the source's own doctor code, because a
name gets typed several ways across a decade and a user per spelling is exactly
the mess this is meant to prevent.
"""
import io
import os
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HEADERS = ["م", "تاريخ الخدمة", "كود المريض", "كود الطبيب", "اسم الطبيب",
           "الخدمة", "السعر الإجمالي"]


def _row(serial, when, what="كشف", code=1, doctor="احمد جمال قنديل"):
    return [serial, datetime.combine(when, time()), "1001", code, doctor,
            what, 200]


def _sheet(rows):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def old_patient(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        clinic["db"].session.add(Patient(
            patient_number="PM-1001", reference_number="1001",
            full_name="طفل 1001", gender="male",
            date_of_birth=date(2020, 1, 1), is_active=True))
        clinic["db"].session.commit()
    return clinic


MAPPING = {"col_source_row": "0", "col_service_date": "1",
           "col_patient_code": "2", "col_doctor_code": "3",
           "col_doctor_name": "4", "col_service_name": "5", "col_price": "6"}


def _token(body):
    import re

    found = re.search(r'name="token" value="([0-9a-f]+)"', body)
    assert found, "the screen did not carry a token forward"
    return found.group(1)


def _wizard(boss, rows, choice):
    """Upload, link with one doctor choice, preview. Returns (preview, token)."""
    reply = boss.post("/patients/import/history", data={"file": (_sheet(rows), "e.xlsx")},
                      content_type="multipart/form-data")
    token = _token(reply.get_data(as_text=True))
    boss.post("/patients/import/history/link", data={"token": token, **MAPPING})
    preview = boss.post("/patients/import/history/link", data={
        "token": token, "confirm": "1", "link_0": "", "doc_0": choice})
    return preview, _token(preview.get_data(as_text=True))


# ===================================================== the account it makes ==
def test_the_created_user_cannot_sign_in(clinic):
    """Inactive is the whole safety argument: creating an account for somebody
    who left in 2018 must not be a way into the program."""
    from app.utils.import_doctors import create_doctor

    with clinic["app"].app_context():
        user = create_doctor("احمد جمال قنديل")
        clinic["db"].session.commit()
        assert user.is_active is False


def test_the_created_user_is_a_practitioner(clinic):
    """Otherwise they never appear in the doctor pickers, and the history that
    was the reason for creating them is still filtered out."""
    from app.utils.import_doctors import create_doctor

    with clinic["app"].app_context():
        user = create_doctor("احمد جمال قنديل")
        clinic["db"].session.commit()
        assert user.role == "doctor" and user.is_practitioner is True


def test_the_file_name_is_what_the_clinic_will_read(clinic):
    from app.utils.import_doctors import create_doctor

    with clinic["app"].app_context():
        user = create_doctor("احمد جمال قنديل")
        clinic["db"].session.commit()
        assert user.full_name == "احمد جمال قنديل"


def test_two_doctors_never_collide_on_one_username(clinic):
    """An Arabic name yields no ASCII at all, so both fall back to the same
    stem — and a duplicate username is a failed import, not a warning."""
    from app.utils.import_doctors import create_all

    with clinic["app"].app_context():
        made = create_all(["احمد جمال", "محمد الخفاجي"])
        clinic["db"].session.commit()
        names = {u.username for u in made.values()}
    assert len(names) == 2


def test_an_existing_username_is_not_taken_over(clinic):
    """"boss" is somebody's login. Handing it to an imported doctor would lock
    a real person out of the program."""
    from app.utils.import_doctors import username_for

    assert username_for("Boss", {"boss"}) != "boss"


# ==================================================== one person, one user ===
def test_the_screen_groups_a_doctor_by_the_code_not_the_spelling(clinic):
    """The plan called this out: a name is typed several ways across ten years,
    and a row per spelling would offer the same person three times — then
    create three users out of them."""
    from app.utils.history_match import doctor_entries

    records = [{"doctor_code": "7", "doctor_name": "احمد جمال"},
               {"doctor_code": "7", "doctor_name": "أحمد جمال قنديل"},
               {"doctor_code": "9", "doctor_name": "سعاد"}]
    entries = doctor_entries(records)
    assert len(entries) == 2
    first = next(e for e in entries if e["code"] == "7")
    assert first["rows"] == 2
    assert len(first["names"]) == 2


def test_the_longest_spelling_is_the_one_offered(clinic):
    """It is the name a user will be created with, so it should be the full
    one rather than whichever row happened to come first."""
    from app.utils.history_match import doctor_entries

    entries = doctor_entries([{"doctor_code": "7", "doctor_name": "احمد"},
                              {"doctor_code": "7", "doctor_name": "احمد جمال قنديل"}])
    assert entries[0]["value"] == "احمد جمال قنديل"


def test_a_file_with_no_doctor_code_still_groups_by_name(clinic):
    """Not every export has one. Falling back to the name is worse and is
    still much better than nothing."""
    from app.utils.history_match import doctor_entries

    entries = doctor_entries([{"doctor_name": "احمد جمال"},
                              {"doctor_name": "احمد جمال"}])
    assert len(entries) == 1 and entries[0]["rows"] == 2


def test_a_row_with_no_doctor_at_all_is_not_a_doctor(clinic):
    from app.utils.history_match import doctor_entries

    assert doctor_entries([{"doctor_name": "", "doctor_code": ""}]) == []


# ============================================================== the screen ===
def test_the_link_screen_offers_to_create_one(boss, old_patient, clinic):
    reply = boss.post("/patients/import/history",
                      data={"file": (_sheet([_row(1, date(2024, 1, 1))]), "e.xlsx")},
                      content_type="multipart/form-data")
    body = boss.post("/patients/import/history/link", data={
        "token": _token(reply.get_data(as_text=True)),
        **MAPPING}).get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.make_user") in body


def test_matching_an_existing_user_stays_the_default(boss, old_patient, clinic):
    """Creating is what is left when nothing matches — the same rule the
    categories and the services follow."""
    from app.models import User

    with clinic["app"].app_context():
        name = clinic["db"].session.get(User, clinic["ids"]["doctor"]).full_name

    rows = [_row(1, date(2024, 1, 1), doctor=name)]
    reply = boss.post("/patients/import/history", data={"file": (_sheet(rows), "e.xlsx")},
                      content_type="multipart/form-data")
    body = boss.post("/patients/import/history/link", data={
        "token": _token(reply.get_data(as_text=True)),
        **MAPPING}).get_data(as_text=True)
    assert f'value="{clinic["ids"]["doctor"]}" selected' in body
    assert 'value="new" selected' not in body


def test_the_preview_names_who_will_be_created(boss, old_patient, clinic):
    """Creating users is the one part of this import that adds *people* to the
    clinic rather than history. It is named before it happens."""
    preview, _ = _wizard(boss, [_row(1, date(2024, 1, 1))], "new")
    body = preview.get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.will_create_users") in body
    assert "احمد جمال قنديل" in body


def test_nothing_is_created_until_the_import_runs(boss, old_patient, clinic):
    """Backing out at the preview must leave no half-made doctors behind."""
    from app.models import User

    _wizard(boss, [_row(1, date(2024, 1, 1))], "new")
    with clinic["app"].app_context():
        assert User.query.filter_by(full_name="احمد جمال قنديل").first() is None


# ================================================== and what the import does ==
def test_importing_creates_the_user_and_points_the_rows_at_them(boss,
                                                                old_patient,
                                                                clinic):
    from app.models import ImportedService, User

    _preview, token = _wizard(boss, [_row(1, date(2024, 1, 1))], "new")
    boss.post("/patients/import/history/commit", data={"token": token},
              follow_redirects=True)

    with clinic["app"].app_context():
        user = User.query.filter_by(full_name="احمد جمال قنديل").one()
        assert user.is_active is False
        assert ImportedService.query.one().doctor_id == user.id


def test_two_spellings_of_one_code_make_one_user(boss, old_patient, clinic):
    """The failure this is meant to prevent, tested end to end."""
    from app.models import User

    rows = [_row(1, date(2024, 1, 1), doctor="احمد جمال"),
            _row(2, date(2024, 2, 1), doctor="أحمد جمال قنديل")]
    _preview, token = _wizard(boss, rows, "new")
    boss.post("/patients/import/history/commit", data={"token": token},
              follow_redirects=True)

    with clinic["app"].app_context():
        made = User.query.filter_by(is_active=False, role="doctor").all()
        assert len(made) == 1
        assert made[0].full_name == "أحمد جمال قنديل"


def test_creating_a_user_is_written_to_the_activity_log(boss, old_patient,
                                                        clinic):
    """Somebody added a person to the clinic. That is not a silent event."""
    from app.models import ActivityLog

    _preview, token = _wizard(boss, [_row(1, date(2024, 1, 1))], "new")
    boss.post("/patients/import/history/commit", data={"token": token},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="history.doctor.create").count() == 1


def test_leaving_the_doctor_blank_creates_nobody(boss, old_patient, clinic):
    from app.models import ImportedService, User

    _preview, token = _wizard(boss, [_row(1, date(2024, 1, 1))], "")
    boss.post("/patients/import/history/commit", data={"token": token},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert User.query.filter_by(is_active=False).count() == 0
        assert ImportedService.query.one().doctor_id is None
