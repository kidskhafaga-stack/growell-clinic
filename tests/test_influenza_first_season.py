"""A first flu shot under nine is two doses, not one.

"First time under 9 years: two doses four weeks apart, then one dose a year."
It was in the catalogue as a sentence of Arabic prose and nothing read it,
because every seasonal path in the module had the same assumption written into
its shape: *a seasonal course is one dose*. The annual recall was computed from
the last dose and there was nowhere for a second dose of the same season to
live.

**What the child loses is real.** One dose in a first season is not a smaller
version of two — the priming series is what makes the season's vaccine work for
a young child who has never met the virus. A four-year-old who came once in
October and was never called back in November was, as far as the register knew,
up to date.

**Matched at the first dose, like every other band.** A child who begins at
eight years and eleven months keeps the second dose; turning nine four weeks
later does not take it away. That is the same rule the doctor was most careful
about on HPV, and it is the same code holding it.

**Ordinary years are untouched.** A returning patient has a course with nothing
pending, so the annual recall fires exactly as it did — which is the assertion
that keeps this from being a change to everybody's flu.
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

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        db.session.commit()
    return clinic


def _child(seeded, years, tag, doses=()):
    """`doses` as [(number, days_ago)] — flu doses already on file."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    with seeded["app"].app_context():
        flu = Vaccine.query.filter_by(code="FLU").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=flu.id,
                                             name="Vaxigrip").first()
        dob = local_today() - timedelta(days=int(years * 365.25))
        kid = Patient(patient_number=f"FL{tag}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, ago in doses:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=flu.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=local_today() - timedelta(days=ago)))
        db.session.commit()
        return kid.id


def _flu(seeded, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        plan = patient_plan(db.session.get(Patient, patient_id))
        return next(v for v in plan if v["vaccine"].code == "FLU")


def _chased(seeded, patient_id):
    """What the register would send about this child's influenza."""
    from app.utils.vaccine_due import due_list

    with seeded["app"].app_context():
        return [r for r in due_list()
                if r["patient"].id == patient_id and r["vaccine"].code == "FLU"]


# --------------------------------------------------------- the course itself

def test_a_first_season_under_nine_is_two_doses(seeded):
    assert len(_flu(seeded, _child(seeded, 4, "a"))["doses"]) == 2


def test_from_nine_it_is_one_a_year(seeded):
    assert len(_flu(seeded, _child(seeded, 10, "b"))["doses"]) == 1


def test_starting_before_nine_keeps_the_second_dose(seeded):
    """The rule the doctor was most careful about on HPV, here again: a
    birthday between the two doses does not cancel the second."""
    kid = _child(seeded, 9.05, "c", doses=[(1, 30)])

    assert len(_flu(seeded, kid)["doses"]) == 2, \
        "turning nine between the doses took the second one away"


# ------------------------------------------------ the second dose is chased

def test_the_second_dose_is_owed_four_weeks_later_not_next_year(seeded):
    """The whole point. Before this the child's next contact was the annual
    recall eleven months away, and the priming series was silently abandoned.
    """
    kid = _child(seeded, 4, "d", doses=[(1, 40)])

    rows = _chased(seeded, kid)

    assert rows, "a child owed their second priming dose was not chased at all"
    assert rows[0]["dose_number"] == 2
    assert rows[0]["status"] == "overdue", rows[0]["status"]


def test_the_visit_panel_offers_it_while_the_child_is_here(seeded):
    """The nurse in front of the child is the last chance to give it, and the
    panel is what they look at."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import visit_vaccine_panel

    kid = _child(seeded, 4, "e", doses=[(1, 40)])

    with seeded["app"].app_context():
        panel = visit_vaccine_panel(db.session.get(Patient, kid))

    offered = [r for r in panel["give_now"] + panel["out_of_stock"]
               if r["vaccine"].code == "FLU"]

    assert offered, "the second priming dose was not offered during the visit"
    assert offered[0]["dose"]["dose_number"] == 2


def test_too_soon_is_not_yet_owed(seeded):
    """Four weeks is a minimum, not a suggestion — a dose given at ten days
    does not count, so the program must not ask for one."""
    kid = _child(seeded, 4, "f", doses=[(1, 5)])

    assert not [r for r in _chased(seeded, kid) if r["status"] == "overdue"]


# ------------------------------------- the priming pair belongs to one season

def test_a_dose_from_years_ago_does_not_hold_a_priming_pair_open(seeded):
    """Found on a real file, on the first patient this ran against.

    A boy of eleven with a single influenza dose from January 2019 was told he
    owed *the second dose of his priming pair, due February 2019*. He does owe
    a flu shot — seven winters of them — but the pair belongs to the season it
    started in. At eleven he needs one dose, and a card offering him the other
    half of something from when he was four is a date nobody can act on.

    The cause: the band was matched on the first dose **ever**, which is right
    for a course a child runs once and wrong for one they run every year.
    """
    kid = _child(seeded, 11, "old", doses=[(1, 2700)])

    doses = _flu(seeded, kid)["doses"]

    assert len(doses) == 1, \
        f"a seven-year-old dose still holds the priming pair open: {doses}"
    # And the dose he is owed is owed **now**. The date used to be computed
    # from his age — birth plus six months — so the file said "overdue since
    # 2016". Nobody can act on a missed 2016 season; what is true is that he
    # needs one this winter.
    assert doses[0]["due_date"] >= local_today().isoformat(), \
        f"his flu shot is dated in the past: {doses[0]['due_date']}"

    rows = _chased(seeded, kid)
    assert rows, "and then nobody called him in for this winter either"


def test_a_dose_from_this_season_still_holds_it_open(seeded):
    """The other side. The fix must not be "a second dose is never owed" — it
    is owed for exactly as long as the season it belongs to."""
    kid = _child(seeded, 4, "same", doses=[(1, 40)])

    doses = _flu(seeded, kid)["doses"]

    assert len(doses) == 2 and doses[1]["status"] == "overdue", doses


def test_a_child_who_had_two_winters_is_not_primed_again(seeded):
    """Two doses well behind them: the course has nothing pending and the
    annual recall is the whole of what they are owed."""
    kid = _child(seeded, 6, "two", doses=[(1, 400), (2, 370)])

    doses = _flu(seeded, kid)["doses"]

    assert len(doses) == 1, \
        f"a child with two winters behind them is being primed again: {doses}"


def test_a_child_who_has_had_this_seasons_shot_is_not_called_again(seeded):
    """Caught while making the change above, and it would have been worse than
    the bug being fixed.

    The record numbers doses across a lifetime — a fifth winter is dose 5 —
    while the season's course has slots one and two. Keyed by the stored
    number, this season's dose 5 matched no slot, and a child who had their
    flu shot three weeks ago was told they still needed one. A stale date
    wastes a phone call; this sends a family in for an injection they have
    already had.
    """
    kid = _child(seeded, 5, "already",
                 doses=[(1, 700), (2, 670), (3, 20)])

    doses = _flu(seeded, kid)["doses"]

    assert [d["status"] for d in doses] == ["done"], \
        f"a child vaccinated three weeks ago is being called in again: {doses}"
    assert not _chased(seeded, kid)


# ------------------------------------------------- ordinary years untouched

def test_a_returning_patient_still_gets_the_annual_recall(seeded):
    """The assertion that keeps this from being a change to everybody's flu.

    Two doses behind them and eleven months since the last: nothing is pending
    in the course, so the recall fires exactly as it always did.
    """
    kid = _child(seeded, 6, "g", doses=[(1, 400), (2, 370)])

    rows = _chased(seeded, kid)

    assert rows, "a returning patient was not called in for this winter"
    # Asserted as "called in, for a date somebody can act on" rather than as
    # the word `seasonal`. That status was the old mechanism: a recall with no
    # date, fired eleven months after the last dose. This season's dose is now
    # a real dose in a real course, so it carries a real date — and pinning
    # the word made this test fail on the improvement.
    assert rows[0]["due_date"] is None \
        or rows[0]["due_date"] >= local_today().isoformat(), rows


def test_an_older_child_is_not_asked_for_a_second_dose(seeded):
    """One dose forty days ago at eleven years is a finished season."""
    kid = _child(seeded, 11, "h", doses=[(1, 40)])

    assert not _chased(seeded, kid), \
        "a child over nine was asked for a priming second dose"


def test_the_two_paths_agree_about_a_primed_child(seeded):
    """The guarantee the whole sweep rests on, on the case that just changed
    shape. The seasonal branch exists twice — once over ORM rows and once over
    flat columns — and a rule added to one of them is a register that
    disagrees with the file it came from.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import doses_for, patient_due_reminders, scan_due

    kid = _child(seeded, 4, "i", doses=[(1, 40)])
    today = local_today()

    with seeded["app"].app_context():
        patient = db.session.get(Patient, kid)
        by_orm = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in patient_due_reminders(
                patient, "ar", today, doses=doses_for([kid]).get(kid, [])))

        rows = db.session.query(
            PatientVaccine.vaccine_id, PatientVaccine.brand_id,
            PatientVaccine.dose_number, PatientVaccine.given_date,
            PatientVaccine.event_type).filter(
            PatientVaccine.patient_id == kid).all()
        by_flat = sorted(
            (r["vaccine"].code, r["dose_number"], r["status"])
            for r in scan_due(patient.date_of_birth, rows, today))

    assert by_orm == by_flat, f"file says {by_orm}, sweep says {by_flat}"


def test_each_band_states_its_own_history_condition(seeded):
    """`_pick_band` directly, because one of these is not reachable any other
    way.

    Measured: strip `previous_max` off and every other test in this file still
    passes, because the band above it asks for two or more and the ordering
    does the rest. That makes it redundant — and redundant is not the same as
    wrong. A band that only works while its neighbour sorts first is a band
    that breaks silently the day somebody reorders them, and reordering rows
    on a screen is exactly what these are for.

    So both conditions are asked here, on the function, where the ordering
    cannot answer for them.
    """
    from datetime import date

    from app.utils.vaccines import _pick_band

    dob = date(2020, 1, 1)
    today = date(2026, 8, 22)
    primed = [{"min": None, "max": 107, "previous_min": 2, "doses": [(6, None)]}]
    priming = [{"min": None, "max": 107, "previous_max": 1,
                "doses": [(6, None), (7, 28)]}]

    assert _pick_band(primed, dob, None, 2, today) is not None
    assert _pick_band(primed, dob, None, 1, today) is None, \
        "a band asking for two previous doses accepted a child with one"

    assert _pick_band(priming, dob, None, 1, today) is not None
    assert _pick_band(priming, dob, None, 2, today) is None, \
        "a band capped at one previous dose accepted a child with two"


# ------------------------------------------------------- it is data, not code

def test_the_bands_are_rows_a_clinic_can_edit(seeded):
    """The standing rule: the schedule is data on a screen. A clinic whose
    guidance changes edits two rows; nobody recompiles anything."""
    from app.models import Vaccine, VaccineScheduleTemplate

    with seeded["app"].app_context():
        flu = Vaccine.query.filter_by(code="FLU").first()
        codes = {r.code for r in
                 VaccineScheduleTemplate.query.filter_by(vaccine_id=flu.id)}

    assert {"FLU-PRIME", "FLU-ANNUAL"} <= codes, codes


def test_the_warning_stops_once_the_leaflet_has_been_read(seeded):
    """"Doses vary with the starting age" is an admission of not knowing. The
    flag stays on the brand — it is still true — but the file stops saying it
    where a band now answers, or a real caution becomes wallpaper."""
    kid = _child(seeded, 4, "j", doses=[(1, 40)])
    row = _flu(seeded, kid)

    assert row["brand"].doses_change_by_start_age is True
    assert row["banded"] is True, \
        "the file would still warn that it does not know the dose count"
