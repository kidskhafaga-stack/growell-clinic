"""The register-wide sweep reads columns, and still gives the file's answer.

The work-list counts walk every child who has ever had a dose here — on a
clinic that imported its history, that is the whole register. Measured at
15,000 children and 75,000 doses: seven queries and four seconds, nearly all
of it building model objects. 22µs apiece in change tracking, instrumented
attributes and lazy-load machinery, for 90,000 records that nothing in the
sweep modifies, to produce a few hundred rows.

Reading columns instead is sixteen times faster on the same query. The risk it
buys is the one worth naming: **two implementations of a schedule**, which do
not disagree on the day they are written and do disagree eventually, in front
of a family.

So there are not two. `course_dates` is the schedule — one function over plain
values — and both the patient's own file and the sweep call it. What differs
is the loading: the file wants the lot number, the doctor and the import batch
behind each dose, and the sweep wants none of them and cannot afford to build
them.

These tests hold the two to the same answer. Not a spot check on a fixture: the
ORM path is run against the flat one over a seeded clinic, dose by dose, and
any disagreement names the child and the vaccine.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from app.utils.clock import local_today  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """Children of assorted ages and histories, including the awkward ones.

    Deliberately mixed: a child part-way through a course, one who never
    started, one past a brand's window, one with a seasonal dose a year old,
    and one with a dose the doctor pencilled in — every branch `course_dates`
    has that a real record can reach. A patient with no birthday is not among
    them: the column is NOT NULL, so that branch is unreachable through the
    database and is checked directly instead.
    """
    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand

    from app.utils.vaccines import seed_vaccines

    with clinic["app"].app_context():
        seed_vaccines()
        db.session.commit()

        pcv = Vaccine.query.filter_by(code="PCV").first()
        mmr = Vaccine.query.filter_by(code="MMR").first()
        var = Vaccine.query.filter_by(code="VARICELLA").first()
        rota = Vaccine.query.filter_by(code="ROTA").first()
        flu = Vaccine.query.filter_by(code="FLU").first()
        prevenar = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                                name="Prevenar 13").first()
        synflorix = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                                 name="Synflorix").first()
        rotarix = VaccineBrand.query.filter_by(vaccine_id=rota.id,
                                               name="RotaRix").first()
        vaxigrip = VaccineBrand.query.filter_by(vaccine_id=flu.id,
                                                name="Vaxigrip").first()
        priorix = VaccineBrand.query.filter_by(vaccine_id=mmr.id,
                                               name="Priorix").first()
        varilrix = VaccineBrand.query.filter_by(vaccine_id=var.id,
                                                name="Varilrix").first()
        today = local_today()

        def kid(tag, age_days):
            p = Patient(patient_number=f"F{tag}", full_name=f"طفل {tag}",
                        gender="female", is_active=True,
                        date_of_birth=today - timedelta(days=age_days))
            db.session.add(p)
            db.session.flush()
            return p

        def dose(p, vaccine, brand, number, days_ago, event="given"):
            db.session.add(PatientVaccine(
                patient_id=p.id, vaccine_id=vaccine.id, brand_id=brand.id,
                dose_number=number, event_type=event,
                given_date=today - timedelta(days=days_ago)))

        a = kid("part", 400)                 # part-way through PCV
        dose(a, pcv, prevenar, 1, 340)
        dose(a, pcv, prevenar, 2, 280)

        b = kid("late", 1200)                # started, then stopped
        dose(b, pcv, prevenar, 1, 1140)

        c = kid("shut", 900)                 # past the rotavirus window
        dose(c, rota, rotarix, 1, 840)

        d = kid("season", 700)               # seasonal, a year old
        dose(d, flu, vaxigrip, 1, 400)

        e = kid("plan", 500)                 # a dose the doctor pencilled in
        dose(e, pcv, prevenar, 1, 440)
        db.session.add(PatientVaccine(
            patient_id=e.id, vaccine_id=pcv.id, brand_id=prevenar.id,
            dose_number=2, event_type="planned",
            given_date=today + timedelta(days=20)))

        g = kid("fresh", 90)                 # inside every window
        dose(g, rota, rotarix, 1, 30)

        # Locked to a brand that is not the default, and still mid-course:
        # Synflorix carries a five-year ceiling that Prevenar 13 does not, so
        # a sweep that reached for the default would differ here and nowhere
        # else in this ward.
        i = kid("brand", 1000)
        dose(i, pcv, synflorix, 1, 940)

        # Two live parenteral vaccines: MMR given a few days ago pushes the
        # varicella dose out by the 28-day spacing rule. Without a child like
        # this in here, a sweep that forgot the rule agreed with the file on
        # every row and the comparison passed — measured, by removing it.
        h = kid("live", 800)
        dose(h, mmr, priorix, 1, 5)      # a live one, days ago
        dose(h, var, varilrix, 1, 700)   # so varicella #2 is long overdue

        db.session.commit()
    return clinic


def _by_orm(clinic, today):
    """What the patient's own file would say, patient by patient."""
    from app.models import Patient
    from app.utils.vaccines import doses_for, patient_due_reminders

    people = Patient.query.filter(Patient.is_active.is_(True)).all()
    doses = doses_for([p.id for p in people])
    out = {}
    for person in people:
        rows = patient_due_reminders(person, "ar", today,
                                     doses=doses.get(person.id, []))
        out[person.id] = sorted(
            (r["vaccine"].code, r["brand"].name if r["brand"] else None,
             r["dose_number"], r["status"], r.get("due_date")) for r in rows)
    return out


def _by_flat(clinic, today):
    """What the sweep says, from columns."""
    from app.extensions import db
    from app.models import Patient, PatientVaccine
    from app.utils.vaccines import scan_due

    rows = db.session.query(Patient.id, Patient.date_of_birth).filter(
        Patient.is_active.is_(True)).all()
    doses = db.session.query(
        PatientVaccine.patient_id, PatientVaccine.vaccine_id,
        PatientVaccine.brand_id, PatientVaccine.dose_number,
        PatientVaccine.given_date, PatientVaccine.event_type).all()
    grouped = {}
    for pid, vid, bid, number, given, event in doses:
        grouped.setdefault(pid, []).append((vid, bid, number, given, event))

    out = {}
    for pid, dob in rows:
        found = scan_due(dob, grouped.get(pid, []), today)
        out[pid] = sorted(
            (r["vaccine"].code, r["brand"].name if r["brand"] else None,
             r["dose_number"], r["status"], r.get("due_date")) for r in found)
    return out


def test_the_two_paths_give_the_same_answer(ward):
    """The guarantee the whole change rests on."""
    today = local_today()

    with ward["app"].app_context():
        orm = _by_orm(ward, today)
        flat = _by_flat(ward, today)

    assert set(orm) == set(flat)
    for patient_id in sorted(orm):
        assert orm[patient_id] == flat[patient_id], (
            f"patient {patient_id}: the file says {orm[patient_id]} "
            f"and the sweep says {flat[patient_id]}")


def test_the_comparison_is_actually_looking_at_something(ward):
    """A comparison of two empty lists passes for ever."""
    today = local_today()

    with ward["app"].app_context():
        orm = _by_orm(ward, today)

    rows = [row for rows in orm.values() for row in rows]
    assert len(rows) >= 4, f"the fixture produced almost nothing: {orm}"
    assert {r[3] for r in rows} & {"overdue", "due", "seasonal"}, \
        "no pending dose in the fixture at all"


def test_a_missing_birthday_does_not_break_the_sweep(ward):
    """`course_dates` guards on a null birthday, so the sweep must survive one.

    The column is NOT NULL, so no row can carry this today — which is exactly
    why it is worth pinning: the guard is unreachable through the database and
    would rot unnoticed until the day somebody relaxes the column.
    """
    from app.utils.vaccines import scan_due

    with ward["app"].app_context():
        assert scan_due(None, [], local_today()) == []


def test_the_shut_window_survives_the_flat_path(ward):
    """The rule added yesterday has to hold on the new road too."""
    from app.utils.vaccine_due import due_list

    with ward["app"].app_context():
        codes = {r["vaccine"].code for r in due_list(today=local_today())}

    assert "ROTA" not in codes or all(
        r["status"] != "expired" for r in due_list(today=local_today())), \
        "an expired dose is being chased through the sweep"


def test_the_sweep_is_flat_and_stays_flat(ward):
    """The point of the change, asserted as shape rather than milliseconds.

    Adding children must not add queries. A stopwatch measures the machine; the
    query count measures the code.
    """
    from sqlalchemy import event

    from app.extensions import db
    from app.models import Patient, PatientVaccine, Vaccine, VaccineBrand
    from app.utils.vaccine_due import due_list

    with ward["app"].app_context():
        engine = db.engine
        pcv = Vaccine.query.filter_by(code="PCV").first()
        brand = VaccineBrand.query.filter_by(vaccine_id=pcv.id,
                                             name="Prevenar 13").first()
        today = local_today()

        counts = []
        for batch in range(2):
            db.session.bulk_insert_mappings(Patient, [
                {"patient_number": f"B{batch}-{i}", "full_name": "ط",
                 "gender": "male", "is_active": True,
                 "date_of_birth": today - timedelta(days=500 + i)}
                for i in range(120)])
            db.session.commit()
            fresh = [r[0] for r in db.session.query(Patient.id).filter(
                Patient.patient_number.like(f"B{batch}-%")).all()]
            db.session.bulk_insert_mappings(PatientVaccine, [
                {"patient_id": pid, "vaccine_id": pcv.id, "brand_id": brand.id,
                 "dose_number": 1, "event_type": "given",
                 "given_date": today - timedelta(days=440)} for pid in fresh])
            db.session.commit()

            state = {"n": 0}

            def _count(conn, cur, statement, params, context, many):
                state["n"] += 1

            event.listen(engine, "after_cursor_execute", _count)
            found = due_list(today=today)
            event.remove(engine, "after_cursor_execute", _count)
            counts.append(state["n"])

        assert found, "the sweep returned nothing, so it counted nothing"

    assert counts[1] <= counts[0] + 2, (
        f"the sweep costs more queries as the clinic grows: {counts}")
