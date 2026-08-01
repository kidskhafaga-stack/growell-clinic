"""A device that arrives priced and unusable is not a feature.

The program seeded a catalogue of devices, and a billable service for each — and
no measurement fields at all. So a clinic got an echo machine in its settings,
with a price, and opening a study said *"this device has no measurement
template, define its fields first"*. Nobody is going to guess that the missing
piece is a form elsewhere in settings.

**The ranges are the interesting part of this file.** A normal range here
decides whether a printed report tells a parent their child's result is
abnormal. Most of these numbers move with age in children — a heart rate of 140
is unremarkable at two months and alarming at twelve years — so one adult range
would flag healthy infants on a document that goes home.

So ranges are filled in only where they genuinely do not depend on age (the
FEV1/FVC ratio, QTc, ejection fraction, hearing thresholds), and left blank
everywhere else. A blank range prints no verdict, which is the honest output
when the program does not know what to expect for this child. Several tests
below exist to keep it that way.

The second half is the patient file: a study recorded in a visit was visible
only in that visit, so anyone opening the file six months later had to remember
which visit it happened in. That is a search, not recall — and the file is meant
to be the answer to "what was done for this child".
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def kit(clinic):
    """A clinic with an echo machine and an ECG, neither with any fields."""
    from app.models import MedicalDevice

    with clinic["app"].app_context():
        echo = MedicalDevice(name="جهاز إيكو", name_en="Echo",
                             device_type="echo", is_active=True)
        ecg = MedicalDevice(name="جهاز رسم قلب", name_en="ECG",
                            device_type="ecg", is_active=True)
        clinic["db"].session.add_all([echo, ecg])
        clinic["db"].session.commit()
        clinic["echo"] = echo.id
        clinic["ecg"] = ecg.id
    return clinic


def _fields(kit, device_id):
    from app.models import MedicalDevice

    dev = kit["db"].session.get(MedicalDevice, device_id)
    return sorted(dev.measurements, key=lambda m: m.sort_order)


# ------------------------------------------------------- the seeding -------
def test_a_seeded_device_can_actually_be_used(kit):
    """The reported failure, stated as the rule it broke."""
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        assert seed_device_measurements() > 0
        assert _fields(kit, kit["echo"]), "the echo still has no fields"


def test_each_device_gets_its_own_kind_of_fields(kit):
    """An echo does not measure FEV1."""
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        seed_device_measurements()
        echo = {m.name_en for m in _fields(kit, kit["echo"])}
        ecg = {m.name_en for m in _fields(kit, kit["ecg"])}
        assert "Ejection fraction (EF)" in echo
        assert "QTc" in ecg
        assert not echo & ecg


def test_the_fields_keep_their_order(kit):
    """A report whose fields come out shuffled is harder to read than one with
    fewer fields."""
    from app.utils.device_templates import measurements_for, seed_device_measurements

    with kit["app"].app_context():
        seed_device_measurements()
        got = [m.name for m in _fields(kit, kit["ecg"])]
        assert got == [row[0] for row in measurements_for("ecg")]


def test_a_device_that_already_has_fields_is_left_completely_alone(kit):
    """Including one somebody stripped down to a single field on purpose — a
    "top up what is missing" rule would quietly undo that every time it ran."""
    from app.models import DeviceMeasurement
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        kit["db"].session.add(DeviceMeasurement(
            device_id=kit["echo"], name="حاجة واحدة بس", sort_order=0))
        kit["db"].session.commit()
        seed_device_measurements()
        assert [m.name for m in _fields(kit, kit["echo"])] == ["حاجة واحدة بس"]


def test_running_it_twice_changes_nothing(kit):
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        seed_device_measurements()
        before = len(_fields(kit, kit["echo"]))
        assert seed_device_measurements() == 0
        assert len(_fields(kit, kit["echo"])) == before


def test_an_unclassified_device_gets_nothing_rather_than_a_guess(kit):
    """`other` is a device the catalogue could not name. Inventing fields for
    it would be worse than the empty form the clinic has to fill in anyway."""
    from app.models import MedicalDevice
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        odd = MedicalDevice(name="جهاز غريب", device_type="other",
                            is_active=True)
        kit["db"].session.add(odd)
        kit["db"].session.commit()
        seed_device_measurements()
        assert _fields(kit, odd.id) == []


def test_every_seeded_device_type_has_fields():
    """The catalogue and the templates have to agree, or the clinic gets back
    the exact bug this fixes for one device type."""
    from app.utils.device_templates import measurements_for
    from app.utils.reference import DEFAULT_DEVICES

    missing = [row[4] for row in DEFAULT_DEVICES if not measurements_for(row[4])]
    assert not missing, f"seeded device types with no template: {missing}"


# ----------------------------------------- ranges: blank beats wrong -------
def test_a_childs_heart_rate_has_no_normal_range():
    """The one that matters most. Normal paediatric heart rate runs from about
    160 in a newborn to 60 in a teenager; a single range would print "high" on
    a healthy infant's report."""
    from app.utils.device_templates import measurements_for

    rate = next(m for m in measurements_for("ecg") if m[1] == "Heart rate")
    assert rate[3] is None and rate[4] is None


def test_volumes_that_scale_with_the_child_have_no_range():
    """FEV1, FVC and chamber sizes all depend on age and height."""
    from app.utils.device_templates import measurements_for

    by_name = {m[1]: m for m in measurements_for("spirometry")}
    by_name.update({m[1]: m for m in measurements_for("echo")})
    for field in ("FEV1", "FVC", "LVEDD", "LVESD"):
        assert by_name[field][3] is None and by_name[field][4] is None, field


def test_the_ratios_and_thresholds_that_do_hold_are_filled_in():
    """Blank everywhere would be its own failure — the ranges that are true at
    any age are worth having, and they are the ones a clinic would not want to
    look up."""
    from app.utils.device_templates import measurements_for

    ratio = next(m for m in measurements_for("spirometry") if m[1] == "FEV1/FVC")
    assert ratio[3] == 80

    ef = next(m for m in measurements_for("echo")
              if m[1] == "Ejection fraction (EF)")
    assert (ef[3], ef[4]) == (55, 70)

    pta = next(m for m in measurements_for("audiometry") if m[1] == "PTA — right")
    assert pta[4] == 20


def test_a_range_never_has_its_ends_the_wrong_way_round():
    """A low above its high flags every value as both, which reads as the
    program being broken rather than the result being odd."""
    from app.utils.device_templates import DEFAULT_MEASUREMENTS

    for kind, fields in DEFAULT_MEASUREMENTS.items():
        for name, _en, _unit, low, high in fields:
            if low is not None and high is not None:
                assert low < high, f"{kind}/{name}"


def test_a_free_text_field_carries_no_unit_and_no_range():
    """"Impression" measured in millimetres would be nonsense on a report."""
    from app.utils.device_templates import DEFAULT_MEASUREMENTS

    for kind, fields in DEFAULT_MEASUREMENTS.items():
        for name, en, unit, low, high in fields:
            if (en or "").lower() in ("impression", "findings", "rhythm",
                                      "valves", "notes"):
                assert (unit, low, high) == (None, None, None), f"{kind}/{name}"


def test_the_range_is_only_used_when_the_program_has_one(kit):
    """End of the argument: a field with no range must return no verdict, not
    "normal". Otherwise a blank range would silently bless every value."""
    from app.models import DeviceMeasurement
    from app.utils.device_templates import seed_device_measurements

    with kit["app"].app_context():
        seed_device_measurements()
        rate = next(m for m in _fields(kit, kit["ecg"])
                    if m.name_en == "Heart rate")
        assert rate.flag(140) == ""
        assert rate.normal_range == ""
        _ = DeviceMeasurement


# --------------------------------------------- a device added by hand -----
def test_a_device_the_clinic_adds_arrives_usable(kit):
    """The seeding runs on ``upgrade-db``; a device added next month has to get
    the same treatment or the bug comes back one device at a time."""
    from app.models import MedicalDevice

    boss = kit["sign_in"]("boss")
    boss.post("/settings/devices", data={
        "name": "جهاز سمعيات", "device_type": "audiometry"},
        follow_redirects=True)
    with kit["app"].app_context():
        made = MedicalDevice.query.filter_by(name="جهاز سمعيات").first()
        assert made is not None and made.measurements


def test_editing_a_device_does_not_resurrect_deleted_fields(kit):
    """Save on the edit form runs the same seeding, so it has to stay an
    empty-only fill."""
    from app.models import DeviceMeasurement, MedicalDevice

    with kit["app"].app_context():
        kit["db"].session.add(DeviceMeasurement(
            device_id=kit["echo"], name="الوحيد", sort_order=0))
        kit["db"].session.commit()

    boss = kit["sign_in"]("boss")
    boss.post("/settings/devices", data={
        "action": "edit", "id": str(kit["echo"]),
        "name": "جهاز إيكو", "device_type": "echo", "is_active": "1"},
        follow_redirects=True)
    with kit["app"].app_context():
        dev = kit["db"].session.get(MedicalDevice, kit["echo"])
        assert [m.name for m in dev.measurements] == ["الوحيد"]


# ------------------------------------------ the studies in the file -------
def _study(kit, when=None, conclusion="وظيفة القلب سليمة"):
    from app.models import DeviceStudy

    with kit["app"].app_context():
        study = DeviceStudy(
            patient_id=kit["ids"]["child"], device_id=kit["echo"],
            visit_id=kit["ids"]["visit"], study_date=when or date.today(),
            performed_by=kit["ids"]["doctor"], conclusion=conclusion)
        kit["db"].session.add(study)
        kit["db"].session.commit()
        return study.id


def test_a_study_shows_in_the_patient_file(kit):
    """The reported gap: it was recorded in a visit and visible only there."""
    _study(kit)
    doc = kit["sign_in"]("doc")
    body = doc.get(f"/patients/{kit['ids']['child']}").get_data(as_text=True)
    assert "وظيفة القلب سليمة" in body
    assert "جهاز إيكو" in body


def test_the_file_links_to_the_study_itself(kit):
    """A row that only shows a conclusion is a teaser. The point is reaching
    the measurements without hunting for the visit."""
    study_id = _study(kit)
    doc = kit["sign_in"]("doc")
    body = doc.get(f"/patients/{kit['ids']['child']}").get_data(as_text=True)
    assert f"/visits/studies/{study_id}" in body


def test_the_newest_study_comes_first(kit):
    """Reading a file starts with what happened most recently."""
    _study(kit, when=date(2025, 1, 1), conclusion="القديمة")
    _study(kit, when=date(2026, 1, 1), conclusion="الجديدة")
    doc = kit["sign_in"]("doc")
    body = doc.get(f"/patients/{kit['ids']['child']}").get_data(as_text=True)
    assert body.index("الجديدة") < body.index("القديمة")


def test_a_child_with_no_studies_is_told_so(kit):
    """An empty section that says nothing reads as a broken section."""
    doc = kit["sign_in"]("doc")
    body = doc.get(f"/patients/{kit['ids']['child']}").get_data(as_text=True)
    assert "مافيش دراسات متسجّلة" in body


def test_one_childs_studies_do_not_appear_in_anothers_file(kit):
    from app.models import Patient

    _study(kit, conclusion="بتاعة الأول")
    with kit["app"].app_context():
        other = Patient(patient_number="P77", full_name="طفل تاني",
                        gender="female", date_of_birth=date(2024, 5, 1),
                        is_active=True)
        kit["db"].session.add(other)
        kit["db"].session.commit()
        other_id = other.id

    doc = kit["sign_in"]("doc")
    body = doc.get(f"/patients/{other_id}").get_data(as_text=True)
    assert "بتاعة الأول" not in body
