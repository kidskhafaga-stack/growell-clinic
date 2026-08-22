"""WHO's pneumococcal schedule, including the part WHO does not decide.

Added because a clinic that had explicitly chosen WHO was still being handed
a fourth infant pneumococcal dose for a healthy ten-year-old: the rule that
ends the routine course lived under the leaflet set, and moving it to the
references that state it left WHO without one.

WHO's is a genuinely different course from the CDC's — **2p+1**, two primary
doses and a booster, against the CDC's 3p+1 — which is the whole reason a
clinic gets to choose between them rather than being handed one.

**And a gap that is WHO's, not the program's.** On a child of 12–23 months the
position paper says, in as many words, that *"current data are insufficient
for a firm recommendation on the optimal number of doses (1 or 2) required"*
as catch-up. It recommends catch-up between one and five years and does not
fix the number.

Neither answer the engine already had was true of that. An empty course says
"nothing is owed", which is the opposite of what the reference says. No band
at all says "this age is not scheduled", and left an unvaccinated two-year-old
with a blank card in a clinic whose guideline recommends vaccinating them. So
a band exists, carries no number, and asks for the doctor — the same rule as
everywhere else here (the program will not invent a clinical number), said
about a gap in a guideline rather than a contradiction in a record.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def who(clinic):
    from app.extensions import db
    from app.models import Setting

    from app.utils.vaccines import seed_vaccines, seed_vaccine_schedules

    with clinic["app"].app_context():
        seed_vaccines()
        seed_vaccine_schedules()
        Setting.set("vaccine_guideline_profile", "who")
        db.session.commit()
    return clinic


_N = [0]


def _child(clinic, age_months, dose_ages=()):
    """Returns ``(review reason, [(dose number, status)])``."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    _N[0] += 1
    with clinic["app"].app_context():
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        dob = local_today() - timedelta(days=int(age_months * 30.44))
        kid = Patient(patient_number=f"W{_N[0]}", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        for number, age in enumerate(dose_ages, start=1):
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=pcv.id, brand_id=brand.id,
                dose_number=number, event_type="given",
                given_date=dob + timedelta(days=int(age * 30.44))))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")
        return row.get("review"), [(d["dose_number"], d["status"])
                                   for d in row["doses"]]


def _owed(doses):
    from app.utils.vaccines import GIVEABLE

    return [n for n, status in doses if status in GIVEABLE]


# ------------------------------------------------------------- 2p+1

def test_the_routine_course_is_two_primary_doses_and_a_booster(who):
    review, doses = _child(who, 2)

    assert review is None
    assert len(doses) == 3, f"WHO's routine is not 2p+1: {doses}"


def test_it_is_a_different_course_from_the_cdc_s(who):
    """Otherwise choosing between them would be a setting that changes
    nothing. The CDC's is 3p+1 and WHO's is 2p+1, and a clinic switching
    should see its babies' schedules change."""
    from app.extensions import db
    from app.models import Setting

    _review, on_who = _child(who, 2)

    with who["app"].app_context():
        Setting.set("vaccine_guideline_profile", "cdc")
        db.session.commit()
    _review, on_cdc = _child(who, 2)

    assert len(on_who) == 3 and len(on_cdc) == 4, \
        f"the two references give the same course: {on_who} / {on_cdc}"


def test_a_late_start_under_a_year_is_still_the_routine_course(who):
    """Nine months and unvaccinated is the series begun late, not a catch-up:
    WHO's booster is stated for them and there is nothing unsettled about it."""
    review, doses = _child(who, 9)

    assert review is None, f"a plain late start was flagged: {review}"
    assert len(doses) == 3


def test_a_child_part_way_through_is_not_a_question(who):
    """Fourteen months with the two primary doses. The booster is owed, and it
    is owed by name — this child must not be swept into the unsettled band
    just because they have reached an age it covers."""
    review, doses = _child(who, 14, [2, 4])

    assert review is None, f"a child mid-course was flagged: {review}"
    assert _owed(doses) == [3], f"the booster is not owed: {doses}"


def test_a_completed_course_is_left_alone(who):
    review, doses = _child(who, 36, [2, 4, 9])

    assert review is None
    assert _owed(doses) == []


# --------------------------------------------- the end of the routine course

@pytest.mark.parametrize("age_months", [72, 120, 192])
@pytest.mark.parametrize("given", [(), (2,), (2, 4, 9)])
def test_a_healthy_child_over_five_is_not_chased(who, age_months, given):
    """The reason this table was added. The position paper is about children
    under five, and a clinic following it was being handed the rest of a
    baby's course for a healthy ten-year-old."""
    review, doses = _child(who, age_months, given)

    assert review is None, f"a plain record was flagged: {review}"
    assert _owed(doses) == [], \
        f"a healthy {age_months // 12}-year-old is still being chased: {doses}"


def test_the_doses_already_given_survive(who):
    _review, doses = _child(who, 72, [2, 4, 9])

    assert [n for n, status in doses if status == "done"] == [1, 2, 3], \
        f"a shut course lost the record of what happened: {doses}"


# ------------------------------------- and the number WHO does not settle

@pytest.mark.parametrize("age_months,given", [
    (14, ()),           # unvaccinated, in the band WHO names
    (14, (13,)),        # one dose, given inside the band
    (36, ()),
    (48, (30,)),
])
def test_the_unsettled_catch_up_asks_the_doctor(who, age_months, given):
    """Not a number, and not a blank either.

    WHO recommends catch-up between one and five years and says the optimal
    number of doses is not established. Writing "1" or writing "2" would be
    this program inventing a clinical number and putting WHO's name on it;
    writing nothing says the child is owed nothing, which is the opposite of
    what the reference says.
    """
    review, doses = _child(who, age_months, given)

    assert review == "guideline_unsettled", \
        f"the unsettled catch-up came out as an answer: {doses}"
    assert _owed(doses) == [], f"a dose count was invented: {doses}"


def test_it_still_shows_what_the_child_had(who):
    """A question about what is next must not erase what already happened."""
    _review, doses = _child(who, 48, [30])

    assert [n for n, status in doses if status == "done"] == [1]


# -------------------------------------------------------- the plumbing

def test_the_new_column_reaches_a_database_that_already_exists(who):
    from app.utils.schema import ADDITIONS

    assert ("vaccine_schedule_templates", "needs_review") in {
        (table, column) for table, column, *_ in ADDITIONS}


def test_every_reason_a_record_can_be_flagged_for_says_why(who):
    """The general hint says "this record cannot be scheduled from", which is
    true of a duplicated dose and false of a guideline that recommends
    something without saying how much. A flag that explains itself wrongly is
    one people stop reading."""
    import ast
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(here, "..", "app", "utils", "vaccines.py")
    with open(source, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    # Every literal assigned to `review` in the module, read rather than
    # searched: the file's own comments name these reasons too.
    reasons = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "review" in targets and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                reasons.add(node.value.value)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            reasons.add(node.value.value)

    reasons &= {"undated_dose", "duplicate_dose", "more_than_scheduled",
                "out_of_order", "guideline_silent", "guideline_unsettled"}
    assert len(reasons) == 6, f"the reader has drifted: {sorted(reasons)}"

    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            block = json.load(fh)["vreview"]
        for reason in reasons:
            assert f"why_{reason}" in block, \
                f"{lang} does not say why a record is flagged for {reason}"
