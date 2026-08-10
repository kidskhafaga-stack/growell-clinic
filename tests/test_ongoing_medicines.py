"""What a child is already on, and the check that could not see it.

The clinic has carried ``chronic_diseases`` as free text for a long time — the
asthma, the epilepsy, the diabetes. It never carried the **medicines**, and
those are the half that interacts with what the doctor is about to write.

**The concrete failure this closes.** ``rx_safety.check`` paired interactions
among the drugs in the prescription being written and nothing else. A child on
carbamazepine for epilepsy, handed a macrolide for a chest infection, produced
no warning at all: the carbamazepine was prescribed months ago by somebody
else and was never in the list. That is the test at the centre of this file,
and it fails without the feature.

**Stopping is not deleting.** A medicine the child was on until March explains
a result, a rash, a decision somebody else made. Removing the row destroys
that and leaves the file reading as though the drug was never given. So a stop
writes a date and a name and the row stays — and a second stop does not move
the first one's date, because a double-click on a slow screen must not quietly
rewrite the record.

**A row nobody could link is still worth having.** Parents say "the white
syrup". That row cannot join an interaction check and it can still stop the
next doctor starting a second one. So free text is accepted and the screen is
honest about which rows the program can reason about, rather than implying a
check that cannot happen.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def _generic(clinic, name_en, name_ar):
    with clinic["app"].app_context():
        from app.models import GenericDrug
        db = clinic["db"]
        row = GenericDrug(name_en=name_en, name_ar=name_ar, is_active=True)
        db.session.add(row)
        db.session.commit()
        return row.id


def _interaction(clinic, a, b):
    with clinic["app"].app_context():
        from app.models import DrugInteraction
        db = clinic["db"]
        db.session.add(DrugInteraction(generic_a_id=a, generic_b_id=b,
                                       severity="severe", is_active=True,
                                       note="خطر"))
        db.session.commit()


# --- the failure this closes ----------------------------------------------

def test_a_drug_the_child_is_already_on_is_checked_against_the_new_one(clinic):
    """The centre of the file.

    Carbamazepine for epilepsy, written months ago by a neurologist. A
    macrolide for a chest infection, written today. The interaction is real,
    and before this the program could not see it — the carbamazepine was
    nowhere in the list it was pairing.
    """
    carba = _generic(clinic, "carbamazepine", "كاربامازيبين")
    macro = _generic(clinic, "clarithromycin", "كلاريثرومايسين")
    _interaction(clinic, carba, macro)

    with clinic["app"].app_context():
        from app.models import GenericDrug, Patient
        from app.utils import patient_meds as meds
        from app.utils.rx_safety import check

        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        meds.add(patient, "تجريتول", generic_id=carba, reason="صرع")

        written = [{"name": "كلاسيد", "generic": db.session.get(GenericDrug, macro)}]
        result = check(written, patient=patient)

        assert result["interactions"], (
            "the child's ongoing epilepsy drug was invisible to the check")
        assert result["has_warnings"] is True


def test_a_stopped_medicine_no_longer_triggers_it(clinic):
    """It has to stop counting, or every past drug warns forever."""
    carba = _generic(clinic, "carbamazepine", "كاربامازيبين")
    macro = _generic(clinic, "clarithromycin", "كلاريثرومايسين")
    _interaction(clinic, carba, macro)

    with clinic["app"].app_context():
        from app.models import GenericDrug, Patient
        from app.utils import patient_meds as meds
        from app.utils.rx_safety import check

        db = clinic["db"]
        patient = db.session.get(Patient, clinic["ids"]["child"])
        row = meds.add(patient, "تجريتول", generic_id=carba)
        meds.stop(row)

        written = [{"name": "كلاسيد", "generic": db.session.get(GenericDrug, macro)}]
        assert check(written, patient=patient)["interactions"] == []


def test_the_check_says_which_ingredients_came_from_the_file(clinic):
    """"Interacts with something" is dismissed; "interacts with the
    carbamazepine he is on" is acted on."""
    carba = _generic(clinic, "carbamazepine", "كاربامازيبين")
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds
        from app.utils.rx_safety import check

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        meds.add(patient, "تجريتول", generic_id=carba)
        assert check([], patient=patient)["ongoing_ids"] == [carba]


def test_no_patient_is_not_a_crash(clinic):
    """The writer runs this before a patient is chosen."""
    with clinic["app"].app_context():
        from app.utils.rx_safety import check

        assert check([], patient=None)["ongoing_ids"] == []


# --- stopping is not deleting ---------------------------------------------

def test_stopping_keeps_the_row(clinic):
    with clinic["app"].app_context():
        from app.models import Patient, PatientMedication
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        row = meds.add(patient, "فنتولين")
        meds.stop(row, reason="خلصت المدة")

        kept = clinic["db"].session.get(PatientMedication, row.id)
        assert kept is not None, "the medicine was deleted rather than stopped"
        assert kept.stopped_on is not None
        assert kept.stop_reason == "خلصت المدة"
        assert kept.is_current is False


def test_stopping_twice_does_not_move_the_date(clinic):
    """A double-click on a slow screen must not rewrite the record."""
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        row = meds.add(patient, "فنتولين")
        meds.stop(row, on=date.today() - timedelta(days=30), reason="الأول")
        first = row.stopped_on
        meds.stop(row, on=date.today(), reason="التاني")

        assert row.stopped_on == first
        assert row.stop_reason == "الأول"


def test_a_stopped_medicine_is_still_in_the_history(clinic):
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        meds.stop(meds.add(patient, "قديم"))
        meds.add(patient, "حالي")

        assert [m.name for m in meds.current(patient)] == ["حالي"]
        assert {m.name for m in meds.history(patient)} == {"قديم", "حالي"}


# --- free text is accepted, and says so -----------------------------------

def test_a_medicine_nobody_could_link_is_still_recorded(clinic):
    """Parents say "the white syrup"."""
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        row = meds.add(patient, "شراب أبيض")
        assert row is not None
        assert row.generic_id is None
        assert meds.ingredient_ids(patient) == [], (
            "an unidentified medicine is being fed to the interaction check")


def test_a_medicine_needs_a_name(clinic):
    with clinic["app"].app_context():
        from app.models import Patient
        from app.utils import patient_meds as meds

        patient = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        assert meds.add(patient, "   ") is None


# --- the screen -----------------------------------------------------------

def test_the_doctor_can_record_one(clinic):
    doc = clinic["sign_in"]("doc")
    response = doc.post(f"/patients/{clinic['ids']['child']}/medications",
                        data={"name": "تجريتول", "dose": "200mg",
                              "frequency": "مرتين", "reason": "صرع"},
                        follow_redirects=True)
    assert response.status_code == 200

    with clinic["app"].app_context():
        from app.models import PatientMedication
        row = PatientMedication.query.filter_by(name="تجريتول").first()
        assert row is not None
        assert row.dose == "200mg"
        assert row.added_by is not None, "nobody is recorded as having said this"


def test_it_shows_on_the_profile(clinic):
    doc = clinic["sign_in"]("doc")
    doc.post(f"/patients/{clinic['ids']['child']}/medications",
             data={"name": "تجريتول", "reason": "صرع"}, follow_redirects=True)
    body = doc.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "تجريتول" in body
    assert 'id="meds"' in body


def test_the_front_desk_does_not_see_the_list(clinic):
    """A child's epilepsy or psychiatric medicines are not front-desk
    information — the section sits behind the same capability as the
    allergy banner above it."""
    doc = clinic["sign_in"]("doc")
    doc.post(f"/patients/{clinic['ids']['child']}/medications",
             data={"name": "تجريتول"}, follow_redirects=True)

    body = clinic["sign_in"]("desk").get(
        f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "تجريتول" not in body


def test_stopping_from_the_screen_works(clinic):
    doc = clinic["sign_in"]("doc")
    doc.post(f"/patients/{clinic['ids']['child']}/medications",
             data={"name": "فنتولين"}, follow_redirects=True)
    with clinic["app"].app_context():
        from app.models import PatientMedication
        med_id = PatientMedication.query.filter_by(name="فنتولين").first().id

    doc.post(f"/patients/medications/{med_id}/stop",
             data={"stop_reason": "خلاص"}, follow_redirects=True)

    with clinic["app"].app_context():
        from app.models import PatientMedication
        row = clinic["db"].session.get(PatientMedication, med_id)
        assert row.is_current is False


@pytest.mark.parametrize("table", ["patient_medications"])
def test_the_table_is_created_by_create_all(clinic, table):
    """A new *table* needs no ADDITIONS entry — but it does need to exist."""
    with clinic["app"].app_context():
        from sqlalchemy import inspect

        assert table in inspect(clinic["db"].engine).get_table_names()
