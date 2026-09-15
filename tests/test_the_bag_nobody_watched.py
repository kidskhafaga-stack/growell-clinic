"""الدم: مين طلبه وليه، ومين علّقه، ومين كان قاعد جنب الطفل — ICD.20 و ICD.21.

المعياران بيطلبوا أربع حاجات في الملف بالنص، ودول اللي الملف ده بيختبرهم:

1. **`ICD.20` دليل ٣** — *"Indication for transfusion is recorded in the
   patient's medical record."* مطلوبة، والطلب من غيرها مرفوض: طلب من غير
   دواعي هو بالظبط الطلب اللي المعيار اتكتب عنه، والسماح بيه كان هيحطّ الفجوة
   في بنك الدم بدل ما تبان على الشاشة.
2. **`ICD.20` دليل ٤** — عاجل ولا عادي، عمود لوحده لأن المعيار بيسمّيه لوحده.
3. **`ICD.21` دليل ٣** — الكيس اتشاف قبل ما يتعلّق، بتلات حالات: كيس اتشاف
   ولقوه غلط دي واقعة تستاهل صف، مش غياب.
4. **`ICD.21` دليل ٤** — *"Monitoring of the patient's condition during
   transfusion is recorded."* والمراقبة **مشتقّة**: القراءات هي `Observation`
   عادية متعلّمة بالكيس، فمفيش نسخة تانية من قراية تبوظ، والقراية بتبان على
   شارت الطفل زي أي قراية.

وحاجتين تانيين:

* **اتنين شافوا، مش واحد راجع نفسه** — نيّة `ICD.21` كلها جملة واحدة عن
  *misidentification of the patient*.
* **وهي بتقول وعمرها ما بتمنع**: الكيس بيتعلّق من غير فحص متسجّل والشاشة
  بتفضل تقول كده. برنامج بيرفض هنا هو برنامج الناس بتلفّ حواليه بورق.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def ward(clinic):
    """A hospital with a ward, two beds and a second child."""
    from app.models import Patient, Setting
    from app.models.place import Bed, Space, Unit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        for module in ("beds", "ward"):
            Setting.set(f"mod_enabled:{module}", "1")
        unit = Unit(name="الداخلي", kind="ward")
        clinic["db"].session.add(unit)
        clinic["db"].session.flush()
        space = Space(unit_id=unit.id, name="غرفة", kind="room")
        clinic["db"].session.add(space)
        clinic["db"].session.flush()
        for order, name in enumerate(("د١", "د٢")):
            clinic["db"].session.add(
                Bed(space_id=space.id, name=name, sort_order=order))
        other = Patient(patient_number="BL-OTHER", full_name="طفل تاني",
                        gender="female", is_active=True,
                        date_of_birth=local_today() - timedelta(days=600))
        clinic["db"].session.add(other)
        clinic["db"].session.commit()
        clinic["beds"] = {b.name: b.id for b in Bed.query.all()}
        clinic["ids"]["other_child"] = other.id
    return clinic


def _admit(clinic, patient_id=None, bed="د١"):
    from app.models import Patient
    from app.models.place import Bed
    from app.utils import beds as place

    with clinic["app"].app_context():
        row = place.admit(Patient.query.get(patient_id or clinic["ids"]["child"]),
                          Bed.query.get(clinic["beds"][bed]),
                          when=datetime.utcnow() - timedelta(hours=6))
        clinic["db"].session.commit()
        return row.id


def _order(clinic, admission_id, product="prbc", indication="هيموجلوبين ٥",
           **form):
    return clinic["sign_in"]("doc").post(
        f"/beds/admission/{admission_id}/blood",
        data={"product": product, "indication": indication, **form},
        follow_redirects=True)


def _request_id(clinic, admission_id=None):
    from app.models import BloodRequest

    with clinic["app"].app_context():
        q = BloodRequest.query
        if admission_id:
            q = q.filter_by(admission_id=admission_id)
        row = q.order_by(BloodRequest.id.desc()).first()
        return row.id if row else None


def _hang(clinic, request_id, who="doc", **form):
    return clinic["sign_in"](who).post(f"/beds/blood/{request_id}/hang",
                                       data=form, follow_redirects=True)


def _bag_id(clinic):
    from app.models import Transfusion

    with clinic["app"].app_context():
        row = Transfusion.query.order_by(Transfusion.id.desc()).first()
        return row.id if row else None


def _watch(clinic, bag_id, **readings):
    return clinic["sign_in"]("doc").post(f"/beds/blood/bag/{bag_id}/watch",
                                         data=readings, follow_redirects=True)


def _state(clinic, bag_id):
    from app.models import Transfusion
    from app.utils import blood

    with clinic["app"].app_context():
        return blood.state(Transfusion.query.get(bag_id))


# ------------------------------------------------ ICD.20: why, and how fast ----
def test_the_indication_is_required_and_a_request_without_one_is_refused(ward):
    """`ICD.20` (د): the reason is recorded *"so that the blood bank can check
    that the product ordered is suitable for diagnosis"*. A request without one
    is exactly what the standard was written about."""
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, indication="   ")

    with ward["app"].app_context():
        assert BloodRequest.query.count() == 0


def test_the_indication_is_kept_word_for_word(ward):
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, indication="نزيف بعد العملية، هيموجلوبين ٦٫٢")

    with ward["app"].app_context():
        row = BloodRequest.query.one()
        assert row.indication == "نزيف بعد العملية، هيموجلوبين ٦٫٢"
        assert row.patient_id == ward["ids"]["child"]
        assert row.admission_id == stay


@pytest.mark.parametrize("urgency", ["routine", "emergency"])
def test_emergency_or_routine_is_its_own_fact(ward, urgency):
    """`ICD.20` evidence 4 names it: the blood bank is told whether it is
    needed on an emergency or a routine basis. Never inferred from how fast
    somebody typed."""
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, urgency=urgency)

    with ward["app"].app_context():
        assert BloodRequest.query.one().urgency == urgency


def test_an_unreadable_urgency_falls_back_to_routine(ward):
    """The safe direction. Calling an unknown word «عاجل» would fill a chasing
    list with ordinary requests until nobody reads it."""
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, urgency="حالاً جداً")

    with ward["app"].app_context():
        assert BloodRequest.query.one().urgency == "routine"


def test_a_product_the_program_does_not_know_is_refused(ward):
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, product="gold")

    with ward["app"].app_context():
        assert BloodRequest.query.count() == 0


@pytest.mark.parametrize("said,expected", [("yes", True), ("no", False),
                                           ("", None)])
def test_the_family_answer_keeps_its_three_states(ward, said, expected):
    """`ICD.20` (ب) — *"Education of patient and family about proposed
    transfusion **and recording in the patient's medical record**."* An empty
    box is not a family who was not told.

    **All three, not only the blank one.** Asserting the blank alone let a
    sweep drop the whole field from the route unnoticed: «محدّش قال» is what a
    dropped answer looks like too.
    """
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay, family_told=said)

    with ward["app"].app_context():
        assert BloodRequest.query.one().family_told is expected


def test_the_sample_check_is_its_own_stamp_and_its_own_person(ward):
    """`ICD.20` (ز) — it happens in the blood bank, after the request was
    written and by somebody else."""
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay)
    req = _request_id(ward, stay)
    ward["sign_in"]("boss").post(f"/beds/blood/{req}/sample",
                                 follow_redirects=True)

    with ward["app"].app_context():
        row = BloodRequest.query.get(req)
        assert row.sample_checked_at is not None
        assert row.sample_checked_by == ward["ids"]["admin"]
        assert row.requested_by == ward["ids"]["doctor"]
        assert row.state == "ready"


# --------------------------------------------- ICD.21: the bag and the eyes ----
def test_a_bag_with_no_check_recorded_says_so_and_is_still_hung(ward):
    """It tells, it never blocks. A program that refused here is a program
    somebody works around with paper, and then nothing is recorded at all."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), unit_code="U-1")

    with ward["app"].app_context():
        assert Transfusion.query.count() == 1
    assert _state(ward, _bag_id(ward)) == "unchecked"


def test_a_bag_found_wrong_is_a_row_and_not_an_absence(ward):
    """`ICD.21` (ج) — *conditions when the bag shall be discarded*. Somebody
    looked and found a problem; that is a fact, not a gap."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), unit_code="U-2", bag_checked="no",
          bag_note="الكيس مقطوع")

    with ward["app"].app_context():
        bag = Transfusion.query.one()
        assert bag.bag_checked is False
        assert bag.bag_note == "الكيس مقطوع"


def test_a_running_bag_nobody_has_watched_is_the_finding(ward):
    """`ICD.21` evidence 4, and the one thing on this card that is a finding
    rather than a gap: the bag is going into a child right now and nothing has
    been written down."""
    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), unit_code="U-3", bag_checked="yes")

    assert _state(ward, _bag_id(ward)) == "unwatched"


def test_one_reading_moves_it_off_the_finding(ward):
    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, temperature_c="37.2", pulse_bpm="110")

    assert _state(ward, bag) == "running"


def test_the_monitoring_is_an_ordinary_reading_on_the_childs_chart(ward):
    """A column, not a table: the readings taken every quarter of an hour
    during a transfusion are the same temperature and pulse the ward writes
    all day, and a second table would have kept them off the chart."""
    from app.models.observation import Observation

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, temperature_c="38.1", pulse_bpm="130", note="ارتعاش")

    with ward["app"].app_context():
        row = Observation.query.filter_by(transfusion_id=bag).one()
        assert row.patient_id == ward["ids"]["child"]
        assert row.temperature_c == 38.1
        assert row.recorded_by == ward["ids"]["doctor"]
        # And it is a plain observation, so it is on the child's chart too.
        assert Observation.query.filter_by(
            patient_id=ward["ids"]["child"]).count() == 1


def test_an_empty_reading_is_refused(ward):
    """It would clear «محدّش بيشوفه» without anybody having gone near the
    child — the same refusal the blank round note is built on."""
    from app.models.observation import Observation

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, note="")

    with ward["app"].app_context():
        assert Observation.query.filter_by(transfusion_id=bag).count() == 0
    assert _state(ward, bag) == "unwatched"


def test_another_bags_readings_never_count_for_this_one(ward):
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    first = _bag_id(ward)
    _watch(ward, first, pulse_bpm="120")

    _order(ward, stay, indication="وحدة تانية")
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    second = _bag_id(ward)

    assert first != second
    assert _state(ward, second) == "unwatched"
    with ward["app"].app_context():
        from app.utils import blood
        assert blood.watching(Transfusion.query.get(second)) == []


def test_two_people_and_not_one_checking_themselves(ward):
    """*"Wrong blood administration incidents are mainly due to human error
    leading to misidentification of the patient."* One signature on a
    double-check means the person who did the thing checked themselves."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes",
          checked_by=ward["ids"]["admin"])

    with ward["app"].app_context():
        bag = Transfusion.query.one()
        assert bag.given_by == ward["ids"]["doctor"]
        assert bag.checked_by == ward["ids"]["admin"]
        assert bag.two_people_checked is True


def test_the_same_person_twice_is_not_two_people(ward):
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes",
          checked_by=ward["ids"]["doctor"])

    with ward["app"].app_context():
        assert Transfusion.query.one().two_people_checked is False


def test_no_second_name_at_all_is_not_two_people(ward):
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")

    with ward["app"].app_context():
        assert Transfusion.query.one().two_people_checked is False


# -------------------------------------------------- what happened after ----
def test_a_reaction_outranks_a_finished_bag(ward):
    """A bag that caused a reaction is the record somebody comes back to.
    Letting «خلص» sit on top of it would file the most important transfusion
    of the month as routine."""
    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, pulse_bpm="120")
    ward["sign_in"]("doc").post(
        f"/beds/blood/bag/{bag}/finish",
        data={"reaction": "yes", "reaction_note": "ارتفاع حرارة، وقفنا الكيس",
              "stopped_early": "1"}, follow_redirects=True)

    assert _state(ward, bag) == "reacted"


def test_no_reaction_and_nobody_said_are_not_the_same(ward):
    """The operative report's «or not», for the fourth time in this codebase."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, pulse_bpm="118")
    ward["sign_in"]("doc").post(f"/beds/blood/bag/{bag}/finish",
                                data={"reaction": ""}, follow_redirects=True)

    with ward["app"].app_context():
        row = Transfusion.query.get(bag)
        assert row.reaction is None
        assert row.finished_at is not None
    assert _state(ward, bag) == "done"


def test_closing_a_bag_again_does_not_erase_the_reaction(ward):
    """The finish form always carries the reaction box, so a second press with
    it blank would send ``None``. ``None`` means *nobody said*, and it must not
    overwrite somebody who did — the most important line on the card erased by
    a stray click."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    ward["sign_in"]("doc").post(
        f"/beds/blood/bag/{bag}/finish",
        data={"reaction": "yes", "reaction_note": "ارتعاش وحرارة"},
        follow_redirects=True)
    ward["sign_in"]("doc").post(f"/beds/blood/bag/{bag}/finish",
                                data={"reaction": ""}, follow_redirects=True)

    with ward["app"].app_context():
        row = Transfusion.query.get(bag)
        assert row.reaction is True
        assert row.reaction_note == "ارتعاش وحرارة"
    assert _state(ward, bag) == "reacted"


def test_another_stays_blood_never_reaches_this_one(ward):
    """The third time this shape has been caught by a sweep in this project:
    a fixture with one stay lets a missing filter pass every test while the
    screen prints another child's transfusion."""
    from app.models.admission import Admission
    from app.utils import blood

    mine = _admit(ward, bed="د١")
    theirs = _admit(ward, patient_id=ward["ids"]["other_child"], bed="د٢")
    _order(ward, theirs, indication="مش بتاعه")

    with ward["app"].app_context():
        assert blood.for_admission(Admission.query.get(mine)) == []
        assert len(blood.for_admission(Admission.query.get(theirs))) == 1

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{mine}").get_data(as_text=True)
    assert "مش بتاعه" not in body


def test_a_bag_that_was_never_hung_is_not_running(ward):
    """«ماشي» means hung and not yet down. Reading only ``finished_at`` would
    call a bag that never went up a bag going into a child — and it is
    ``is_running`` that decides whether the watch form is offered and whether
    the readings can be late."""
    from app.models import Transfusion

    with ward["app"].app_context():
        never_hung = Transfusion(request_id=1,
                                 patient_id=ward["ids"]["child"])
        assert never_hung.is_running is False


def test_stopped_early_is_its_own_fact(ward):
    """A transfusion that was stopped and one that ran through are not the
    same record, and reading it off `finished_at` would make them identical."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    ward["sign_in"]("doc").post(
        f"/beds/blood/bag/{bag}/finish",
        data={"reaction": "no", "stopped_early": "1"}, follow_redirects=True)

    with ward["app"].app_context():
        assert Transfusion.query.get(bag).stopped_early is True


def test_a_cancelled_request_cannot_have_a_bag_hung_on_it(ward):
    """Recording blood given against an order that was withdrawn."""
    from app.models import Transfusion

    stay = _admit(ward)
    _order(ward, stay)
    req = _request_id(ward, stay)
    ward["sign_in"]("doc").post(f"/beds/blood/{req}/cancel",
                                data={"cancel_reason": "الحالة اتحسّنت"},
                                follow_redirects=True)
    _hang(ward, req, bag_checked="yes")

    with ward["app"].app_context():
        assert Transfusion.query.count() == 0


def test_a_request_with_blood_already_given_cannot_be_cancelled(ward):
    """It would leave blood in a child with no order behind it."""
    from app.models import BloodRequest

    stay = _admit(ward)
    _order(ward, stay)
    req = _request_id(ward, stay)
    _hang(ward, req, bag_checked="yes")
    ward["sign_in"]("doc").post(f"/beds/blood/{req}/cancel",
                                follow_redirects=True)

    with ward["app"].app_context():
        assert BloodRequest.query.get(req).state == "transfused"


# ------------------------------------------------- the clinic's own clock ----
def test_nothing_is_late_until_the_hospital_states_an_interval(ward):
    """The standard leaves *the rate for blood transfusion* and the monitoring
    to the hospital's policy. A ward that has been running for two years gains
    the record on upgrade day and gains no red with it."""
    from app.models import Transfusion
    from app.utils import blood

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, pulse_bpm="120")

    with ward["app"].app_context():
        assert blood.interval_minutes() is None
        assert blood.overdue_watch(
            Transfusion.query.get(bag),
            now=datetime.utcnow() + timedelta(days=2)) is False


def test_once_the_policy_names_an_interval_a_stale_watch_is_late(ward):
    from app.models import Setting, Transfusion
    from app.utils import blood

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, pulse_bpm="120")
    with ward["app"].app_context():
        Setting.set(blood.INTERVAL_SETTING, "15")
        ward["db"].session.commit()

        row = Transfusion.query.get(bag)
        fresh = blood.overdue_watch(row, now=datetime.utcnow())
        later = blood.overdue_watch(
            row, now=datetime.utcnow() + timedelta(minutes=20))
    assert (fresh, later) == (False, True)


@pytest.mark.parametrize("written", ["", "0", "-5", "كل ربع ساعة"])
def test_an_interval_that_is_not_minutes_is_no_interval(ward, written):
    from app.models import Setting
    from app.utils import blood

    with ward["app"].app_context():
        Setting.set(blood.INTERVAL_SETTING, written)
        ward["db"].session.commit()
        assert blood.interval_minutes() is None


def test_a_finished_bag_is_never_late_for_a_reading(ward):
    """A bag that is down cannot be behind on watching."""
    from app.models import Setting, Transfusion
    from app.utils import blood

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")
    bag = _bag_id(ward)
    _watch(ward, bag, pulse_bpm="120")
    ward["sign_in"]("doc").post(f"/beds/blood/bag/{bag}/finish",
                                data={"reaction": "no"}, follow_redirects=True)
    with ward["app"].app_context():
        Setting.set(blood.INTERVAL_SETTING, "15")
        ward["db"].session.commit()
        assert blood.overdue_watch(
            Transfusion.query.get(bag),
            now=datetime.utcnow() + timedelta(hours=3)) is False


# ------------------------------------------------------------- the screen ----
def test_the_stay_screen_shows_the_request_and_its_reason(ward):
    stay = _admit(ward)
    _order(ward, stay, indication="نزيف بعد العملية", urgency="emergency")

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-blood" in body
    assert 'data-blood-urgency="emergency"' in body
    assert "نزيف بعد العملية" in body


def test_the_screen_calls_out_the_bag_nobody_is_watching(ward):
    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-blood-summary="unwatched"' in body
    assert 'data-bag-state="unwatched"' in body


def test_the_screen_says_when_only_one_person_checked(ward):
    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay), bag_checked="yes")

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-bag-one-person" in body


def test_a_stay_with_no_blood_is_not_shouted_at(ward):
    stay = _admit(ward)

    body = ward["sign_in"]("doc").get(
        f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-blood-summary" not in body


def test_the_ward_door_is_shut_when_the_module_is_off(ward):
    from app.models import Setting

    stay = _admit(ward)
    with ward["app"].app_context():
        Setting.set("mod_enabled:beds", "0")
        ward["db"].session.commit()
    page = ward["sign_in"]("doc").post(f"/beds/admission/{stay}/blood",
                                       data={"product": "prbc",
                                             "indication": "أي حاجة"})
    assert page.status_code == 404


def test_nothing_here_stands_between_a_child_and_a_discharge(ward):
    """It tells, it never blocks — with a bag still running."""
    from app.models.admission import Admission

    stay = _admit(ward)
    _order(ward, stay)
    _hang(ward, _request_id(ward, stay))
    ward["sign_in"]("doc").post(f"/beds/admission/{stay}/discharge",
                                data={"outcome": "home"},
                                follow_redirects=True)

    with ward["app"].app_context():
        assert Admission.query.get(stay).discharged_at is not None


# -------------------------------------------------------------- the words ----
def test_every_blood_word_is_written_in_both_languages(ward):
    from app.i18n import _load_translations, _lookup
    from app.models.blood import PRODUCTS, REQUEST_STATES, URGENCIES
    from app.utils.blood import BAG_STATES

    tables = _load_translations()
    keys = ["title", "none_yet", "order", "product", "units", "urgency",
            "indication", "indication_ph", "family_told", "requested",
            "not_requested", "sample_check", "sample_ok", "sample_ok_short",
            "hang", "hung", "not_hung", "unit_code", "bag_checked_q",
            "bag_sound", "bag_wrong", "second_checker", "one_person", "rate",
            "hung_at", "watch", "watched", "watch_late", "needs_a_reading",
            "n_readings", "n_unwatched", "temp", "pulse", "spo2", "sys",
            "dia", "note", "finish", "finished", "reaction_q", "reaction",
            "reaction_note", "stopped_early", "cancel", "cancel_reason",
            "cancelled", "cannot_cancel", "yes", "no", "unsaid"]
    keys += [f"product_{p}" for p in PRODUCTS]
    keys += [f"urgency_{u}" for u in URGENCIES]
    keys += [f"req_{s}" for s in REQUEST_STATES]
    keys += [f"bag_{s}" for s in BAG_STATES]
    for key in keys:
        for lang in ("ar", "en"):
            assert _lookup(tables, lang, f"blood.{key}"), f"{lang}:{key}"


def test_the_states_are_the_ones_the_screen_can_draw(ward):
    from app.models.blood import PRODUCTS, REQUEST_STATES, URGENCIES
    from app.utils.blood import BAG_STATES

    assert URGENCIES == ("routine", "emergency")
    assert REQUEST_STATES == ("requested", "ready", "transfused", "cancelled")
    assert BAG_STATES == ("ordered", "unchecked", "running", "unwatched",
                          "reacted", "done")
    assert "other" in PRODUCTS
