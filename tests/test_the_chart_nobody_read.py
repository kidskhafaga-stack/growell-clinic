"""The clinical pharmacist: the chart nobody read.

`HOSPITAL_PLAN.md` مرحلة ج بند ٧ is *"الصيدلية الإكلينيكية — الجرعة بالكيلو،
والتعارضات، ومراجعة الروشتة"*, and the counter that came first answered the
last of those for **outpatients**: somebody standing at a window holding paper.

This is the other half of the same profession, and the half a hospital is
bought for — a pharmacist who reads the drug chart of every child in a bed,
against that child's weight and the four other things they are on, and says
something to the doctor **before** a dose is given.

None of the clinical rules are written here and one of the tests below exists
to keep it that way: the dose lives in `dosing`, the interactions and
allergies in `rx_safety`, and the ward already hands its chart to that check.
A third rulebook would defeat the point of a third pair of eyes.

What is asserted is the work, and it has the shape of every other ward
question this program answers:

* **who has nobody been through today** — a chart reviewed on Monday says
  nothing about the drug started on Wednesday;
* **a review is a row**, because a stay with no query on it looks exactly like
  a stay nobody opened, and those are opposite facts;
* **and a query is a question, never a block** — the drug goes on being given
  while it is open, because the answer is usually "yes, I meant it" and the
  child is in the bed.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A ward with a child in a bed and a pharmacist to read their chart."""
    from app.models import Service, Setting, User
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        for module in ("observations", "beds", "ward", "pharmacy",
                       "prescriptions"):
            Setting.set(f"mod_enabled:{module}", "1")

        chemist = User(username="chem", full_name="الصيدلي الإكلينيكي",
                       role="pharmacy", is_active=True)
        chemist.set_password("secret")
        clinic["db"].session.add(chemist)

        night = Service(name="ليلة داخلي", category="other", price=500)
        clinic["db"].session.add(night)
        clinic["db"].session.flush()
        unit = Unit(name="الداخلي", kind="ward", rate_service_id=night.id)
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        clinic["db"].session.add_all([Bed(space_id=space.id, name="د١"),
                                      Bed(space_id=space.id, name="د٢")])
        clinic["db"].session.commit()

        clinic["chemist"] = chemist.id
        clinic["beds"] = [b.id for b in Bed.query.order_by(Bed.id).all()]
    return clinic


def _child(ward, name, days=800):
    from app.models import Patient
    from app.utils.clock import local_today

    with ward["app"].app_context():
        row = Patient(patient_number=f"C{name}", full_name=name,
                      gender="male", is_active=True,
                      date_of_birth=local_today() - timedelta(days=days))
        ward["db"].session.add(row)
        ward["db"].session.commit()
        return row.id


def _admit(ward, patient_id, bed=0):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with ward["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(ward["beds"][bed]),
                          when=datetime.utcnow() - timedelta(days=1))
        ward["db"].session.commit()
        return row.id


def _order(ward, admission_id, drug="أموكسيسيلين"):
    from app.models.admission import Admission
    from app.utils import drug_round

    with ward["app"].app_context():
        row = drug_round.order(
            ward["db"].session.get(Admission, admission_id), drug,
            dose="250 mg", every_hours=8,
            when=datetime.utcnow() - timedelta(hours=2))
        ward["db"].session.commit()
        return row.id


def _board(ward):
    from app.utils import clinical_pharmacy

    with ward["app"].app_context():
        return [{"stay": r["admission"].id,
                 "reviewed": r["review"] is not None,
                 "drugs": r["drugs"],
                 "queries": len(r["queries"])}
                for r in clinical_pharmacy.board()]


# ===================== who has nobody been through today ====================
def test_a_child_in_a_bed_starts_unreviewed(ward):
    """**The question the screen exists to answer.** Before this there was no
    way to ask it: the chart was there and nothing recorded whether a second
    pair of eyes had read it."""
    stay = _admit(ward, _child(ward, "أ"))
    _order(ward, stay)

    assert _board(ward) == [{"stay": stay, "reviewed": False, "drugs": 1,
                             "queries": 0}]


def test_recording_a_review_takes_them_off_the_unreviewed_list(ward):
    stay = _admit(ward, _child(ward, "ب"))
    _order(ward, stay)

    ward["sign_in"]("chem").post(f"/pharmacy/ward/{stay}/reviewed",
                                 data={"note": "الجرعات مظبوطة"},
                                 follow_redirects=True)

    assert _board(ward)[0]["reviewed"] is True


def test_yesterdays_review_does_not_count_for_today(ward):
    """A chart reviewed on Monday says nothing about the drug started on
    Wednesday — the same rule the ward round runs on."""
    from app.models.admission import Admission
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ج"))
    _order(ward, stay)
    with ward["app"].app_context():
        clinical_pharmacy.review(
            ward["db"].session.get(Admission, stay),
            at=datetime.utcnow() - timedelta(days=1))
        ward["db"].session.commit()

    assert _board(ward)[0]["reviewed"] is False


def test_the_unreviewed_come_first(ward):
    """The whole reason to open this screen is to find who was missed, and a
    list that buries them among the done is read from the top and abandoned.
    """
    seen = _admit(ward, _child(ward, "د"), bed=0)
    missed = _admit(ward, _child(ward, "هـ"), bed=1)
    _order(ward, seen)
    ward["sign_in"]("chem").post(f"/pharmacy/ward/{seen}/reviewed",
                                 follow_redirects=True)

    assert [r["stay"] for r in _board(ward)] == [missed, seen]


def test_a_discharged_child_leaves_the_board(ward):
    """The board is who is in a bed now."""
    from app.models.admission import Admission
    from app.utils import beds as place

    stay = _admit(ward, _child(ward, "و"))
    with ward["app"].app_context():
        place.discharge(ward["db"].session.get(Admission, stay), "home")
        ward["db"].session.commit()

    assert _board(ward) == []


def test_the_review_records_how_many_drugs_it_covered(ward):
    """Stored rather than counted later: a review that covered four drugs on
    Tuesday is not evidence about the six the child is on today, and a screen
    that recomputed it would quietly claim it was."""
    from app.models import ChartReview

    stay = _admit(ward, _child(ward, "ز"))
    _order(ward, stay)
    _order(ward, stay, drug="باراسيتامول")
    ward["sign_in"]("chem").post(f"/pharmacy/ward/{stay}/reviewed",
                                 follow_redirects=True)
    _order(ward, stay, drug="أوميبرازول")

    with ward["app"].app_context():
        assert ChartReview.query.one().drugs_seen == 2


# ===================== a question, never a block ============================
def test_a_query_never_stops_the_drug(ward):
    """The answer is usually "yes, I meant it" and the child is in the bed. A
    pharmacy that can stop a ward's drug is one the ward writes around."""
    from app.models import MedicationOrder
    from app.utils import drug_round

    stay = _admit(ward, _child(ward, "ح"))
    order = _order(ward, stay)

    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/ask",
                                 data={"note": "الجرعة عالية للوزن"},
                                 follow_redirects=True)

    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        assert row.query_note == "الجرعة عالية للوزن"
        # Still running, still on the drug round, still due.
        assert row.is_running
        assert order in [o.id for o in
                         drug_round.running_orders([stay]).get(stay) or []]


def test_the_screen_says_the_drug_is_still_given(ward):
    """A warning that looked like a stop would have a nurse holding a dose
    while somebody goes looking for the doctor."""
    stay = _admit(ward, _child(ward, "ط"))
    order = _order(ward, stay)
    client = ward["sign_in"]("chem")
    client.post(f"/pharmacy/order/{order}/ask", data={"note": "سؤال"},
                follow_redirects=True)

    page = client.get(f"/pharmacy/ward/{stay}")

    assert b"data-still-given" in page.data


def test_a_blank_question_is_refused(ward):
    """It would flag the order and say nothing, which reads on the doctor's
    screen as somebody having looked and been satisfied."""
    from app.models import MedicationOrder
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ي"))
    order = _order(ward, stay)

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            clinical_pharmacy.ask(
                ward["db"].session.get(MedicationOrder, order), note="  ")
        ward["db"].session.rollback()
        assert ward["db"].session.get(MedicationOrder,
                                      order).queried_at is None


def test_the_doctor_answers_and_the_question_stays(ward):
    """What was asked and what came back is the record. Clearing it would
    leave a changed dose with nothing saying why, and an unchanged one with
    nothing saying it was defended."""
    from app.models import MedicationOrder

    stay = _admit(ward, _child(ward, "ك"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/ask",
                                 data={"note": "الجرعة عالية"},
                                 follow_redirects=True)

    ward["sign_in"]("doc").post(f"/beds/order/{order}/answer",
                                data={"note": "مقصودة، الطفل عنده تشنجات"},
                                follow_redirects=True)

    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        assert row.query_note == "الجرعة عالية"
        assert row.answer_note == "مقصودة، الطفل عنده تشنجات"
        assert row.answered_by == ward["ids"]["doctor"]


def test_an_answered_question_leaves_the_waiting_list(ward):
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ل"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/ask",
                                 data={"note": "سؤال"}, follow_redirects=True)
    assert _board(ward)[0]["queries"] == 1

    ward["sign_in"]("doc").post(f"/beds/order/{order}/answer",
                                data={"note": "تمام"}, follow_redirects=True)

    with ward["app"].app_context():
        assert clinical_pharmacy.open_queries() == {}


def test_asking_again_reopens_it(ward):
    """A doctor answered, the pharmacist is still not happy, and the second
    question is the one that matters."""
    from app.models import MedicationOrder

    stay = _admit(ward, _child(ward, "م"))
    order = _order(ward, stay)
    chem = ward["sign_in"]("chem")
    chem.post(f"/pharmacy/order/{order}/ask", data={"note": "أول سؤال"},
              follow_redirects=True)
    ward["sign_in"]("doc").post(f"/beds/order/{order}/answer",
                                data={"note": "مقصودة"}, follow_redirects=True)

    chem.post(f"/pharmacy/order/{order}/ask", data={"note": "لسه عالية"},
              follow_redirects=True)

    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        assert row.query_note == "لسه عالية"
        assert row.answered_at is None
    assert _board(ward)[0]["queries"] == 1


def test_the_question_reaches_the_doctor_where_the_doctor_is(ward):
    """**On the stay screen, not the pharmacy's.** The first version put the
    reply on the pharmacy screen, which the doctor cannot open at all — the
    module is not theirs — so the pharmacist would have waited for ever with
    no way to tell that from being ignored."""
    stay = _admit(ward, _child(ward, "ص"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/ask",
                                 data={"note": "الجرعة عالية"},
                                 follow_redirects=True)

    page = ward["sign_in"]("doc").get(f"/beds/admission/{stay}")

    assert b"data-pharmacy-query" in page.data
    assert "الجرعة عالية".encode() in page.data
    assert f"/beds/order/{order}/answer".encode() in page.data


def test_answering_something_nobody_asked_about_is_refused(ward):
    from app.models import MedicationOrder
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ن"))
    order = _order(ward, stay)

    with ward["app"].app_context():
        with pytest.raises(ValueError):
            clinical_pharmacy.answer(
                ward["db"].session.get(MedicationOrder, order), note="تمام")
        ward["db"].session.rollback()


# ===================== the check is the clinic's one check ==================
def test_the_pharmacist_sees_the_wards_own_safety_check(ward):
    """`drug_round.safety` and nothing else — the same call the ward screen
    makes. A clinical pharmacy with its own idea of an interaction would be a
    second copy of a clinical rule, free to disagree with the prescription
    screen about the same child on the same day."""
    from app.models.admission import Admission
    from app.utils import clinical_pharmacy, drug_round

    stay = _admit(ward, _child(ward, "س"))
    _order(ward, stay)

    with ward["app"].app_context():
        row = ward["db"].session.get(Admission, stay)
        mine = clinical_pharmacy.chart(row)
        theirs = drug_round.safety(row)
        assert [ln["name"] for ln in mine["safety"]["lines"]] == \
               [ln["name"] for ln in theirs["lines"]]
        assert mine["safety"]["interactions"] == theirs["interactions"]


# ===================== the doors ===========================================
def test_the_ward_screens_are_absent_without_beds(ward):
    """A clinic with no inpatients has no charts to review, and an empty board
    would read as something broken rather than something they do not have."""
    from app.models import Setting

    stay = _admit(ward, _child(ward, "ع"))
    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()

    client = ward["sign_in"]("chem")
    assert client.get("/pharmacy/ward").status_code == 404
    assert client.get(f"/pharmacy/ward/{stay}").status_code == 404


def test_the_counter_leads_to_the_ward_board(ward):
    """Without a link from somewhere, the screen exists and nothing reaches
    it."""
    page = ward["sign_in"]("chem").get("/pharmacy/")

    assert b"/pharmacy/ward" in page.data


def test_the_counter_does_not_offer_the_ward_where_there_are_no_beds(ward):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()

    page = ward["sign_in"]("chem").get("/pharmacy/")

    assert b"/pharmacy/ward" not in page.data


def test_the_board_draws_who_was_missed(ward):
    stay = _admit(ward, _child(ward, "ف"))
    _order(ward, stay)

    page = ward["sign_in"]("chem").get("/pharmacy/ward")

    assert page.status_code == 200
    assert b"data-not-reviewed" in page.data
    assert b"data-unreviewed" in page.data


def test_the_capability_switches_the_beds_on_with_it(ward):
    """A clinical pharmacist reads the charts of children in beds. Ticking the
    capability and getting no ward screens would be a box that changes nothing
    anybody can point at."""
    from app.utils.facility import CAPABILITY_MODULES

    needed = CAPABILITY_MODULES["clinical_pharmacy"]
    assert {"pharmacy", "beds"} <= needed
