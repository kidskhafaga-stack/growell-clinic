"""What the cardiologist can actually record, and what was missing.

Asked while checking the specialty was covered end to end: *"وفى القلب فى رسم
قلب بالمجهود ورسم القلب المطول — احنا معانا الحاجات دي علشان نبقى غطينا تخصص
القلب كله؟"*

The answer was half, and the half that was "yes" turned out to be no.

* **The exercise ECG** was missing outright — not a device type, not a template.
* **The Holter** had a full field template written for it and **no Holter device
  was ever seeded**, so nothing in any clinic could ever use it. A template with
  nothing to attach to is a feature that exists in the source and in no clinic.

And the seeding list itself was written out twice — once in `app/utils/
reference.py` and again in `app/cli.py` — which is two lists the moment somebody
edits the file they happen to have open. A fresh install and an upgrade run
different seeders; they would have started handing out different catalogues.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

HEART = ["ecg", "stress_ecg", "holter", "echo"]


@pytest.mark.parametrize("kind", HEART)
def test_the_device_type_exists(clinic, kind):
    from app.models.device import DEVICE_TYPES

    assert kind in DEVICE_TYPES


@pytest.mark.parametrize("kind", HEART)
def test_it_knows_what_that_device_measures(clinic, kind):
    """A device with no template arrives configured, priced and unusable —
    the note at the top of device_templates.py is about exactly that."""
    from app.utils.device_templates import DEFAULT_MEASUREMENTS

    fields = DEFAULT_MEASUREMENTS.get(kind)
    assert fields, f"{kind} has no measurement template"
    assert len(fields) >= 4


@pytest.mark.parametrize("kind", HEART)
def test_a_clinic_actually_gets_one(clinic, kind):
    """The Holter's gap. Being in the type list and having a template is not
    the same as a clinic having the device — and nothing seeded one."""
    from app.utils.reference import DEFAULT_DEVICES

    assert any(row[4] == kind for row in DEFAULT_DEVICES), \
        f"no {kind} device is seeded, so its template can never be reached"


def test_the_seeded_list_is_written_once(clinic):
    """Two copies drift. The upgrade path and the fresh-install path would
    have handed out different catalogues the first time one was edited."""
    import inspect

    from app import cli

    source = inspect.getsource(cli)
    assert "_DEFAULT_DEVICES = [" not in source, \
        "app/cli.py carries its own copy of the device catalogue again"
    assert "from app.utils.reference import DEFAULT_DEVICES" in source


def test_both_paths_seed_the_same_devices(clinic):
    """Checked by running one of them, not by reading it."""
    from app.extensions import db
    from app.models import MedicalDevice
    from app.utils.reference import DEFAULT_DEVICES

    with clinic["app"].app_context():
        from app.cli import _seed_devices_safe

        _seed_devices_safe()
        db.session.commit()
        seeded = {d.device_type for d in MedicalDevice.query.all()}

    assert {row[4] for row in DEFAULT_DEVICES} <= seeded


def test_the_exercise_test_states_no_range_where_it_would_mislead(clinic):
    """The judgement worth pinning. 85% of predicted maximum is the usual
    threshold for an *adequate* test and is age-independent — so it looks like
    a range belongs there. It does not: falling short means the child did not
    push hard enough, not that the child is abnormal, and this column prints
    as "out of range" on a report a parent takes home."""
    from app.utils.device_templates import DEFAULT_MEASUREMENTS

    rows = {r[1]: r for r in DEFAULT_MEASUREMENTS["stress_ecg"]}
    predicted = rows["% of predicted max HR"]

    assert predicted[3] is None and predicted[4] is None, \
        "a percentage that means 'submaximal test' was given a range that " \
        "prints as 'abnormal'"


def test_the_heart_rate_columns_carry_no_paediatric_range(clinic):
    """The rule the rest of that file follows: a range only where it genuinely
    does not move with age. A peak heart rate does."""
    from app.utils.device_templates import DEFAULT_MEASUREMENTS

    for kind in ("stress_ecg", "holter"):
        for row in DEFAULT_MEASUREMENTS[kind]:
            if row[2] == "bpm":
                assert row[3] is None and row[4] is None, \
                    f"{kind}/{row[1]} carries an adult heart-rate range"
