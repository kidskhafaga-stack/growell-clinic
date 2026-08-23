"""A date the schedule projected onto a birthday, once that date has passed.

Reported from a real file: a woman of twenty-nine, no doses on this clinic's
record. Her vaccination screen opened on nineteen suggested courses and
announced, in the banner headed *"the next due vaccination"*, the hexavalent's
first dose — *at 2 months* — dated **1997**.

Nothing there was miscalculated. Every unpromised status means, in the
engine's own words, that *neither is a course this clinic ever promised*:
`suggested` is offered because the age fits, `national` is given free at the
government unit, `on_demand` waits for a dog bite. Their "due dates" are the
age the schedule states, run through a birthday. That is a true statement
about arithmetic, and once the date is behind us it is a useless one about
medicine — nobody made an appointment for 1997.

**The fix is about what is printed, not about what is offered**, and the line
between those two is the whole of this file. Withdrawing the offer on the
strength of a passed date would mean the program deciding an upper age for
each vaccine, and it does not know one: thirty-seven of the catalogue's
forty-eight products carry no finish ceiling at all. A three-year-old who never
had varicella is owed a catch-up and still gets one here; what they no longer
get is a stale calendar date beside it. The age band stays on every row, which
is the sentence the schedule actually makes.

Two smaller things ride along, both from the same screen. The banner is not
allowed to answer with a stale projection — with nothing else to name,
"nothing is due" is the honest line. And the suggestions shelf no longer opens
on arrival, because on this file it opened over the one thing the doctor came
for.
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


_COUNTER = [0]


def _patient(seeded, years):
    """Somebody of `years`, with nothing at all on this clinic's record."""
    from app.extensions import db
    from app.models import Patient

    _COUNTER[0] += 1
    with seeded["app"].app_context():
        dob = local_today() - timedelta(days=int(years * 365.25))
        person = Patient(patient_number=f"AG{_COUNTER[0]}", full_name="مريض",
                         gender="female", date_of_birth=dob, is_active=True)
        db.session.add(person)
        db.session.commit()
        return person.id


def _plan(seeded, patient_id):
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        return patient_plan(db.session.get(Patient, patient_id))


# ------------------------------------------------------------ the rule itself

def test_a_date_nobody_promised_keeps_its_age_and_loses_its_date(seeded):
    """The engine marks it; the screens read the mark rather than the date.

    Marked in one place on purpose. The banner, the dose rows and the
    certificate all need the answer, and this file has already once had two
    screens work the same rule out separately and disagree about the same
    child.
    """
    from app.utils.vaccines import PROMISED

    patient_id = _patient(seeded, 29)
    plan = _plan(seeded, patient_id)

    stale = [d for item in plan for d in item["doses"] if d.get("stale_date")]
    assert stale, "not one of an adult's infant-schedule dates was marked"
    for d in stale:
        assert d["status"] not in PROMISED, \
            f"a promised appointment was treated as a projection: {d}"
        assert not d.get("given_date"), \
            f"a dose that actually happened was marked stale: {d}"
        assert d["due_date"] < local_today().isoformat(), \
            f"a date still ahead of us was marked stale: {d}"
        assert d["age_label"], \
            "the date was taken away and nothing was left in its place"


def test_the_offer_survives_the_date(seeded):
    """The line this whole change has to stay on the right side of.

    A three-year-old who never had varicella is owed a catch-up — the dose was
    recommended at twelve months, which is eighteen months ago, and none of
    that makes it too late to give. Deciding otherwise would mean this program
    inventing an upper age for a product whose leaflet states none, which is
    the one thing it is not allowed to do.
    """
    from app.utils.vaccines import GIVEABLE

    patient_id = _patient(seeded, 3)
    plan = _plan(seeded, patient_id)

    varicella = next(v for v in plan if v["vaccine"].code == "VARICELLA")
    doses = varicella["doses"]

    assert any(d.get("stale_date") for d in doses), \
        "the case is not being exercised — no dose here has a passed date"
    assert [d["dose_number"] for d in doses if d["status"] in GIVEABLE], \
        "hiding a date withdrew the catch-up it was attached to"


def test_a_promise_keeps_its_date_however_late_it_got(seeded):
    """`due` and `overdue` mean somebody started this course here or agreed to
    it. That is an appointment, and an appointment missed in March is still an
    appointment — the date is exactly what the doctor needs to see.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        varicella = Vaccine.query.filter_by(code="VARICELLA").first()
        brand = (VaccineBrand.query.filter_by(vaccine_id=varicella.id)
                 .order_by(VaccineBrand.id).first())
        dob = local_today() - timedelta(days=int(4 * 365.25))
        kid = Patient(patient_number="AGpromise", full_name="طفل",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        db.session.add(PatientVaccine(
            patient_id=kid.id, vaccine_id=varicella.id, brand_id=brand.id,
            dose_number=1, event_type="given",
            given_date=dob + timedelta(days=380)))
        db.session.commit()
        row = next(v for v in patient_plan(kid)
                   if v["vaccine"].code == "VARICELLA")

    owed = [d for d in row["doses"] if d["status"] != "done"]
    assert owed, "the second dose vanished"
    for d in owed:
        assert not d.get("stale_date"), \
            f"a started course was treated as a projection: {d}"
        assert d["due_date"], "a promised dose lost the date it was promised for"


# ------------------------------------------------------------- and the banner

def test_the_next_due_banner_will_not_answer_with_1997(seeded):
    """The reported sentence, by name.

    The banner is headed *"the next due vaccination"*. A dose from twenty-nine
    years ago is neither next nor due, and naming one there is the screen
    telling a doctor something it does not mean.
    """
    from app.utils.vaccines import next_due_dose

    patient_id = _patient(seeded, 29)
    plan = _plan(seeded, patient_id)

    nxt = next_due_dose(plan)
    if nxt is not None:
        assert nxt[3]["due_date"] >= local_today().isoformat(), \
            (f"the banner is announcing {nxt[1].code} dose "
             f"{nxt[3]['dose_number']} for {nxt[3]['due_date']}")


def test_with_nothing_left_to_name_it_says_nothing_is_due(seeded):
    """And the other half of that: the banner going quiet has to be reachable,
    or "never answers with a stale date" could be satisfied by always having
    something stale to fall back on.

    Influenza is dropped rather than the test being written around it. Its
    suggestion is projected onto today every day of the year — it is a
    seasonal course, so there is no age it is late for — which makes it the one
    thing on an adult's plan that is never stale, and the reason the previous
    test's banner is not silent.
    """
    from app.utils.vaccines import next_due_dose

    patient_id = _patient(seeded, 29)
    plan = [item for item in _plan(seeded, patient_id)
            if not item["vaccine"].is_seasonal]

    assert plan, "the plan was emptied by the filter, so nothing is under test"
    assert next_due_dose(plan) is None, \
        "a date that has been and gone is being offered as the next one due"


# --------------------------------------------------------------- the shelves

def test_the_suggestions_shelf_does_not_open_over_the_answer(seeded):
    """Asked for directly, and the reported file is the argument.

    A patient with no doses on this clinic's record has *every* age-appropriate
    course on the suggestions shelf — nineteen of them on the screen that was
    sent in — so the courses already under way, which is what somebody opens
    this page to see, were below a wall of them.

    Nothing is hidden. The counter at the top of the page still says how many
    there are and the heading carries the count; the shelf simply arrives
    shut.
    """
    from app.utils.vaccines import OPEN_GROUPS

    assert "started" in OPEN_GROUPS, \
        "the courses owing a dose today no longer open on arrival"
    assert "ready" not in OPEN_GROUPS, \
        "the wall of suggestions is opening over the answer again"


def test_the_screen_shows_the_shelves_that_way(seeded):
    """And through the page itself, because a constant nothing renders is not
    a behaviour. `<details open>` is what the browser acts on."""
    import re

    patient_id = _patient(seeded, 29)
    page = seeded["sign_in"]("boss").get(
        f"/vaccinations/{patient_id}").get_data(as_text=True)

    shelves = re.findall(r"<details[^>]*vac-group[^>]*>", page)
    assert shelves, "the plan is not being rendered on shelves at all"
    assert not any(" open" in tag for tag in shelves), \
        f"a shelf opened on a patient who has started nothing: {shelves}"


def test_the_page_does_not_print_the_projected_date(seeded):
    """End to end, on the rendered HTML, because the marking is only worth
    anything if a template reads it.

    Matched on the row rather than on the date alone. Two vaccines recommended
    at the same age project onto the same day, so a bare search for the date
    finds a row this rule was never about and the test fails on its own
    fixture — which is how the first draft of it failed.
    """
    import re

    patient_id = _patient(seeded, 29)
    plan = _plan(seeded, patient_id)

    hidden = [d for item in plan for d in item["doses"] if d.get("stale_date")]
    assert hidden, "the case is not being exercised"

    page = seeded["sign_in"]("boss").get(
        f"/vaccinations/{patient_id}").get_data(as_text=True)
    printed = set(re.findall(r'<span class="dd">([^<]*·[^<]*)</span>', page))

    for d in hidden:
        row = f"{d['age_label']} · {d['due_date']}"
        assert row not in printed, \
            (f"the screen is still printing {d['due_date']} for a dose "
             f"recommended at {d['age_label']}")

    # And the age band did not go with the date: every hidden dose's age still
    # stands in a cell of its own.
    bare = {cell.strip() for cell in
            re.findall(r'<span class="dd">([^<·]*)</span>', page)}
    missing = {d["age_label"] for d in hidden} - bare
    assert not missing, \
        f"the date was taken away and the age went with it: {missing}"
