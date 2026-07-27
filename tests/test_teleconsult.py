"""A decision taken over WhatsApp, written into the medical record.

The film comes back, the doctor reads it, and tells the family to carry on —
or to change the medicine, or to go and have one more test done. That is a
consultation. It happened on a phone rather than in the room, and that is the
only unusual thing about it.

**A WhatsApp message is not a medical record.** A thread proves words were
exchanged; it does not record that a doctor decided something, on what, and
when. A year later, whoever opens the file has to understand why the medicine
changed on a day the child never came in — and a file that says nothing
happened is worse than silence, because it looks correct.

So what is checked here is not "was a message sent". It is what the file says
afterwards.
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 300


@pytest.fixture()
def waiting(clinic, tmp_path):
    """A result that arrived and is waiting to be read."""
    static = tmp_path / "static"
    (static / "uploads" / "patient_docs").mkdir(parents=True)
    clinic["app"].static_folder = str(static)

    with clinic["app"].app_context():
        from app.models import Family, Parent, Patient

        family = Family(family_name="عائلة")
        clinic["db"].session.add(family)
        clinic["db"].session.flush()
        clinic["db"].session.add(Parent(family_id=family.id, full_name="الأم",
                                        relation="mother", phone="01000000001"))
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        child.family_id = family.id
        clinic["db"].session.commit()

    doctor = clinic["sign_in"]("doc")
    doctor.post(f"/visits/{clinic['ids']['visit']}/investigations",
                data={"name_ar": "أشعة صدر", "kind": "imaging"},
                follow_redirects=True)

    from app.utils import wa_media
    from app.utils.inbound import handle_inbound

    original = wa_media.download
    wa_media.download = lambda m, cfg=None: (PNG, "image/png")
    try:
        with clinic["app"].app_context():
            handle_inbound({"from_phone": "01000000001", "text": "أشعة الصدر",
                            "media": {"id": "m1"}}, "meta")
            clinic["db"].session.commit()
    finally:
        wa_media.download = original

    from app.models import VisitInvestigation

    with clinic["app"].app_context():
        clinic["order"] = VisitInvestigation.query.one().id
    clinic["doctor_client"] = doctor
    return clinic


def _decide(waiting, decision, **extra):
    data = {"decision": decision, "result_text": "التهاب شعبي"}
    data.update(extra)
    return waiting["doctor_client"].post(
        f"/visits/investigations/{waiting['order']}/decide",
        data=data, follow_redirects=True)


def _consults(waiting):
    from app.models import Visit

    with waiting["app"].app_context():
        return Visit.query.filter_by(channel="whatsapp").all()


# ------------------------------------------------- what the file says after --
def test_the_decision_is_a_visit_in_the_childs_history(waiting):
    """Not a note attached to a message — a consultation, which is what it
    was. It appears in the history and the printouts like any other because
    it is one."""
    _decide(waiting, "continue")

    with waiting["app"].app_context():
        consults = _consults(waiting)
        assert len(consults) == 1
        visit = consults[0]
        assert visit.patient_id == waiting["ids"]["child"]
        assert visit.doctor_id == waiting["ids"]["doctor"]
        assert visit.visit_date == date.today()


def test_the_record_says_it_was_decided_remotely(waiting):
    """Which of the two it was is part of the record, not a detail. Without
    it the file reads as though the child was seen."""
    _decide(waiting, "continue")
    assert _consults(waiting)[0].channel == "whatsapp"


def test_the_record_says_which_result_it_was_decided_on(waiting):
    """The question, the answer and the decision are one chain — otherwise
    they are three loose rows that only a person can join back up."""
    _decide(waiting, "continue")
    assert _consults(waiting)[0].based_on_id == waiting["order"]


@pytest.mark.parametrize("decision", ["continue", "change", "investigate"])
def test_what_was_decided_is_recorded_as_a_decision(waiting, decision):
    """"He replied with some text" is not something anybody can search,
    count, or be held to."""
    _decide(waiting, decision, test_name="صورة دم")
    assert _consults(waiting)[0].decision == decision


def test_the_detail_of_a_change_is_written_down(waiting):
    _decide(waiting, "change",
            note="وقف الشراب وابدأ الأقراص ٥ مل مرتين يومياً")
    assert "الأقراص" in _consults(waiting)[0].plan


def test_reading_it_here_takes_it_off_the_waiting_list(waiting):
    """Deciding on a result and having read it are one thought. Leaving the
    order unread afterwards would keep it on the list for something already
    dealt with."""
    from app.utils.results_inbox import arrived_unread

    _decide(waiting, "continue")
    with waiting["app"].app_context():
        assert arrived_unread() == []


def test_the_result_text_lands_on_the_order_itself(waiting):
    from app.models import VisitInvestigation

    _decide(waiting, "continue")
    with waiting["app"].app_context():
        order = waiting["db"].session.get(VisitInvestigation, waiting["order"])
        assert order.status == "resulted"
        assert "التهاب شعبي" in order.result_text
        assert order.resulted_at is not None


# ------------------------------------------------- ordering one more test --
def test_asking_for_another_test_actually_creates_it(waiting):
    """"Have one more test done" is a decision only if the test exists
    afterwards — otherwise it is a sentence in a message."""
    from app.models import VisitInvestigation

    _decide(waiting, "investigate", test_name="صورة دم كاملة",
            test_kind="lab", note="نتأكد من الأنيميا")

    with waiting["app"].app_context():
        new = VisitInvestigation.query.filter_by(name="صورة دم كاملة").one()
        assert new.status == "requested"
        assert new.kind == "lab"
        assert new.patient_id == waiting["ids"]["child"]
        # …and it hangs off the remote consultation that ordered it.
        assert new.visit_id == _consults(waiting)[0].id


def test_asking_for_another_test_without_naming_it_orders_nothing(waiting):
    """Better a decision with no test attached than a nameless row nobody
    can act on."""
    from app.models import VisitInvestigation

    _decide(waiting, "investigate", test_name="   ")
    with waiting["app"].app_context():
        assert VisitInvestigation.query.count() == 1        # only the original


def test_the_other_decisions_order_nothing(waiting):
    from app.models import VisitInvestigation

    _decide(waiting, "continue", test_name="صورة دم")
    with waiting["app"].app_context():
        assert VisitInvestigation.query.count() == 1


# ---------------------------------------------------- telling the family --
def test_the_family_is_told_from_the_clinics_number(waiting):
    """Not from the doctor's own phone — the conversation stays in one place
    and the record stays with the clinic."""
    from app.models import MessageLog

    _decide(waiting, "continue")
    with waiting["app"].app_context():
        out = MessageLog.query.filter_by(direction="out").all()
        assert len(out) == 1
        assert out[0].patient_id == waiting["ids"]["child"]


def test_the_doctors_own_words_are_what_gets_sent(waiting):
    from app.models import MessageLog

    _decide(waiting, "change", message="الصدر أحسن، غيّرنا الدوا للأقراص.")
    with waiting["app"].app_context():
        body = MessageLog.query.filter_by(direction="out").one().body
        assert "غيّرنا الدوا" in body


def test_leaving_the_message_empty_drafts_one(waiting):
    """A doctor who typed the decision should not have to type it twice."""
    from app.models import MessageLog

    _decide(waiting, "continue", message="")
    with waiting["app"].app_context():
        body = MessageLog.query.filter_by(direction="out").one().body
        assert body.strip()


def test_the_record_survives_the_message_failing(waiting):
    """A provider outage must never cost the record. The clinic is told the
    message did not go — which is a different problem, and a smaller one."""
    from app.models import MessageLog, Patient

    with waiting["app"].app_context():
        child = waiting["db"].session.get(Patient, waiting["ids"]["child"])
        child.family_id = None          # nothing left to send to
        waiting["db"].session.commit()

    resp = _decide(waiting, "continue")
    assert resp.status_code == 200
    assert len(_consults(waiting)) == 1, "the decision was lost with the send"
    with waiting["app"].app_context():
        assert MessageLog.query.filter_by(direction="out").count() == 0


# ------------------------------------------------------------ refusals ----
def test_a_decision_that_is_not_one_records_nothing(waiting):
    resp = _decide(waiting, "maybe-later")
    assert resp.status_code == 200
    assert _consults(waiting) == []


def test_no_decision_records_nothing(waiting):
    _decide(waiting, "")
    assert _consults(waiting) == []


def test_an_ordinary_clinic_visit_is_not_marked_remote(waiting):
    """The default has to stay "seen in the clinic" — every visit already on
    file was one, and a column that defaults the other way rewrites history."""
    from app.models import Visit

    with waiting["app"].app_context():
        visit = waiting["db"].session.get(Visit, waiting["ids"]["visit"])
        assert visit.channel == "clinic"
        assert visit.decision is None


def test_two_results_give_two_separate_consultations(waiting):
    """Each decision stands on its own result. Merging them would leave the
    file unable to say which finding produced which instruction."""
    from app.models import VisitInvestigation

    _decide(waiting, "continue")
    doctor = waiting["doctor_client"]
    doctor.post(f"/visits/{waiting['ids']['visit']}/investigations",
                data={"name_ar": "صورة دم", "kind": "lab"},
                follow_redirects=True)
    with waiting["app"].app_context():
        second = (VisitInvestigation.query
                  .filter_by(name="صورة دم").one())
        second.result_text = "Hb 11"
        second.status = "resulted"
        second.resulted_at = datetime.utcnow()
        waiting["db"].session.commit()
        second_id = second.id

    doctor.post(f"/visits/investigations/{second_id}/decide",
                data={"decision": "change", "note": "حديد شهر"},
                follow_redirects=True)

    consults = _consults(waiting)
    assert len(consults) == 2
    assert {c.based_on_id for c in consults} == {waiting["order"], second_id}


# ------------------------------------------- and it is visible, not just stored --
def test_the_printed_visit_says_the_child_was_not_in_the_room(waiting):
    """The printed page is what somebody reads a year later. Stored and
    invisible is the same as not recorded: the file would read as an
    ordinary examination that never happened."""
    _decide(waiting, "change", note="وقف الشراب وابدأ الأقراص")

    visit = _consults(waiting)[0]
    body = waiting["doctor_client"].get(
        f"/visits/{visit.id}").get_data(as_text=True)

    assert "استشارة عن بُعد" in body
    assert "تعديل العلاج" in body
    assert "أشعة صدر" in body, "the result it was decided on is missing"


def test_the_childs_history_shows_it_as_remote(waiting):
    _decide(waiting, "continue")
    body = waiting["doctor_client"].get(
        f"/patients/{waiting['ids']['child']}").get_data(as_text=True)
    assert "استشارة عن بُعد" in body


def test_an_ordinary_visit_is_not_labelled_remote_anywhere(waiting):
    body = waiting["doctor_client"].get(
        f"/visits/{waiting['ids']['visit']}").get_data(as_text=True)
    assert "استشارة عن بُعد" not in body
