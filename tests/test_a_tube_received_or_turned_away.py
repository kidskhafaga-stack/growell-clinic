"""A tube marked urgent, received at the lab, or turned away — GAHAR DAS.14,
DAS.15 and DAS.22.

Step one of the laboratory plan, from the chapter's own words:

* **DAS.14 (أ)** — the request carries «special marking for urgent tests»;
  one box where the test is ordered, ticked by itself for a child the
  emergency triage called urgent;
* **DAS.22** — an urgent tube is first on the rack and held to the test's
  STAT time, which the catalogue had and no order could use;
* **DAS.15 (ب-١/٣)** — an accepted tube is recorded with when it reached the
  lab and who received it, and a suboptimal one accepted anyway says why;
  a tray is received by scanning it;
* **DAS.15 (ب-٢)** — a refused tube is kept with its cause, time, the person
  refusing it and the person told; the order goes back to be drawn, and the
  new tube never shares the refused one's number;
* the reasons are the laboratory's own list, empty until it writes it;
* nothing changes for a lab that never presses «received».
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _collect(c, order_id):
    from app.utils import labs

    with c["app"].app_context():
        labs.collect(_row(c, order_id))
        c["db"].session.commit()
        return _row(c, order_id).sample_code


# --------------------------------------------------------------- urgent --
def test_the_doctor_marks_a_test_urgent_with_one_box(lab):
    from app.models import VisitInvestigation

    doc = lab["sign_in"]("doc")
    visit = lab["ids"]["visit"]
    doc.post(f"/visits/{visit}/investigations",
             data={"investigation_id": lab["cbc"], "kind": "lab", "urgent": "1"})
    doc.post(f"/visits/{visit}/investigations",
             data={"investigation_id": lab["urine"], "kind": "lab"})
    with lab["app"].app_context():
        rows = VisitInvestigation.query.order_by(VisitInvestigation.id).all()
        assert [(r.name, r.urgent) for r in rows] == [("صورة دم", True), ("تحليل بول", None)]
    page = doc.get(f"/visits/{visit}/record").get_data(as_text=True)
    assert "data-inv-urgent" in page


def test_urgent_is_first_on_the_rack_and_held_to_the_stat_time(lab):
    from app.models import Investigation
    from app.utils import lab_results, labs

    old = _order(lab, minutes_ago=90)
    stat = _order(lab, name="تحليل بول", test="urine", minutes_ago=5)
    with lab["app"].app_context():
        db = lab["db"]
        _row(lab, stat).urgent = True
        inv = db.session.get(Investigation, lab["urine"])
        inv.tat_max, inv.tat_stat_max = 240, 30
        db.session.commit()
        assert [r.id for r in labs.worklist()] == [stat, old]
        assert labs.urgent_count() == 1
        row = _row(lab, stat)
        labs.collect(row, at=datetime.utcnow() - timedelta(minutes=45))
        assert lab_results.late(row) is True, "an urgent tube is held to its STAT time"
        row.urgent = None
        assert lab_results.late(row) is False, "the routine time for a routine tube"
    page = lab["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-urgent-open" in page


def test_a_child_triaged_urgent_has_urgent_tubes_without_a_word(lab):
    from app.models import Patient, Setting, User
    from app.utils import emergency as util
    from app.utils import emergency_orders as eo

    with lab["app"].app_context():
        db = lab["db"]
        Setting.set("mod_enabled:emergency", "1")
        att = util.arrive(db.session.get(Patient, lab["ids"]["child"]))
        db.session.flush()
        util.triage(att, level="أحمر", urgent=True)
        doctor = db.session.get(User, lab["ids"]["doctor"])
        assert eo.order_test(att, doctor, name="غازات الدم").urgent is True
        assert eo.order_test(att, doctor, name="صورة دم", urgent=False).urgent is None
        util.triage(att, level="أخضر", urgent=False)
        assert eo.order_test(att, doctor, name="سكر").urgent is None


# ------------------------------------------------------------- received --
def test_a_tube_received_keeps_its_first_time_and_a_note(lab):
    order = _order(lab)
    _collect(lab, order)
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/receive", data={})
    with lab["app"].app_context():
        first = _row(lab, order).received_at
        assert first is not None and _row(lab, order).received_by == lab["ids"]["admin"]
    boss.post(f"/labs/order/{order}/receive", data={"note": "كمية قليلة — اتقبلت للمستعجل"})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.received_at == first and row.received_note.startswith("كمية قليلة")
    page = boss.get(f"/labs/order/{order}").get_data(as_text=True)
    assert "data-received-note" in page


def test_a_tray_is_received_by_scanning_it(lab):
    order = _order(lab)
    code = _collect(lab, order)
    boss = lab["sign_in"]("boss")
    answer = boss.get(f"/labs/scan?code={code}&receive=1")
    assert "receive=1" in answer.headers["Location"]
    with lab["app"].app_context():
        assert _row(lab, order).received_at is not None
    assert "data-scan-receive" in boss.get("/labs/?receive=1").get_data(as_text=True)


def test_a_result_is_saved_whether_or_not_anyone_pressed_received(lab):
    order = _order(lab)
    _collect(lab, order)
    lab["sign_in"]("boss").post(f"/labs/order/{order}/result",
                                data={"result_value": "11.2", "result_unit": "g/dL"})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.status == "resulted" and row.received_at is None


# -------------------------------------------------------------- refused --
def test_a_refused_tube_is_kept_and_the_order_goes_back_to_be_drawn(lab):
    from app.models import SampleRejection
    from app.utils import labs

    order = _order(lab)
    code = _collect(lab, order)
    boss = lab["sign_in"]("boss")
    # No reason, or nobody told: refused.
    boss.post(f"/labs/order/{order}/reject", data={"told_to": "تمريض الداخلي"})
    boss.post(f"/labs/order/{order}/reject", data={"reason_text": "متجلّطة"})
    with lab["app"].app_context():
        assert SampleRejection.query.count() == 0 and _row(lab, order).status == "collected"
    boss.post(f"/labs/order/{order}/reject",
              data={"reason_text": "متجلّطة", "told_to": "تمريض الداخلي"})
    with lab["app"].app_context():
        refused = SampleRejection.query.one()
        assert (refused.sample_code, refused.reason_text, refused.told_to,
                refused.rejected_by) == (code, "متجلّطة", "تمريض الداخلي", lab["ids"]["admin"])
        assert refused.collected_at is not None
        row = _row(lab, order)
        assert (row.status, row.sample_code, row.collected_at) == ("requested", None, None)
        again = labs.label_code(row)
        assert again != code and again.endswith("-2")
    rack = boss.get("/labs/").get_data(as_text=True)
    assert "data-refused" in rack and "متجلّطة" in rack
    register = boss.get("/labs/rejections").get_data(as_text=True)
    assert f'data-refused-row="{refused.id}"' in register


def test_the_reasons_are_the_lab_s_own_list(lab):
    from app.models import Lookup, SampleRejection
    from app.utils import lab_reception

    boss = lab["sign_in"]("boss")
    page = boss.get("/labs/settings").get_data(as_text=True)
    assert "data-reject-reasons" in page and "data-no-reasons" in page
    boss.post("/labs/reject-reasons", data={"name": "عينة متكسّرة الدم"})
    with lab["app"].app_context():
        reason = Lookup.query.filter_by(domain=lab_reception.REASONS_DOMAIN).one()
        key, reason_id = reason.key, reason.id
    order = _order(lab)
    _collect(lab, order)
    assert f'value="{key}"' in boss.get(f"/labs/order/{order}").get_data(as_text=True)
    boss.post(f"/labs/order/{order}/reject", data={"reason_key": key, "told_to": "د. أحمد"})
    boss.post(f"/labs/reject-reasons/{reason_id}/retire")
    with lab["app"].app_context():
        refused = SampleRejection.query.one()
        assert refused.reason_key == key
        assert lab_reception.reason_label(refused) == "عينة متكسّرة الدم", \
            "a retired reason is still named on the tube it refused"
        assert lab_reception.reasons() == []
    # Only whoever builds the lists writes this one.
    lab["sign_in"]("doc").post("/labs/reject-reasons", data={"name": "أي حاجة"})
    with lab["app"].app_context():
        assert Lookup.query.filter_by(domain=lab_reception.REASONS_DOMAIN).count() == 1


def test_a_resulted_or_undrawn_order_cannot_be_refused(lab):
    from app.models import SampleRejection

    undrawn = _order(lab)
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/order/{undrawn}/reject", data={"reason_text": "x", "told_to": "y"})
    done = _order(lab, name="تحليل بول", test="urine")
    _collect(lab, done)
    boss.post(f"/labs/order/{done}/result", data={"result_text": "سليم"})
    boss.post(f"/labs/order/{done}/reject", data={"reason_text": "x", "told_to": "y"})
    with lab["app"].app_context():
        assert SampleRejection.query.count() == 0
