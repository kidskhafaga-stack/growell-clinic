"""Whether a series may be *begun*, which is a different question from when.

The program asked when to give a dose and never whether it may. Rotavirus is
where that shows: the series has to be finished by 24 weeks on RotaRix, and it
also must not be *started* after about 15. Those are two deadlines, and a
child can be past the first while still inside the second.

Before this, an eighteen-week-old who had never had it was offered the course
— a first dose the label does not allow — and a three-year-old was offered it
too, held off only by the finish ceiling that arrived later.

    18 weeks, nothing yet     not_eligible, not_eligible
    18 weeks, started at 8    done, overdue        ← still inside the finish window
    30 weeks, started at 8    done, expired

The middle row is the whole reason these are separate columns. One ceiling
could not tell those two children apart, and the difference between them is a
dose that should be given and a dose that should not.

`not_eligible` is its own status rather than `expired`: expired is about
finishing something begun, this is about never beginning. Neither is in
`GIVEABLE`, so both leave the offer list and the reminders together.
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


def _rota(seeded, tag, weeks_old, started_at_weeks=None):
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                             name="RotaRix").first()
        dob = local_today() - timedelta(weeks=weeks_old)
        kid = Patient(patient_number=f"SW{tag}", full_name="رضيع",
                      gender="male", date_of_birth=dob, is_active=True)
        db.session.add(kid)
        db.session.flush()
        if started_at_weeks is not None:
            db.session.add(PatientVaccine(
                patient_id=kid.id, vaccine_id=rota.id, brand_id=brand.id,
                dose_number=1, event_type="given",
                given_date=dob + timedelta(weeks=started_at_weeks)))
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "ROTA")
        return [d["status"] for d in row["doses"]]


# ------------------------------------------------------------ the window

def test_a_baby_inside_the_window_is_offered_it(seeded):
    """The half that proves the rule did not switch the vaccine off."""
    states = _rota(seeded, "a", 8)

    assert "not_eligible" not in states
    assert states[0] in ("suggested", "due", "overdue")


def test_a_baby_past_the_start_window_is_not(seeded):
    """Eighteen weeks, nothing given. The label does not allow beginning."""
    assert set(_rota(seeded, "b", 18)) == {"not_eligible"}


def test_an_older_child_is_not_offered_it_either(seeded):
    assert set(_rota(seeded, "c", 160)) == {"not_eligible"}


# ------------------------------------------- the two deadlines are different

def test_a_series_already_begun_carries_on_past_the_start_window(seeded):
    """The row that makes these two separate columns.

    Eighteen weeks old and started at eight: past the deadline for *starting*,
    inside the one for *finishing*. The second dose is owed, and a single
    ceiling could not tell this child from the one above.
    """
    states = _rota(seeded, "d", 18, started_at_weeks=8)

    assert states[0] == "done"
    assert "overdue" in states, \
        f"a series already begun was cut off by the start window: {states}"
    assert "not_eligible" not in states


def test_and_still_stops_at_the_finish_window(seeded):
    """Beyond 24 weeks the remaining dose expires — the other ceiling, which
    this must not have replaced."""
    states = _rota(seeded, "e", 30, started_at_weeks=8)

    assert states[0] == "done"
    assert "expired" in states


# ------------------------------------------------------------- the status

def test_it_is_not_on_the_giveable_list(seeded):
    """So it leaves the visit panel and the reminders together."""
    from app.utils.vaccines import GIVEABLE

    assert "not_eligible" not in GIVEABLE


def test_it_is_not_chased_by_the_sweep(seeded):
    from app.utils.vaccine_due import due_list

    _rota(seeded, "f", 18)

    with seeded["app"].app_context():
        codes = {r["vaccine"].code for r in due_list()}

    assert "ROTA" not in codes


def test_the_catalogue_carries_both_ceilings(seeded):
    """Two numbers per brand, because the label states two."""
    from app.models import Vaccine, VaccineBrand

    with seeded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        got = {b.name: (b.max_age_first_dose_days, b.max_age_final_dose_days)
               for b in VaccineBrand.query.filter_by(vaccine_id=rota.id)}

    assert got == {"RotaRix": (15 * 7, 24 * 7),
                   "RotaTeq": (15 * 7, 32 * 7),
                   "Rotasiil": (15 * 7, 34 * 7)}


def test_a_vaccine_with_no_start_window_is_untouched(seeded):
    """Most of the catalogue has no deadline for beginning."""
    from app.extensions import db
    from app.models import Patient
    from app.utils.vaccines import patient_plan

    with seeded["app"].app_context():
        kid = Patient(patient_number="SWpcv", full_name="طفل", gender="male",
                      date_of_birth=local_today() - timedelta(days=900),
                      is_active=True)
        db.session.add(kid)
        db.session.commit()
        row = next(v for v in patient_plan(kid) if v["vaccine"].code == "PCV")

    assert "not_eligible" not in [d["status"] for d in row["doses"]]


# ------------------------------------------- one concept, and it has two words

def test_neither_shut_window_is_printed_as_a_suggestion(seeded):
    """The bug this section exists for, found a day after the split.

    Splitting a shut window into two words left every place that had written
    `== "expired"` offering the other half. The certificate did: a
    two-year-old was handed a printed rotavirus suggestion, dated to when
    they were two months old — a course no clinic on earth can give them.

    Both children are built, because that is the only way this could have
    caught it: one who never began (`not_eligible`) and one who began and ran
    out of time (`expired`). Asserting either alone passes.

    Read from the template's own context rather than by searching the page.
    A child who *started* has rotavirus printed on the certificate as a
    record — correctly — so grepping the HTML for the vaccine's name cannot
    tell a record from a suggestion, and a test that cannot tell them apart
    is a test that will be deleted the first time it fires.
    """
    from flask import template_rendered

    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    with seeded["app"].app_context():
        rota = Vaccine.query.filter_by(code="ROTA").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                             name="RotaRix").first()
        made = {}
        for tag, weeks, started in (("never", 104, None), ("ranout", 30, 8)):
            dob = local_today() - timedelta(weeks=weeks)
            kid = Patient(patient_number=f"SWc{tag}", full_name="رضيع",
                          gender="male", date_of_birth=dob, is_active=True)
            db.session.add(kid)
            db.session.flush()
            if started is not None:
                db.session.add(PatientVaccine(
                    patient_id=kid.id, vaccine_id=rota.id, brand_id=brand.id,
                    dose_number=1, event_type="given",
                    given_date=dob + timedelta(weeks=started)))
            made[tag] = kid.id
        db.session.commit()

    client = seeded["sign_in"]("doc")
    for tag, patient_id in made.items():
        seen = []

        def record(_sender, template, context, **_kw):
            for key in ("suggested", "upcoming"):
                if key in context:
                    seen.append(context[key])

        # **Both** tables. The certificate has two, and which one a child
        # lands in depends on whether they ever started: the one who never
        # began is in "what the age suggests", the one who ran out of time is
        # in "what is left". Asking only the first is how the `expired` half
        # of this filter stayed untested — measured, by removing it.
        template_rendered.connect(record, seeded["app"])
        try:
            client.get(
                f"/vaccinations/{patient_id}/certificate?suggest=1&schedule=1",
                follow_redirects=True)
        finally:
            template_rendered.disconnect(record, seeded["app"])

        assert seen, "the certificate rendered neither table"
        offered = {r["vaccine"].code for rows in seen for r in rows}
        assert "ROTA" not in offered, \
            f"the certificate still prints a shut course ({tag}): {offered}"


def test_the_filter_asks_the_named_set_rather_than_a_word(seeded):
    """Written against the source because the failure was structural.

    A literal status word in a filter is a filter that is correct until the
    vocabulary grows, and then silently is not. The set is named once in
    `vaccines.py`; a third shut status added there has to reach the paper
    without anybody remembering this file.
    """
    import ast

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "app/blueprints/vaccinations/routes.py"),
              encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    from app.utils.vaccines import SHUT

    literals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value in SHUT]

    assert not literals, (
        "a shut-window status is written as a literal in the vaccinations "
        f"routes at line(s) {[n.lineno for n in literals]} — it should ask "
        "`SHUT`")


def test_shut_and_giveable_do_not_overlap(seeded):
    """A status in both would make a dose simultaneously offerable and
    impossible, which is the shape of the bug rather than a typo.

    The set is pinned as well as checked for overlap, so a status joining or
    leaving it is a deliberate edit here. `out_of_scope` joined when the
    schedule's range became a thing separate from the product's licence: it
    shuts a course for the same practical purpose — nothing owed, nothing
    offered, nothing reprinted on a certificate as outstanding — while saying
    something different about why.
    """
    from app.utils.vaccines import GIVEABLE, SHUT

    assert not set(SHUT) & set(GIVEABLE)
    assert set(SHUT) == {"expired", "not_eligible", "out_of_scope"}


def test_the_wording_exists_in_both_languages(seeded):
    import json

    here = os.path.dirname(os.path.abspath(__file__))
    for lang in ("ar", "en"):
        with open(os.path.join(here, "..", "app/i18n/locales", f"{lang}.json"),
                  encoding="utf-8") as fh:
            assert "not_eligible" in json.load(fh)["vstatus"], \
                f"{lang} has no word for a window that never opened"
