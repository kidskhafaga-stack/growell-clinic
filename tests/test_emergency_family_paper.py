"""The emergency paper for the family (DOCTOR_EASE_PLAN ٤-أ ط-٦).

Departure recorded the condition and the follow-up, and the family left with
nothing in hand. Now a paper from the attendance: the diagnosis on its
encounter, what was given, the condition, the follow-up — and «come back at
once if…» in the hospital's own words. The program writes no clinical line of
its own: none written by the hospital, a blank space the doctor fills by hand.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_emergency_treatment_on_the_bill import er  # noqa: E402,F401


def _attendance_with_a_given_dose(er):
    from app.models import Patient, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with er["app"].app_context():
        db = er["db"]
        row = util.arrive(db.session.get(Patient, er["ids"]["child"]))
        db.session.flush()
        order = eo.write(row, db.session.get(User, er["ids"]["doctor"]),
                         name="Salbutamol", dose="2.5 mg", route="inhaled")
        eo.give(order, db.session.get(User, er["ids"]["nurse"]))
        eo.write(row, db.session.get(User, er["ids"]["doctor"]), name="Dexamethasone")
        db.session.commit()
        return row.id


def test_the_paper_has_a_door_and_says_what_was_given(er):
    att = _attendance_with_a_given_dose(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}").get_data(as_text=True)
    assert "data-to-family-paper" in page, "the door"
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/paper").get_data(as_text=True)
    assert "data-family-paper" in page
    given = page.split("data-paper-given", 1)[1].split("</section>", 1)[0]
    assert "Salbutamol" in given and "2.5 mg" in given
    assert "Dexamethasone" not in given, "written but not given — not on the paper"


def test_the_departure_and_the_encounter_reach_the_paper(er):
    from app.models import Diagnosis, EmergencyVisit, Visit

    att = _attendance_with_a_given_dose(er)
    doc = er["sign_in"]("doc")
    doc.post(f"/emergency/attendance/{att}/visit")
    with er["app"].app_context():
        row = er["db"].session.get(EmergencyVisit, att)
        visit = er["db"].session.get(Visit, row.visit_id)
        er["db"].session.add(Diagnosis(visit_id=visit.id, code="J45.9", title="Asthma",
                                       dx_type="final"))
        visit.followup_instructions = "جلسة تانية بكرة في العيادة"
        er["db"].session.commit()
    doc.post(f"/emergency/depart/{att}", data={
        "disposition": "home", "condition": "مستقر، بيتنفس كويس",
        "followup": "البخاخة كل ٤ ساعات"})
    page = doc.get(f"/emergency/attendance/{att}/paper").get_data(as_text=True)
    assert "J45.9" in page or "Asthma" in page
    assert "مستقر، بيتنفس كويس" in page
    assert "البخاخة كل ٤ ساعات" in page and "جلسة تانية بكرة في العيادة" in page


def test_come_back_at_once_is_the_hospital_s_words_or_a_blank(er):
    from app.models import Setting

    att = _attendance_with_a_given_dose(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/paper").get_data(as_text=True)
    assert "data-return-blank" in page and "data-return-signs" not in page, \
        "the program writes no signs of its own"
    with er["app"].app_context():
        Setting.set("er_return_signs", "نَفَس سريع\nمش بيرضع")
        er["db"].session.commit()
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/paper").get_data(as_text=True)
    signs = page.split("data-return-signs", 1)[1].split("</ul>", 1)[0]
    assert "نَفَس سريع" in signs and "مش بيرضع" in signs


def test_the_paper_prints_in_english_too(er):
    att = _attendance_with_a_given_dose(er)
    page = er["sign_in"]("doc").get(f"/emergency/attendance/{att}/paper?lang=en").get_data(as_text=True)
    assert "Come back to emergency at once if" in page


def test_the_hospital_writes_its_signs_in_settings(er):
    page = er["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-er-return-signs" in page
