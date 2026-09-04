"""The drug round — the order, the dose, and the silence between them.

``HOSPITAL_PLAN.md`` names three things the inpatient wards need beyond a bed:
the daily round, **the drug round**, and the daily bed charge. This is the
second of them, and it is the one with a body count behind it in real
hospitals, so almost everything tested here is a refusal.

**The order is not the dose.** A doctor writes a standing instruction; a
nurse, eight times over three days, records what actually happened. A single
"last given" column on the order would answer *is it due* and would answer
*what happened at two o'clock* with tonight's answer for every night of the
stay — which is exactly the question asked afterwards when something goes
wrong.

**Nothing is scheduled ahead.** No rows exist for doses that have not
happened; due-ness is worked out from the order and the last dose, the same
way a late observation is. A table of future doses drifts the moment an order
changes at midnight, and the first thing it does when it drifts is say a child
was given something they were not.

**A held dose is a decision. Silence is not.** Holding moves the clock exactly
as giving does — somebody stood at the bed. What must never exist is a dose
nobody wrote anything about, and that is why a hold with no reason is refused:
it looks exactly like a dose somebody forgot, and it silences the board either
way.

**Writing and giving are two permissions.** The oldest safety rule on a ward:
whoever holds the syringe is not the one who decided what is in it.

**And the safety check is not a second one.** Dose ceilings, allergies and
interaction pairs come from ``rx_safety`` — the check the prescription screen
uses — reading the child's pre-existing medicines along with the new orders. A
ward with its own idea of an interaction would be a second copy of a clinical
rule, free to disagree with the prescription screen about the same child on
the same day.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A ward with three beds, switched on."""
    from app.models import Setting, User
    from app.models.place import Bed, Space, Unit

    with clinic["app"].app_context():
        for module in ("observations", "beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        # The person this module was built for. Not in the shared fixture,
        # and the half of the drug round that matters here: nursing gives.
        nurse = User(username="nurse", full_name="الممرضة", role="nursing",
                     is_active=True)
        nurse.set_password("secret")
        clinic["db"].session.add(nurse)
        unit = Unit(name="الداخلي", kind="ward")
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة ١", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        for order, name in enumerate(("س١", "س٢", "س٣")):
            clinic["db"].session.add(
                Bed(space_id=space.id, name=name, sort_order=order))
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
    return clinic


def _child(clinic, name):
    from app.models import Patient
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        child = Patient(patient_number=f"D{name}", full_name=name,
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=800))
        clinic["db"].session.add(child)
        clinic["db"].session.commit()
        return child.id


def _admit(clinic, patient_id, bed_name="س١"):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id),
                          Bed.query.get(clinic["beds"][bed_name]))
        clinic["db"].session.commit()
        return row.id


def _order(clinic, admission_id, name="أموكسيسيلين", hours_ago=0, **extra):
    from app.models.admission import Admission
    from app.utils import drug_round

    with clinic["app"].app_context():
        row = drug_round.order(
            clinic["db"].session.get(Admission, admission_id), name,
            when=datetime.utcnow() - timedelta(hours=hours_ago),
            **{"dose": "250 mg", "every_hours": 8, **extra})
        clinic["db"].session.commit()
        return row.id


def _standing(clinic, order_id):
    from app.models.medication import MedicationOrder
    from app.utils import drug_round

    with clinic["app"].app_context():
        row = clinic["db"].session.get(MedicationOrder, order_id)
        last = drug_round.latest_dose_for([order_id]).get(order_id)
        return drug_round.state(row, last.at if last else None)


def _doses(clinic, order_id):
    from app.models.medication import MedicationDose

    with clinic["app"].app_context():
        return MedicationDose.query.filter_by(order_id=order_id).all()


# ------------------------------------------------------------ the order ----
def test_an_order_with_no_interval_is_refused(ward):
    """"Give amoxicillin" with no *how often* is not an instruction anybody
    can carry out. Stored, it would sit on the chart for ever: never due, and
    therefore never late."""
    from app.utils import drug_round

    child = _child(ward, "بدون_توقيت")
    admission = _admit(ward, child)

    with ward["app"].app_context():
        from app.models.admission import Admission

        with pytest.raises(ValueError):
            drug_round.order(ward["db"].session.get(Admission, admission),
                             "أموكسيسيلين", dose="250 mg")


def test_an_order_with_no_drug_is_refused(ward):
    from app.utils import drug_round

    child = _child(ward, "بدون_دوا")
    admission = _admit(ward, child)

    with ward["app"].app_context():
        from app.models.admission import Admission

        with pytest.raises(ValueError):
            drug_round.order(ward["db"].session.get(Admission, admission),
                             "   ", every_hours=8)


def test_when_needed_needs_no_interval(ward):
    """A PRN has no clock. What it has instead is a floor under how soon it
    may be repeated, which is the only safety number it carries."""
    order_id = None
    child = _child(ward, "لزوم")
    admission = _admit(ward, child)
    # The interval is sent as well, because that is what a form does when
    # somebody types 6 and then ticks "when needed". It has to be cleared:
    # the only rhythm a PRN has is its floor, and a second number beside it
    # would be a second rule about the same thing.
    order_id = _order(ward, admission, "باراسيتامول", every_hours=6,
                      is_prn=True, min_gap_hours=6)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder
        row = ward["db"].session.get(MedicationOrder, order_id)
        assert row.is_prn and row.every_hours is None
        assert row.min_gap_hours == 6


def test_the_screen_refuses_them_with_words_that_say_which(ward):
    """Two different refusals send whoever is at the keyboard to two different
    boxes. One message for both wastes the trip."""
    from app.i18n import t

    child = _child(ward, "رسايل")
    admission = _admit(ward, child)
    client = ward["sign_in"]("doc")

    with ward["app"].test_request_context("/"):
        no_drug, no_interval = t("meds.needs_drug"), t("meds.needs_interval")

    page = client.post(f"/beds/admission/{admission}/medication",
                       data={"drug_name": "", "every_hours": 8},
                       follow_redirects=True).get_data(as_text=True)
    assert no_drug in page

    page = client.post(f"/beds/admission/{admission}/medication",
                       data={"drug_name": "أموكسيسيلين"},
                       follow_redirects=True).get_data(as_text=True)
    assert no_interval in page


# ------------------------------------------------------- who may do what ---
def test_writing_an_order_and_giving_one_are_two_permissions(ward):
    """The oldest safety rule on a ward. A capability rather than
    ``role == "doctor"``, because roles here are editable and a hospital that
    invents "registrar" must be able to say what a registrar may do."""
    from app.models.permissions import (CAPABILITIES, role_capabilities,
                                        role_modules)

    assert "medication_order" in CAPABILITIES
    assert "medication_order" in role_capabilities("doctor")
    assert "medication_order" not in role_capabilities("nursing")
    # And nursing still walks the round and gives the drugs.
    assert "beds" in role_modules("nursing")


def test_a_nurse_may_give_but_may_not_prescribe(ward):
    child = _child(ward, "تمريض")
    admission = _admit(ward, child)
    order_id = _order(ward, admission)

    nurse = ward["sign_in"]("nurse")
    assert nurse.post(f"/beds/admission/{admission}/medication",
                      data={"drug_name": "دوا تاني",
                            "every_hours": 6}).status_code == 403
    assert nurse.post(f"/beds/medication/{order_id}/dose",
                      data={"outcome": "given"}).status_code in (302, 200)
    assert len(_doses(ward, order_id)) == 1


# ------------------------------------------------------- due, and late -----
def test_a_dose_is_due_from_the_last_one_not_from_a_timetable(ward):
    """A child started on something at two in the afternoon is due their next
    at six, not at whatever hour a fixed timetable names."""
    from app.utils import drug_round

    child = _child(ward, "مواعيد")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    # Nothing given yet: due is counted from when it was written, and twenty
    # hours on an eight-hourly order is well past.
    assert _standing(ward, order_id)["level"] == drug_round.LATE

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder
        drug_round.give(ward["db"].session.get(MedicationOrder, order_id),
                        "given", at=datetime.utcnow() - timedelta(hours=1))
        ward["db"].session.commit()

    after = _standing(ward, order_id)
    assert after["level"] == drug_round.OK
    assert after["minutes_late"] < 0


def test_a_held_dose_moves_the_clock_exactly_as_a_given_one_does(ward):
    """The round happened; somebody stood at the bed and decided. What must
    not move the clock is silence."""
    from app.utils import drug_round

    child = _child(ward, "تأجيل")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder
        drug_round.give(ward["db"].session.get(MedicationOrder, order_id),
                        "held", reason="الطفل بيرجّع",
                        at=datetime.utcnow() - timedelta(hours=1))
        ward["db"].session.commit()

    assert _standing(ward, order_id)["level"] == drug_round.OK


def test_silence_does_not_move_the_clock(ward):
    """The other half, and the reason the board exists. Nothing recorded is
    not the same as a dose dealt with, however long ago the order was
    written."""
    from app.utils import drug_round

    child = _child(ward, "سكوت")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=30)

    assert _doses(ward, order_id) == []
    assert _standing(ward, order_id)["level"] == drug_round.LATE
    assert _standing(ward, order_id)["minutes_late"] > 60


def test_the_grace_follows_the_interval(ward):
    """Ten minutes late on an hourly infusion is a real gap; ten minutes late
    on a once-a-day tablet is a nurse walking down a corridor. The same shape
    as the observations' grace, so that "late" means one thing on a ward."""
    from app.models.medication import lateness_grace

    assert lateness_grace(1) == 15        # the floor
    assert lateness_grace(2) == 30
    assert lateness_grace(4) == 60        # the ceiling
    assert lateness_grace(24) == 60


def test_a_prn_is_never_late(ward):
    """There is no hour it was owed at. Marking it late would put a red row on
    a board for a painkiller nobody has needed."""
    from app.utils import drug_round

    child = _child(ward, "لزوم_متأخر")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, "باراسيتامول", hours_ago=48,
                      every_hours=None, is_prn=True, min_gap_hours=6)

    assert _standing(ward, order_id)["level"] == drug_round.OK


# ---------------------------------------------------------- the refusals ---
def test_a_hold_with_no_reason_is_refused(ward):
    """**The test this file exists for.**

    A hold with nothing said about why is indistinguishable from a dose
    somebody forgot — and it silences the board either way, which is the one
    failure the board is built to prevent.
    """
    from app.utils import drug_round

    child = _child(ward, "تأجيل_بدون")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder
        with pytest.raises(drug_round.NoReason):
            drug_round.give(ward["db"].session.get(MedicationOrder, order_id),
                            "held")

    assert _doses(ward, order_id) == []
    assert _standing(ward, order_id)["level"] == drug_round.LATE


def test_the_screen_says_why_a_blank_hold_was_refused(ward):
    from app.i18n import t

    child = _child(ward, "تأجيل_شاشة")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    page = ward["sign_in"]("nurse").post(
        f"/beds/medication/{order_id}/dose",
        data={"outcome": "held", "reason": "  "},
        follow_redirects=True).get_data(as_text=True)

    with ward["app"].test_request_context("/"):
        assert t("meds.needs_reason") in page
    assert _doses(ward, order_id) == []


def test_giving_needs_no_reason(ward):
    """Only the refusals do. Asking for a reason to give a drug that was
    ordered is a box every nurse learns to type a full stop into."""
    child = _child(ward, "إعطاء")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    ward["sign_in"]("nurse").post(f"/beds/medication/{order_id}/dose",
                                  data={"outcome": "given"},
                                  follow_redirects=True)
    assert len(_doses(ward, order_id)) == 1


def test_a_when_needed_dose_inside_its_own_floor_is_refused(ward):
    """The only safety number a PRN carries, and the only place the program
    can enforce it: two nurses ten minutes apart, one relieving the other."""
    from app.utils import drug_round

    child = _child(ward, "قريب")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, "باراسيتامول", every_hours=None,
                      is_prn=True, min_gap_hours=6)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        row = ward["db"].session.get(MedicationOrder, order_id)
        drug_round.give(row, "given", at=datetime.utcnow() - timedelta(hours=2))
        ward["db"].session.commit()
        with pytest.raises(drug_round.TooSoon):
            drug_round.give(row, "given")

    assert len(_doses(ward, order_id)) == 1


def test_the_floor_lifts_once_the_hours_have_passed(ward):
    """A refusal that never lifts is a control nobody can use."""
    from app.utils import drug_round

    child = _child(ward, "بعد_المدة")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, "باراسيتامول", every_hours=None,
                      is_prn=True, min_gap_hours=6)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        row = ward["db"].session.get(MedicationOrder, order_id)
        drug_round.give(row, "given", at=datetime.utcnow() - timedelta(hours=7))
        ward["db"].session.commit()
        drug_round.give(row, "given")
        ward["db"].session.commit()

    assert len(_doses(ward, order_id)) == 2


def test_a_when_needed_dose_is_not_owed_at_any_hour(ward):
    """A PRN dose carries no ``due_at``, because there was none. Stamping one
    would make the file say a painkiller given at four had been owed since
    midday, and the "how late was it" column would start inventing minutes
    for every drug nobody was waiting for."""
    from app.utils import drug_round

    child = _child(ward, "لزوم_بدون_ميعاد")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, "باراسيتامول", hours_ago=30,
                      every_hours=6, is_prn=True, min_gap_hours=6)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        given = drug_round.give(
            ward["db"].session.get(MedicationOrder, order_id), "given")
        ward["db"].session.commit()
        assert given.due_at is None
        assert given.minutes_late is None


def test_a_dose_on_a_stopped_order_is_refused(ward):
    """The order was stopped for a reason, and a chart that accepts a dose
    afterwards cannot be trusted to say what a child is on."""
    from app.utils import drug_round

    child = _child(ward, "موقوف")
    admission = _admit(ward, child)
    order_id = _order(ward, admission)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        row = ward["db"].session.get(MedicationOrder, order_id)
        drug_round.stop(row, reason="خلص الكورس")
        ward["db"].session.commit()
        with pytest.raises(ValueError):
            drug_round.give(row, "given")

    assert _doses(ward, order_id) == []


def test_stopping_an_order_keeps_the_doses_it_already_had(ward):
    """A drug that was stopped is not a drug the child was never on, and the
    file has to be able to say what they were on last Tuesday."""
    from app.utils import drug_round

    child = _child(ward, "تاريخ_دوا")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        row = ward["db"].session.get(MedicationOrder, order_id)
        drug_round.give(row, "given", at=datetime.utcnow() - timedelta(hours=9))
        drug_round.stop(row, reason="خلص الكورس")
        ward["db"].session.commit()

    assert len(_doses(ward, order_id)) == 1
    # And it leaves the running list, because it is not running.
    with ward["app"].app_context():
        assert drug_round.running_orders([admission]).get(admission) is None


# ------------------------------------------------------------ the board ----
def test_the_board_puts_the_most_overdue_at_the_top(ward):
    from app.utils import drug_round

    # The one who is *not* late is admitted first, so insertion order says
    # the opposite of what the board must say. With them the other way round
    # a board sorted by nothing at all would have passed this.
    soon = _child(ward, "قريب_ميعاده")
    late = _child(ward, "متأخر")
    soon_stay = _admit(ward, soon, "س٢")
    late_stay = _admit(ward, late, "س١")
    _order(ward, soon_stay, hours_ago=8, every_hours=8)
    _order(ward, late_stay, hours_ago=30)

    with ward["app"].app_context():
        rows = drug_round.board()
        assert rows[0]["patient"].full_name == "متأخر"
        assert rows[0]["level"] == drug_round.LATE


def test_a_child_on_nothing_is_not_a_row_on_the_drug_round(ward):
    """They are on every other ward screen. Putting them here as well would
    bury the four children actually owed a dose under the twenty who are
    not."""
    from app.utils import drug_round

    on_something = _child(ward, "عليه_دوا")
    on_nothing = _child(ward, "مفيش_دوا")
    stay = _admit(ward, on_something, "س١")
    _admit(ward, on_nothing, "س٢")
    _order(ward, stay, hours_ago=20)

    with ward["app"].app_context():
        names = [r["patient"].full_name for r in drug_round.board()]
    assert names == ["عليه_دوا"]


def test_nobody_owed_anything_reads_as_an_answer(ward):
    """Not an empty screen. "Nothing is due" is a real and good answer and it
    has to read as one rather than as a module that failed to load."""
    from app.i18n import t

    child = _child(ward, "هادي")
    _admit(ward, child)

    page = ward["sign_in"]("boss").get("/beds/drugs").get_data(as_text=True)
    with ward["app"].test_request_context("/"):
        assert t("meds.nothing_due") in page


def test_the_department_card_says_how_many_are_owed(ward):
    """Counted, not listed: a card that named five drugs would stop being
    readable from across a room, which is the only thing that screen is for.
    And it links to where the answer is."""
    child = _child(ward, "لوحة")
    stay = _admit(ward, child)
    _order(ward, stay, hours_ago=30)

    page = ward["sign_in"]("doc").get("/ward/").get_data(as_text=True)
    assert 'data-drugs="late"' in page
    assert "/beds/drugs" in page


def test_the_drug_round_has_a_way_in(ward):
    """The recurring failure in this project: built, wired, tested, and
    nothing links to it."""
    page = ward["sign_in"]("doc").get("/beds/").get_data(as_text=True)
    assert "/beds/drugs" in page


def test_a_full_ward_costs_what_an_empty_one_costs(ward):
    """Size comparison rather than a guessed ceiling. Written as a loop, the
    orders and their last doses would be two queries per child — invisible on
    the three-bed ward a developer tests with."""
    from app.models.place import Bed, Space
    from app.utils import drug_round

    with ward["app"].app_context():
        space = Space.query.first()
        for n in range(20):
            ward["db"].session.add(
                Bed(space_id=space.id, name=f"ك{n}", sort_order=50 + n))
        ward["db"].session.commit()
        ward["beds"] = {b.name: b.id for b in Bed.query.all()}

    stays = []
    for n in range(20):
        stays.append(_admit(ward, _child(ward, f"كتير{n}"), f"ك{n}"))
    for stay in stays:
        _order(ward, stay, hours_ago=20)

    from sqlalchemy import event

    from app.extensions import db

    def count(ids):
        seen = []
        with ward["app"].app_context():
            engine = db.engine

            def record(conn, cursor, statement, params, ctx, many):
                seen.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                drug_round.for_admissions(ids)
            finally:
                event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    assert count(stays[:4]) == count(stays)


# ----------------------------------------------------- the safety check ----
def test_the_ward_uses_the_clinics_own_safety_check(ward):
    """Not a second one. A ward with its own idea of an interaction would be a
    second copy of a clinical rule, free to disagree with the prescription
    screen about the same child on the same day."""
    from app.models.drugbook import GenericDrug
    from app.models.prescription import Drug, DrugInteraction
    from app.utils import drug_round

    child = _child(ward, "تعارض")
    admission = _admit(ward, child)

    with ward["app"].app_context():
        a = GenericDrug(name_en="carbamazepine", name_ar="كاربامازيبين")
        b = GenericDrug(name_en="clarithromycin", name_ar="كلاريثرومايسين")
        ward["db"].session.add_all([a, b])
        ward["db"].session.flush()
        one = Drug(trade_name="Tegretol", generic_id=a.id, is_active=True)
        two = Drug(trade_name="Klacid", generic_id=b.id, is_active=True)
        ward["db"].session.add_all([one, two])
        ward["db"].session.add(DrugInteraction(
            generic_a_id=a.id, generic_b_id=b.id, severity="severe",
            is_active=True))
        ward["db"].session.commit()

        from app.models.admission import Admission
        stay = ward["db"].session.get(Admission, admission)
        drug_round.order(stay, "Tegretol", drug=one, dose="100 mg",
                         every_hours=12)
        drug_round.order(stay, "Klacid", drug=two, dose="125 mg",
                         every_hours=12)
        ward["db"].session.commit()

        result = drug_round.safety(stay)
        assert result["interactions"], "the clinic's own rule was not applied"


def test_what_the_child_was_already_on_is_in_the_check(ward):
    """The carbamazepine somebody else wrote months ago is exactly the half
    that interacts with what is about to be started — and it lives in
    ``PatientMedication``, not on any order this ward wrote."""
    from app.models.drugbook import GenericDrug
    from app.models.patient_medication import PatientMedication
    from app.models.prescription import Drug, DrugInteraction
    from app.utils import drug_round

    child = _child(ward, "من_برة")
    admission = _admit(ward, child)

    with ward["app"].app_context():
        from app.models.admission import Admission

        a = GenericDrug(name_en="carbamazepine", name_ar="كاربامازيبين")
        b = GenericDrug(name_en="clarithromycin", name_ar="كلاريثرومايسين")
        ward["db"].session.add_all([a, b])
        ward["db"].session.flush()
        new = Drug(trade_name="Klacid", generic_id=b.id, is_active=True)
        ward["db"].session.add(new)
        ward["db"].session.add(DrugInteraction(
            generic_a_id=a.id, generic_b_id=b.id, severity="severe",
            is_active=True))
        # Written months ago by a neurologist, and the only place it exists.
        ward["db"].session.add(PatientMedication(
            patient_id=child, name="كاربامازيبين", generic_id=a.id,
            dose="200 mg"))
        ward["db"].session.commit()

        stay = ward["db"].session.get(Admission, admission)
        drug_round.order(stay, "Klacid", drug=new, dose="125 mg",
                         every_hours=12)
        ward["db"].session.commit()

        assert drug_round.safety(stay)["interactions"]


# ------------------------------------------------------ the two clocks -----
def test_the_hour_it_was_given_is_kept_beside_the_hour_it_was_owed(ward):
    """"The eight o'clock dose, given at nine twenty" is a fact about a ward,
    and the two halves say different things."""
    from app.utils import drug_round

    child = _child(ward, "ساعتين")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    with ward["app"].app_context():
        from app.models.medication import MedicationOrder

        given = drug_round.give(
            ward["db"].session.get(MedicationOrder, order_id), "given",
            at=datetime.utcnow() - timedelta(hours=2))
        ward["db"].session.commit()
        assert given.due_at is not None
        assert given.due_at != given.at
        assert given.minutes_late > 0


def test_a_local_hour_typed_on_the_form_is_stored_as_utc(ward):
    """The mistake four money reports were fixed for. The screen offers the
    clinic's wall clock; storing it unconverted is three hours out every
    night."""
    from app.utils.clock import local_now, to_utc

    child = _child(ward, "ساعة_محلية")
    admission = _admit(ward, child)
    order_id = _order(ward, admission, hours_ago=20)

    walked = (local_now() - timedelta(hours=1)).replace(second=0,
                                                        microsecond=0)
    ward["sign_in"]("nurse").post(
        f"/beds/medication/{order_id}/dose",
        data={"outcome": "given", "at": walked.strftime("%Y-%m-%dT%H:%M")},
        follow_redirects=True)

    doses = _doses(ward, order_id)
    assert len(doses) == 1
    assert doses[0].at == to_utc(walked.replace(tzinfo=None))


# --------------------------------------------------------- said in both -----
def test_every_word_on_the_drug_screens_exists_in_both_languages():
    import json

    with open("app/i18n/locales/ar.json", encoding="utf-8") as fh:
        ar = json.load(fh)
    with open("app/i18n/locales/en.json", encoding="utf-8") as fh:
        en = json.load(fh)

    from app.models.medication import ROUTES

    for key in ("round", "chart", "given", "held", "refused", "needs_reason",
                "needs_drug", "needs_interval", "too_soon", "nothing_due",
                "prn", "late_by", "n_late", "n_due"):
        assert key in ar["meds"] and key in en["meds"]
        assert ar["meds"][key] != en["meds"][key]
    for way in ROUTES:
        assert f"route_{way}" in ar["meds"] and f"route_{way}" in en["meds"]


def test_the_guide_explains_the_drug_round():
    from app.utils.handbook import CAPABILITY_LABELS, SECTIONS

    keys = {s["key"] for s in SECTIONS}
    assert "beds_drugs" in keys
    assert "medication_order" in CAPABILITY_LABELS
    for section in SECTIONS:
        if section["key"] == "beds_drugs":
            assert section["module"] == "beds"
            assert len(section["lines"]) >= 4
