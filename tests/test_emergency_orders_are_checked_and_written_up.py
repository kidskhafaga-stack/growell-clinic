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


# ------------------------------------------------- the skin test (owner) --
#
# «خد بالك من اختبار حساسية المضادات الحيوية» — the skin test before the
# injection: «given» waits for a result, never after a positive one, and a
# positive one goes on the child's allergies (``utils/skin_test``).

def _order(er, att, name, route):
    from app.models import EmergencyOrder

    er["sign_in"]("doc").post(f"/emergency/attendance/{att}/order",
                              data={"source": "ours", "name": name, "dose": "500 mg",
                                    "route": route})
    with er["app"].app_context():
        return EmergencyOrder.query.order_by(EmergencyOrder.id.desc()).first().id


def _give(er, order_id):
    return er["sign_in"]("nurse").post(f"/emergency/order/{order_id}/give",
                                       follow_redirects=True).get_data(as_text=True)


def _given(er, order_id):
    from app.models import EmergencyOrder

    with er["app"].app_context():
        return er["db"].session.get(EmergencyOrder, order_id).given_at is not None


def test_an_antibiotic_injection_waits_for_a_negative_skin_test(er):
    att = _attendance(er)
    oid = _order(er, att, "Ceftriaxone", "im")
    page = er["sign_in"]("nurse").get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-skin-test" in page
    assert f'data-order="{oid}"' in page
    page = _give(er, oid)
    assert not _given(er, oid) and "اختبار الجلد" in page
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/skin-test", data={"result": "negative"})
    _give(er, oid)
    assert _given(er, oid)


def test_a_positive_skin_test_stops_the_injection_and_is_an_allergy(er):
    from app.models import Patient

    att = _attendance(er)
    oid = _order(er, att, "Ceftriaxone", "iv")
    er["sign_in"]("nurse").post(f"/emergency/order/{oid}/skin-test", data={"result": "positive"})
    _give(er, oid)
    assert not _given(er, oid), "never after a positive one"
    with er["app"].app_context():
        allergies = er["db"].session.get(Patient, er["ids"]["child"]).allergies
        assert "Ceftriaxone" in allergies and "اختبار جلد" in allergies
    # The allergy check now knows it: the next cephalosporin is warned about.
    page = _write(er, att, "Cefotaxime")
    assert 'class="flash flash--danger"' in page


def test_no_skin_test_for_a_syrup_or_a_drug_that_is_not_an_antibiotic(er):
    att = _attendance(er)
    oral = _order(er, att, "Amoxicillin", "oral")
    other = _order(er, att, "Paracetamol", "iv")
    _give(er, oral)
    _give(er, other)
    assert _given(er, oral) and _given(er, other)


def test_a_hospital_that_does_not_skin_test_switches_it_off(er):
    from app.models import Setting

    with er["app"].app_context():
        Setting.set("er_skin_test", "0")
        er["db"].session.commit()
    att = _attendance(er)
    oid = _order(er, att, "Ceftriaxone", "im")
    _give(er, oid)
    assert _given(er, oid)


# ---------------------------------------------------- ط-٣ weight and dose --
#
# The dose box was free text. Now the order form asks the clinic's own dosing
# rules (``rx_safety.check`` → ``dosing.calculate``) for this child as soon
# as the drug is named, with the weight it was worked from — a suggestion the
# doctor presses to use. And the child can be weighed from the attendance.

def _paracetamol(er):
    from app.models.drugbook import GenericDrug

    with er["app"].app_context():
        er["db"].session.add(GenericDrug(name_ar="باراسيتامول", name_en="Paracetamol",
                                         dose_per_kg=15, doses_per_day=4))
        er["db"].session.commit()


def test_weigh_the_child_then_the_dose_follows_the_weight(er):
    _paracetamol(er)
    att = _attendance(er)
    nurse = er["sign_in"]("nurse")
    page = nurse.get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-er-weight" in page and "مفيش وزن" in page
    nurse.post(f"/emergency/attendance/{att}/weight", data={"weight_kg": "12"})
    page = nurse.get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "12.0" in page or "12 " in page
    d = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/dose?name=Paracetamol").get_json()
    assert d["weight"] == 12 and d["dose_mg"] == 180, "15 mg/kg × 12 kg, by the clinic's own rule"
    assert d["allergy"] is None


def test_the_dose_box_also_says_the_allergy(er):
    att = _attendance(er, allergies="Amoxicillin")
    d = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/dose?name=Amoxicillin").get_json()
    assert d["allergy"] and "Amoxicillin" in d["allergy"]


def test_a_weight_that_is_not_a_child_s_is_refused(er):
    from app.models import GrowthRecord

    att = _attendance(er)
    er["sign_in"]("nurse").post(f"/emergency/attendance/{att}/weight", data={"weight_kg": "1200"})
    with er["app"].app_context():
        assert GrowthRecord.query.filter_by(source="emergency").count() == 0
