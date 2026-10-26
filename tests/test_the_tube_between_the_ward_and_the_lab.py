"""The tube between the ward and the lab — LAB_GLAB360_PLAN.md م-٣.

*«أماكن سحب العينات: في المعمل، أو الحضانة، أو العناية المركزة، أو في
الطوارئ غرفة الإجراءات، أو في الداخلي»* — the owner's list.

The program knew when a tube was drawn and when the lab received it, and
nothing between: a tube lost on the way looked exactly like one nobody had
drawn. Now: where it was drawn (guessed from where the child is), the tubes
drawn outside the lab sent as a numbered batch with a list, the lab's door
marking each arrived, what never arrived shown — late after half an hour —
and every step of a tube's journey on its order. A clinic with the lab alone
sees none of it.
"""
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _admit, _order, lab  # noqa: E402,F401


def _in_bed(lab, minutes_ago=0):
    """An order for the child in the ward bed, as the stay screen writes it."""
    from app.models import VisitInvestigation

    stay = _admit(lab)
    oid = _order(lab, minutes_ago=minutes_ago)
    with lab["app"].app_context():
        lab["db"].session.get(VisitInvestigation, oid).admission_id = stay
        lab["db"].session.commit()
    return oid


def _row(lab, oid):
    from app.models import VisitInvestigation

    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, oid)
        return {"where": row.collected_where, "code": row.sample_code,
                "received": row.received_at is not None, "status": row.status}


def _draw(c, oid, **form):
    return c.post(f"/labs/order/{oid}/collect", data=form)


def test_a_clinic_with_the_lab_alone_sees_no_place_and_no_batch(lab):
    from app.models import Setting

    with lab["app"].app_context():
        Setting.set("mod_enabled:ward", "0")
        lab["db"].session.commit()
    oid = _order(lab)
    c = lab["sign_in"]("boss")
    page = c.get(f"/labs/order/{oid}").get_data(as_text=True)
    assert "data-draw-place" not in page and "data-to-transfer" not in page
    assert c.get("/labs/transfer").status_code == 404
    _draw(c, oid)
    assert _row(lab, oid)["where"] is None          # the lab's, as always
    assert "data-journey" in c.get(f"/labs/order/{oid}").get_data(as_text=True)


def test_where_it_was_drawn_is_guessed_from_the_childs_bed(lab):
    from app.utils import lab_transfer

    oid = _in_bed(lab)
    c = lab["sign_in"]("boss")
    page = c.get(f"/labs/order/{oid}").get_data(as_text=True)
    box = page[page.index("data-draw-place"):]
    box = box[:box.index("</select>")]
    assert re.search(r'value="ward" selected', box)
    # The departments that are off are not offered.
    assert 'value="nicu"' not in box and 'value="lab"' in box
    _draw(c, oid)
    assert _row(lab, oid)["where"] == "ward"
    # A word that is not a place here is the guess, not stored as typed.
    other = _order(lab)
    _draw(c, other, where="nicu")
    assert _row(lab, other)["where"] == "lab"
    with lab["app"].app_context():
        from app.models import Setting

        Setting.set("mod_enabled:nicu", "1")
        lab["db"].session.commit()
        assert lab_transfer.available() == ["lab", "nicu", "ward"]


def test_tubes_drawn_in_the_ward_go_as_one_batch_with_a_list(lab):
    c = lab["sign_in"]("boss")
    one, two, here = _in_bed(lab), _order(lab), _order(lab)
    _draw(c, one)
    _draw(c, two, where="ward")
    _draw(c, here, where="lab")                     # drawn at the lab: nothing to send
    page = c.get("/labs/transfer").get_data(as_text=True)
    assert f'data-waiting-tube="{one}"' in page and f'data-waiting-tube="{two}"' in page
    assert f'data-waiting-tube="{here}"' not in page
    assert 'data-in-transit' in page                 # the lab's bar counts them
    reply = c.post("/labs/transfer/send", data={"place": "ward", "order": [one, two]})
    assert reply.status_code == 302 and "/labs/transfer/T" in reply.headers["Location"]
    manifest = c.get(reply.headers["Location"]).get_data(as_text=True)
    assert f'data-manifest-tube="{one}"' in manifest and 'data-arrived="no"' in manifest
    assert _row(lab, one)["code"] in manifest
    page = c.get("/labs/transfer").get_data(as_text=True)
    assert "data-waiting-tube" not in page           # nothing left to send
    assert 'data-missing="2"' in page and "data-batch-late" not in page


def test_the_lab_door_marks_each_tube_arrived(lab):
    from app.models import SampleBatchItem

    c = lab["sign_in"]("boss")
    oid = _in_bed(lab)
    _draw(c, oid)
    c.post("/labs/transfer/send", data={"place": "ward", "order": [oid]})
    code = _row(lab, oid)["code"]
    c.get(f"/labs/scan?code={code}&receive=1")
    assert _row(lab, oid)["received"]
    with lab["app"].app_context():
        item = SampleBatchItem.query.one()
        assert item.outcome == "received" and item.arrived_at is not None
        batch = item.batch.code
    assert "data-batch-complete" in c.get(f"/labs/transfer/{batch}").get_data(as_text=True)
    assert "data-nothing-on-the-way" in c.get("/labs/transfer").get_data(as_text=True)


def test_a_refused_tube_arrived_and_its_redraw_goes_on_a_new_batch(lab):
    from app.models import SampleBatchItem

    c = lab["sign_in"]("boss")
    oid = _in_bed(lab)
    _draw(c, oid)
    c.post("/labs/transfer/send", data={"place": "ward", "order": [oid]})
    first = _row(lab, oid)["code"]
    c.post(f"/labs/order/{oid}/reject", data={"reason_text": "متجلطة", "told_to": "تمريض الداخلي"})
    with lab["app"].app_context():
        assert SampleBatchItem.query.one().outcome == "rejected"
    assert _row(lab, oid)["where"] is None
    _draw(c, oid)                                   # drawn again at the bed
    second = _row(lab, oid)["code"]
    assert second != first
    page = c.get("/labs/transfer").get_data(as_text=True)
    assert f'data-waiting-tube="{oid}"' in page     # the new tube waits to leave
    journey = c.get(f"/labs/order/{oid}").get_data(as_text=True)
    assert 'data-step="refused"' in journey and journey.count('data-step="drawn"') == 2


def test_a_tube_that_never_arrived_is_shown_and_late_after_half_an_hour(lab):
    from app.models import SampleBatch
    from app.utils import lab_transfer

    c = lab["sign_in"]("boss")
    oid = _in_bed(lab)
    _draw(c, oid)
    c.post("/labs/transfer/send", data={"place": "ward", "order": [oid]})
    with lab["app"].app_context():
        batch = SampleBatch.query.one()
        batch.sent_at = datetime.utcnow() - timedelta(minutes=lab_transfer.LATE_MINUTES + 15)
        lab["db"].session.commit()
    page = c.get("/labs/transfer").get_data(as_text=True)
    assert "data-batch-late" in page and f'data-missing-tube="{oid}"' in page
    journey = c.get(f"/labs/order/{oid}").get_data(as_text=True)
    assert 'data-step="on_the_way"' in journey


def test_the_journey_says_each_step_who_and_how_long(lab):
    from app.models import SampleBatch, VisitInvestigation

    c = lab["sign_in"]("boss")
    oid = _in_bed(lab, minutes_ago=50)
    _draw(c, oid)
    c.post("/labs/transfer/send", data={"place": "ward", "order": [oid]})
    with lab["app"].app_context():
        row = lab["db"].session.get(VisitInvestigation, oid)
        row.collected_at = datetime.utcnow() - timedelta(minutes=40)
        SampleBatch.query.one().sent_at = datetime.utcnow() - timedelta(minutes=30)
        lab["db"].session.commit()
    c.get(f"/labs/scan?code={_row(lab, oid)['code']}&receive=1")
    page = c.get(f"/labs/order/{oid}").get_data(as_text=True)
    steps = re.findall(r'data-step="(\w+)"', page)
    assert steps[:4] == ["ordered", "drawn", "sent", "received"]
    drawn = page[page.index('data-step="drawn"'):]
    assert "الداخلي" in drawn[:drawn.index("</li>")]
    sent = page[page.index('data-step="sent"'):]
    assert "+10" in sent[:sent.index("</li>")]      # drawn → sent: ten minutes


def test_sending_refuses_a_place_that_is_off_and_an_empty_tick(lab):
    c = lab["sign_in"]("boss")
    oid = _in_bed(lab)
    _draw(c, oid)
    for form in ({"place": "nicu", "order": [oid]}, {"place": "lab", "order": [oid]},
                 {"place": "ward"}):
        reply = c.post("/labs/transfer/send", data=form)
        assert reply.headers["Location"].endswith("/labs/transfer")
    assert f'data-waiting-tube="{oid}"' in c.get("/labs/transfer").get_data(as_text=True)


def test_turnaround_says_where_the_time_went_by_place(lab):
    from app.models import VisitInvestigation
    from app.utils import lab_transfer
    from app.utils.clock import local_today

    c = lab["sign_in"]("boss")
    ward, here = _in_bed(lab), _order(lab)
    now = datetime.utcnow()
    with lab["app"].app_context():
        for oid, where, drawn, door in ((ward, "ward", 90, 50), (here, None, 30, 25)):
            row = lab["db"].session.get(VisitInvestigation, oid)
            row.collected_at = now - timedelta(minutes=drawn)
            row.received_at = now - timedelta(minutes=door)
            row.resulted_at = now - timedelta(minutes=5)
            row.collected_where, row.status = where, "resulted"
        lab["db"].session.commit()
        report = {e["place"]: e for e in lab_transfer.place_report(local_today(), local_today())}
    assert report["ward"]["to_lab"] == 40 and report["ward"]["at_lab"] == 45
    assert report["lab"]["to_lab"] == 5
    page = c.get("/labs/turnaround").get_data(as_text=True)
    assert 'data-place-row="ward"' in page and 'data-place-row="lab"' in page
