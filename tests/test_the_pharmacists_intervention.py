"""The clinical pharmacist's intervention — the form's boxes, so it counts.

``HOSPITAL_PLAN.md`` مرحلة ج ٧، ص-١. The owner sent a hospital's «Clinical
Pharmacy Intervention Form» and asked whether it helps; the question and the
answer on an order were free text, and nothing about them could be counted.

What is held here:

* the pharmacist fills the form's boxes — the problem and its sub-kind, the
  urgency, the expected outcome, a comment on each — on one of this child's
  orders, on a dose recorded as not given, or on neither;
* a sub-kind the form has is required, a box missing is refused, and an
  order of another child is refused;
* it reaches the doctor **on the stay screen**, and the doctor — holding the
  right to write drug orders — accepts, accepts with a change, or rejects;
  a change or a rejection needs its words;
* it never stops a drug;
* the report counts them, with acceptance out of those answered;
* each prints on A4 with the boxes ticked;
* none of it exists without the wards.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from test_the_chart_nobody_read import _admit, _child, _order, ward  # noqa: E402,F401


def _form(**extra):
    base = {"problem": "dosage", "detail": "dose", "severity": "high",
            "outcome": "adr_prevented", "problem_note": "٥٠ مجم/كجم أكتر من الحد"}
    base.update(extra)
    return base


@pytest.fixture()
def stay(ward):
    kid = _child(ward, "سلمى")
    adm = _admit(ward, kid)
    ward["stay"] = adm
    ward["order"] = _order(ward, adm)
    return ward


def _rows(c):
    from app.models import PharmacyIntervention

    with c["app"].app_context():
        return [(r.number, r.problem, r.detail, r.severity, r.outcome,
                 r.order_id, r.response)
                for r in PharmacyIntervention.query.order_by(
                    PharmacyIntervention.id)]


def test_the_pharmacist_fills_the_forms_boxes(stay):
    page = stay["sign_in"]("chem").get(f"/pharmacy/ward/{stay['stay']}")
    html = page.get_data(as_text=True)
    assert "data-intervention-form" in html
    for box in ('value="dosage"', 'value="frequency"', 'value="drug_food"',
                'value="untreated_condition"', 'value="high"',
                'value="cost_saving"', 'name="with_consultant"'):
        assert box in html, box
    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=stay["order"]))
    assert _rows(stay) == [("PI-000001", "dosage", "dose", "high",
                            "adr_prevented", stay["order"], "pending")]


def test_a_missing_box_is_refused(stay):
    client = stay["sign_in"]("chem")
    url = f"/pharmacy/ward/{stay['stay']}/intervention"
    client.post(url, data=_form(detail="", order_id=stay["order"]))
    client.post(url, data=_form(severity="", order_id=stay["order"]))
    client.post(url, data=_form(outcome="sometimes", order_id=stay["order"]))
    # A problem with nothing to point at must say what it is about.
    client.post(url, data=_form(problem="untreated_condition", detail="",
                                problem_note=""))
    assert _rows(stay) == []


def test_another_childs_order_is_refused(stay):
    other = _admit(stay, _child(stay, "آدم"), bed=1)
    theirs = _order(stay, other, drug="سيفترياكسون")
    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=theirs))
    assert _rows(stay) == []


def test_a_condition_with_no_order_and_a_dose_not_given(stay):
    from app.extensions import db
    from app.models import PharmacyIntervention
    from app.models.medication import HELD, MedicationOrder
    from app.utils import drug_round

    client = stay["sign_in"]("chem")
    url = f"/pharmacy/ward/{stay['stay']}/intervention"
    client.post(url, data=_form(problem="untreated_condition", detail="",
                                problem_note="حرارة ٣٩ من غير خافض حرارة",
                                order_id=stay["order"]))
    with stay["app"].app_context():
        order = db.session.get(MedicationOrder, stay["order"])
        dose = drug_round.give(order, outcome=HELD, reason="نايم",
                               at=datetime.utcnow() - timedelta(hours=1))
        db.session.commit()
        dose_id = dose.id
    client.post(url, data=_form(problem="not_administered", detail="",
                                dose_id=dose_id))
    with stay["app"].app_context():
        first, second = PharmacyIntervention.query.order_by(
            PharmacyIntervention.id).all()
        # «No drug ordered for it» is about no order, whatever was posted.
        assert (first.problem, first.order_id) == ("untreated_condition", None)
        assert (second.dose_id, second.order_id) == (dose_id, stay["order"])


def test_the_doctor_answers_on_the_stay_screen(stay):
    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=stay["order"]))
    from app.models import PharmacyIntervention

    with stay["app"].app_context():
        row_id = PharmacyIntervention.query.one().id
    doctor = stay["sign_in"]("doc")
    page = doctor.get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert 'data-open-intervention="PI-000001"' in page
    # A change with no words is refused — the pharmacist needs them.
    doctor.post(f"/beds/intervention/{row_id}/respond",
                data={"response": "modified", "note": ""})
    assert _rows(stay)[0][-1] == "pending"
    doctor.post(f"/beds/intervention/{row_id}/respond",
                data={"response": "modified", "note": "خليتها ٣٠ مجم/كجم"})
    assert _rows(stay)[0][-1] == "modified"
    page = doctor.get(f"/beds/admission/{stay['stay']}").get_data(as_text=True)
    assert 'data-open-intervention="PI-000001"' not in page


def test_only_a_prescriber_answers(stay):
    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=stay["order"]))
    from app.models import PharmacyIntervention

    with stay["app"].app_context():
        row_id = PharmacyIntervention.query.one().id
    resp = stay["sign_in"]("desk").post(
        f"/beds/intervention/{row_id}/respond", data={"response": "accepted"})
    assert resp.status_code in (302, 403, 404)
    assert _rows(stay)[0][-1] == "pending"


def test_it_never_stops_the_drug(stay):
    from app.extensions import db
    from app.models.medication import MedicationOrder

    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=stay["order"]))
    with stay["app"].app_context():
        order = db.session.get(MedicationOrder, stay["order"])
        assert order.is_running


def test_the_report_counts_and_acceptance_is_of_the_answered(stay):
    from app.extensions import db
    from app.models import PharmacyIntervention
    from app.utils import pharmacy_interventions as cpi
    from app.utils.clock import local_today

    client = stay["sign_in"]("chem")
    url = f"/pharmacy/ward/{stay['stay']}/intervention"
    client.post(url, data=_form(order_id=stay["order"]))
    client.post(url, data=_form(problem="interaction", detail="drug_food",
                                severity="moderate", outcome="enhance_effect",
                                order_id=stay["order"]))
    client.post(url, data=_form(problem="wrong_drug", detail="",
                                severity="minor", outcome="cost_saving",
                                order_id=stay["order"]))
    with stay["app"].app_context():
        a, b, _c = PharmacyIntervention.query.order_by(
            PharmacyIntervention.id).all()
        cpi.respond(a, "accepted")
        cpi.respond(b, "rejected", note="مش مهم هنا")
        db.session.commit()
        got = cpi.summary(local_today(), local_today())
    assert got["total"] == 3
    assert got["by_problem"]["dosage"] == 1
    assert got["by_problem"]["interaction"] == 1
    assert got["by_detail"] == {"dosage.dose": 1, "interaction.drug_food": 1}
    assert got["by_severity"] == {"high": 1, "moderate": 1, "minor": 1}
    # One accepted of two answered — the third is waiting, not refused.
    assert (got["answered"], got["accepted_share"]) == (2, 50.0)
    assert got["by_unit"] == {"الداخلي": 3}
    page = client.get("/pharmacy/interventions").get_data(as_text=True)
    assert 'data-cpi-total>3<' in page and "50.0%" in page
    assert "/pharmacy/interventions" in client.get("/pharmacy/ward").get_data(
        as_text=True)


def test_it_prints_on_a4_with_the_boxes_ticked(stay):
    from app.models import PharmacyIntervention

    stay["sign_in"]("chem").post(
        f"/pharmacy/ward/{stay['stay']}/intervention",
        data=_form(order_id=stay["order"]))
    with stay["app"].app_context():
        row_id = PharmacyIntervention.query.one().id
    html = stay["sign_in"]("chem").get(
        f"/pharmacy/interventions/{row_id}/print").get_data(as_text=True)
    assert 'data-cpi-print="PI-000001"' in html
    assert "استمارة تدخّل الصيدلي الإكلينيكي" in html
    assert "سلمى" in html and "٥٠ مجم/كجم" in html
    # Four ticks: the problem, its sub-kind, the urgency, the outcome.
    assert html.count("✓") == 4


def test_no_wards_no_form(clinic):
    """A clinic with no beds has no drug charts, and no intervention screen."""
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        clinic["db"].session.commit()
    assert clinic["sign_in"]("boss").get(
        "/pharmacy/interventions").status_code == 404
