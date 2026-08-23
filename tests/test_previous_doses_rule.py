"""A schedule that reads the child's history, not only their birthday.

The leaflets do not name a course by age alone. The category is
"**Unvaccinated** 7 to <12 months", and the first word carries half the
meaning: a child who already had two pneumococcal doses and is switching
product is not unvaccinated, and handing them that catch-up course restarts a
series they are most of the way through.

Two rules were stated, and they only make sense together.

**The doses already given count, whatever the trade name.** A dose of Prevenar
is a pneumococcal dose when the next one is Vaxneuvance. The leaflets say so
explicitly, and `dose_infer` has numbered doses per vaccine rather than per
brand since the first import for the same reason.

**The course follows the product being used now.** "ينتقل إلى جدول Vaxneuvance
المناسب لعمره وحالته وقت الانتقال" — not the schedule the first needle put
them on. So the age band is matched at *this brand's* first dose, and a
history condition decides whether an unvaccinated band applies at all.

For a course on one product throughout, this brand's first dose and the
child's first dose are the same date and nothing changes — which is why HPV
still locks its two-or-three at the start and stays there.
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

    from app.models import Setting

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        # Pneumococcal is the vehicle here, for a leaflet's own bands and for
        # dose numbering across trade names. The Egyptian profile computes no
        # pneumococcal schedule at all — deliberately — so the leaflet is what
        # these are read against, which is also whose rules they are.
        Setting.set("vaccine_guideline_profile", "manufacturer")
        db.session.commit()
    return clinic


def _course(seeded, tag, age_years, doses):
    """A child with `doses` as [(brand_name, age_in_months)], newest last."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brands = {b.name: b for b in
                  VaccineBrand.query.filter_by(vaccine_id=pcv.id).all()}
        dob = local_today() - timedelta(days=int(age_years * 365.25))
        kid = Patient(patient_number=f"PD{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, (brand_name, months) in enumerate(doses, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id,
                brand_id=brands[brand_name].id, dose_number=number,
                event_type="given",
                given_date=dob + timedelta(days=int(months * 30.4))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        return {
            "brand": row["brand"].name,
            "total": len(row["doses"]),
            "done": sum(1 for d in row["doses"] if d["status"] == "done"),
        }


# ------------------------------------------------------- the unvaccinated band

def test_a_child_with_no_history_gets_the_catch_up_course(seeded):
    """Nine months, nothing before it: three doses, per the leaflet."""
    got = _course(seeded, "a", 0.85, [("Vaxneuvance", 9)])

    assert got["total"] == 3
    assert got["brand"] == "Vaxneuvance"


def test_a_child_with_history_is_not_treated_as_unvaccinated(seeded):
    """The bug this rule exists for.

    Two Prevenar at two and four months, switching to Vaxneuvance at nine.
    Matched on age alone the child lands in "unvaccinated 7 to <12 months" and
    is handed a fresh three-dose course — two injections they have already had.
    """
    got = _course(seeded, "b", 0.85,
                  [("Prevenar 13", 2), ("Prevenar 13", 4), ("Vaxneuvance", 9)])

    assert got["total"] == 4, \
        f"a PCV-experienced child was put on the unvaccinated course: {got}"
    assert got["done"] == 3, \
        f"doses already given were not counted: {got}"


def test_the_doses_already_given_count_across_brands(seeded):
    """A Prevenar dose is a pneumococcal dose when the next is Vaxneuvance."""
    got = _course(seeded, "c", 0.85, [("Prevenar 13", 2), ("Prevenar 13", 4)])

    assert got["done"] == 2


# -------------------------------------------------- which product it follows

def test_the_course_follows_the_product_being_used_now(seeded):
    """Not the one it started on. Locked to the first dose the record shows a
    child on a product they stopped, and schedules that product's course."""
    got = _course(seeded, "d", 0.85,
                  [("Prevenar 13", 2), ("Prevenar 13", 4), ("Vaxneuvance", 9)])

    assert got["brand"] == "Vaxneuvance"


def test_a_course_that_never_switched_is_unaffected(seeded):
    """Nearly every course. First and last dose are the same product."""
    got = _course(seeded, "e", 0.85, [("Prevenar 13", 2), ("Prevenar 13", 4)])

    assert got["brand"] == "Prevenar 13"
    assert got["total"] == 4


def test_hpv_still_locks_at_the_start(seeded):
    """The other rule, unchanged: a child who began HPV at fourteen and eleven
    months stays on two doses. One product throughout, so "this brand's first
    dose" and "the first dose" are the same day."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=hpv.id,
                                             name="Gardasil 9").first()
        dob = local_today() - timedelta(days=int(15.1 * 365.25))
        kid = Patient(patient_number="PDhpv", full_name="طفلة",
                      gender="female", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=hpv.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(14.9 * 365.25))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "HPV")

    assert len(row["doses"]) == 2


# ------------------------------------------------------------- the condition

def test_the_catch_up_bands_say_they_are_for_the_unvaccinated(seeded):
    """In the data, where somebody editing them can see it — not in code."""
    from app.models import VaccineScheduleTemplate

    with seeded["app"].app_context():
        band = VaccineScheduleTemplate.query.filter_by(code="PCV15-CU7").first()

        assert band is not None
        assert band.requires_previous_doses == "none"


def test_the_routine_band_applies_to_anybody(seeded):
    """A condition on every band would make the ordinary course unreachable."""
    from app.models import VaccineScheduleTemplate

    with seeded["app"].app_context():
        band = VaccineScheduleTemplate.query.filter_by(code="PCV15-INF").first()

        assert band is not None
        assert band.requires_previous_doses is None


def test_the_band_is_matched_at_the_switch_not_at_the_first_needle(seeded):
    """"لعمره وحالته وقت الانتقال" — the age when the product changed.

    The two rules overlap on the catch-up bands, which carry a history
    condition and would exclude a switched child anyway. This pins the other
    half on its own: a band with **no** history condition, covering an age the
    child only reaches later. Matched at the first needle the child is filed
    under the infant course; matched at the switch they are on this one.

    Built here rather than seeded because it is the mechanism being tested,
    not a leaflet — and building it from the screen's own form is the point:
    a clinic adds bands like this without a developer.
    """
    from app.extensions import db
    from app.models import Vaccine, VaccineBrand, VaccineScheduleTemplate

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        vax = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                           name="Vaxneuvance").first()
        vaccine_id, brand_id = pcv.id, vax.id

    # A leaflet band, so the clinic has to be following the leaflet for it to
    # be read at all: the guideline a clinic chooses outranks a trade name's
    # schedule, and the default one has a pneumococcal table of its own. The
    # property under test is the leaflet's — that its band is matched at the
    # switch — so this is where it has to be measured.
    from app.extensions import db as _db
    from app.models import Setting

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", "manufacturer")
        _db.session.commit()

    client = seeded["sign_in"]("boss")
    client.post(f"/vaccinations/manage/vaccine/{vaccine_id}/schedules/new",
                data={"code": "PCV15-SWITCH", "source": "manufacturer",
                      "label": "switching in at 12–23 months",
                      "brand_id": brand_id,
                      "start_age_min_months": "12",
                      "start_age_max_months": "23"},
                follow_redirects=True)

    with seeded["app"].app_context():
        from app.models import VaccineScheduleDose
        tpl = VaccineScheduleTemplate.query.filter_by(
            code="PCV15-SWITCH").first()
        assert tpl is not None and tpl.requires_previous_doses is None
        # Two doses, so the band is distinguishable from the four-dose course.
        for number, age in ((1, 12), (2, 14)):
            db.session.add(VaccineScheduleDose(
                template_id=tpl.id, dose_number=number,
                recommended_age_months=age,
                min_interval_days=(60 if number > 1 else None)))
        tpl.sort_order = -1          # ahead of the seeded catch-up bands
        db.session.commit()

    # Two Prevenar as an infant, switching to Vaxneuvance at 18 months.
    got = _course(seeded, "sw", 1.7,
                  [("Prevenar 13", 2), ("Prevenar 13", 4), ("Vaxneuvance", 18)])

    assert got["brand"] == "Vaxneuvance"
    assert got["total"] == 2, (
        "the band was matched at the child's first dose rather than at the "
        f"switch: {got}")
