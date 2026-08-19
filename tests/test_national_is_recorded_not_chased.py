"""The national schedule belongs in the record, not on the chase list.

Reported plainly: *the plan is computed over the government vaccines too, and
I only register those as given outside the clinic if I feel like it.*

Measured on a healthy two-year-old who has had nothing here — the ordinary
case in a clinic whose families use the government units:

    25 vaccines, 47 doses, 41 of them "suggested"
    of which 9 vaccines and 17 doses were the national schedule

A third of the child's plan, for a schedule this clinic does not give, does
not stock, cannot bill and is not measured on. The program already knew the
difference in two other places — the compliance screen excludes mandatory
vaccines by name, and the visit panel declines to offer them — so the plan and
the certificate were the last two counting them.

On-demand vaccines are the same shape for a different reason. Rabies is given
because a dog bit somebody; projected from a birthday it came out due at
birth, so every child in the register was being suggested it.

**They stay in the plan.** The row is what the doctor clicks to record a dose
given at a government unit, and that record is the whole point of the
certificate a parent carries. What changes is that nothing chases them: not
"overdue", which would be a promise this clinic never made, and not
"suggested", which would be advice about a schedule somebody else runs.
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


def _child(clinic, days=730, tag="N1"):
    from app.extensions import db
    from app.models import Patient

    kid = Patient(patient_number=tag, full_name="طفل", gender="male",
                  date_of_birth=local_today() - timedelta(days=days),
                  is_active=True)
    db.session.add(kid)
    db.session.commit()
    return kid


def test_nothing_national_is_chased_or_suggested(seeded):
    """The measurement this exists for: 41 suggestions became 21."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(_child(seeded))
        gov = [v for v in plan if v["vaccine"].is_mandatory]

        assert gov, "the government schedule is not in the catalogue at all"
        states = {d["status"] for v in gov for d in v["doses"]}
        assert states <= {"national", "upcoming", "done"}, \
            f"the national schedule is still being chased: {states}"


def test_rabies_is_not_offered_to_every_newborn(seeded):
    """Projected from a birthday it fell due at birth, for everybody."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(_child(seeded, tag="N2"))
        rabies = next(v for v in plan if v["vaccine"].code == "RABIES")

        assert {d["status"] for d in rabies["doses"]} == {"on_demand"}


def test_the_optional_schedule_is_untouched(seeded):
    """The half that proves this did not simply switch suggestions off."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(_child(seeded, tag="N3"))
        pcv = next(v for v in plan if v["vaccine"].code == "PCV")

        assert "suggested" in {d["status"] for d in pcv["doses"]}, \
            "the optional schedule stopped suggesting anything"


def test_a_government_dose_given_here_still_behaves_normally(seeded):
    """Some clinics do give them. Once a dose is recorded here the course is
    this clinic's, and the next one really can be late — the same rule that
    has always decided what "late" means."""
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        penta = Vaccine.query.filter_by(code="PENTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=penta.id).first()
        kid = _child(seeded, tag="N4")
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=penta.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=kid.date_of_birth + timedelta(days=60)))
        db.session.commit()

        plan = patient_plan(kid)
        row = next(v for v in plan if v["vaccine"].code == "PENTA")
        states = [d["status"] for d in row["doses"]]

        assert states[0] == "done"
        assert "overdue" in states, \
            f"a course this clinic started is not being followed: {states}"


def test_the_plan_still_carries_the_row_to_record_against(seeded):
    """The reason they are not simply dropped: the doctor needs somewhere to
    write down the dose the government unit gave."""
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(_child(seeded, tag="N5"))
        codes = {v["vaccine"].code for v in plan}

    for code in ("PENTA", "BCG", "MEASLES"):
        assert code in codes, f"{code} vanished from the plan entirely"


def test_a_dose_given_outside_stays_on_the_certificate(seeded):
    """What the paper is for. A parent carries it to show the child's history,
    and a history missing the national schedule is not one."""
    from app.extensions import db
    from app.models import PatientVaccine, Vaccine, VaccineBrand

    with seeded["app"].app_context():
        penta = Vaccine.query.filter_by(code="PENTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=penta.id).first()
        kid = _child(seeded, tag="N6")
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=penta.id, brand_id=brand.id,
            dose_number=1, event_type="given", given_outside=True,
            outside_place="وحدة صحية", given_date=local_today()
            - timedelta(days=600)))
        db.session.commit()
        kid_id = kid.id

    page = seeded["sign_in"]("doc").get(
        f"/vaccinations/{kid_id}/certificate?suggest=1",
        follow_redirects=True).data.decode()

    assert "وحدة صحية" in page or "الخماسي" in page, \
        "the dose given at a government unit is not on the certificate"


def test_the_opt_in_certificate_table_still_offers_them(seeded):
    """The one place the national schedule is still allowed to be suggested.

    This table prints only when the doctor asks for it, and being "what the age
    suggests rather than anything this clinic promised" is the whole reason it
    is opt-in — which in Egypt is mostly the government schedule. My first
    version of this change filtered it out here too and broke two older tests
    that existed to protect exactly that: removing it from a table somebody
    deliberately switched on is deleting the feature, not fixing it.

    What is filtered here is a shut window, which no clinic can give at all.
    """
    from app.i18n import t

    with seeded["app"].app_context():
        kid_id = _child(seeded, tag="N7").id

    page = seeded["sign_in"]("doc").get(
        f"/vaccinations/{kid_id}/certificate?suggest=1",
        follow_redirects=True).data.decode()

    with seeded["app"].test_request_context("/"):
        assert t("vaccinations.cert_suggested_hint") in page, \
            "the opt-in suggestions table stopped rendering"


def test_a_shut_window_is_never_suggested_on_paper(seeded):
    """Rotavirus for a two-year-old cannot be given by anybody."""
    from app.extensions import db
    from app.models import Patient

    with seeded["app"].app_context():
        kid = _child(seeded, tag="N8")
        kid_id = kid.id
        db.session.commit()
        assert db.session.get(Patient, kid_id) is not None

    page = seeded["sign_in"]("doc").get(
        f"/vaccinations/{kid_id}/certificate?suggest=1",
        follow_redirects=True).data.decode()

    assert "فيروس الروتا" not in page, \
        "the certificate is offering a vaccine whose window has shut"


def test_both_statuses_read_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vstatus"]
        for key in ("national", "on_demand"):
            assert key in block, f"{lang} has no word for {key}"
