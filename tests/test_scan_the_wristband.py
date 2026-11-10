"""«Scan the wristband» (DOCTOR_EASE ٤-ب د-٨).

Asked by the owner: the band was printed and nothing read it. Now a scan
opens the child, and a scan with a dose, a blood bag or a sample refuses
another child's band. **The hospital chooses** how strict: optional (the
default — no scan is allowed), required, or off.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def _mode(ward, mode):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("band_scan", mode)
        ward["db"].session.commit()


def _number(ward, pid):
    from app.models import Patient

    with ward["app"].app_context():
        return ward["db"].session.get(Patient, pid).patient_number


def _order(ward, stay):
    from app.models import MedicationOrder

    ward["sign_in"]("boss").post(f"/beds/admission/{stay}/medication",
                                 data={"drug_name": "Paracetamol", "dose": "150 mg",
                                       "route": "oral", "every_hours": "6"})
    with ward["app"].app_context():
        return MedicationOrder.query.order_by(MedicationOrder.id.desc()).first().id


def _give(ward, oid, band=None):
    data = {"outcome": "given"}
    if band is not None:
        data["band"] = band
    return ward["sign_in"]("boss").post(f"/beds/medication/{oid}/dose", data=data,
                                        follow_redirects=True).get_data(as_text=True)


def _doses(ward, oid):
    from app.models import MedicationDose

    with ward["app"].app_context():
        return [(d.outcome, d.band_scanned) for d in MedicationDose.query.filter_by(order_id=oid)]


def test_a_scan_opens_the_child_s_stay(ward):
    pid = _child(ward, "يوسف")
    stay = _admit(ward, pid)
    page = ward["sign_in"]("boss").get("/ward/").get_data(as_text=True)
    assert "data-band-scan" in page, "the box on the ward board"
    r = ward["sign_in"]("boss").get(f"/beds/scan?code=*{_number(ward, pid)}*")
    assert r.status_code == 302 and f"/beds/admission/{stay}" in r.headers["Location"]
    r = ward["sign_in"]("boss").get("/beds/scan?code=NOPE", follow_redirects=True)
    assert "NOPE" in r.get_data(as_text=True)


def test_another_child_s_band_is_refused_and_the_right_one_is_recorded(ward):
    pid = _child(ward, "يوسف")
    other = _child(ward, "مريم")
    stay = _admit(ward, pid)
    oid = _order(ward, stay)
    page = _give(ward, oid, band=_number(ward, other))
    assert _doses(ward, oid) == [] and "مريم" in page
    _give(ward, oid, band=_number(ward, pid))
    assert _doses(ward, oid) == [("given", True)]


def test_optional_by_default_no_scan_is_allowed(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    oid = _order(ward, stay)
    _give(ward, oid)
    assert _doses(ward, oid) == [("given", None)]


def test_required_waits_for_the_scan_and_off_shows_no_box(ward):
    pid = _child(ward, "يوسف")
    stay = _admit(ward, pid)
    oid = _order(ward, stay)
    _mode(ward, "required")
    _give(ward, oid)
    assert _doses(ward, oid) == []
    _give(ward, oid, band=_number(ward, pid))
    assert _doses(ward, oid) == [("given", True)]
    _mode(ward, "off")
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'name="band"' not in page
    assert "data-band-scan" not in ward["sign_in"]("boss").get("/ward/").get_data(as_text=True)


def test_a_clinic_child_s_tube_is_never_asked_for_a_band(ward):
    """The clinic's behaviour does not change: an outpatient wears no band."""
    from app.utils import band_scan

    pid = _child(ward, "يوسف")
    _mode(ward, "required")
    with ward["app"].app_context():
        from app.models import Patient
        child = ward["db"].session.get(Patient, pid)
        assert band_scan.wears_a_band(child) is False
        assert band_scan.check(pid, "", banded=band_scan.wears_a_band(child)) is None
        _admit(ward, pid)
        assert band_scan.wears_a_band(child) is True
        assert band_scan.check(pid, "", banded=True)[0] == "band_needed"


def test_the_hospital_chooses_in_settings(ward):
    page = ward["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-band-scan-setting" in page


def test_a_blood_bag_goes_up_on_this_child_s_band_only(clinic):
    from tests.test_the_bag_nobody_watched import _admit as admit_one
    from tests.test_the_bag_nobody_watched import _bag_id, _hang, _order as order_blood
    from tests.test_the_bag_nobody_watched import _request_id, ward as bag_ward

    world = bag_ward.__wrapped__(clinic) if hasattr(bag_ward, "__wrapped__") else None
    assert world is not None
    stay = admit_one(world)
    order_blood(world, stay)
    rid = _request_id(world, stay)
    page = _hang(world, rid, unit_code="U1", band="BL-OTHER").get_data(as_text=True)
    assert _bag_id(world) is None and "طفل تاني" in page
    from app.models import Patient, Transfusion

    with world["app"].app_context():
        mine = world["db"].session.get(Patient, world["ids"]["child"]).patient_number
    _hang(world, rid, unit_code="U1", band=mine)
    with world["app"].app_context():
        assert Transfusion.query.one().band_scanned is True
