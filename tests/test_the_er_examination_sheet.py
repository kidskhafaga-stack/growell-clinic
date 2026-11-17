"""«Child Examination (ER)» — the department's record of an attendance.

The owner brought the paper form an emergency department fills by hand —
«بص ده ممكن يفيدنا فى الطوارئ». Everything on it was already written
somewhere in the program; what was missing was the page itself, two of its
boxes («Admitted: PICU · NICU · INP · Surgical intervention», and the
discharge order by the treating doctor), and the height.

These hold it:

* the sheet has a door, prints in the paper's order, and in English too;
* what the file has is printed, what it has not is lines for a pen — and the
  weight is the one taken *during this attendance*, never last month's;
* every drug order carries when it was written and by whom, and when it was
  given and by whom («each order must be dated, timed and signed»);
* «admitted» says where, and only when the child was admitted;
* the discharge order is the treating doctor's: the doctor who presses it,
  or the doctor the nurse names — never the nurse, never a guess.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_emergency_treatment_on_the_bill import er  # noqa: E402,F401


def _attendance(er, given=True):
    from app.models import Patient, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with er["app"].app_context():
        db = er["db"]
        row = util.arrive(db.session.get(Patient, er["ids"]["child"]))
        db.session.flush()
        order = eo.write(row, db.session.get(User, er["ids"]["doctor"]),
                         name="Salbutamol", dose="2.5 mg", route="nebulised")
        if given:
            eo.give(order, db.session.get(User, er["ids"]["nurse"]))
        db.session.commit()
        return row.id


def _sheet(er, att, who="doc", lang=None):
    url = f"/emergency/attendance/{att}/sheet" + (f"?lang={lang}" if lang else "")
    return er["sign_in"](who).get(url).get_data(as_text=True)


def _part(page, mark):
    return page.split(mark, 1)[1].split("</div>\n", 1)[0]


def test_the_sheet_has_a_door_and_the_paper_s_sections(er):
    att = _attendance(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}") \
        .get_data(as_text=True)
    assert "data-to-exam-sheet" in page
    page = _sheet(er, att)
    assert "data-exam-sheet" in page
    for mark in ("data-sheet-history", "data-sheet-exam", "data-sheet-dx",
                 "data-sheet-tests", "data-sheet-orders",
                 "data-sheet-disposition", "data-sheet-discharge-order",
                 "data-sheet-condition", "data-sheet-followup"):
        assert mark in page, mark
    # Nothing written yet: the examination is lines for a pen, not words.
    assert "ers-line" in _part(page, "data-sheet-exam")
    english = _sheet(er, att, lang="en")
    assert "Child Examination (ER)" in english
    assert "Discharge order by the treating doctor" in english


def test_each_order_is_dated_timed_and_signed(er):
    from app.models import EmergencyOrder, User

    att = _attendance(er)
    with er["app"].app_context():
        db = er["db"]
        from app.utils import emergency_orders as eo
        from app.models import EmergencyVisit
        row = db.session.get(EmergencyVisit, att)
        gone = eo.write(row, db.session.get(User, er["ids"]["doctor"]),
                        name="Ceftriaxone")
        gone.cancelled_at = datetime.utcnow()
        db.session.commit()
        doctor = db.session.get(User, er["ids"]["doctor"]).display_name("ar")
        nurse = db.session.get(User, er["ids"]["nurse"]).display_name("ar")
        assert EmergencyOrder.query.count() == 2
    orders = _sheet(er, att).split("data-sheet-orders", 1)[1] \
        .split("</table>", 1)[0]
    assert "R/ Salbutamol" in orders and "2.5 mg" in orders
    assert doctor in orders and nurse in orders, "written by, given by"
    assert orders.count("data-sheet-order>") == 1
    assert "Ceftriaxone" not in orders, "a cancelled order was not ordered"


def test_the_weight_is_today_s_or_a_blank(er):
    from app.models import EmergencyVisit, GrowthRecord

    att = _attendance(er)
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        er["db"].session.add(GrowthRecord(
            patient_id=row.patient_id, record_date=date.today() - timedelta(days=40),
            weight_kg=11.0, height_cm=80.0))
        er["db"].session.commit()
    page = _sheet(er, att)
    assert "data-sheet-weight" not in page, "last month's weight is not today's"
    er["sign_in"]("doc").post(f"/emergency/attendance/{att}/weight",
                              data={"weight_kg": "12.4", "height_cm": "86"})
    measures = _sheet(er, att).split("data-sheet-measures", 1)[1] \
        .split("</div>\n  </div>", 1)[0]
    assert "12.4 kg" in measures and "86.0 cm" in measures


def test_a_nurse_names_the_doctor_and_where_the_child_went(er):
    from app.models import EmergencyVisit

    att = _attendance(er)
    page = er["sign_in"]("nurse").get(f"/emergency/attendance/{att}") \
        .get_data(as_text=True)
    assert "data-discharge-doctor" in page and "data-admitted-to" in page
    er["sign_in"]("nurse").post(f"/emergency/depart/{att}", data={
        "disposition": "admitted", "admitted_to": "picu",
        "discharge_doctor_id": str(er["ids"]["doctor"])})
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        assert (row.disposition, row.admitted_to, row.discharge_doctor_id,
                row.by_id) == ("admitted", "picu", er["ids"]["doctor"],
                               er["ids"]["nurse"])
    page = _sheet(er, att)
    assert 'data-sheet-admit="picu:on"' in page
    assert 'data-sheet-admit="nicu"' in page
    assert "data-sheet-discharge-doctor" in page


def test_a_nurse_is_not_the_treating_doctor(er):
    from app.models import EmergencyVisit

    att = _attendance(er)
    er["sign_in"]("nurse").post(f"/emergency/depart/{att}", data={
        "disposition": "home", "admitted_to": "picu",
        "discharge_doctor_id": str(er["ids"]["nurse"])})
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        assert row.disposition == "home"
        assert row.admitted_to is None, "where to only when admitted"
        assert row.discharge_doctor_id is None, "a nurse named is no doctor"
    assert "data-sheet-discharge-doctor" not in _sheet(er, att)


def test_the_doctor_who_closes_it_is_the_one_who_ordered_it(er):
    from app.models import EmergencyVisit

    att = _attendance(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}") \
        .get_data(as_text=True)
    assert "data-discharge-doctor" not in page, "a doctor is not asked who"
    er["sign_in"]("doc").post(f"/emergency/depart/{att}", data={
        "disposition": "self_discharge", "condition": "مستقر"})
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        assert row.discharge_doctor_id == er["ids"]["doctor"]


def test_what_the_file_says_reaches_the_sheet(er):
    from app.models import Diagnosis, EmergencyVisit, Patient, Visit
    from app.utils import emergency as util

    att = _attendance(er)
    doc = er["sign_in"]("doc")
    doc.post(f"/emergency/attendance/{att}/visit")
    with er["app"].app_context():
        db = er["db"]
        row = db.session.get(EmergencyVisit, att)
        visit = db.session.get(Visit, row.visit_id)
        visit.chief_complaint = "كحة وصفير من يومين"
        visit.clinical_exam = "Bilateral wheeze, no recession"
        db.session.add(Diagnosis(visit_id=visit.id, code="J45.9",
                                 title="Asthma", dx_type="working"))
        kid = db.session.get(Patient, row.patient_id)
        kid.allergies = "Penicillin"
        # An earlier attendance the family left against advice.
        before = util.arrive(kid, at=row.arrived_at - timedelta(days=30))
        db.session.flush()
        util.depart(before, "self_discharge",
                    at=row.arrived_at - timedelta(days=30, hours=-2))
        db.session.commit()
    page = _sheet(er, att)
    assert "كحة وصفير من يومين" in _part(page, "data-sheet-history")
    assert "Bilateral wheeze" in _part(page, "data-sheet-exam")
    assert "J45.9" in page.split("data-sheet-dx", 1)[1].split("</ul>", 1)[0]
    assert "Penicillin" in page.split("data-sheet-allergy", 1)[1][:40]
    assert "☑" in page.split("data-sheet-dama-before", 1)[1][:80]
