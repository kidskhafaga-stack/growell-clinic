"""Fluid balance on the ward (DOCTOR_EASE ٤-ب د-٥).

Nothing in the program wrote what went in and what came out. Now the nurse
writes amounts in millilitres; the stay shows the last 24 hours (in, out, the
difference, urine per kilo per hour from the latest weight), day by day, and
the entries — a wrong one struck through, never deleted. No limits from the
program: the reading of the numbers is the doctor's.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_chart_nobody_read import _admit, _child, ward  # noqa: E402,F401


def _write(ward, stay, kind, ml, at=None):
    data = {"kind": kind, "ml": str(ml)}
    if at:
        data["at"] = at
    return ward["sign_in"]("boss").post(f"/beds/stay/{stay}/fluid", data=data,
                                        follow_redirects=True).get_data(as_text=True)


def test_in_and_out_add_up_with_the_difference(ward):
    stay = _admit(ward, _child(ward, "يوسف"))
    _write(ward, stay, "iv", 500)
    _write(ward, stay, "oral", 120)
    page = _write(ward, stay, "urine", 300)
    assert "data-fluid" in page
    assert 'data-fluid-in>620<' in page and 'data-fluid-out>300<' in page
    assert 'data-fluid-net>+320<' in page


def test_urine_per_kilo_per_hour_from_the_latest_weight(ward):
    from app.models import FluidEntry, GrowthRecord
    from app.utils.clock import local_today

    pid = _child(ward, "يوسف")
    stay = _admit(ward, pid)       # admitted a day ago
    with ward["app"].app_context():
        ward["db"].session.add(GrowthRecord(patient_id=pid, record_date=local_today(),
                                            weight_kg=10, source="ward"))
        ward["db"].session.add(FluidEntry(admission_id=stay, patient_id=pid, direction="out",
                                          kind="urine", ml=480,
                                          at=datetime.utcnow() - timedelta(hours=2)))
        ward["db"].session.commit()
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    rate = page.split("data-urine-rate", 1)[1][:120]
    assert "2.0" in rate, "480 mL / 10 kg / 24 h"


def test_a_wrong_amount_is_struck_not_deleted(ward):
    from app.models import FluidEntry

    stay = _admit(ward, _child(ward, "يوسف"))
    _write(ward, stay, "iv", 900)
    with ward["app"].app_context():
        eid = FluidEntry.query.one().id
    page = ward["sign_in"]("boss").post(f"/beds/fluid/{eid}/strike",
                                        follow_redirects=True).get_data(as_text=True)
    assert "data-struck" in page and 'data-fluid-in>0<' in page
    with ward["app"].app_context():
        assert FluidEntry.query.count() == 1


def test_amounts_and_kinds_are_checked(ward):
    from app.models import FluidEntry

    stay = _admit(ward, _child(ward, "يوسف"))
    _write(ward, stay, "iv", 0)
    _write(ward, stay, "iv", 99999)
    _write(ward, stay, "coffee", 100)
    with ward["app"].app_context():
        assert FluidEntry.query.count() == 0


def test_the_hour_the_nurse_writes_is_kept(ward):
    from app.models import FluidEntry
    from app.utils.clock import local_now, to_utc

    stay = _admit(ward, _child(ward, "يوسف"))
    two_hours_ago = (local_now() - timedelta(hours=2)).replace(second=0, microsecond=0)
    _write(ward, stay, "urine", 50, at=two_hours_ago.strftime("%Y-%m-%dT%H:%M"))
    with ward["app"].app_context():
        row = FluidEntry.query.one()
        assert abs((row.at - to_utc(two_hours_ago.replace(tzinfo=None))).total_seconds()) < 61
