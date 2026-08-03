"""Taking one import back — and nothing else.

Ten thousand rows written against a clinic's real data needs a way back, and
the only kind worth having is one that is **exact**. Every row an import creates
carries its batch, so undoing removes what that import added and leaves
untouched everything the clinic has entered or corrected since.

The judgement in here is what an undo must *refuse* to delete. A dose the doctor
has since corrected — renumbered, redated, marked as given elsewhere — is their
record now, not the import's. Throwing it away would discard the very review the
import was built to invite, which is the one thing that would make a clinic stop
trusting the feature.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def imported(clinic):
    """One import: two history rows and two vaccination records."""
    from app.models import ImportBatch, ImportedService, PatientVaccine

    with clinic["app"].app_context():
        db = clinic["db"]
        batch = ImportBatch(kind="history", filename="old.xlsx",
                            created_by=clinic["ids"]["admin"], rows_total=2,
                            rows_added=2)
        db.session.add(batch)
        db.session.flush()
        for n, when in ((1, date(2023, 3, 1)), (2, date(2023, 6, 1))):
            db.session.add(ImportedService(
                batch_id=batch.id, patient_id=clinic["ids"]["child"],
                service_date=when, source_name="Prevenar", price=900,
                vaccine_brand_id=clinic["ids"]["brand"], dose_number=n,
                source_key=f"r:{n}"))
            db.session.add(PatientVaccine(
                patient_id=clinic["ids"]["child"],
                vaccine_id=clinic["ids"]["pcv"],
                brand_id=clinic["ids"]["brand"], dose_number=n,
                given_date=when, event_type="given",
                import_batch_id=batch.id))
        db.session.commit()
        return batch.id


def _counts(clinic):
    from app.models import ImportedService, PatientVaccine

    with clinic["app"].app_context():
        return {
            "history": ImportedService.query.count(),
            "doses": PatientVaccine.query.count(),
        }


# =============================================================== the undo ===
def test_an_import_can_be_taken_back(imported, boss, clinic):
    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    assert _counts(clinic) == {"history": 0, "doses": 0}


def test_it_removes_only_that_import(imported, boss, clinic):
    """A second import's rows are not this import's to delete."""
    from app.models import ImportBatch, ImportedService

    with clinic["app"].app_context():
        db = clinic["db"]
        other = ImportBatch(kind="history", filename="newer.xlsx",
                            created_by=clinic["ids"]["admin"], rows_added=1)
        db.session.add(other)
        db.session.flush()
        db.session.add(ImportedService(
            batch_id=other.id, patient_id=clinic["ids"]["child"],
            service_date=date(2024, 1, 1), source_name="كشف", price=200,
            source_key="r:99"))
        db.session.commit()

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    assert _counts(clinic)["history"] == 1


def test_what_the_clinic_typed_itself_is_never_touched(imported, boss, clinic):
    """It carries no batch, so an undo has no claim on it."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["opv"],
            brand_id=clinic["ids"]["gov_brand"], dose_number=1,
            given_date=date(2024, 5, 1), event_type="given"))
        clinic["db"].session.commit()

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    assert _counts(clinic)["doses"] == 1


def test_a_dose_the_doctor_corrected_is_kept(imported, boss, clinic):
    """Renumbered, redated or marked given elsewhere, it is the doctor's record
    now — not the import's. Deleting it would throw away the review the whole
    import was built to invite."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        dose = PatientVaccine.query.filter_by(dose_number=2).one()
        dose.given_outside = True
        dose.outside_place = "وحدة صحة حكومية"
        clinic["db"].session.commit()

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)

    with clinic["app"].app_context():
        left = PatientVaccine.query.all()
    assert len(left) == 1
    assert left[0].outside_place == "وحدة صحة حكومية"


def test_a_kept_dose_stops_belonging_to_the_import(imported, boss, clinic):
    """Otherwise undoing twice would finally delete it."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        dose = PatientVaccine.query.filter_by(dose_number=2).one()
        dose.given_outside = True
        clinic["db"].session.commit()

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    with clinic["app"].app_context():
        assert PatientVaccine.query.one().import_batch_id is None


# ========================================================= the record of it =
def test_the_batch_row_survives_the_undo(imported, boss, clinic):
    """"This import was undone, by whom and when" is part of the file's own
    history — a clinic asking six months later why a decade of vaccinations is
    missing deserves an answer."""
    from app.models import ImportBatch

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    with clinic["app"].app_context():
        batch = clinic["db"].session.get(ImportBatch, imported)
        assert batch is not None
        assert batch.notes == "undone"
        assert batch.rows_added == 0


def test_the_undo_is_logged(imported, boss, clinic):
    from app.models import ActivityLog

    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="history.import.undo").count() == 1


def test_undoing_twice_is_refused_rather_than_repeated(imported, boss, clinic):
    for _ in range(2):
        boss.post(f"/patients/import/history/batches/{imported}/undo",
                  follow_redirects=True)
    from app.models import ActivityLog

    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(
            action="history.import.undo").count() == 1


# ============================================================== the screen ==
def test_the_imports_are_listed(imported, boss):
    body = boss.get("/patients/import/history/batches").get_data(as_text=True)
    assert "old.xlsx" in body


def test_the_list_offers_the_undo(imported, boss, clinic):
    body = boss.get("/patients/import/history/batches").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.undo") in body
    assert f"/batches/{imported}/undo" in body


def test_an_undone_import_is_not_offered_again(imported, boss, clinic):
    boss.post(f"/patients/import/history/batches/{imported}/undo",
              follow_redirects=True)
    body = boss.get("/patients/import/history/batches").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.undone_badge") in body
    assert f"/batches/{imported}/undo" not in body


def test_the_import_screen_links_to_the_list(clinic, boss):
    body = boss.get("/patients/import/history").get_data(as_text=True)
    assert "/patients/import/history/batches" in body


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("batches_title", "batches_hint", "undo", "undo_confirm",
                    "undone", "undone_badge", "no_batches", "already_undone"):
            assert data["history_import"].get(key), f"{lang}.history_import.{key}"


# ================================= the imported services, in the patient file
@pytest.fixture()
def in_file(clinic):
    """A plain service brought across — كشف, not a vaccine."""
    from app.models import ImportedService

    with clinic["app"].app_context():
        row = ImportedService(
            patient_id=clinic["ids"]["child"], service_date=date(2019, 4, 2),
            source_name="كشف", price=80, source_key="r:500")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def test_the_imported_services_appear_in_the_patient_file(in_file, boss, clinic):
    """They were stored and shown nowhere. The vaccinations among an import
    become vaccination records so they surface; the plain services — which are
    most of a real export — had no screen at all, which made "the clinic does
    not lose its history" only half true."""
    body = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "كشف" in body
    assert "2019-04-02" in body


def test_the_tab_only_appears_when_there_is_history(clinic, boss):
    """An empty tab labelled "history" on every patient file is furniture."""
    body = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.in_file") not in body


def test_a_line_can_be_corrected(in_file, boss, clinic):
    """Ten years of somebody else's data has wrong dates and wrong prices, and
    a clinic that cannot fix a line in its own file does not trust the file."""
    from app.models import ImportedService

    boss.post(f"/patients/imported/{in_file}/edit", data={
        "service_date": "2019-04-05", "source_name": "كشف متابعة",
        "price": "120"}, follow_redirects=True)

    with clinic["app"].app_context():
        row = clinic["db"].session.get(ImportedService, in_file)
        assert row.service_date == date(2019, 4, 5)
        assert row.source_name == "كشف متابعة"
        assert row.price == 120


def test_a_line_can_be_removed(in_file, boss, clinic):
    """For the single row that should never have been there — a duplicate in
    the old program, a service billed to the wrong child years ago."""
    from app.models import ImportedService

    boss.post(f"/patients/imported/{in_file}/delete", follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(ImportedService, in_file) is None


def test_correcting_a_line_is_recorded(in_file, boss, clinic):
    from app.models import ActivityLog

    boss.post(f"/patients/imported/{in_file}/edit",
              data={"price": "150"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="history.row.edit").count() == 1


def test_a_bad_date_does_not_wipe_the_good_one(in_file, boss, clinic):
    from app.models import ImportedService

    boss.post(f"/patients/imported/{in_file}/edit",
              data={"service_date": "nonsense"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(
            ImportedService, in_file).service_date == date(2019, 4, 2)


def test_the_screen_says_the_money_is_history_not_takings(in_file, boss, clinic):
    """A decade of another program's revenue sitting in a patient file needs to
    say what it is, or somebody will reconcile against it."""
    body = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("history_import.in_file_hint") in body
