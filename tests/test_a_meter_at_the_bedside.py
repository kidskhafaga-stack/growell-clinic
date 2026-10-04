"""Point-of-care testing — GAHAR DAS.24.

Step seven of the laboratory plan:

* the laboratory names who supervises point-of-care testing;
* every device is listed with where it is and what it measures;
* each device has its trained operators, competent until a date; a reading
  charted by somebody not on the list is kept, and said;
* the bedside reading goes on the ward's own observation chart, with the
  meter it was read on — and a hospital that keeps no devices sees the
  chart exactly as before;
* each device's controls are recorded; a failed one without an action, or
  one overdue against the laboratory's own frequency, is said in red.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401


def _device(c, **extra):
    from app.models import PoctDevice

    data = {"name": "جلوكوميتر ١", "location": "الحضانة", "tests": "سكر الدم", **extra}
    c["sign_in"]("boss").post("/labs/poct/devices", data=data)
    with c["app"].app_context():
        row = PoctDevice.query.order_by(PoctDevice.id.desc()).first()
        return row.id if row else None


def test_the_supervisor_and_the_sites_are_listed(lab):
    from app.utils import lab_poct

    boss = lab["sign_in"]("boss")
    assert "data-no-devices" in boss.get("/labs/poct").get_data(as_text=True)
    boss.post("/labs/poct/supervisor", data={"user_id": lab["ids"]["doctor"]})
    did = _device(lab)
    with lab["app"].app_context():
        assert lab_poct.supervisor().id == lab["ids"]["doctor"]
    page = boss.get("/labs/poct").get_data(as_text=True)
    assert f'data-device="{did}"' in page and "الحضانة" in page
    # Only an admin or the supervisor sets devices up.
    lab["sign_in"]("desk").post("/labs/poct/devices", data={"name": "جهاز غازات"})
    with lab["app"].app_context():
        from app.models import PoctDevice
        assert PoctDevice.query.count() == 1


def test_a_reading_on_the_ward_chart_says_its_meter_and_who_is_trained(lab):
    from app.models import Observation, Setting

    with lab["app"].app_context():
        Setting.set("mod_enabled:observations", "1")
        lab["db"].session.commit()
    chart = f"/observations/patient/{lab['ids']['child']}"
    boss = lab["sign_in"]("boss")
    assert "data-poct-device" not in boss.get(chart).get_data(as_text=True), \
        "no devices kept, the chart is as it was"
    did = _device(lab)
    assert "data-poct-device" in boss.get(chart).get_data(as_text=True)
    answer = boss.post(chart + "/record", data={"glucose_mgdl": "88", "poct_device_id": str(did)},
                       follow_redirects=True).get_data(as_text=True)
    assert "جلوكوميتر ١" in answer, "not on the trained list — said"
    boss.post(f"/labs/poct/device/{did}/operators", data={
        "user_id": lab["ids"]["admin"], "trained_on": date.today().isoformat(),
        "competent_until": (date.today() + timedelta(days=365)).isoformat()})
    with lab["app"].app_context():
        row = Observation.query.one()
        assert (row.glucose_mgdl, row.poct_device_id) == (88, did)
    page = boss.get(f"/labs/poct/device/{did}").get_data(as_text=True)
    assert f'data-poct-reading="{row.id}"' in page and f'data-operator="{lab["ids"]["admin"]}"' in page


def test_controls_failed_or_overdue_are_said(lab):
    from app.models import PoctDevice, PoctQc
    from app.utils import lab_poct

    did = _device(lab, qc_every_days="1")
    boss = lab["sign_in"]("boss")
    with lab["app"].app_context():
        assert lab_poct.qc_state(lab["db"].session.get(PoctDevice, did)) == "overdue"
    boss.post(f"/labs/poct/device/{did}/qc", data={"level": "عالي", "result": "310", "passed": "0"})
    assert "data-poct-attention" in boss.get("/labs/").get_data(as_text=True)
    with lab["app"].app_context():
        check_id = PoctQc.query.one().id
        assert lab_poct.qc_state(lab["db"].session.get(PoctDevice, did)) == "failed"
    boss.post(f"/labs/poct/qc/{check_id}/action", data={"action": "شرائط جديدة وإعادة الكنترول"})
    boss.post(f"/labs/poct/device/{did}/qc", data={"level": "عالي", "result": "298", "passed": "1"})
    with lab["app"].app_context():
        assert lab_poct.qc_state(lab["db"].session.get(PoctDevice, did)) == "ok"
        for n, check in enumerate(PoctQc.query.order_by(PoctQc.id).all()):
            check.run_at = datetime.utcnow() - timedelta(days=4 - n)
        lab["db"].session.commit()
        assert lab_poct.qc_state(lab["db"].session.get(PoctDevice, did)) == "overdue"
