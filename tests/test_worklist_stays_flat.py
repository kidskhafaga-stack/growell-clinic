"""The desk's work-list counts walked every vaccinated patient, one at a time.

Reported as thirteen seconds on `/messages/desk`, with a screenshot that ruled
out everything easy: "waiting for server response 12.18 s" against a desk
saying nobody was waiting and no messages at all. So not the network, not the
assets, and nothing to do with the message log — which is where the previous
day of desk work had been looking.

What runs regardless is the work-list card, and its vaccine half asks
`due_list`, which walks every patient who has ever had a dose here and builds
their whole plan. Each plan read the patient's doses (already loaded a line
earlier, then asked for again per vaccine by `chosen_brand`) and re-read the
vaccine catalogue.

    2,000 vaccinated patients   12,005 queries   4,364 ms   ->   9 queries   228 ms
    the desk around it           4,587 ms                        428 ms

Measured before and after, and the card it was drawing said zero.

These assert the **shape**, not a millisecond: that the work does not grow with
the register. A stopwatch measures the machine; the query count measures the
code.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def counting(clinic):
    """Counts SQL statements while something is worked out."""
    from sqlalchemy import event

    from app.extensions import db

    with clinic["app"].app_context():
        engine = db.engine

    state = {"n": 0, "on": False}

    def _count(conn, cur, statement, params, context, many):
        if state["on"]:
            state["n"] += 1

    event.listen(engine, "after_cursor_execute", _count)
    clinic["count"] = state
    yield clinic
    event.remove(engine, "after_cursor_execute", _count)


def _vaccinated(clinic, n, offset=0):
    """`n` more children who have each had a dose here.

    That is the set `due_list` walks — not every patient on file, which is the
    one thing it was already careful about.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, VaccineBrand

    brand = VaccineBrand.query.first()
    today = local_today()
    kids = []
    for i in range(offset, offset + n):
        kid = Patient(patient_number=f"W{i}", full_name=f"طفل {i}",
                      gender="male",
                      date_of_birth=today - timedelta(days=400 + (i % 300)),
                      is_active=True)
        db.session.add(kid)
        kids.append(kid)
    db.session.flush()
    for i, kid in enumerate(kids):
        db.session.add(PatientVaccine(
            patient_id=kid.id, brand_id=brand.id, vaccine_id=brand.vaccine_id,
            dose_number=1, event_type="given",
            given_date=today - timedelta(days=200 + (i % 90))))
    db.session.commit()


def _cost(counting, work):
    counting["count"]["n"] = 0
    counting["count"]["on"] = True
    with counting["app"].app_context():
        work()
    counting["count"]["on"] = False
    return counting["count"]["n"]


# --------------------------------------------------------------- the shape

def test_the_due_list_does_not_ask_per_patient(counting):
    """The assertion that would have caught this: adding children must not add
    queries."""
    from app.utils.vaccine_due import due_list

    with counting["app"].app_context():
        _vaccinated(counting, 40)
    small = _cost(counting, lambda: due_list(status="overdue"))

    with counting["app"].app_context():
        _vaccinated(counting, 160, offset=1000)
    big = _cost(counting, lambda: due_list(status="overdue"))

    assert small > 2, "the counter did not see the list being built"
    assert big <= small + 2, (
        f"five times the patients cost {big} queries instead of {small} — "
        "the list is asking per patient again")


def test_the_desk_does_not_ask_per_patient_either(counting):
    """End to end, on the screen that was reported."""
    with counting["app"].app_context():
        _vaccinated(counting, 40)
    client = counting["sign_in"]("desk")

    counting["count"]["n"] = 0
    counting["count"]["on"] = True
    client.get("/messages/desk", follow_redirects=True)
    counting["count"]["on"] = False
    small = counting["count"]["n"]

    with counting["app"].app_context():
        _vaccinated(counting, 160, offset=2000)

    counting["count"]["n"] = 0
    counting["count"]["on"] = True
    answer = client.get("/messages/desk", follow_redirects=True)
    counting["count"]["on"] = False
    big = counting["count"]["n"]

    assert answer.status_code == 200
    assert small > 5
    assert big <= small + 3, (
        f"the desk cost {small} queries at 40 vaccinated patients and {big} "
        "at 200")


def test_the_catalogue_is_read_once(counting):
    """A dozen rows that do not change while a page is built, re-read for every
    patient the list walked."""
    from app.utils.vaccines import _all_vaccines

    with counting["app"].app_context():
        _vaccinated(counting, 20)

    def twice():
        _all_vaccines()
        _all_vaccines()
        _all_vaccines()

    with counting["app"].test_request_context("/"):
        assert _cost(counting, twice) <= 1, \
            "the vaccine catalogue is read more than once per request"


# ----------------------------------------------------- the answer is the same

def test_the_batched_doses_give_the_same_plan(clinic):
    """A faster answer that disagrees with the slow one is not an optimisation.

    Checked against the unbatched path itself rather than a fixture, so the two
    cannot drift apart quietly.
    """
    from app.models import Patient
    from app.utils.vaccines import doses_for, patient_plan

    with clinic["app"].app_context():
        _vaccinated(clinic, 6)
        kids = Patient.query.filter(Patient.patient_number.like("W%")).all()
        batched = doses_for([k.id for k in kids])

        for kid in kids:
            slow = patient_plan(kid)
            fast = patient_plan(kid, doses=batched.get(kid.id, []))
            assert len(slow) == len(fast)
            for a, b in zip(slow, fast):
                assert a["vaccine"].id == b["vaccine"].id
                a_brand = a["brand"].id if a["brand"] else None
                b_brand = b["brand"].id if b["brand"] else None
                assert a_brand == b_brand, \
                    "the batched plan locked a different brand"
                assert ([d["status"] for d in a["doses"]]
                        == [d["status"] for d in b["doses"]])


def test_the_locked_brand_is_the_one_sql_would_have_picked(clinic):
    """`chosen_brand` takes the **latest** given dose — the product the course
    is on now — and rows do not arrive in that order. Reproduced in Python
    rather than approximated, because this decides which brand a child is
    followed on: pick the wrong row and the plan quietly switches them to
    another manufacturer.

    It caught exactly that. The rule changed from "the first dose" to "the
    latest" when a child switching from Prevenar to Vaxneuvance had to be
    followed on Vaxneuvance, and only the batched path was moved — so a child
    with two doses recorded on one day came out on two different
    manufacturers depending on which screen asked.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccines import chosen_brand, doses_for

    with clinic["app"].app_context():
        kid = Patient.query.first()
        vaccine = Vaccine.query.first()
        first = VaccineBrand.query.filter_by(vaccine_id=vaccine.id).first()
        other = VaccineBrand(vaccine_id=vaccine.id, name="Other", price=100,
                             doses_per_vial=1)
        db.session.add(other)
        db.session.flush()
        today = local_today()
        # Inserted second-dose-first: the row order and the dose order
        # disagree, which is the only thing that makes this test able to fail.
        db.session.add_all([
            PatientVaccine(patient_id=kid.id, vaccine_id=vaccine.id,
                           brand_id=other.id, dose_number=2,
                           event_type="given", given_date=today),
            PatientVaccine(patient_id=kid.id, vaccine_id=vaccine.id,
                           brand_id=first.id, dose_number=1,
                           event_type="given", given_date=today),
        ])
        db.session.commit()

        slow_brand, slow_locked = chosen_brand(kid.id, vaccine)
        batched = doses_for([kid.id])
        by_vaccine = {}
        for pv in batched[kid.id]:
            if (pv.event_type or "given") == "given":
                by_vaccine.setdefault(pv.vaccine_id, []).append(pv)
        fast_brand, fast_locked = chosen_brand(kid.id, vaccine, given=by_vaccine)

        assert slow_locked is True and fast_locked is True
        assert slow_brand.id == fast_brand.id, (
            "the batched lookup locked a different brand than the query it "
            f"replaced: {fast_brand.name} vs {slow_brand.name}")


def test_a_patient_with_no_doses_is_not_invented(clinic):
    from app.utils.vaccines import doses_for

    with clinic["app"].app_context():
        assert doses_for([]) == {}
        assert doses_for([999999]) == {}
