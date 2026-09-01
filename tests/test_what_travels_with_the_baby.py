"""What has to go with a newborn who is being sent on.

Phase 5 of EMERGENCY_NEWBORN_PLAN.md.

A clinic does not run a neonatal unit; it decides a baby needs one and sends
them. The referral for that already existed. What was missing is everything a
receiving unit asks on the phone — gestation, birth weight, **hours** of age,
the bilirubin readings and when each was drawn — which a clinic then reads out
from four different screens while somebody is holding a baby.

Two properties carry the weight here:

* **it gathers, it does not decide.** Nothing here says a baby should be
  transferred and nothing here produces a threshold.
* **it says what is missing out loud.** A sheet that omits the gestation
  because nobody recorded it reads, to whoever receives it, as a term baby.
"""
from datetime import date, datetime, time, timedelta

import pytest

from app.utils import transfer


@pytest.fixture
def newborn(clinic):
    from app.models import Patient
    from app.utils.clock import local_now

    with clinic["app"].app_context():
        born = local_now().replace(tzinfo=None) - timedelta(hours=61)
        row = Patient(patient_number="T1", full_name="مولود", gender="male",
                      date_of_birth=born.date(),
                      birth_time=time(born.hour, born.minute),
                      gestation_weeks=35, gestation_days=4,
                      birth_weight_kg=2.1, is_active=True)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        yield row


def _bilirubin(kit, patient, value, when=None):
    from app.models import Measurement

    with kit["app"].app_context():
        row = Measurement(patient_id=patient.id, code="bilirubin",
                          value_num=value, unit="mg/dL")
        if when is not None:
            row.recorded_at = when
        kit["db"].session.add(row)
        kit["db"].session.commit()


# ----------------------------------------------------- it carries the facts -
def test_it_carries_the_gestation_as_it_was_written(clinic, newborn):
    """"35+4", not 35.57. That is how a discharge summary prints it and how
    the unit on the phone will say it back."""
    with clinic["app"].app_context():
        assert transfer.summary(newborn)["gestation"] == "35+4"


def test_it_carries_hours_and_not_only_days(clinic, newborn):
    """A newborn's thresholds move by the hour. "Two days old" is the fact
    that loses the baby a decision."""
    with clinic["app"].app_context():
        out = transfer.summary(newborn)
    assert out["age_hours"] == pytest.approx(61, abs=1)
    assert out["age_days"] == pytest.approx(2, abs=1)


def test_it_carries_the_birth_weight_and_that_they_were_preterm(clinic,
                                                                newborn):
    with clinic["app"].app_context():
        out = transfer.summary(newborn)
    assert out["birth_weight"] == 2.1
    assert out["preterm"] is True


def test_it_carries_the_bilirubin_readings_with_their_times(clinic, newborn):
    """A single number is a snapshot; the series is the thing a unit acts on,
    because the rate of rise is the question."""
    older = datetime.utcnow() - timedelta(hours=12)
    _bilirubin(clinic, newborn, 11.0, when=older)
    _bilirubin(clinic, newborn, 14.2)

    with clinic["app"].app_context():
        readings = transfer.summary(newborn)["bilirubin"]
    assert [r["value"] for r in readings] == [14.2, 11.0], "newest first"
    assert all(r["taken_at"] is not None for r in readings)


def test_the_readings_are_dated_when_drawn_not_when_typed(clinic, newborn):
    """On a value phoned in from a lab those are different days, and a sheet
    dated by the typing would put a rising baby's readings in the wrong
    order."""
    from app.models import Measurement

    yesterday = datetime.utcnow() - timedelta(days=1)
    _bilirubin(clinic, newborn, 9.0, when=yesterday)
    _bilirubin(clinic, newborn, 15.0, when=datetime.utcnow())

    with clinic["app"].app_context():
        readings = transfer.summary(newborn)["bilirubin"]
        assert readings[0]["value"] == 15.0
        assert readings[0]["taken_at"] > readings[1]["taken_at"]


def test_it_reads_the_measurements_the_clinic_already_records(clinic, newborn):
    """Not a second place to type a bilirubin. Two stores would mean two
    answers to "what was his bilirubin yesterday"."""
    import inspect

    assert "Measurement" in inspect.getsource(transfer)


# ------------------------------------------------ it names what is missing --
def test_a_baby_with_nothing_recorded_says_so_rather_than_looking_term(clinic):
    """The failure this list prevents. A sheet that silently omits the
    gestation reads as a term baby to whoever receives it."""
    from app.models import Patient

    with clinic["app"].app_context():
        bare = Patient(patient_number="T2", full_name="مولود", gender="female",
                       date_of_birth=date.today(), is_active=True)
        clinic["db"].session.add(bare)
        clinic["db"].session.commit()
        out = transfer.summary(bare)

    assert out["gestation"] is None
    assert set(out["missing"]) == set(transfer.WANTED)


def test_nothing_is_missing_when_everything_is_there(clinic, newborn):
    _bilirubin(clinic, newborn, 14.2)
    with clinic["app"].app_context():
        assert transfer.summary(newborn)["missing"] == []


def test_each_gap_is_named_on_its_own(clinic, newborn):
    _bilirubin(clinic, newborn, 14.2)
    with clinic["app"].app_context():
        newborn.birth_weight_kg = None
        clinic["db"].session.commit()
        out = transfer.summary(newborn)
    assert out["missing"] == ["birth_weight"]


def test_no_birth_time_is_a_named_gap_and_not_a_guess(clinic, newborn):
    """`age_hours` is deliberately `None` without an hour of birth. A summary
    that filled it from midnight would be up to twelve hours wrong on the one
    number the receiving unit reads first."""
    _bilirubin(clinic, newborn, 14.2)
    with clinic["app"].app_context():
        newborn.birth_time = None
        clinic["db"].session.commit()
        out = transfer.summary(newborn)
    assert out["age_hours"] is None
    assert "age_hours" in out["missing"]


# --------------------------------------------- and it decides nothing -------
def test_it_produces_no_threshold_and_no_verdict(clinic, newborn):
    """It gathers. Whether this baby needs phototherapy is
    `app/utils/jaundice.py`, which will not answer until a clinician has
    accepted its table — and whether they should be transferred is a person's
    decision, not a field."""
    import ast
    import inspect

    # Checked as imports and output, not as words. The first version of this
    # searched the module text for "threshold" and "jaundice" and failed on
    # the docstring, which mentions both to say it does neither — the test was
    # reading the explanation instead of the code.
    tree = ast.parse(inspect.getsource(transfer))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert not any("jaundice" in name for name in imported), imported

    _bilirubin(clinic, newborn, 22.0)
    with clinic["app"].app_context():
        out = transfer.summary(newborn)
    assert "points_at" not in out and "verdict" not in out
