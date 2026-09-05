"""One program, two clinics — and the workflow must not damage either.

Asked in exactly these words: *"فيه عيادة بتطلب التحاليل بس والمريض بيروح
يعملها برّه، بس لو العيادة دي في مركز فيه تحاليل وسحب عينات هيروح للمعمل
الطلب... لو مشغّل البرنامج في عيادة طبيب واحد مفيش ورك فلو، لو في مركز هيبقى
فيه ورك فلو كامل."*

Two clinics, one program:

**The single doctor** orders a test and the family goes and has it done
somewhere else. There is no rack, no sample and no bench anywhere in their
copy — and everything they already had has to keep working untouched: the
order, the result they type in from the paper report, the pending list on the
next consultation, and the results inbox that tells them a film came back.

**The centre** has a lab, so the same order becomes work: somebody draws the
sample, somebody runs it, and it is charged. That is the whole of the
difference, and it is one switch.

**And the switch must not damage the doctor's own screens**, which is the half
that actually broke. The bench added a third state — `collected` — between
`requested` and `resulted`, and four places asked `status == "requested"` to
mean *no answer yet*: the results inbox, the pending list, the WhatsApp file
matcher and the status list itself. Every one of them made an order **vanish**
the moment the sample was drawn: the report was sitting on the record and the
doctor was never told it had come. Most of this file is about that.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def practice(clinic):
    """A clinic that orders tests. Whether it runs a lab is one setting."""
    from app.models import Investigation, Service

    with clinic["app"].app_context():
        priced = Service(name="صورة دم كاملة", category="lab", price=150,
                         is_active=True)
        clinic["db"].session.add(priced)
        clinic["db"].session.flush()
        cbc = Investigation(name_ar="صورة دم", name_en="CBC", kind="lab",
                            unit="g/dL", service_id=priced.id)
        clinic["db"].session.add(cbc)
        clinic["db"].session.commit()
        clinic["cbc"] = cbc.id
    return clinic


def _bench_on(practice, on=True):
    from app.models import Setting

    with practice["app"].app_context():
        Setting.set("mod_enabled:labs", "1" if on else "0")
        practice["db"].session.commit()


def _order(practice, days_ago=1, visit_id=None):
    """A test ordered on a visit, as the consultation screen writes one."""
    from app.models import VisitInvestigation

    with practice["app"].app_context():
        row = VisitInvestigation(
            visit_id=visit_id or practice["ids"]["visit"],
            patient_id=practice["ids"]["child"],
            investigation_id=practice["cbc"], kind="lab", name="صورة دم",
            status="requested",
            created_at=datetime.utcnow() - timedelta(days=days_ago))
        practice["db"].session.add(row)
        practice["db"].session.commit()
        return row.id


def _attach_a_report(practice, order_id):
    """A file answering the order — the photograph of a report a mother sends,
    or a scan taken at the desk."""
    from app.models import PatientAttachment

    with practice["app"].app_context():
        practice["db"].session.add(PatientAttachment(
            patient_id=practice["ids"]["child"],
            visit_id=practice["ids"]["visit"],
            investigation_id=order_id, filename="cbc.jpg",
            original_name="cbc.jpg", kind="result", source="whatsapp"))
        practice["db"].session.commit()


def _draw(practice, order_id):
    from app.models import VisitInvestigation
    from app.utils import labs

    with practice["app"].app_context():
        labs.collect(practice["db"].session.get(VisitInvestigation, order_id))
        practice["db"].session.commit()


# ==================== the single doctor: no workflow at all =================
def test_the_single_doctor_has_no_bench_anywhere(practice):
    """Not an empty rack. Absent."""
    _bench_on(practice, False)
    client = practice["sign_in"]("boss")

    assert client.get("/labs/").status_code == 404
    assert client.get("/labs/tests").status_code == 404


def test_the_single_doctor_still_orders_and_records_a_result(practice):
    """The whole of what they do, and none of it depends on the lab module."""
    from app.models import VisitInvestigation

    _bench_on(practice, False)
    order = _order(practice)

    practice["sign_in"]("doc").post(
        f"/visits/investigations/{order}/result",
        data={"result_value": "11.2", "result_unit": "g/dL"},
        follow_redirects=True)

    with practice["app"].app_context():
        row = practice["db"].session.get(VisitInvestigation, order)
        assert row.status == "resulted"
        assert row.result_value == 11.2


def test_the_single_doctors_curve_is_drawn_the_same(practice):
    """The feature they were already sold. Two readings, one line."""
    from app.models import Visit, VisitInvestigation
    from app.utils import lab_series
    from app.utils.clock import local_today

    _bench_on(practice, False)
    with practice["app"].app_context():
        older = Visit(patient_id=practice["ids"]["child"],
                      doctor_id=practice["ids"]["doctor"],
                      visit_date=local_today() - timedelta(days=30))
        practice["db"].session.add(older)
        practice["db"].session.commit()
        first = older.id

    for row_id, value in ((_order(practice, visit_id=first), 9.4),
                          (_order(practice), 12.0)):
        with practice["app"].app_context():
            row = practice["db"].session.get(VisitInvestigation, row_id)
            row.result_value = value
            row.result_unit = "g/dL"
            row.status = "resulted"
            row.resulted_at = datetime.utcnow()
            practice["db"].session.commit()

    with practice["app"].app_context():
        series = lab_series.series_for(practice["ids"]["child"])
        assert [p["value"] for p in series[0]["points"]] == [9.4, 12.0]


def test_nothing_is_charged_for_a_test_done_somewhere_else(practice):
    """They ordered it; somebody else drew it, ran it and was paid for it."""
    _bench_on(practice, False)
    _order(practice)

    page = practice["sign_in"]("boss").get(
        f"/finance/collect/{practice['ids']['child']}")

    assert page.status_code == 200
    assert b'"test_id"' not in page.data


# ==================== the centre: the same order becomes work ===============
def test_the_centre_gets_the_order_as_work(practice):
    """One switch, and the same row is on somebody's rack."""
    from app.utils import labs

    _bench_on(practice, True)
    order = _order(practice)

    with practice["app"].app_context():
        assert [r.id for r in labs.worklist()] == [order]
        assert labs.counts() == {"to_collect": 1, "to_run": 0}

    assert practice["sign_in"]("boss").get("/labs/").status_code == 200


def test_the_centre_charges_what_its_own_bench_drew(practice):
    """And only once the sample exists."""
    from app.utils import labs

    _bench_on(practice, True)
    order = _order(practice)
    with practice["app"].app_context():
        assert labs.unbilled(patient_id=practice["ids"]["child"]) == []

    _draw(practice, order)

    page = practice["sign_in"]("boss").get(
        f"/finance/collect/{practice['ids']['child']}")
    assert f'"test_id": {order}'.encode() in page.data


# ============ and the switch must not damage the doctor's screens ==========
def test_a_drawn_sample_does_not_hide_the_report_that_came_back(practice):
    """**The regression the bench introduced.**

    The results inbox asked for `status == "requested"` to mean *no answer
    yet*. Once the sample is drawn the status is `collected`, so a film whose
    report was sitting on the record dropped off the doctor's list in silence
    — and silence here is indistinguishable from "nothing came back".
    """
    from app.utils.results_inbox import arrived_count, arrived_unread

    _bench_on(practice, True)
    order = _order(practice)
    _attach_a_report(practice, order)

    with practice["app"].app_context():
        assert arrived_count() == 1

    _draw(practice, order)

    with practice["app"].app_context():
        waiting = arrived_unread()
        assert [row["order"].id for row in waiting] == [order]


def test_a_drawn_sample_still_shows_on_the_next_consultation(practice):
    """The pending list is "what did I ask for that has no answer" — not
    "which of the states before the answer is it in"."""
    from app.models import Visit
    from app.utils.clock import local_today

    _bench_on(practice, True)
    order = _order(practice, days_ago=5)
    _draw(practice, order)

    with practice["app"].app_context():
        today = Visit(patient_id=practice["ids"]["child"],
                      doctor_id=practice["ids"]["doctor"],
                      visit_date=local_today())
        practice["db"].session.add(today)
        practice["db"].session.commit()
        second = today.id

    page = practice["sign_in"]("doc").get(f"/visits/{second}/record")

    assert page.status_code == 200
    # The order's own result form, not merely its id: a bare number appears
    # all over a consultation screen, and asserting on one would pass with the
    # pending section empty.
    assert f"/visits/investigations/{order}/result".encode() in page.data


def test_a_report_sent_in_still_finds_the_order_it_answers(practice):
    """A family photographs the report and sends it. It answers the order
    whether or not our own bench drew a sample for it — and matching only
    `requested` filed it against nothing at exactly the clinics that run
    both."""
    from app.utils.wa_media import answered_order

    _bench_on(practice, True)
    order = _order(practice)
    _draw(practice, order)

    with practice["app"].app_context():
        assert answered_order(practice["ids"]["child"], "lab") == order


def test_an_answered_order_is_not_offered_to_anybody_again(practice):
    """The other direction: once there is a result it is off every list —
    the rack, the inbox and the pending page."""
    from app.models import VisitInvestigation
    from app.utils import labs
    from app.utils.results_inbox import arrived_count

    _bench_on(practice, True)
    order = _order(practice)
    _attach_a_report(practice, order)
    _draw(practice, order)

    with practice["app"].app_context():
        row = practice["db"].session.get(VisitInvestigation, order)
        labs.record(row, value=10.5, unit="g/dL")
        practice["db"].session.commit()

        assert labs.worklist() == []
        assert arrived_count() == 0


def test_the_three_states_are_named_in_one_place(practice):
    """One copy of "which states mean no answer yet".

    Four screens asked the question and each held its own answer; the day a
    fourth state is added, one copy is the difference between it appearing
    everywhere and orders vanishing off four screens again.
    """
    from app.models.visit import INVESTIGATION_OPEN, INVESTIGATION_STATUSES
    from app.utils import labs

    assert INVESTIGATION_STATUSES == ["requested", "collected", "resulted"]
    assert list(labs.OPEN_STATES) == INVESTIGATION_OPEN
    assert "resulted" not in INVESTIGATION_OPEN
