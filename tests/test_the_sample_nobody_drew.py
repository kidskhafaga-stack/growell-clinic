"""The lab bench — and the difference between two things that looked alike.

``HOSPITAL_PLAN.md`` مرحلة ج، بند ٦ asks for four things and two of them were
built in August: the numeric result, and the curve drawn from it. Ordering has
worked from the visit screen for years, and reading a result has an inbox of
its own.

**What had no screen anywhere is the middle**, and it is where a hospital
lives. An order went from `requested` straight to `resulted`, because the only
hands it passed through were the doctor's, typing in what a paper report said.
So two completely different situations were stored identically:

* nobody has drawn this child's blood, and
* the blood is in a rack downstairs.

The first needs a person to walk to a bed; the second needs only time. That is
the distinction this module exists to make, and most of what is asserted here
is some form of it.

The rest is the money, which follows the same rule every other chargeable
thing in this program follows: the price is the switch, and charging starts at
the moment something was actually spent — **the draw, not the order**.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def lab(clinic):
    """A clinic with a bench, one priced test and one that is not priced."""
    from app.models import Investigation, Service, Setting
    from app.utils import accounting as acct

    with clinic["app"].app_context():
        acct.ensure_seeded()
        Setting.set("mod_enabled:labs", "1")

        cbc_service = Service(name="صورة دم كاملة", category="lab", price=150,
                              commission_type="percent", commission_value=10,
                              is_active=True)
        clinic["db"].session.add(cbc_service)
        clinic["db"].session.flush()

        cbc = Investigation(name_ar="صورة دم", name_en="CBC", kind="lab",
                            unit="g/dL", sample_type="دم",
                            service_id=cbc_service.id)
        # No service on this one: the clinic does not bill it separately.
        urine = Investigation(name_ar="تحليل بول", kind="lab", sample_type="بول")
        clinic["db"].session.add_all([cbc, urine])
        clinic["db"].session.commit()

        clinic["cbc"] = cbc.id
        clinic["urine"] = urine.id
        clinic["cbc_service"] = cbc_service.id
    return clinic


def _order(lab, test="cbc", name="صورة دم", visit_id=None, minutes_ago=0):
    """A test ordered on the child's visit, as the visit screen writes it."""
    from app.models import VisitInvestigation

    with lab["app"].app_context():
        row = VisitInvestigation(
            visit_id=visit_id or lab["ids"]["visit"],
            patient_id=lab["ids"]["child"],
            investigation_id=lab[test] if test else None,
            kind="lab", name=name, status="requested",
            created_at=datetime.utcnow() - timedelta(minutes=minutes_ago))
        lab["db"].session.add(row)
        lab["db"].session.commit()
        return row.id


def _state(lab, order_id):
    from app.models import VisitInvestigation

    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, order_id)
        return {"status": row.status, "code": row.sample_code,
                "collected": row.collected_at is not None,
                "collected_by": row.collected_by,
                "resulted_by": row.resulted_by,
                "value": row.result_value, "unit": row.result_unit,
                "low": row.result_low, "high": row.result_high,
                "billed": row.invoice_item_id is not None}


# ============================ the distinction the module exists for =========
def test_a_drawn_sample_and_an_undrawn_one_are_not_the_same_row(lab):
    """**The whole of it.** Before the bench both of these were "requested",
    and a list that cannot tell them apart is a list checked by phone."""
    from app.models import VisitInvestigation
    from app.utils import labs

    waiting = _order(lab)
    drawn = _order(lab, name="تحليل بول", test="urine")

    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, drawn))
        lab["db"].session.commit()

    assert _state(lab, waiting)["status"] == "requested"
    assert _state(lab, drawn)["status"] == "collected"

    with lab["app"].app_context():
        assert labs.counts() == {"to_collect": 1, "to_run": 1}


def test_the_rack_is_oldest_first(lab):
    """A rack is worked from the bottom. A list that puts this minute's order
    on top is one where the sample taken at eight is still there at two."""
    from app.utils import labs

    newest = _order(lab, minutes_ago=1)
    oldest = _order(lab, minutes_ago=300, name="تحليل بول", test="urine")
    middle = _order(lab, minutes_ago=60, name="وظائف كلى", test=None)

    with lab["app"].app_context():
        assert [r.id for r in labs.worklist()] == [oldest, middle, newest]


def test_an_answered_order_leaves_the_rack(lab):
    """Once there is an answer the order belongs to whoever asked for it, and
    that list already exists — the results inbox."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, order)
        labs.collect(row)
        labs.record(row, value=11.2, unit="g/dL")
        lab["db"].session.commit()
        assert labs.worklist() == []
        assert labs.counts() == {"to_collect": 0, "to_run": 0}


def test_the_tube_labels_itself(lab):
    """A label nobody has to invent is a label that actually ends up on the
    tube at three in the morning."""
    from app.utils.clock import local_today

    order = _order(lab)
    client = lab["sign_in"]("boss")
    client.post(f"/labs/order/{order}/collect", follow_redirects=True)

    code = _state(lab, order)["code"]
    assert code == f"{local_today():%y%m%d}-{order:05d}"


def test_a_label_somebody_wrote_by_hand_wins(lab):
    """The tube in front of them is the tube that matters."""
    order = _order(lab)
    lab["sign_in"]("boss").post(f"/labs/order/{order}/collect",
                                data={"code": "A-77"}, follow_redirects=True)

    assert _state(lab, order)["code"] == "A-77"


def test_the_sample_says_who_drew_it_and_when(lab):
    """A tube with no name on it is a tube nobody can ask about."""
    order = _order(lab)
    lab["sign_in"]("boss").post(f"/labs/order/{order}/collect",
                                follow_redirects=True)

    state = _state(lab, order)
    assert state["collected"]
    assert state["collected_by"] == lab["ids"]["admin"]


def test_an_answered_order_is_not_re_drawn(lab):
    """A keystroke on the wrong row would otherwise put a fresh sample time on
    a result taken from an older one."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, order)
        labs.collect(row)
        labs.record(row, value=9.0)
        lab["db"].session.commit()
        with pytest.raises(ValueError):
            labs.collect(lab["db"].session.get(VisitInvestigation, order))
        lab["db"].session.rollback()

    assert _state(lab, order)["status"] == "resulted"


def test_a_haemolysed_sample_is_drawn_again(lab):
    """Re-drawing an unanswered order is normal and overwrites: the tube that
    matters is the one that reached the bench."""
    order = _order(lab)
    client = lab["sign_in"]("boss")
    client.post(f"/labs/order/{order}/collect", data={"code": "A-1"},
                follow_redirects=True)
    client.post(f"/labs/order/{order}/collect", data={"code": "A-2"},
                follow_redirects=True)

    assert _state(lab, order)["code"] == "A-2"


# ============================ the answer ====================================
def test_the_result_lands_on_the_order_it_answers(lab):
    """No second place for the number: the same row the visit screen shows and
    the curve is drawn from."""
    order = _order(lab)
    client = lab["sign_in"]("boss")
    client.post(f"/labs/order/{order}/collect", follow_redirects=True)
    client.post(f"/labs/order/{order}/result",
                data={"result_value": "10.4", "result_unit": "g/dL",
                      "result_low": "11", "result_high": "14"},
                follow_redirects=True)

    state = _state(lab, order)
    assert state["status"] == "resulted"
    assert state["value"] == 10.4
    assert state["low"] == 11 and state["high"] == 14
    assert state["resulted_by"] == lab["ids"]["admin"]


def test_the_curve_reads_what_the_bench_wrote(lab):
    """The point of not having a second results table."""
    from app.models import Visit, VisitInvestigation
    from app.utils import lab_series, labs
    from app.utils.clock import local_today

    with lab["app"].app_context():
        second = Visit(patient_id=lab["ids"]["child"],
                       doctor_id=lab["ids"]["doctor"],
                       visit_date=local_today() - timedelta(days=7))
        lab["db"].session.add(second)
        lab["db"].session.commit()
        older = second.id

    first = _order(lab, visit_id=older)
    latest = _order(lab)
    with lab["app"].app_context():
        for row_id, value in ((first, 9.5), (latest, 11.8)):
            row = lab["db"].session.get(VisitInvestigation, row_id)
            labs.collect(row)
            labs.record(row, value=value, unit="g/dL")
        lab["db"].session.commit()

        series = lab_series.series_for(lab["ids"]["child"])
        assert len(series) == 1
        assert [p["value"] for p in series[0]["points"]] == [9.5, 11.8]


def test_a_cleared_number_takes_its_range_with_it(lab):
    """A band with nothing to compare it to is a band on an empty chart."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, order)
        labs.collect(row)
        labs.record(row, value=10.0, low=11.0, high=14.0)
        labs.record(row, value=None, low=11.0, high=14.0)
        lab["db"].session.commit()

    state = _state(lab, order)
    assert state["value"] is None
    assert state["low"] is None and state["high"] is None


def test_clearing_the_result_does_not_send_anybody_back_to_the_bed(lab):
    """It falls back to where the *sample* says it is. The blood was still
    drawn, and sending a nurse to draw it again because a number was typed and
    deleted is how a ward stops trusting the screen."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, order)
        labs.collect(row)
        labs.record(row, value=10.0)
        labs.record(row, value=None, text="")
        lab["db"].session.commit()

    assert _state(lab, order)["status"] == "collected"


def test_the_visit_screen_and_the_bench_write_the_same_way(lab):
    """One door. The doctor typing in what a paper report said and the bench
    writing what it measured are the same act, and they were two copies of
    it — the half that drifts decides whether the order counts as finished."""
    order = _order(lab)
    client = lab["sign_in"]("doc")

    client.post(f"/visits/investigations/{order}/result",
                data={"result_value": "12.1", "result_unit": "g/dL"},
                follow_redirects=True)

    state = _state(lab, order)
    assert state["status"] == "resulted"
    assert state["value"] == 12.1
    # And it says who wrote it, which the visit screen never recorded.
    assert state["resulted_by"] == lab["ids"]["doctor"]


def test_a_report_with_no_number_still_finishes_the_order(lab):
    """A culture and a film are not numbers and never will be."""
    order = _order(lab)
    lab["sign_in"]("boss").post(
        f"/labs/order/{order}/result",
        data={"result_text": "مفيش نمو بعد ٤٨ ساعة"}, follow_redirects=True)

    assert _state(lab, order)["status"] == "resulted"


# ============================ the money =====================================
def test_charging_starts_at_the_draw_not_at_the_order(lab):
    """An order somebody wrote and thought better of costs nothing; the clinic
    has spent something the moment the sample exists."""
    from app.models import VisitInvestigation
    from app.utils import labs

    ordered = _order(lab)
    with lab["app"].app_context():
        assert labs.unbilled(patient_id=lab["ids"]["child"]) == []
        labs.collect(lab["db"].session.get(VisitInvestigation, ordered))
        lab["db"].session.commit()
        assert [r.id for r in
                labs.unbilled(patient_id=lab["ids"]["child"])] == [ordered]


def test_a_test_nobody_priced_never_reaches_a_bill(lab):
    """The price is the switch — how a hospital that does not bill its lab
    separately says so, with no setting for it."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab, test="urine", name="تحليل بول")
    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, order))
        lab["db"].session.commit()
        assert labs.unbilled(patient_id=lab["ids"]["child"]) == []


def test_a_drawn_test_is_offered_at_the_desk(lab):
    """The outpatient half of the bill. Without it the bench ran and the money
    never moved."""
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, order))
        lab["db"].session.commit()

    page = lab["sign_in"]("boss").get(f"/finance/collect/{lab['ids']['child']}")

    assert f'"test_id": {order}'.encode() in page.data
    # And the screen carries it into the form it submits — the checkout
    # rebuilds every line from a fixed list of fields.
    assert b"test_id:l.test_id" in page.data


def test_collecting_stamps_the_test_so_it_never_comes_back(lab):
    from app.models import VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, order))
        lab["db"].session.commit()

    client = lab["sign_in"]("boss")
    client.post(f"/finance/collect/{lab['ids']['child']}", data={
        "doctor_id": lab["ids"]["doctor"], "discount_id": "none",
        "line_service_id": [str(lab["cbc_service"])],
        "line_desc": ["صورة دم كاملة"], "line_price": ["150"],
        "line_qty": ["1"], "line_no_commission": ["0"], "line_brand_id": [""],
        "line_dose_id": [""], "line_dose_number": [""], "line_vs_id": [""],
        "line_op_id": [""], "line_test_id": [str(order)],
    }, follow_redirects=True)

    assert _state(lab, order)["billed"]
    again = client.get(f"/finance/collect/{lab['ids']['child']}")
    assert b'"test_id"' not in again.data


def test_the_desk_says_nothing_about_the_lab_when_the_module_is_off(lab):
    """A module off is a module absent, on the busiest screen in the clinic."""
    from app.models import Setting, VisitInvestigation
    from app.utils import labs

    order = _order(lab)
    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, order))
        Setting.set("mod_enabled:labs", "0")
        lab["db"].session.commit()

    page = lab["sign_in"]("boss").get(f"/finance/collect/{lab['ids']['child']}")

    assert page.status_code == 200
    assert b'"test_id"' not in page.data


# ============================ the doors =====================================
def test_the_module_off_means_the_bench_is_absent(lab):
    """A clinic that sends its tests out has no bench — and ordering from the
    visit screen has never depended on this module."""
    from app.models import Setting

    with lab["app"].app_context():
        Setting.set("mod_enabled:labs", "0")
        lab["db"].session.commit()

    client = lab["sign_in"]("boss")
    assert client.get("/labs/").status_code == 404
    assert client.get("/labs/tests").status_code == 404


def test_the_rack_shows_both_jobs_and_how_long_each_has_waited(lab):
    from app.models import VisitInvestigation
    from app.utils import labs

    _order(lab, minutes_ago=90)
    drawn = _order(lab, name="تحليل بول", test="urine", minutes_ago=20)
    with lab["app"].app_context():
        labs.collect(lab["db"].session.get(VisitInvestigation, drawn))
        lab["db"].session.commit()

    page = lab["sign_in"]("boss").get("/labs/")

    assert b'data-count="to_collect"' in page.data
    assert b"data-needs-sample" in page.data
    assert b"data-sample" in page.data
    assert b"data-waited" in page.data


def test_a_test_is_added_to_the_list_from_the_screen(lab):
    """From the screen, never from a release — the same argument that put the
    wards and the incubators on a settings page."""
    from app.models import Investigation

    lab["sign_in"]("boss").post("/labs/tests/add", data={
        "name_ar": "وظائف كبد", "kind": "lab", "unit": "U/L",
        "sample_type": "دم", "service_id": lab["cbc_service"]},
        follow_redirects=True)

    with lab["app"].app_context():
        row = Investigation.query.filter_by(name_ar="وظائف كبد").one()
        assert row.service_id == lab["cbc_service"]
        assert row.sample_type == "دم"


def test_a_clinic_can_stop_charging_for_a_test(lab):
    """An empty price box means nobody, not "leave it as it was" — a clinic
    that stops billing a test has to be able to say so."""
    from app.models import Investigation

    lab["sign_in"]("boss").post(f"/labs/tests/{lab['cbc']}", data={
        "name_ar": "صورة دم", "unit": "g/dL", "service_id": "",
        "is_active": "1"}, follow_redirects=True)

    with lab["app"].app_context():
        assert lab["db"].session.get(Investigation, lab["cbc"]).service_id is None


def test_the_test_list_is_the_owners(lab):
    """It decides what things cost."""
    assert lab["sign_in"]("doc").get("/labs/tests").status_code == 403
