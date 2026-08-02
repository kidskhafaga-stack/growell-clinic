"""Bringing a clinic's case history across from the program it used before.

Built against a real export — 9,908 service rows for 1,402 patients, April 2016
to July 2026 — and the numbers in these tests come from measuring that file,
not from guessing at it.

**Speed was a requirement, not a nicety.** Reading the workbook takes about a
second; the database is what can make an import take an hour instead. Two rules
carry it, and both are tested here rather than merely written down:

* every lookup is done **in bulk, once** — resolving the patient per row is ten
  thousand round trips;
* rows are written with **one bulk insert and one commit** — committing per row
  on SQLite is a disk sync per row.

**And a second upload is compared, not appended.** A clinic re-uploads because
it added a few months, because it corrected something in the old program, or
because it cannot remember whether it already did. Every row lands in one of
four buckets and only new ones are written.
"""
import io
import os
import sys
from datetime import date, datetime, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

# The real export's header row, verbatim — including the summary block and the
# unnamed column that sit at the end of the data sheet.
REAL_HEADERS = ["م", "تاريخ الخدمة", "وقت الخدمة", "كود المريض", "اسم المريض",
                "كود الطبيب", "اسم الطبيب", "الخدمة", "فئة الخدمة",
                "نوع الخدمة", "القسم الطبي", "التعاقد", "نوع الدخول",
                "التمريض", "رقم الفاتورة", "نصيب الطبيب", "السعر الإجمالي",
                "شركات", "نقدي", "حالة المراجعة", "", "ملخص الفترة", "القيمة"]


def _row(serial, code, when, what, price=200, at=time(10, 30), name="طفل"):
    return [serial, datetime.combine(when, time()), at, code, name, 1,
            "احمد جمال قنديل", what, None, "الكشف", "GROWELL Clinic", "نقدي",
            "مستشفي", None, None, 80, price, 0, price, None, None, None, None]


def _sheet(rows, headers=None):
    """An .xlsx in memory, shaped like the clinic's own export."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers or REAL_HEADERS)
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
def old_patients(clinic):
    """Patients already imported, carrying the old program's codes."""
    from app.models import Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        for code in ("1001", "1002"):
            db.session.add(Patient(
                patient_number=f"PM-{code}", reference_number=code,
                full_name=f"طفل {code}", gender="male",
                date_of_birth=date(2020, 1, 1), is_active=True))
        db.session.commit()
    return clinic


def _upload(boss, buf, name="export.xlsx"):
    return boss.post("/patients/import/history",
                     data={"file": (buf, name)},
                     content_type="multipart/form-data")


def _map_and_preview(boss, token, mapping=None, links=None):
    """Walk the wizard: map the columns, confirm the names, land on preview."""
    data = {"token": token}
    default = {"source_row": 0, "service_date": 1, "service_time": 2,
               "patient_code": 3, "patient_name": 4, "doctor_name": 6,
               "service_name": 7, "client_category": 11, "doctor_share": 15,
               "price": 16, "paid_company": 17, "paid_cash": 18}
    for key, index in (mapping or default).items():
        data[f"col_{key}"] = str(index)
    linking = boss.post("/patients/import/history/link", data=data)
    confirm = {"token": token, "confirm": "1"}
    confirm.update(links or {})
    return boss.post("/patients/import/history/link", data=confirm)


def _token(body):
    import re

    found = re.search(r'name="token" value="([0-9a-f]+)"', body)
    assert found, "the screen did not carry a token forward"
    return found.group(1)


# =============================================== the columns map themselves ==
def test_the_real_export_maps_without_renaming_anything(clinic):
    """The whole premise: a clinic uploads what its program produced."""
    from app.utils.history_import import guess_mapping

    guess = guess_mapping(REAL_HEADERS)
    for key in ("source_row", "service_date", "service_time", "patient_code",
                "patient_name", "doctor_code", "doctor_name", "service_name",
                "client_category", "price", "doctor_share", "paid_cash",
                "paid_company"):
        assert guess[key] != "", f"{key} was not recognised"


def test_the_aliases_are_folded_the_same_way_the_headers_are(clinic):
    """Written by hand the alias table ends up half-folded — "فئة الخدمه" with
    the ة on one word and not the other — and a real header spelt "فئة الخدمة"
    then misses by one letter and the column goes silently unmapped."""
    from app.utils.history_import import guess_mapping

    assert guess_mapping(["فئة الخدمة"])["service_group"] == 0
    assert guess_mapping(["فئه الخدمه"])["service_group"] == 0


def test_a_differently_spelt_header_still_lands(clinic):
    from app.utils.history_import import guess_mapping

    guess = guess_mapping(["التاريخ", "رقم الملف", "البند", "المبلغ"])
    assert guess["service_date"] == 0
    assert guess["patient_code"] == 1
    assert guess["service_name"] == 2
    assert guess["price"] == 3


def test_an_english_export_maps_too(clinic):
    from app.utils.history_import import guess_mapping

    guess = guess_mapping(["Date", "Patient Code", "Service", "Total"])
    assert guess["service_date"] == 0 and guess["service_name"] == 2


# ======================================================= the summary block ==
def test_the_summary_block_is_recognised_as_not_data(clinic):
    """The export ends with "من تاريخ / إلى تاريخ / عدد الخدمات" laid out like
    columns inside the data sheet. Anything that trusts the header row imports
    them as though every service had a period summary."""
    from app.utils.history_import import summary_columns

    rows = [_row(i, "1001", date(2024, 3, 1), "كشف") for i in range(200)]
    rows[0][21], rows[0][22] = "من تاريخ", datetime(2016, 4, 11)
    rows[1][21], rows[1][22] = "إلى تاريخ", datetime(2026, 7, 27)
    rows[2][21], rows[2][22] = "عدد الخدمات", 9908

    found = summary_columns(REAL_HEADERS, rows)
    assert 21 in found and 22 in found


def test_a_real_column_is_not_mistaken_for_a_summary(clinic):
    """The detector must not eat a column that is merely at the end."""
    from app.utils.history_import import summary_columns

    rows = [_row(i, "1001", date(2024, 3, 1), "كشف") for i in range(200)]
    assert 16 not in summary_columns(REAL_HEADERS, rows)   # السعر الإجمالي


# ============================================================ the key =======
def test_the_source_row_number_is_the_key_when_there_is_one(clinic):
    from app.utils.history_import import source_key

    a = {"source_row": "7889", "patient_code": "1", "service_date": date(2024, 1, 1),
         "service_time": None, "service_name": "كشف", "price": 200}
    b = dict(a, price=999, service_name="حاجة تانية")
    assert source_key(a) == source_key(b), "the row number should identify it"


def test_without_a_row_number_the_fingerprint_identifies_it(clinic):
    from app.utils.history_import import source_key

    base = {"source_row": "", "patient_code": "1",
            "service_date": date(2024, 1, 1), "service_time": time(10, 0),
            "service_name": "كشف", "price": 200}
    assert source_key(base) == source_key(dict(base))
    assert source_key(base) != source_key(dict(base, price=250))


def test_the_time_is_part_of_the_fingerprint(clinic):
    """Dropping it produces 80 collisions on the real export — eighty rows of
    history read as duplicates of each other and silently lost."""
    from app.utils.history_import import source_key

    base = {"source_row": "", "patient_code": "1",
            "service_date": date(2024, 1, 1), "service_time": time(10, 0),
            "service_name": "كشف", "price": 200}
    twice = dict(base, service_time=time(17, 30))
    assert source_key(base) != source_key(twice)


def test_the_fingerprint_ignores_how_arabic_was_spelt(clinic):
    from app.utils.history_import import source_key

    base = {"source_row": "", "patient_code": "1",
            "service_date": date(2024, 1, 1), "service_time": time(10, 0),
            "service_name": "إستشارة", "price": 0}
    assert source_key(base) == source_key(dict(base, service_name="استشاره"))


# ==================================================== patients come first ===
def test_the_screen_says_patients_first_before_anything_is_uploaded(clinic, boss):
    body = boss.get("/patients/import/history").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.patients_first") in body
        assert t("history_import.patients_first_hint") in body


def test_a_row_for_an_unknown_patient_is_refused(old_patients, boss):
    reply = _upload(boss, _sheet([_row(1, "9999", date(2024, 3, 1), "كشف")]))
    body = _map_and_preview(boss, _token(reply.get_data(as_text=True))).get_data(as_text=True)
    assert "9999" in body


def test_the_missing_codes_are_listed_not_just_counted(old_patients, boss, clinic):
    """"412 rows rejected" tells a clinic nothing; the fix needs to know which."""
    rows = [_row(i, "8888", date(2024, 3, 1), "كشف", name="مفقود") for i in range(3)]
    reply = _upload(boss, _sheet(rows))
    body = _map_and_preview(boss, _token(reply.get_data(as_text=True))).get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.missing_patients") in body
    assert "مفقود" in body


def test_no_patient_is_invented_from_a_history_row(old_patients, boss, clinic):
    """The export has no date of birth, gender or phone — a patient built from
    it would be a half-record nobody asked for."""
    from app.models import Patient

    with clinic["app"].app_context():
        before = Patient.query.count()
    reply = _upload(boss, _sheet([_row(1, "9999", date(2024, 3, 1), "كشف")]))
    _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    with clinic["app"].app_context():
        assert Patient.query.count() == before


# ======================================================== the four buckets ==
def _counts(clinic, boss, rows):
    reply = _upload(boss, _sheet(rows))
    body = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    return body.get_data(as_text=True), _token(body.get_data(as_text=True))


def test_a_first_upload_is_all_new(old_patients, boss, clinic):
    from app.utils.history_import import build_rows
    from app.utils.history_match import classify

    rows = [_row(1, "1001", date(2024, 3, 1), "كشف"),
            _row(2, "1002", date(2024, 3, 2), "إستشارة", price=0)]
    with clinic["app"].app_context():
        records = build_rows(
            [[c if not isinstance(c, datetime) else c for c in r] for r in rows],
            {"source_row": 0, "service_date": 1, "service_time": 2,
             "patient_code": 3, "service_name": 7, "price": 16})
        _records, counts = classify(records)
    assert counts["new"] == 2 and counts["rejected"] == 0


def test_the_same_file_twice_adds_nothing(old_patients, boss, clinic):
    """The normal state of a second upload, and not an error."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2024, 3, 1), "كشف"),
            _row(2, "1002", date(2024, 3, 2), "إستشارة", price=0)]
    for _ in range(2):
        reply = _upload(boss, _sheet(rows))
        preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
        boss.post("/patients/import/history/commit",
                  data={"token": _token(preview.get_data(as_text=True))},
                  follow_redirects=True)

    with clinic["app"].app_context():
        assert ImportedService.query.count() == 2


def test_a_row_edited_in_the_old_program_shows_as_changed(old_patients, boss,
                                                          clinic):
    rows = [_row(1, "1001", date(2024, 3, 1), "كشف", price=200)]
    reply = _upload(boss, _sheet(rows))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    edited = [_row(1, "1001", date(2024, 3, 1), "كشف", price=350)]
    reply = _upload(boss, _sheet(edited))
    body = _map_and_preview(boss, _token(reply.get_data(as_text=True))).get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.st_changed") in body
    assert "350" in body and "200" in body, "the difference itself must be shown"


def test_a_changed_row_is_left_alone_unless_asked_for(old_patients, boss, clinic):
    """The clinic decides. Overwriting reviewed history on its behalf is the
    thing that makes people distrust an import."""
    from app.models import ImportedService

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف", price=200)]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف", price=350)]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        rows = ImportedService.query.all()
        assert len(rows) == 1 and rows[0].price == 200


def test_a_changed_row_is_taken_when_it_is_asked_for(old_patients, boss, clinic):
    from app.models import ImportedService

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف", price=200)]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف", price=350)]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True)),
                    "update_changed": "1"}, follow_redirects=True)

    with clinic["app"].app_context():
        rows = ImportedService.query.all()
        assert len(rows) == 1 and rows[0].price == 350


def test_a_file_that_repeats_a_row_imports_it_once(old_patients, boss, clinic):
    """Even on the very first upload — a source that exported a row twice must
    not become two pieces of history."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2024, 3, 1), "كشف"),
            _row(1, "1001", date(2024, 3, 1), "كشف")]
    reply = _upload(boss, _sheet(rows))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ImportedService.query.count() == 1


# ================================================== what actually got stored
def test_the_history_lands_on_the_patient(old_patients, boss, clinic):
    from app.models import ImportedService, Patient

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف")]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        row = ImportedService.query.one()
        patient = clinic["db"].session.get(Patient, row.patient_id)
        assert patient.reference_number == "1001"
        assert row.service_date == date(2024, 3, 1)
        assert row.source_name == "كشف"
        assert row.price == 200


def test_the_source_wording_is_kept_verbatim(old_patients, boss, clinic):
    """The clinic recognises its own wording, and a mapping got wrong later can
    be re-read from it."""
    from app.models import ImportedService

    name = "Synflorix - مكورات رئوية - PCV 10"
    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), name, price=300)]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ImportedService.query.one().source_name == name


def test_the_time_of_day_survives_the_wizard(old_patients, boss, clinic):
    """It travels through a JSON cache between screens. The patient import's
    serialiser formats dates as %Y-%m-%d, which would drop it — and the time is
    what tells two services on the same day apart."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2024, 3, 1), "كشف", at=time(9, 15)),
            _row(2, "1001", date(2024, 3, 1), "كشف", at=time(18, 45))]
    reply = _upload(boss, _sheet(rows))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        times = sorted(r.service_time for r in ImportedService.query.all())
        assert times == [time(9, 15), time(18, 45)]


def test_the_import_is_recorded_as_a_batch(old_patients, boss, clinic):
    """Ten thousand rows against real data needs a way back."""
    from app.models import ImportBatch

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف")]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        batch = ImportBatch.query.one()
        assert batch.rows_added == 1
        assert batch.filename == "export.xlsx"
        assert batch.created_by == clinic["ids"]["admin"]


def test_taking_a_decade_of_history_in_is_logged(old_patients, boss, clinic):
    from app.models import ActivityLog

    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف")]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="history.import").count() == 1


def test_the_money_does_not_become_an_invoice(old_patients, boss, clinic):
    """A decade of another program's takings replayed as live invoices would
    count ten years of revenue twice — in the reports and in the accountant's
    opening balances."""
    from app.models import Invoice

    with clinic["app"].app_context():
        before = Invoice.query.count()
    reply = _upload(boss, _sheet([_row(1, "1001", date(2024, 3, 1), "كشف")]))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert Invoice.query.count() == before


# ============================================================ speed =========
def test_the_lookups_are_done_in_bulk_not_per_row(clinic):
    """Ten thousand rows resolved one at a time is ten thousand round trips —
    the difference between an import somebody watches finish and one they
    assume has hung."""
    import inspect

    from app.utils import history_match

    source = inspect.getsource(history_match.classify)
    assert "query" not in source, "classify() must not touch the database"
    assert "patient_index" in source and "existing_keys" in source


def test_the_rows_are_written_in_one_bulk_insert(clinic):
    """Adding them one at a time costs a round trip each, and committing per
    row on SQLite costs a disk sync each."""
    import inspect

    from app.blueprints.patients import routes

    source = inspect.getsource(routes.history_import_commit)
    assert "bulk_insert_mappings" in source
    assert source.count("db.session.commit()") == 1


def test_ten_thousand_rows_are_classified_quickly(old_patients, clinic):
    """A real export is 9,908 rows. Measured, not assumed."""
    import time as clock

    from app.utils.history_import import build_rows
    from app.utils.history_match import classify

    raw = [[i, datetime(2024, 3, 1), time(10, 0), "1001", "طفل", 1, "د",
            "كشف", None, None, None, "نقدي", None, None, None, 80, 200, 0,
            200, None, None, None, None] for i in range(10000)]
    mapping = {"source_row": 0, "service_date": 1, "service_time": 2,
               "patient_code": 3, "service_name": 7, "price": 16}

    with clinic["app"].app_context():
        records = build_rows(raw, mapping)
        started = clock.time()
        _records, counts = classify(records)
        elapsed = clock.time() - started

    assert counts["new"] == 10000
    assert elapsed < 5, f"classifying 10,000 rows took {elapsed:.1f}s"


# ============================================================ the template ==
def test_a_template_can_be_downloaded(clinic, boss):
    reply = boss.get("/patients/import/history/template")
    assert reply.status_code == 200
    assert "attachment" in reply.headers["Content-Disposition"]


def test_the_template_is_not_required(clinic):
    """The real export maps without anybody renaming a column, and that has to
    stay the normal case rather than the lucky one."""
    from app.utils.history_import import guess_mapping

    guess = guess_mapping(REAL_HEADERS)
    mapped = sum(1 for v in guess.values() if v != "")
    assert mapped >= 13


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("title", "patients_first", "patients_first_hint",
                    "st_new", "st_same", "st_changed", "st_rejected",
                    "missing_patients", "commit", "done", "need_columns"):
            assert data["history_import"].get(key), f"{lang}.history_import.{key}"


# ================================================= the range, read off the file
def _span(clinic, rows):
    from app.utils.history_import import build_rows
    from app.utils.history_match import date_span

    mapping = {"source_row": 0, "service_date": 1, "service_time": 2,
               "patient_code": 3, "service_name": 7, "price": 16}
    with clinic["app"].app_context():
        return date_span(build_rows(rows, mapping))


def test_the_file_says_what_it_covers(clinic):
    """Read off the file rather than asked for. A clinic uploading ten years
    does not know its own export's first date to the day."""
    rows = [_row(1, "1001", date(2016, 4, 11), "كشف"),
            _row(2, "1001", date(2021, 6, 1), "كشف"),
            _row(3, "1001", date(2026, 7, 27), "كشف")]
    span = _span(clinic, rows)
    assert span["first"] == date(2016, 4, 11)
    assert span["last"] == date(2026, 7, 27)


def test_the_file_says_how_much_is_in_each_year(clinic):
    """Somebody choosing a range wants to see where the weight is."""
    rows = ([_row(i, "1001", date(2016, 4, 11), "كشف") for i in range(3)]
            + [_row(9 + i, "1001", date(2024, 4, 11), "كشف") for i in range(5)])
    years = {y["year"]: y["rows"] for y in _span(clinic, rows)["years"]}
    assert years == {2016: 3, 2024: 5}


def test_an_empty_file_has_no_span_rather_than_crashing(clinic):
    assert _span(clinic, [])["first"] is None


def test_everything_is_imported_when_no_range_is_given(old_patients, boss,
                                                       clinic):
    """The case that needs no thought: a clinic leaving its old program wants
    everything, and making it say so is a step that exists to be got wrong."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2016, 4, 11), "كشف"),
            _row(2, "1001", date(2024, 6, 1), "كشف")]
    reply = _upload(boss, _sheet(rows))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ImportedService.query.count() == 2


def test_a_range_keeps_only_what_falls_inside_it(old_patients, boss, clinic):
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2016, 4, 11), "قديم"),
            _row(2, "1001", date(2024, 6, 1), "جديد")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token)
    boss.post("/patients/import/history/commit", data={
        "token": _token(preview.get_data(as_text=True)),
        "from": "2020-01-01"}, follow_redirects=True)

    with clinic["app"].app_context():
        names = [r.source_name for r in ImportedService.query.all()]
    assert names == ["جديد"]


def test_both_ends_of_the_range_are_honoured(old_patients, boss, clinic):
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2016, 4, 11), "قديم"),
            _row(2, "1001", date(2021, 6, 1), "وسط"),
            _row(3, "1001", date(2026, 7, 27), "حديث")]
    reply = _upload(boss, _sheet(rows))
    preview = _map_and_preview(boss, _token(reply.get_data(as_text=True)))
    boss.post("/patients/import/history/commit", data={
        "token": _token(preview.get_data(as_text=True)),
        "from": "2020-01-01", "to": "2022-12-31"}, follow_redirects=True)

    with clinic["app"].app_context():
        assert [r.source_name for r in ImportedService.query.all()] == ["وسط"]


def test_a_row_outside_the_range_is_set_aside_not_rejected(clinic, old_patients):
    """Nothing is wrong with it — it simply was not asked for. Calling that an
    error would bury the rows that really are broken."""
    from app.utils.history_import import build_rows
    from app.utils.history_match import classify

    rows = [_row(1, "1001", date(2016, 4, 11), "قديم"),
            _row(2, "1001", date(2024, 6, 1), "جديد")]
    mapping = {"source_row": 0, "service_date": 1, "service_time": 2,
               "patient_code": 3, "service_name": 7, "price": 16}
    with clinic["app"].app_context():
        _records, counts = classify(build_rows(rows, mapping),
                                    start=date(2020, 1, 1))
    assert counts["out_of_range"] == 1
    assert counts["rejected"] == 0
    assert counts["new"] == 1


def test_a_broken_row_outside_the_range_still_reads_as_broken(clinic,
                                                              old_patients):
    """That is the thing the clinic has to act on."""
    from app.utils.history_import import build_rows
    from app.utils.history_match import classify

    rows = [_row(1, "9999", date(2016, 4, 11), "كشف")]     # unknown patient
    mapping = {"source_row": 0, "service_date": 1, "service_time": 2,
               "patient_code": 3, "service_name": 7, "price": 16}
    with clinic["app"].app_context():
        _records, counts = classify(build_rows(rows, mapping),
                                    start=date(2020, 1, 1))
    assert counts["rejected"] == 1 and counts["out_of_range"] == 0


def test_the_preview_shows_the_span_and_the_years(old_patients, boss, clinic):
    rows = [_row(1, "1001", date(2016, 4, 11), "كشف"),
            _row(2, "1001", date(2024, 6, 1), "كشف")]
    reply = _upload(boss, _sheet(rows))
    body = _map_and_preview(boss, _token(reply.get_data(as_text=True))).get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.span") in body
    assert "2016-04-11" in body and "2024-06-01" in body
    assert "2016" in body and "2024" in body


def test_the_range_survives_from_the_preview_to_the_import(old_patients, boss,
                                                           clinic):
    """Without it somebody narrows to one year, sees 400 rows, and imports ten
    thousand."""
    page = _read_template("patients", "history_preview.html")
    assert 'name="from" value="{{ f_from }}"' in page
    assert 'name="to" value="{{ f_to }}"' in page


def test_changing_the_range_does_not_ask_for_the_mapping_again(old_patients,
                                                               boss, clinic):
    """The mapping was submitted once and stored — coming back to narrow the
    dates must not send somebody through the column screen a second time."""
    rows = [_row(1, "1001", date(2016, 4, 11), "قديم"),
            _row(2, "1001", date(2024, 6, 1), "جديد")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    _map_and_preview(boss, token)

    again = boss.post("/patients/import/history/map",
                      data={"token": token, "from": "2020-01-01"})
    assert again.status_code == 200
    body = again.get_data(as_text=True)
    assert "جديد" in body


def _read_template(*parts):
    root = os.path.join(os.path.dirname(__file__), "..", "app", "templates")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ============================== the names become vaccines, and doses get numbers
@pytest.fixture()
def with_catalogue(old_patients):
    """The clinic's real vaccine catalogue, so names have something to hit."""
    from app.utils.vaccines import seed_vaccines

    with old_patients["app"].app_context():
        seed_vaccines()
        old_patients["db"].session.commit()
    return old_patients


def _brand(clinic, needle):
    from app.models import VaccineBrand

    with clinic["app"].app_context():
        return VaccineBrand.query.filter(VaccineBrand.name.ilike(f"%{needle}%")).first().id


def _link_index(boss, token, name):
    """Which link_N field on the screen belongs to ``name``."""
    import re

    body = boss.post("/patients/import/history/link",
                     data={"token": token}).get_data(as_text=True)
    for match in re.finditer(r'name="link_(\d+)"', body):
        pass
    return body


def test_the_linking_screen_lists_each_name_once(with_catalogue, boss):
    """Thousands of rows, few distinct names — that is what makes confirming
    them by hand possible at all."""
    rows = [_row(i, "1001", date(2024, 3, 1), "كشف") for i in range(5)]
    rows += [_row(10 + i, "1001", date(2024, 4, 1),
                  "Synflorix - مكورات رئوية - PCV 10") for i in range(3)]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))

    data = {"token": token, "col_source_row": "0", "col_service_date": "1",
            "col_service_time": "2", "col_patient_code": "3",
            "col_service_name": "7", "col_price": "16"}
    body = boss.post("/patients/import/history/link", data=data).get_data(as_text=True)
    assert body.count('name="link_') == 2, "one row per distinct name"
    assert "Synflorix" in body


def test_the_screen_proposes_the_catalogue_match(with_catalogue, boss, clinic):
    rows = [_row(1, "1001", date(2024, 3, 1), "Varivax-جديرى مائى")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    data = {"token": token, "col_service_date": "1", "col_patient_code": "3",
            "col_service_name": "7", "col_price": "16"}
    body = boss.post("/patients/import/history/link", data=data).get_data(as_text=True)

    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.conf_high") in body
    assert f'value="brand:{_brand(clinic, "Varivax")}" selected' in body


def test_a_confirmed_name_becomes_a_real_vaccine_on_the_record(with_catalogue,
                                                               boss, clinic):
    """The point of the screen. Without it the row is a piece of text with a
    price on it."""
    from app.models import ImportedService

    brand_id = _brand(clinic, "Varivax")
    rows = [_row(1, "1001", date(2024, 3, 1), "Varivax-جديرى مائى", price=400)]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={"link_0": f"brand:{brand_id}"})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        row = ImportedService.query.one()
        assert row.vaccine_brand_id == brand_id
        assert row.dose_number == 1


def test_a_name_left_as_a_plain_service_stays_one(with_catalogue, boss, clinic):
    """كشف and إستشارة are most of the file. Nothing should attach a vaccine
    to them."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2024, 3, 1), "كشف")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={"link_0": ""})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        row = ImportedService.query.one()
        assert row.vaccine_brand_id is None
        assert row.dose_number is None


def test_nothing_is_matched_without_the_clinic_confirming(with_catalogue, boss,
                                                          clinic):
    """A matcher that wrote its own guesses into ten years of vaccination
    records is one nobody could trust, and the case it gets wrong is a child
    recorded as having had a vaccine they did not."""
    from app.models import ImportedService

    rows = [_row(1, "1001", date(2024, 3, 1), "Varivax-جديرى مائى")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={"link_0": ""})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert ImportedService.query.one().vaccine_brand_id is None


def test_the_doses_are_numbered_across_the_whole_import(with_catalogue, boss,
                                                        clinic):
    from app.models import ImportedService

    brand_id = _brand(clinic, "Varivax")
    rows = [_row(1, "1001", date(2024, 6, 1), "Varivax-جديرى مائى"),
            _row(2, "1001", date(2023, 3, 1), "Varivax-جديرى مائى"),
            _row(3, "1001", date(2023, 9, 1), "Varivax-جديرى مائى")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={"link_0": f"brand:{brand_id}"})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        by_date = {r.service_date: r.dose_number
                   for r in ImportedService.query.all()}
    assert by_date == {date(2023, 3, 1): 1, date(2023, 9, 1): 2,
                       date(2024, 6, 1): 3}


def test_two_brands_of_one_vaccine_continue_the_same_course(with_catalogue,
                                                            boss, clinic):
    """Patient 1080 in the real export: Synflorix (PCV 10) three times, then
    Prevenar (PCV 13). Numbered per brand that fourth dose is "dose 1", and the
    schedule then chases the child for doses they have already had."""
    from app.models import ImportedService

    synflorix = _brand(clinic, "Synflorix")
    prevenar = _brand(clinic, "Prevenar 13")
    rows = [_row(1, "1001", date(2023, 3, 20), "Synflorix - مكورات رئوية - PCV 10"),
            _row(2, "1001", date(2023, 5, 27), "Synflorix - مكورات رئوية - PCV 10"),
            _row(3, "1001", date(2023, 7, 22), "Synflorix - مكورات رئوية - PCV 10"),
            _row(4, "1001", date(2024, 2, 21), "Prevenar - مكورات رؤية - PCV 13")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={
        "link_0": f"brand:{synflorix}", "link_1": f"brand:{prevenar}"})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        row = ImportedService.query.filter_by(
            vaccine_brand_id=prevenar).one()
        assert row.dose_number == 4, "the course restarted at the brand change"


def test_two_patients_do_not_share_a_course_through_the_import(with_catalogue,
                                                               boss, clinic):
    from app.models import ImportedService

    brand_id = _brand(clinic, "Varivax")
    rows = [_row(1, "1001", date(2023, 3, 1), "Varivax-جديرى مائى"),
            _row(2, "1002", date(2023, 9, 1), "Varivax-جديرى مائى")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    preview = _map_and_preview(boss, token, links={"link_0": f"brand:{brand_id}"})
    boss.post("/patients/import/history/commit",
              data={"token": _token(preview.get_data(as_text=True))},
              follow_redirects=True)

    with clinic["app"].app_context():
        assert sorted(r.dose_number for r in ImportedService.query.all()) == [1, 1]


def test_the_link_choices_survive_a_change_of_date_range(with_catalogue, boss,
                                                         clinic):
    """Narrowing the range must not silently drop what was just confirmed."""
    from app.models import ImportedService

    brand_id = _brand(clinic, "Varivax")
    rows = [_row(1, "1001", date(2016, 4, 11), "Varivax-جديرى مائى"),
            _row(2, "1001", date(2024, 6, 1), "Varivax-جديرى مائى")]
    reply = _upload(boss, _sheet(rows))
    token = _token(reply.get_data(as_text=True))
    _map_and_preview(boss, token, links={"link_0": f"brand:{brand_id}"})

    narrowed = boss.post("/patients/import/history/map",
                         data={"token": token, "from": "2020-01-01"})
    boss.post("/patients/import/history/commit",
              data={"token": _token(narrowed.get_data(as_text=True)),
                    "from": "2020-01-01"}, follow_redirects=True)

    with clinic["app"].app_context():
        row = ImportedService.query.one()
        assert row.vaccine_brand_id == brand_id
