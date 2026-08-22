"""A childhood course that stops being a childhood course.

From the audit of the long reminder screen, and answered by the doctor
directly: *"PCV → age-based catch-up rule, not PCV → continue the infant
series up to sixteen years. A healthy child who reaches twenty-four months
after an earlier dose is not treated as though still in the infant series."*

The measurement it came from: a child with one pneumococcal dose as a baby
read `overdue` on doses 2, 3 and 4 at three years old, at ten, and at sixteen
— dated 2011 — because `Prevenar 13` carries no finish ceiling and the course
was matched on the age at the **first** dose. Rotavirus had exactly this shape
until its ceiling was filled in.

**Matched on today's age, which is the opposite of HPV, and deliberately.**
HPV locks at the first dose so that a birthday between doses cannot add a
third. A catch-up re-reads the child every time, because that is what a
catch-up is. Both are now stated per band rather than assumed.

**Only the ceiling is here.** The middle of the catch-up — one dose to
complete for a healthy child of two to four — is deliberately absent: a
one-dose course has its single slot filled by the infant dose the child
already had, so "one more" comes out as "nothing owed". That needs the engine
to treat a catch-up's doses as *additional* to what is on file, which is a
change to make deliberately rather than to guess at.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def seeded(clinic):
    from app.extensions import db

    from app.utils.vaccines import seed_vaccine_schedules, seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _child(clinic, years, tag, doses=((1, 2),)):
    """`doses` as [(number, age_in_months)] of the default pneumococcal."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine

    with clinic["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        dob = local_today() - timedelta(days=int(years * 365.25))
        kid = Patient(patient_number=f"RC{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, months in doses:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id,
                brand_id=pcv.default_brand.id, dose_number=number,
                event_type="given",
                given_date=dob + timedelta(days=int(months * 30.44))))
        db.session.commit()
        return kid.id


def _pcv(clinic, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with clinic["app"].app_context():
        plan = patient_plan(db.session.get(Patient, patient_id))
        return next(v for v in plan if v["vaccine"].code == "PCV")


# ------------------------------------------------------ the reported screen

def test_a_sixteen_year_old_is_not_chased_for_a_babys_course(seeded):
    """The row that was on the screen: doses 2, 3 and 4 overdue since 2011."""
    from app.utils.vaccine_due import due_list

    kid_id = _child(seeded, 16, "16")

    # Nothing **owed** — not an empty course. The dose he had as a baby is
    # still on his file, and must be: the record is not the schedule.
    assert not [d for d in _pcv(seeded, kid_id)["doses"]
                if d["status"] != "done"]

    with seeded["app"].app_context():
        chased = [r for r in due_list()
                  if r["patient"].id == kid_id and r["vaccine"].code == "PCV"]

    assert not chased


@pytest.mark.parametrize("years", [5.1, 6, 10, 16])
def test_the_routine_course_is_over_from_five(seeded, years):
    row = _pcv(seeded, _child(seeded, years, str(years)))

    assert not [d for d in row["doses"] if d["status"] != "done"]


# --------------------------------------------- and nothing below it moved

@pytest.mark.parametrize("years", [0.25, 0.5, 1.2, 1.9])
def test_every_child_under_two_is_scheduled_exactly_as_before(seeded, years):
    """The half that matters most. A ceiling put one band too low silently
    stops vaccinating toddlers, and it would look like a tidier screen.

    Under two, and not under five, because two to four now has a catch-up of
    its own — one dose, not the infant series — which is the change the
    section below this one is about.
    """
    assert len(_pcv(seeded, _child(seeded, years, f"u{years}"))["doses"]) == 4


def test_a_baby_is_still_chased_for_the_doses_they_owe(seeded):
    from app.utils.vaccine_due import due_list

    kid_id = _child(seeded, 1.2, "baby")

    with seeded["app"].app_context():
        chased = [r for r in due_list()
                  if r["patient"].id == kid_id and r["vaccine"].code == "PCV"]

    assert chased, "a one-year-old stopped being chased for their series"


def test_it_reads_the_age_now_and_not_the_age_they_started_at(seeded):
    """The mechanism, stated where it can be seen.

    Both of these children started at two months. One is four, one is six, and
    a band matched on the first dose cannot tell them apart — which is exactly
    how the sixteen-year-old was still in a baby's course.
    """
    four = _pcv(seeded, _child(seeded, 4, "m4"))
    six = _pcv(seeded, _child(seeded, 6, "m6"))

    # The four-year-old is on a catch-up — one dose owed on top of the one
    # they had. The six-year-old is past the routine course entirely and owes
    # nothing, though the dose they *did* have is still on their file.
    assert [d["status"] for d in four["doses"]] == ["done", "due"]
    assert [d["status"] for d in six["doses"]] == ["done"]


def test_hpv_still_locks_at_the_first_dose(seeded):
    """The rule this must not have broken. A girl who begins at fourteen and
    eleven months keeps two doses after her fifteenth birthday — the thing the
    doctor was most careful about — and it is the same function deciding."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        hpv = Vaccine.query.filter_by(code="HPV").first()
        dob = local_today() - timedelta(days=int(15.1 * 365.25))
        girl = Patient(patient_number="RChpv", full_name="طفلة",
                       gender="female", date_of_birth=dob, is_active=True)
        db.session.add(girl)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=girl.id, vaccine_id=hpv.id,
            brand_id=hpv.default_brand.id, dose_number=1, event_type="given",
            given_date=dob + timedelta(days=int(14.9 * 365.25))))
        db.session.commit()

        row = next(v for v in patient_plan(girl) if v["vaccine"].code == "HPV")

    assert len(row["doses"]) == 2, \
        "matching on today's age has reached HPV and added a third dose"


# ------------------------------------------- a catch-up is doses still owed

def test_a_toddler_with_one_infant_dose_is_owed_one_more(seeded):
    """The case decided directly: *"a healthy child of two to four with an
    earlier pneumococcal dose needs one additional dose — it must read 'one
    catch-up dose owed', not 'complete, nothing due'."*

    It read "nothing owed", and the reason is worth keeping: a course of one
    dose has its single slot filled by the infant dose already on file, so
    "one more" and "one in total" are the same sentence to a scheduler that
    counts slots. A catch-up says how many are owed **now**.
    """
    row = _pcv(seeded, _child(seeded, 3, "cu1", doses=((1, 2),)))
    owed = [d for d in row["doses"] if d["status"] != "done"]

    assert len(owed) == 1, f"the catch-up dose is not owed: {row['doses']}"
    assert owed[0]["due_date"] >= local_today().isoformat(), \
        "the catch-up dose is dated in the past"


def test_the_owed_dose_is_owed_now(seeded):
    """The failure the counting version walks into. A dose worked out by
    subtraction has no date, so something has to invent one — and the thing
    that invents it is the child's age, which is how influenza came to say
    "overdue since 2016". A catch-up is a short course that starts today.
    """
    row = _pcv(seeded, _child(seeded, 4, "cu2", doses=((1, 2),)))
    owed = [d for d in row["doses"] if d["status"] != "done"]

    assert owed[0]["due_date"] == local_today().isoformat()


def test_a_child_who_never_had_one_is_owed_the_same_single_dose(seeded):
    """Two to four and unvaccinated is one dose, the same as two to four and
    partly vaccinated. The band is about the age, and how many they have had
    only decides whether it applies at all."""
    row = _pcv(seeded, _child(seeded, 3, "cu3", doses=()))

    assert len([d for d in row["doses"] if d["status"] != "done"]) == 1


def test_a_completed_series_is_not_asked_for_another(seeded):
    """The half that stops a catch-up becoming a permanent extra dose. A child
    with the full four is complete, no band matches them, and they fall back
    to the product's own rows where every dose is already done."""
    row = _pcv(seeded, _child(seeded, 3, "cu4",
                              doses=((1, 2), (2, 4), (3, 6), (4, 12))))

    assert [d["status"] for d in row["doses"]] == ["done"] * 4


def test_the_doses_on_file_are_not_swallowed_by_the_catch_up(seeded):
    """They are still on the record and still count — a catch-up changes what
    is *owed*, not what happened."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine

    patient_id = _child(seeded, 3, "cu5", doses=((1, 2), (2, 4)))

    with seeded["app"].app_context():
        kept = PatientVaccine.query.filter_by(patient_id=patient_id).count()

    assert kept == 2


def test_a_baby_is_not_given_a_catch_up_instead_of_a_series(seeded):
    """Under two the infant series is the course, unchanged. A catch-up band
    reaching them would replace four doses with one."""
    row = _pcv(seeded, _child(seeded, 1.2, "cu6", doses=((1, 2),)))

    assert len(row["doses"]) == 4


def test_the_sweep_agrees_with_the_file_about_a_catch_up(seeded):
    """The guarantee the register rests on, on the case that just changed
    shape. The catch-up is decided in two places — over ORM rows and over flat
    columns — and a rule added to one of them is a register that disagrees
    with the file it came from."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import doses_for, patient_due_reminders, scan_due

    patient_id = _child(seeded, 3, "cu7", doses=((1, 2),))
    today = local_today()

    with seeded["app"].app_context():
        patient = db.session.get(Patient, patient_id)
        by_orm = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in patient_due_reminders(
                patient, "ar", today,
                doses=doses_for([patient_id]).get(patient_id, [])))

        rows = db.session.query(
            PatientVaccine.vaccine_id, PatientVaccine.brand_id,
            PatientVaccine.dose_number, PatientVaccine.given_date,
            PatientVaccine.event_type).filter(
            PatientVaccine.patient_id == patient_id).all()
        by_flat = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in scan_due(patient.date_of_birth, rows, today))

    assert by_orm == by_flat, f"file says {by_orm}, sweep says {by_flat}"


def test_the_history_condition_counts_the_whole_record(seeded):
    """`previous` alone is what came before *this brand*, which is zero for
    nearly every child — a condition written against it would never fire. What
    a catch-up asks about is how many doses the child has had."""
    from app.utils.vaccines import _pick_band

    band = [{"min": 24, "max": 59, "previous_max": 3, "match_on": "today",
             "catch_up": True, "doses": [(24, None)]}]
    dob = date(2023, 8, 22)
    today = date(2026, 8, 22)

    assert _pick_band(band, dob, None, 0, today, given_count=1) is not None
    assert _pick_band(band, dob, None, 0, today, given_count=4) is None, \
        "a child with a complete series was offered a catch-up dose"


# ------------------------------------------------------- it is a row, editable

def test_a_shut_course_still_shows_what_was_given(seeded):
    """Found while making the catch-up work, and the same mistake twice.

    An empty course dropped the child's doses off their own file, so a
    six-year-old's certificate lost the pneumococcal dose they were actually
    given. A course that is over must still show what happened in it — the
    record is not the schedule.
    """
    row = _pcv(seeded, _child(seeded, 6, "shut", doses=((1, 2),)))

    assert [d["status"] for d in row["doses"]] == ["done"]


def test_a_child_past_it_with_nothing_on_file_has_nothing_to_show(seeded):
    """The other side — an empty file stays empty rather than inventing a row."""
    assert _pcv(seeded, _child(seeded, 6, "shutnone", doses=()))["doses"] == []


def test_the_ceiling_is_a_row_a_clinic_can_change(seeded):
    """Every clinical number in this engine is data on a screen. A clinic that
    vaccinates a child of six on indication edits or deletes this row; nobody
    recompiles anything.

    There is one per reference now. It used to be a single row tagged with the
    leaflet set, which is how it reached every clinic whichever guideline it
    had chosen — see the test below, which is where that stopped.
    """
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        rows = {r.source: r for r in VaccineScheduleTemplate.query.filter_by(
            vaccine_id=pcv.id, is_active=True, brand_id=None).all()
            if r.start_age_min_months == 60}

        assert set(rows) == {"egypt", "cdc"}, \
            f"the ceiling is not a row under each reference that states it: {rows}"
        for source, row in rows.items():
            assert row.match_age_on == "today", source
            assert row.doses == [], source


def test_it_is_the_rule_of_the_references_that_state_it(seeded):
    """It used to be everybody's, and that was the bug rather than the design.

    The engine loads the leaflet set *plus* whichever profile the clinic
    follows, so a row tagged with a guideline is invisible to a clinic
    following another one — and `manufacturer` was the only tag they would all
    read. Tagging the end of the routine course that way made a statement by
    one reference into a rule applied to clinics that had never chosen it.

    So it now lives in the references that make it, and this test holds both
    halves: it applies where those references are followed, and it does not
    apply where they are not. The second half is a real consequence and is
    written down rather than glossed — a clinic that has explicitly chosen the
    leaflet gets the leaflet, which does not end the course at five.
    """
    from app.extensions import db
    from app.models import Setting

    def owing(profile):
        with seeded["app"].app_context():
            Setting.set("vaccine_guideline_profile", profile)
            db.session.commit()
        row = _pcv(seeded, _child(seeded, 8, f"g{profile}"))
        return [d for d in row["doses"] if d["status"] != "done"]

    for profile in ("egypt", "cdc"):
        assert not owing(profile), \
            f"the ceiling disappears for a clinic following {profile}"

    for profile in ("manufacturer", "who"):
        assert owing(profile), \
            (f"{profile} does not end the routine course at five, and a clinic "
             f"that chose it is being given a rule from elsewhere")


def test_a_profile_band_does_not_blank_the_babies(seeded):
    """Measured, not reasoned about, and it is why this is one lone band.

    A band whose source *is* the chosen profile makes that profile
    authoritative for the whole vaccine, and its silence about an age then
    means "no course". Seeded under `cdc`, this ceiling blanked the infant
    series for every baby in a clinic following the CDC.
    """
    from app.extensions import db
    from app.models import Setting

    with seeded["app"].app_context():
        Setting.set("vaccine_guideline_profile", "cdc")
        db.session.commit()

    assert len(_pcv(seeded, _child(seeded, 0.25, "cdcbaby"))["doses"]) == 4


def test_the_new_column_is_registered_for_an_existing_database(seeded):
    from app.utils.schema import ADDITIONS

    assert ("vaccine_schedule_templates", "match_age_on") in {
        (table, column) for table, column, *_ in ADDITIONS}
