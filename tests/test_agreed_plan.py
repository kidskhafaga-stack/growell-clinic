"""The vaccines a doctor agreed on, and what agreeing changes.

Asked for as: *"if the doctor agreed with the family on certain vaccines for
this case, give those to the child as a reminder and let them stay with them."*

The program worked out what a child was due from their birthday and the doses
on file. Right for a schedule everybody follows, wrong for the part a clinic
sells: a two-year-old who had nothing here carried twenty-one suggestions,
because every optional vaccine they were old enough for looked equally like an
idea worth having, and nothing distinguished the three the family actually
agreed to from the eighteen nobody had mentioned.

**A plan is a promise, and the promise changes the sentence.** A course nobody
agreed on is a suggestion by age. The same course, once doctor and family have
settled on it, is something this clinic said it would do — so it can be late,
and being late is worth a message. That is the rule the program already had
for a course somebody had *started*, moved one step earlier: the agreement
counts, not only the first needle.

**It hides nothing.** Asked directly and answered directly: everything else
stays a suggestion for the child's age and condition. The plan raises what was
agreed; it does not narrow the file to it. That is the single assertion most
worth keeping here, because the tempting implementation — "the plan is now the
schedule" — quietly deletes the clinic's ability to notice anything it has not
already thought of.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()
    return clinic


def _child(clinic, days=730, tag="A1"):
    from app.extensions import db
    from app.models import Patient

    kid = Patient(patient_number=tag, full_name="طفل", gender="female",
                  date_of_birth=local_today() - timedelta(days=days),
                  is_active=True)
    db.session.add(kid)
    db.session.commit()
    return kid


def _agree(clinic, patient, code, outside=False):
    from app.extensions import db
    from app.models import Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    vaccine = Vaccine.query.filter_by(code=code).first()
    db.session.add(VaccinePlanItem(patient_id=patient.id,
                                   vaccine_id=vaccine.id,
                                   supplied_outside=outside))
    db.session.commit()
    return vaccine


def _states(plan, code):
    for v in plan:
        if v["vaccine"].code == code:
            return [d["status"] for d in v["doses"]]
    raise AssertionError(f"{code} is not in the plan")


# --------------------------------------------------- what agreeing changes

def test_an_agreed_course_can_be_late(seeded):
    """The whole feature in one assertion."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded)
        before = _states(patient_plan(kid), "PCV")
        assert set(before) == {"suggested"}, before

        _agree(seeded, kid, "PCV")
        after = _states(patient_plan(kid), "PCV")

    assert "overdue" in after, \
        f"a course the doctor agreed to is still only a suggestion: {after}"


def test_everything_else_stays_a_suggestion(seeded):
    """The answer to the question that was actually asked.

    The tempting version of this feature makes the plan *the* schedule, and
    the clinic stops being told about anything nobody has thought of yet.
    """
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded, tag="A2")
        _agree(seeded, kid, "PCV")
        plan = patient_plan(kid)

        others = {v["vaccine"].code for v in plan
                  for d in v["doses"] if d["status"] == "suggested"}

    assert others, "agreeing one vaccine silenced every other suggestion"
    assert "MENB" in others or "HAV" in others, others


def test_the_national_schedule_is_not_dragged_in(seeded):
    """Agreeing to a pneumococcal does not make this clinic owe the
    government's doses."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded, tag="A3")
        _agree(seeded, kid, "PCV")
        penta = _states(patient_plan(kid), "PENTA")

    assert set(penta) <= {"national", "upcoming"}, penta


def test_a_shut_window_stays_shut(seeded):
    """Agreement is not a time machine. Rotavirus cannot be given to a
    three-year-old whatever anybody agreed."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded, days=1100, tag="A4")
        _agree(seeded, kid, "ROTA")
        rota = _states(patient_plan(kid), "ROTA")

    assert set(rota) == {"expired"}, rota


def test_removing_it_puts_the_course_back_where_it_was(seeded):
    """Not gone — the child did not get younger, and the doctor may only have
    changed their mind about the timing."""
    from app.extensions import db
    from app.models.vaccine_plan import VaccinePlanItem
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded, tag="A5")
        _agree(seeded, kid, "PCV")
        assert "overdue" in _states(patient_plan(kid), "PCV")

        VaccinePlanItem.query.filter_by(patient_id=kid.id).delete()
        db.session.commit()

        assert set(_states(patient_plan(kid), "PCV")) == {"suggested"}


# ------------------------------------------------------------ the sweep

def test_the_sweep_finds_a_child_with_a_plan_and_no_doses(seeded):
    """The reason the sweep's entry condition had to change: before this it
    only ever looked at children who had already had something here, and an
    agreed plan with nothing given yet is exactly the case worth chasing."""
    from app.utils.vaccine_due import due_list

    with seeded["app"].app_context():
        kid = _child(seeded, tag="A6")
        _agree(seeded, kid, "PCV")

        found = due_list(status="overdue")
        mine = [r for r in found if r["patient"].id == kid.id]

    assert mine, "a child with an agreed plan and no doses is invisible"
    assert {r["vaccine"].code for r in mine} == {"PCV"}


def test_the_two_paths_still_agree_about_a_planned_child(seeded):
    """The guarantee the flat sweep rests on has to hold for this too."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import (doses_for, patient_due_reminders, scan_due)
    from app.models.vaccine_plan import planned_by_patient

    today = local_today()
    with seeded["app"].app_context():
        kid = _child(seeded, tag="A7")
        _agree(seeded, kid, "PCV")
        _agree(seeded, kid, "HAV")

        agreed = planned_by_patient([kid.id]).get(kid.id, set())
        by_orm = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in patient_due_reminders(
                kid, "ar", today, doses=doses_for([kid.id]).get(kid.id, [])))

        rows = db.session.query(
            PatientVaccine.vaccine_id, PatientVaccine.brand_id,
            PatientVaccine.dose_number, PatientVaccine.given_date,
            PatientVaccine.event_type).filter(
            PatientVaccine.patient_id == kid.id).all()
        by_flat = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in scan_due(db.session.get(Patient, kid.id).date_of_birth,
                              rows, today, agreed=agreed))

    assert by_orm == by_flat, f"file says {by_orm}, sweep says {by_flat}"


# ------------------------------------------------------------- the screen

def test_the_doctor_can_agree_one_from_the_file(seeded):
    from app.models import Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    with seeded["app"].app_context():
        kid_id = _child(seeded, tag="A8").id
        pcv_id = Vaccine.query.filter_by(code="PCV").first().id

    seeded["sign_in"]("doc").post(f"/vaccinations/{kid_id}/plan/add",
                                  data={"vaccine_id": pcv_id},
                                  follow_redirects=True)

    with seeded["app"].app_context():
        assert VaccinePlanItem.query.filter_by(patient_id=kid_id,
                                               vaccine_id=pcv_id).count() == 1


def test_agreeing_the_same_one_twice_does_not_double_it(seeded):
    from app.models import Vaccine
    from app.models.vaccine_plan import VaccinePlanItem

    with seeded["app"].app_context():
        kid_id = _child(seeded, tag="A9").id
        pcv_id = Vaccine.query.filter_by(code="PCV").first().id

    client = seeded["sign_in"]("doc")
    for _ in range(2):
        client.post(f"/vaccinations/{kid_id}/plan/add",
                    data={"vaccine_id": pcv_id}, follow_redirects=True)

    with seeded["app"].app_context():
        assert VaccinePlanItem.query.filter_by(patient_id=kid_id).count() == 1


def test_the_national_schedule_is_not_offered_to_agree_to(seeded):
    """Agreeing to it here would promise something this clinic does not do."""
    with seeded["app"].app_context():
        kid_id = _child(seeded, tag="A10").id

    page = seeded["sign_in"]("doc").get(f"/vaccinations/{kid_id}",
                                        follow_redirects=True).data.decode()
    import re
    block = re.search(r'<select[^>]*name="vaccine_id".*?</select>', page, re.S)

    assert block, "there is no way to agree a vaccine on the file at all"
    for word in ("الدرن", "شلل الأطفال الفموي", "فيتامين أ"):
        assert word not in block.group(0), \
            f"the national schedule is offered as something to agree to: {word}"


def test_the_family_supplying_it_is_still_a_plan(seeded):
    """Still followed — the visit has to be arranged and the dose recorded —
    and never counted into an order."""
    from app.models.vaccine_plan import VaccinePlanItem
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = _child(seeded, tag="A11")
        _agree(seeded, kid, "PCV", outside=True)

        assert "overdue" in _states(patient_plan(kid), "PCV")
        row = VaccinePlanItem.query.filter_by(patient_id=kid.id).first()
        assert row.supplied_outside is True


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    keys = ["title", "add", "remove", "added", "removed", "already",
            "pick_one", "outside", "none", "hint", "supplied_hint"]
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vplan"]
        for key in keys:
            assert key in block, f"{lang} is missing vplan.{key}"
