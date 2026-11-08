"""Emergency: the medicine checked, and a door to write the visit
(DOCTOR_EASE_PLAN.md ٤-أ — ط-١ and ط-٢).

* **ط-١** — the prescription screen and the ward's drug round pass every
  medicine through the clinic's own safety check (``rx_safety.check``: the
  allergies on the file, the interaction pairs, the dose ceilings). A drug
  written in emergency did not: a child with an amoxicillin allergy could be
  written amoxicillin without a word. Now the same check, the same words, said
  when the order is written and kept on the attendance while it stands —
  never a block, the doctor decides knowingly.
* **ط-٢** — the attendance said «still missing: the doctor's assessment, the
  diagnosis» and had no door to write them. «اكتب الكشف» opens the
  attendance's own encounter on the visit screen.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_emergency_treatment_on_the_bill import er  # noqa: E402,F401


def _attendance(er, allergies=None):
    from app.models import Patient
    from app.utils import emergency as util

    with er["app"].app_context():
        child = er["db"].session.get(Patient, er["ids"]["child"])
        child.allergies = allergies
        row = util.arrive(child)
        er["db"].session.commit()
        return row.id


def _write(er, att, name, user="doc"):
    return er["sign_in"](user).post(f"/emergency/attendance/{att}/order",
                                    data={"source": "ours", "name": name, "dose": "250 mg"},
                                    follow_redirects=True).get_data(as_text=True)


def test_an_allergy_on_the_file_is_said_when_the_drug_is_written(er):
    att = _attendance(er, allergies="Amoxicillin")
    page = _write(er, att, "Amoxicillin")
    assert 'class="flash flash--danger"' in page
    assert "Amoxicillin" in page.split('class="flash flash--danger"', 1)[1][:600]
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-er-safety" in page and "data-er-allergy" in page, \
        "kept on the attendance while the order stands"

    from app.models import EmergencyOrder

    with er["app"].app_context():
        assert EmergencyOrder.query.count() == 1, "a warning, never a block"


def test_a_child_with_no_allergy_gets_no_warning(er):
    att = _attendance(er, allergies=None)
    page = _write(er, att, "Amoxicillin")
    assert "data-er-safety" not in er["sign_in"]("doc").get(
        f"/emergency/attendance/{att}").get_data(as_text=True)
    assert 'class="flash flash--danger"' not in page


def test_a_cancelled_order_is_no_longer_warned_about(er):
    from app.models import EmergencyOrder
    from app.utils import emergency_orders as eo

    att = _attendance(er, allergies="Amoxicillin")
    _write(er, att, "Amoxicillin")
    with er["app"].app_context():
        from app.models import User
        order = EmergencyOrder.query.one()
        eo.cancel(order, er["db"].session.get(User, er["ids"]["doctor"]), reason="غلط")
        er["db"].session.commit()
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-er-safety" not in page


def test_write_the_visit_opens_the_attendance_s_own_encounter(er):
    from app.models import EmergencyVisit, Visit

    att = _attendance(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-write-visit" in page
    r = er["sign_in"]("doc").post(f"/emergency/attendance/{att}/visit")
    assert r.status_code == 302 and "/visits/" in r.headers["Location"]
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        visit = er["db"].session.get(Visit, row.visit_id)
        assert visit.channel == "emergency" and visit.doctor_id == er["ids"]["doctor"]
        assert row.seen_at is not None, "the doctor writing the visit has seen the child"
    # Pressed again, the same encounter — not a second one.
    er["sign_in"]("doc").post(f"/emergency/attendance/{att}/visit")
    with er["app"].app_context():
        assert Visit.query.filter_by(channel="emergency").count() == 1
