"""Why a family left against advice, and how the stay went — in their words.

Asked as: *«الخروج على المسئولية محتاج تقييم: هل السعر عالي؟ مشكلة في الخدمة
الطبية؟ … تقييم للي بيخلص خدمة … من الناحية الطبية والخدمية والمالية».*

The program knew **that** a family took their child home against advice,
and (``PCC.10``) what they were told first. It did not know **why**. And
the survey went out after an outpatient visit only — never after three
nights in the NICU — and asked about the doctor and the service, never
about the bill.

What is held here:

* against advice, the reason is taken in one tap, from the clinic's own
  list, on the ward and in emergency; a reason not on the list is not
  recorded; an ordinary discharge records none; it never holds the
  discharge up;
* a family is asked how it went after a stay and after emergency — never
  after a death, never after a transfer, and not twice in a week — and the
  survey remembers which unit it is about;
* the survey asks about the money too, with the quick "what bothered you",
  and a low score on the money reaches the inbox like any other;
* a reason in use cannot be deleted from the list.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


@pytest.fixture()
def ward(hospital):
    from app.models import Setting

    with hospital["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        hospital["db"].session.commit()
    return hospital


def _kid(clinic, name, phone="01012345678"):
    from app.models import Patient

    pid = _child(clinic, name)
    with clinic["app"].app_context():
        clinic["db"].session.get(Patient, pid).own_phone = phone
        clinic["db"].session.commit()
    return pid


def _discharge(clinic, admission_id, outcome, reason="", note=""):
    return clinic["sign_in"]("boss").post(
        f"/beds/admission/{admission_id}/discharge",
        data={"outcome": outcome, "note": "", "leave_reason": reason,
              "leave_note": note}, follow_redirects=True)


def _stay(clinic, admission_id):
    from app.models.admission import Admission

    with clinic["app"].app_context():
        row = clinic["db"].session.get(Admission, admission_id)
        return {"outcome": row.outcome, "reason": row.leave_reason,
                "note": row.leave_note}


def _surveys(clinic, patient_id):
    from app.models import Feedback, MessageLog

    with clinic["app"].app_context():
        rows = Feedback.query.filter_by(patient_id=patient_id).all()
        logs = MessageLog.query.filter_by(patient_id=patient_id,
                                          template_type="feedback").all()
        return ([{"admission": f.admission_id, "er": f.emergency_visit_id,
                  "centre": f.cost_centre.key if f.cost_centre else None,
                  "token": f.token} for f in rows],
                [(log.status, log.error) for log in logs])


# ------------------------------------------------------- why they left ----
def test_against_advice_the_reason_is_kept_with_their_words(ward):
    pid = _kid(ward, "سعر")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "self_discharge", reason="price",
               note="التأمين مش مغطّي")
    assert _stay(ward, stay) == {"outcome": "self_discharge", "reason": "price",
                                 "note": "التأمين مش مغطّي"}
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert 'data-left-because="price"' in page


def test_a_reason_that_is_not_on_the_list_is_not_recorded(ward):
    pid = _kid(ward, "غلط")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "self_discharge", reason="made_up")
    assert _stay(ward, stay)["reason"] is None
    assert _stay(ward, stay)["outcome"] == "self_discharge"   # never held up


def test_an_ordinary_discharge_records_no_reason(ward):
    pid = _kid(ward, "عادي")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "home", reason="price", note="x")
    assert _stay(ward, stay) == {"outcome": "home", "reason": None, "note": None}


def test_the_discharge_form_offers_the_reasons(ward):
    pid = _kid(ward, "فورم")
    stay = _admit(ward, pid)
    page = ward["sign_in"]("boss").get(f"/beds/admission/{stay}").get_data(as_text=True)
    box = page[page.index("data-leave-reason"):]
    box = box[:box.index("</select>")]
    assert 'value="price"' in box and 'value="unsaid"' in box


def _er(clinic, pid):
    from app.models import EmergencyVisit

    with clinic["app"].app_context():
        row = EmergencyVisit(patient_id=pid)
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def test_emergency_left_unseen_keeps_its_reason_and_asks_how_it_went(ward):
    from app.models import EmergencyVisit

    pid = _kid(ward, "طوارئ")
    visit = _er(ward, pid)
    ward["sign_in"]("boss").post(f"/emergency/depart/{visit}", data={
        "disposition": "left_unseen", "leave_reason": "service"})
    with ward["app"].app_context():
        row = ward["db"].session.get(EmergencyVisit, visit)
        assert (row.disposition, row.leave_reason) == ("left_unseen", "service")
    surveys, _logs = _surveys(ward, pid)
    assert [(s["er"], s["centre"]) for s in surveys] == [(visit, "emergency")]


def test_admitted_from_emergency_is_asked_later_not_now(ward):
    pid = _kid(ward, "اتحجز")
    visit = _er(ward, pid)
    ward["sign_in"]("boss").post(f"/emergency/depart/{visit}", data={
        "disposition": "admitted", "leave_reason": "price"})
    from app.models import EmergencyVisit

    with ward["app"].app_context():
        assert ward["db"].session.get(EmergencyVisit, visit).leave_reason is None
    assert _surveys(ward, pid)[0] == []


# -------------------------------------------------------- how it went ----
def test_after_a_stay_the_family_is_asked_about_that_unit(ward):
    from app.models.place import Unit

    pid = _kid(ward, "بيت")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "home")
    surveys, logs = _surveys(ward, pid)
    with ward["app"].app_context():
        unit_key = f"unit:{Unit.query.one().id}"
    assert [(s["admission"], s["centre"]) for s in surveys] == [(stay, unit_key)]
    assert logs and logs[0][0] != "skipped"
    page = ward["app"].test_client().get(f"/f/{surveys[0]['token']}").get_data(as_text=True)
    assert "data-q-finance" in page and 'value="finance:price"' in page
    assert "الداخلي" in page                     # it says which stay it is about


@pytest.mark.parametrize("outcome", ["died", "transferred"])
def test_never_after_a_death_or_a_transfer(ward, outcome):
    pid = _kid(ward, f"لا {outcome}")
    stay = _admit(ward, pid)
    _discharge(ward, stay, outcome)
    assert _surveys(ward, pid) == ([], [])


def test_not_twice_in_a_week(ward):
    from app.models import Feedback

    pid = _kid(ward, "مرتين")
    with ward["app"].app_context():
        ward["db"].session.add(Feedback(
            patient_id=pid, token="earlier", status="sent",
            created_at=datetime.utcnow() - timedelta(days=3)))
        ward["db"].session.commit()
    stay = _admit(ward, pid)
    _discharge(ward, stay, "home")
    surveys, logs = _surveys(ward, pid)
    assert len(surveys) == 1 and ("skipped", "recent_survey") in logs


def test_a_family_with_no_number_is_written_down_not_dropped(ward):
    pid = _kid(ward, "بدون", phone=None)
    stay = _admit(ward, pid)
    _discharge(ward, stay, "self_discharge", reason="unsaid")
    assert _surveys(ward, pid) == ([], [("skipped", "missing_phone")])


def test_the_money_side_and_what_bothered_them_reach_the_inbox(ward):
    from app.models import Feedback, MessageLog

    pid = _kid(ward, "فاتورة")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "self_discharge", reason="price")
    token = _surveys(ward, pid)[0][0]["token"]
    ward["app"].test_client().post(f"/f/{token}", data={
        "doctor_rating": "5", "service_rating": "5", "finance_rating": "2",
        "concern": ["finance:price", "finance:not_told", "finance:hacked",
                    "nonsense"],
        "nps": "7", "comment": "الفاتورة زادت"})
    with ward["app"].app_context():
        fb = Feedback.query.filter_by(token=token).one()
        assert fb.finance_rating == 2
        assert fb.concerns == "finance:price,finance:not_told"
        body = MessageLog.query.filter_by(
            direction="in", template_type="feedback_complaint").one().body
    assert "المالية 2/5" in body and "الإقامة" in body
    assert "السعر عالي" in body and "الفاتورة زادت" in body


def test_a_high_score_everywhere_reaches_nobody(ward):
    from app.models import MessageLog

    pid = _kid(ward, "مبسوط")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "home")
    token = _surveys(ward, pid)[0][0]["token"]
    ward["app"].test_client().post(f"/f/{token}", data={
        "doctor_rating": "5", "service_rating": "4", "finance_rating": "4",
        "nps": "9"})
    with ward["app"].app_context():
        assert MessageLog.query.filter_by(
            direction="in", template_type="feedback_complaint").count() == 0


def test_a_reason_in_use_cannot_be_deleted_from_the_list(ward):
    """The clinic's own reason, added on the lists screen: once a family's
    stay carries it, deleting it would leave that stay pointing at nothing."""
    from app.models import Lookup
    from app.utils import leave_reasons, lookups

    with ward["app"].app_context():
        leave_reasons.ensure_seeded()
        ward["db"].session.add(Lookup(domain="leave_reason", key="distance",
                                      name_ar="المسافة", sort_order=9))
        ward["db"].session.commit()
    pid = _kid(ward, "مستعمل")
    stay = _admit(ward, pid)
    _discharge(ward, stay, "self_discharge", reason="distance")
    with ward["app"].app_context():
        counts = lookups.usage_counts("leave_reason")
        assert counts["distance"] == 1 and counts["price"] == 0
        row = Lookup.query.filter_by(domain="leave_reason", key="distance").one()
        allowed, _why = lookups.can_delete(row, counts)
        assert not allowed
