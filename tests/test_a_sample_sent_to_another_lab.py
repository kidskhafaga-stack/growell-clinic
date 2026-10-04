"""A sample drawn here and sent to a referral laboratory — GAHAR DAS.13 and
DAS.15 (د).

Step three of the laboratory plan:

* **the referral laboratories** are the hospital's own list — accreditation
  as stated, the turnaround its agreement promises, the date the agreement
  runs to, the last evaluation — and a lapsing agreement says so;
* a test the lab sends out is **drawn here**, on the bench — not handed to
  the family the way a test the clinic does not do is;
* samples are **sent on a numbered batch** with a manifest to print; a sample
  sent by mistake is taken back;
* a sample is **late only against its laboratory's promise**, and it is
  **back** when its result is written;
* the **register** says what went where, what came back, what is late, and
  the turnaround each laboratory actually kept.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _referral(c, **extra):
    from app.models import ReferralLab

    data = {"name": "المعمل المرجعي", "accreditation": "ISO 15189",
            "tat_days": "3", **extra}
    c["sign_in"]("boss").post("/labs/referral-labs", data=data)
    with c["app"].app_context():
        return ReferralLab.query.order_by(ReferralLab.id.desc()).first().id


def _drawn(c, **kw):
    from app.utils import labs

    order = _order(c, **kw)
    with c["app"].app_context():
        labs.collect(_row(c, order))
        c["db"].session.commit()
    return order


def test_the_referral_laboratories_are_the_hospital_s_list(lab):
    from app.models import ReferralLab
    from app.utils import lab_sendout

    boss = lab["sign_in"]("boss")
    assert "data-no-referral-labs" in boss.get("/labs/referral-labs").get_data(as_text=True)
    soon = (date.today() + timedelta(days=10)).isoformat()
    ref = _referral(lab, agreement_until=soon)
    with lab["app"].app_context():
        row = lab["db"].session.get(ReferralLab, ref)
        assert (row.accreditation, row.tat_days, row.is_active) == ("ISO 15189", 3, True)
        assert lab_sendout.agreement_state(row) == "ending"
    page = boss.get("/labs/referral-labs").get_data(as_text=True)
    assert 'data-agreement="ending"' in page
    # Unticked, it is out of use; only whoever builds the lists edits it.
    boss.post(f"/labs/referral-labs/{ref}", data={"name": "المعمل المرجعي", "is_active": "0"})
    lab["sign_in"]("doc").post("/labs/referral-labs", data={"name": "معمل تاني"})
    with lab["app"].app_context():
        assert lab["db"].session.get(ReferralLab, ref).is_active is False
        assert ReferralLab.query.count() == 1


def test_a_test_sent_out_is_drawn_here_not_handed_to_the_family(lab):
    from app.models import Investigation, VisitInvestigation

    ref = _referral(lab)
    with lab["app"].app_context():
        inv = lab["db"].session.get(Investigation, lab["urine"])
        inv.in_house = False
        inv.referral_lab_id = ref
        lab["db"].session.commit()
    lab["sign_in"]("doc").post(f"/visits/{lab['ids']['visit']}/investigations",
                               data={"investigation_id": lab["urine"], "kind": "lab"})
    with lab["app"].app_context():
        row = VisitInvestigation.query.one()
        assert row.done_outside is False, "the lab draws it and ships it"
    assert "data-referral-lab" in lab["sign_in"]("boss").get("/labs/tests").get_data(as_text=True)


def test_samples_go_on_a_numbered_batch_with_a_manifest(lab):
    first = _drawn(lab)
    second = _drawn(lab, name="تحليل بول", test="urine")
    ref = _referral(lab)
    boss = lab["sign_in"]("boss")
    assert f'data-to-send-row="{first}"' in boss.get("/labs/send-out").get_data(as_text=True)
    answer = boss.post("/labs/send-out", data={"order_id": [str(first), str(second)],
                                                "lab_id": str(ref)})
    with lab["app"].app_context():
        a, b = _row(lab, first), _row(lab, second)
        assert a.sent_batch == b.sent_batch and a.sent_batch.startswith("SO-")
        assert (a.sent_lab_id, a.sent_by, a.status) == (ref, lab["ids"]["admin"], "collected")
        code = a.sent_batch
    assert code in answer.headers["Location"]
    manifest = boss.get(f"/labs/send-out/batch/{code}").get_data(as_text=True)
    assert f'data-manifest-row="{first}"' in manifest and f'data-manifest-row="{second}"' in manifest
    assert "data-sent" in boss.get("/labs/").get_data(as_text=True)
    # Sent once only; and an undrawn sample is not sent at all.
    boss.post("/labs/send-out", data={"order_id": str(first), "lab_id": str(ref)})
    undrawn = _order(lab)
    boss.post("/labs/send-out", data={"order_id": str(undrawn), "lab_id": str(ref)})
    with lab["app"].app_context():
        assert _row(lab, first).sent_batch == code and _row(lab, undrawn).sent_at is None


def test_late_only_against_its_lab_and_back_when_the_result_is_written(lab):
    from app.utils import lab_sendout

    order = _drawn(lab)
    ref = _referral(lab, tat_days="2")
    boss = lab["sign_in"]("boss")
    boss.post("/labs/send-out", data={"order_id": str(order), "lab_id": str(ref)})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert lab_sendout.late(row) is False
        row.sent_at = datetime.utcnow() - timedelta(days=3)
        lab["db"].session.commit()
        assert lab_sendout.late(_row(lab, order)) is True
    assert "data-sent-late" in boss.get(f"/labs/order/{order}").get_data(as_text=True)
    boss.post(f"/labs/order/{order}/result", data={"result_text": "سلبي"})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.returned_at is not None and lab_sendout.late(row) is None


def test_a_sample_sent_by_mistake_is_taken_back(lab):
    order = _drawn(lab)
    ref = _referral(lab)
    boss = lab["sign_in"]("boss")
    boss.post("/labs/send-out", data={"order_id": str(order), "lab_id": str(ref)})
    boss.post(f"/labs/order/{order}/recall")
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.sent_at is None and row.sent_batch is None and row.status == "collected"


def test_the_register_says_what_each_lab_kept(lab):
    first = _drawn(lab)
    second = _drawn(lab, name="تحليل بول", test="urine")
    ref = _referral(lab, tat_days="2")
    boss = lab["sign_in"]("boss")
    boss.post("/labs/send-out", data={"order_id": [str(first), str(second)], "lab_id": str(ref)})
    with lab["app"].app_context():
        a = _row(lab, first)
        a.sent_at = datetime.utcnow() - timedelta(days=4)
        lab["db"].session.commit()
    boss.post(f"/labs/order/{second}/result", data={"result_text": "سلبي"})
    page = boss.get("/labs/send-out/register").get_data(as_text=True)
    assert f'data-sent-row="{first}"' in page and f'data-sent-row="{second}"' in page
    from app.utils import lab_sendout
    from app.utils.clock import local_today

    with lab["app"].app_context():
        _rows, per_lab = lab_sendout.register(local_today() - timedelta(days=10), local_today())
        (entry,) = per_lab
        assert (entry["sent"], entry["back"], entry["late"]) == (2, 1, 1)
        assert entry["kept_days"] is not None
