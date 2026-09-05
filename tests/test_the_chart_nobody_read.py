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


# ===================== making the ward's doses up ===========================
def _supply(ward):
    from app.utils import clinical_pharmacy

    with ward["app"].app_context():
        return [{"stay": r["admission"].id, "left": r["left"],
                 "lines": [(ln["order"].id, ln["doses"], ln["units"],
                            ln["prep"] is not None) for ln in r["lines"]]}
                for r in clinical_pharmacy.supply_list()]


def test_the_count_is_arithmetic_on_the_doctors_own_order(ward):
    """**Never a judgement about what a child needs.** Six-hourly for a day is
    four, and that is all this number ever is."""
    from app.models.admission import Admission
    from app.utils import clinical_pharmacy, drug_round

    stay = _admit(ward, _child(ward, "ق"))
    with ward["app"].app_context():
        row = drug_round.order(
            ward["db"].session.get(Admission, stay), "أموكسيسيلين",
            dose="250 mg", every_hours=6, units_per_dose=2)
        ward["db"].session.commit()
        order = row.id
        assert clinical_pharmacy.doses_in_a_day(row) == 4

    # Four doses a day, and two ampoules in each of them: the ward is owed
    # four and eight left the shelf, and neither can be worked back from the
    # other once somebody changes the order.
    assert _supply(ward)[0]["lines"] == [(order, 4, 8, False)]


def test_a_prn_order_has_no_daily_count(ward):
    """There is no hour it is owed at, so there is no number of them in a day
    — and a pharmacy supplies those by agreement rather than by a figure this
    program made up."""
    from app.models.admission import Admission
    from app.utils import clinical_pharmacy, drug_round

    stay = _admit(ward, _child(ward, "ر٢"))
    with ward["app"].app_context():
        order = drug_round.order(
            ward["db"].session.get(Admission, stay), "باراسيتامول",
            dose="5 ml", is_prn=True, min_gap_hours=6)
        ward["db"].session.commit()
        assert clinical_pharmacy.doses_in_a_day(order) is None

    assert _supply(ward)[0]["lines"][0][1] is None


def test_making_it_up_takes_it_off_the_list(ward):
    """The list is the work remaining. One that keeps everybody on it is one
    nobody can see the end of."""
    stay = _admit(ward, _child(ward, "ش"))
    order = _order(ward, stay)

    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/prepare",
                                 data={"label": "كيس ٤ جرعات"},
                                 follow_redirects=True)

    assert _supply(ward) == []


def test_a_child_with_one_drug_left_stays_on_the_list(ward):
    """Off the list means *everything* is made up, not something."""
    stay = _admit(ward, _child(ward, "ت"))
    first = _order(ward, stay)
    _order(ward, stay, drug="باراسيتامول")

    ward["sign_in"]("chem").post(f"/pharmacy/order/{first}/prepare",
                                 follow_redirects=True)

    rows = _supply(ward)
    assert len(rows) == 1 and rows[0]["left"] == 1


def test_making_it_up_again_the_same_day_is_one_bag(ward):
    """A bag redone because the order changed at noon is still one bag going
    up to the ward, and two rows would tell the ward it was ready twice."""
    from app.models import DosePrep

    stay = _admit(ward, _child(ward, "ث"))
    order = _order(ward, stay)
    client = ward["sign_in"]("chem")
    client.post(f"/pharmacy/order/{order}/prepare", follow_redirects=True)
    client.post(f"/pharmacy/order/{order}/prepare", data={"label": "تاني"},
                follow_redirects=True)

    with ward["app"].app_context():
        row = DosePrep.query.one()
        assert row.label == "تاني"


def test_yesterdays_bag_does_not_cover_today(ward):
    """Supply is daily. Yesterday's four doses are given and gone."""
    from datetime import timedelta as td

    from app.models.medication import MedicationOrder
    from app.utils import clinical_pharmacy
    from app.utils.clock import local_today

    stay = _admit(ward, _child(ward, "خ"))
    order = _order(ward, stay)
    with ward["app"].app_context():
        clinical_pharmacy.prepare(
            ward["db"].session.get(MedicationOrder, order),
            on_date=local_today() - td(days=1))
        ward["db"].session.commit()

    assert _supply(ward)[0]["left"] == 1


def test_a_stopped_order_is_never_made_up(ward):
    """Making up a drug nobody may give is the one mistake this list can
    cause, so it is refused rather than left to the screen."""
    from app.models import DosePrep
    from app.models.medication import MedicationOrder
    from app.utils import clinical_pharmacy, drug_round

    stay = _admit(ward, _child(ward, "ذ"))
    order = _order(ward, stay)
    with ward["app"].app_context():
        drug_round.stop(ward["db"].session.get(MedicationOrder, order),
                        reason="اتوقف")
        ward["db"].session.commit()

    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/prepare",
                                 follow_redirects=True)

    with ward["app"].app_context():
        assert DosePrep.query.count() == 0


def test_the_ward_trolley_says_whether_it_is_here(ward):
    """**"Is it here?" is asked at the trolley**, so it is answered at the
    trolley — not on the pharmacy's own screen, which would send somebody down
    a corridor to find out."""
    stay = _admit(ward, _child(ward, "ض"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/prepare",
                                 follow_redirects=True)

    page = ward["sign_in"]("doc").get("/beds/drugs")

    assert b"data-prepared" in page.data


def test_the_trolley_says_nothing_when_no_pharmacy_prepares_anything(ward):
    """A ward whose drugs come off its own shelf has nobody preparing them,
    and a column reading "not ready" for ever would be a fault report about a
    service they do not buy."""
    from app.models import Setting

    stay = _admit(ward, _child(ward, "ظ"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/prepare",
                                 follow_redirects=True)
    with ward["app"].app_context():
        Setting.set("mod_enabled:pharmacy", "0")
        ward["db"].session.commit()

    page = ward["sign_in"]("doc").get("/beds/drugs")

    assert page.status_code == 200
    assert b"data-prepared" not in page.data


def test_the_supply_screen_is_absent_without_beds(ward):
    from app.models import Setting

    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()

    assert ward["sign_in"]("chem").get("/pharmacy/supply").status_code == 404


def test_the_board_leads_to_the_bench(ward):
    page = ward["sign_in"]("chem").get("/pharmacy/ward")

    assert b"/pharmacy/supply" in page.data


def test_the_screen_says_a_prn_has_no_daily_count(ward):
    """Rather than printing a number nobody worked out."""
    from app.models.admission import Admission
    from app.utils import drug_round

    stay = _admit(ward, _child(ward, "غ"))
    with ward["app"].app_context():
        drug_round.order(ward["db"].session.get(Admission, stay),
                         "باراسيتامول", dose="5 ml", is_prn=True,
                         min_gap_hours=6)
        ward["db"].session.commit()

    page = ward["sign_in"]("chem").get("/pharmacy/supply")

    assert b"data-prn" in page.data


# ============ the hospital's own high-alert list ============================
def _flag(ward, name="أموكسيسيلين", reason="أخطاء بعشر أضعاف",
          precaution="مراجعة تانية قبل الإعطاء"):
    """Put one ingredient on this hospital's list."""
    from app.models import GenericDrug, HighAlertDrug

    with ward["app"].app_context():
        generic = GenericDrug(name_ar=name, name_en=name)
        ward["db"].session.add(generic)
        ward["db"].session.flush()
        ward["db"].session.add(HighAlertDrug(
            generic_id=generic.id, reason=reason, precaution=precaution))
        ward["db"].session.commit()
        return generic.id


def test_nothing_is_flagged_until_the_hospital_writes_its_list(ward):
    """**Nothing is seeded, and that is the design.** The standards say the
    list is the hospital's own, built from its own use and its own near
    misses — and a paediatric oncology unit and a village clinic do not fear
    the same molecules."""
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ه٢"))
    _order(ward, stay)

    with ward["app"].app_context():
        assert clinical_pharmacy.high_alert_map() == {}
    page = ward["sign_in"]("doc").get("/beds/drugs")
    assert b"data-high-alert" not in page.data


def test_a_flagged_ingredient_is_marked_wherever_it_appears(ward):
    """Keyed on the ingredient so every brand of it is caught — including the
    one this clinic has not stocked yet."""
    _flag(ward)
    stay = _admit(ward, _child(ward, "و٢"))
    _order(ward, stay)

    trolley = ward["sign_in"]("doc").get("/beds/drugs")
    chart = ward["sign_in"]("chem").get(f"/pharmacy/ward/{stay}")

    assert b"data-high-alert" in trolley.data
    assert b"data-high-alert" in chart.data


def test_the_flag_carries_the_reason_and_what_to_do(ward):
    """"Insulin" on a list with nothing beside it tells a night nurse nothing;
    what to do about it tells them everything."""
    _flag(ward)
    stay = _admit(ward, _child(ward, "ز٢"))
    _order(ward, stay)

    page = ward["sign_in"]("chem").get(f"/pharmacy/ward/{stay}")

    assert b"data-alert-reason" in page.data
    assert "مراجعة تانية قبل الإعطاء".encode() in page.data
    # And at the trolley, where the syringe is.
    trolley = ward["sign_in"]("doc").get("/beds/drugs")
    assert "مراجعة تانية قبل الإعطاء".encode() in trolley.data


def test_a_row_with_no_reason_is_refused(ward):
    """A name on a list is not a warning."""
    from app.models import GenericDrug, HighAlertDrug

    with ward["app"].app_context():
        generic = GenericDrug(name_ar="مورفين", name_en="morphine")
        ward["db"].session.add(generic)
        ward["db"].session.commit()
        ident = generic.id

    ward["sign_in"]("boss").post("/pharmacy/high-alert/add",
                                 data={"generic_id": ident, "reason": "  "},
                                 follow_redirects=True)

    with ward["app"].app_context():
        assert HighAlertDrug.query.count() == 0


def test_a_row_naming_nothing_is_refused(ward):
    """A rule that matches nothing reads as cover."""
    from app.models import HighAlertDrug

    ward["sign_in"]("boss").post("/pharmacy/high-alert/add",
                                 data={"reason": "خطير"},
                                 follow_redirects=True)

    with ward["app"].app_context():
        assert HighAlertDrug.query.count() == 0


def test_taking_one_off_the_list_stops_the_flag(ward):
    """Off without losing that it was once on."""
    from app.models import HighAlertDrug

    _flag(ward)
    stay = _admit(ward, _child(ward, "ح٢"))
    _order(ward, stay)

    with ward["app"].app_context():
        row = HighAlertDrug.query.one()
        ident = row.id
    ward["sign_in"]("boss").post(f"/pharmacy/high-alert/{ident}/toggle",
                                 follow_redirects=True)

    page = ward["sign_in"]("doc").get("/beds/drugs")
    assert b"data-high-alert" not in page.data
    with ward["app"].app_context():
        # Still there, still readable — just not marking anything.
        assert HighAlertDrug.query.count() == 1


def test_the_list_is_the_owners(ward):
    """It decides what a whole hospital is warned about."""
    assert ward["sign_in"]("chem").get(
        "/pharmacy/high-alert").status_code == 403


# ============ a pharmacist checked it, and it is never a block ==============
def test_an_order_starts_unchecked(ward):
    """What the medication-management standards ask about and the program had
    no room for: an order was written and given, and nothing recorded whether
    anybody with a pharmacy training had looked at it first."""
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ط٢"))
    order = _order(ward, stay)

    with ward["app"].app_context():
        assert [o.id for o in clinical_pharmacy.unverified()] == [order]


def test_checking_it_records_who_and_when(ward):
    from app.models.medication import MedicationOrder

    stay = _admit(ward, _child(ward, "ي٢"))
    order = _order(ward, stay)

    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/verify",
                                 follow_redirects=True)

    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        assert row.verified_at is not None
        assert row.verified_by == ward["chemist"]


def test_an_unchecked_order_is_still_given(ward):
    """**Never a block.** A hospital at three in the morning with no
    pharmacist on site still gives the antibiotic, and a program that refused
    would be worked around by the end of the first night — which is how a
    control stops meaning anything."""
    from app.models.medication import MedicationOrder
    from app.utils import drug_round

    stay = _admit(ward, _child(ward, "ك٢"))
    order = _order(ward, stay)

    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        assert row.verified_at is None
        # Given, recorded, and charged exactly as it would have been.
        drug_round.give(row, "given")
        ward["db"].session.commit()
        assert row.doses


def test_the_unchecked_high_alert_ones_come_first(ward):
    """The order the standards care about most is the one nobody looked at,
    and among those the ones this hospital already said it is careful with."""
    from app.utils import clinical_pharmacy

    _flag(ward, name="مورفين")
    stay = _admit(ward, _child(ward, "ل٢"))
    ordinary = _order(ward, stay, drug="باراسيتامول")
    flagged = _order(ward, stay, drug="مورفين")

    with ward["app"].app_context():
        assert [o.id for o in clinical_pharmacy.unverified()][0] == flagged
        assert ordinary in [o.id for o in clinical_pharmacy.unverified()]


def test_the_board_counts_both_things_the_standards_ask_about(ward):
    _flag(ward)
    stay = _admit(ward, _child(ward, "م٢"))
    _order(ward, stay)

    page = ward["sign_in"]("chem").get("/pharmacy/ward")

    assert b"data-high-alert" in page.data
    assert b"data-unverified-orders" in page.data


def test_a_checked_order_drops_off_the_unchecked_count(ward):
    from app.utils import clinical_pharmacy

    stay = _admit(ward, _child(ward, "ن٢"))
    order = _order(ward, stay)
    ward["sign_in"]("chem").post(f"/pharmacy/order/{order}/verify",
                                 follow_redirects=True)

    with ward["app"].app_context():
        assert clinical_pharmacy.unverified() == []


def test_a_stopped_order_is_not_checked(ward):
    from app.models.medication import MedicationOrder
    from app.utils import clinical_pharmacy, drug_round

    stay = _admit(ward, _child(ward, "س٢"))
    order = _order(ward, stay)
    with ward["app"].app_context():
        row = ward["db"].session.get(MedicationOrder, order)
        drug_round.stop(row, reason="اتوقف")
        ward["db"].session.commit()
        with pytest.raises(ValueError):
            clinical_pharmacy.verify(row)
        ward["db"].session.rollback()
