"""Correcting a dose the program only *inferred*.

Reported as the reason the import needs a way out: *"the doctor sees he had 2
with me and one outside and the booster with me"*.

The old program's file holds what happened **at this clinic**. Dose numbers were
worked out from the order of those dates, so a child who had two doses here, one
somewhere else, and the booster here comes out numbered 1, 2, 3 when they are
really 1, 3, 4. Nothing in the data can see the gap — no amount of cleverness
recovers a dose that was never written down here.

So the inference is a starting point the doctor overrides. Without that, the
imported history is a wall a doctor cannot fix, and a clinic that cannot fix its
own records goes back to the program it came from.

And the other half: an imported dose has to be a **real vaccination record**.
The schedule, the reminders and the certificate all read ``PatientVaccine`` — a
dose that stays outside that table is history the program can show and cannot
use, and the reminder screen would still chase the child for a dose they had in
2023.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def dose(clinic):
    """One recorded dose, as an import would have left it."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        row = PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=2, event_type="given",
            given_date=date(2023, 5, 1), import_batch_id=7)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _dose(clinic, pv_id):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        row = clinic["db"].session.get(PatientVaccine, pv_id)
        return {"number": row.dose_number, "date": row.given_date,
                "outside": row.given_outside, "place": row.outside_place,
                "batch": row.import_batch_id}


# ==================================================== the correction itself =
def test_the_dose_number_can_be_changed(dose, boss, clinic):
    """The reported case: two here, one outside, then the booster. The import
    numbers them 1, 2, 3 and they are really 1, 3, 4."""
    boss.post(f"/vaccinations/dose/{dose}/correct",
              data={"dose_number": "3"}, follow_redirects=True)
    assert _dose(clinic, dose)["number"] == 3


def test_a_dose_can_be_marked_as_given_elsewhere(dose, boss, clinic):
    """It stays in the child's record — so the course is not restarted — while
    saying this clinic did not give it, which is what the stock and the money
    must not assume."""
    boss.post(f"/vaccinations/dose/{dose}/correct", data={
        "dose_number": "2", "given_outside": "1",
        "outside_place": "وحدة صحة حكومية"}, follow_redirects=True)
    row = _dose(clinic, dose)
    assert row["outside"] is True
    assert row["place"] == "وحدة صحة حكومية"


def test_unticking_outside_clears_the_place(dose, boss, clinic):
    """A place left behind on a dose no longer marked outside is a line on a
    certificate that contradicts itself."""
    boss.post(f"/vaccinations/dose/{dose}/correct", data={
        "dose_number": "2", "given_outside": "1", "outside_place": "مكان"},
        follow_redirects=True)
    boss.post(f"/vaccinations/dose/{dose}/correct",
              data={"dose_number": "2"}, follow_redirects=True)
    row = _dose(clinic, dose)
    assert row["outside"] is False and row["place"] is None


def test_the_date_can_be_corrected(dose, boss, clinic):
    boss.post(f"/vaccinations/dose/{dose}/correct", data={
        "dose_number": "2", "given_date": "2023-06-15"}, follow_redirects=True)
    assert _dose(clinic, dose)["date"] == date(2023, 6, 15)


def test_a_bad_date_is_ignored_rather_than_wiping_the_good_one(dose, boss,
                                                               clinic):
    boss.post(f"/vaccinations/dose/{dose}/correct", data={
        "dose_number": "2", "given_date": "not-a-date"}, follow_redirects=True)
    assert _dose(clinic, dose)["date"] == date(2023, 5, 1)


def test_two_doses_cannot_be_given_the_same_number(dose, boss, clinic):
    """A duplicate number would make the course read as complete when it is
    not — and the schedule would stop asking for a dose the child still needs."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=1, event_type="given",
            given_date=date(2023, 3, 1)))
        clinic["db"].session.commit()

    boss.post(f"/vaccinations/dose/{dose}/correct",
              data={"dose_number": "1"}, follow_redirects=True)
    assert _dose(clinic, dose)["number"] == 2, "the clash was accepted"


def test_a_correction_is_recorded(dose, boss, clinic):
    """Changing a child's vaccination record is not a quiet edit."""
    from app.models import ActivityLog

    boss.post(f"/vaccinations/dose/{dose}/correct",
              data={"dose_number": "3"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert ActivityLog.query.filter_by(action="vaccine.correct").count() == 1


# ================================================= it shows in the file =====
def test_the_patient_file_offers_the_correction(dose, boss, clinic):
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.correct") in body
    assert f"/vaccinations/dose/{dose}/correct" in body


def test_an_imported_dose_says_so(dose, boss, clinic):
    """The doses whose numbering was inferred rather than observed are exactly
    the ones a doctor may need to look at."""
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.imported") in body


def test_a_dose_recorded_here_is_not_labelled_imported(clinic, boss):
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=1, event_type="given",
            given_date=date(2023, 3, 1)))
        clinic["db"].session.commit()

    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    with clinic["app"].test_request_context("/"):
        from app.i18n import t
        assert t("vaccinations.imported") not in body


def test_given_outside_is_shown_on_the_dose(dose, boss, clinic):
    boss.post(f"/vaccinations/dose/{dose}/correct", data={
        "dose_number": "2", "given_outside": "1",
        "outside_place": "وحدة صحة حكومية"}, follow_redirects=True)
    body = boss.get(f"/vaccinations/{clinic['ids']['child']}").get_data(as_text=True)
    assert "وحدة صحة حكومية" in body


# ============================== an imported dose is a real vaccination record
def test_the_schedule_counts_an_imported_dose(dose, clinic):
    """The half that makes the import worth doing. The schedule reads
    PatientVaccine, so a dose left outside that table is history the program
    can show and cannot use — and the reminder screen would still chase the
    child for a dose they had in 2023."""
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        plan = patient_plan(patient)
        pcv = [v for v in plan if v["vaccine"].id == clinic["ids"]["pcv"]][0]
        done = [d for d in pcv["doses"] if d["status"] == "done"]
    assert done, "the imported dose does not count toward the schedule"


def test_the_reminder_does_not_chase_a_dose_already_imported(dose, clinic):
    from app.utils.vaccine_due import due_list

    with clinic["app"].app_context():
        rows = due_list()
    assert all(r["dose_number"] != 2 for r in rows
               if r["vaccine"].id == clinic["ids"]["pcv"])


def test_an_imported_dose_does_not_touch_the_fridge(dose, clinic):
    """The vial was used years ago at another program. Deducting it now would
    invent a stock movement that never happened here."""
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        row = clinic["db"].session.get(PatientVaccine, dose)
        assert row.inventory_id is None


def test_a_dose_the_clinic_recorded_is_not_overwritten_by_an_import(clinic):
    """A dose the nurse entered by hand outranks one inferred from dates."""
    from app.blueprints.patients.routes import _record_imported_doses
    from app.models import PatientVaccine

    with clinic["app"].app_context():
        clinic["db"].session.add(PatientVaccine(
            patient_id=clinic["ids"]["child"], vaccine_id=clinic["ids"]["pcv"],
            brand_id=clinic["ids"]["brand"], dose_number=1, event_type="given",
            given_date=date(2023, 3, 1), lot_number="TYPED-BY-HAND"))
        clinic["db"].session.commit()

        made = _record_imported_doses([{
            "patient_id": clinic["ids"]["child"],
            "vaccine_brand_id": clinic["ids"]["brand"], "dose_number": 1,
            "service_date": date(2023, 3, 1)}], batch_id=9)
        clinic["db"].session.commit()

        rows = PatientVaccine.query.filter_by(
            patient_id=clinic["ids"]["child"], dose_number=1).all()
    assert made == 0
    assert len(rows) == 1 and rows[0].lot_number == "TYPED-BY-HAND"


def test_both_languages_carry_the_new_words(clinic):
    import json

    root = os.path.join(os.path.dirname(__file__), "..")
    for lang in ("ar", "en"):
        with open(os.path.join(root, "app", "i18n", "locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            data = json.load(fh)
        for key in ("correct", "imported", "imported_hint", "dose_corrected"):
            assert data["vaccinations"].get(key), f"{lang}.vaccinations.{key}"
