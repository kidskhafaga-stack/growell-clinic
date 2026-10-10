"""A lab result reviewed, released and printed — GAHAR DAS.20.

Step two of the laboratory plan:

* **(ب) reviewing, verifying and reporting by authorized staff** — off until
  the hospital switches it on; on, a result still reaches the doctor at once
  but says «not verified yet» until somebody holding ``lab_release``
  releases it, and a result typed again is unverified again;
* **(أ) the final report** — the laboratory, the child, each test with its
  specimen, collection and reporting times, the values against their
  reference, the ordering doctor, who released it, and the comment; a
  result not yet released prints as preliminary;
* the report is read by the lab and by whoever treats the child, not by the
  front desk, and never mixes two children.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_the_sample_nobody_drew import _order, lab  # noqa: E402,F401


def _row(c, order_id):
    from app.models import VisitInvestigation

    return c["db"].session.get(VisitInvestigation, order_id)


def _resulted(c, value="11.2", **extra):
    from app.utils import labs

    order = _order(c)
    with c["app"].app_context():
        labs.collect(_row(c, order))
        c["db"].session.commit()
    c["sign_in"]("boss").post(f"/labs/order/{order}/result",
                              data={"result_value": value, "result_unit": "g/dL",
                                    "result_low": "11", "result_high": "14.5", **extra})
    return order


def _switch(c, on=True):
    c["sign_in"]("boss").post("/labs/verify-setting", data={"required": "1"} if on else {})


def test_off_a_result_is_final_as_written(lab):
    order = _resulted(lab)
    with lab["app"].app_context():
        assert _row(lab, order).awaiting_verification is False
    boss = lab["sign_in"]("boss")
    assert "data-to-verify" not in boss.get("/labs/").get_data(as_text=True)
    page = boss.get(f"/labs/report?ids={order}").get_data(as_text=True)
    assert "data-report-preliminary" not in page and "data-lab-report-page" in page


def test_on_a_result_says_so_until_somebody_authorized_releases_it(lab):
    _switch(lab)
    order = _resulted(lab)
    boss = lab["sign_in"]("boss")
    with lab["app"].app_context():
        assert _row(lab, order).awaiting_verification is True
    visit = boss.get(f"/visits/{lab['ids']['visit']}/record").get_data(as_text=True)
    assert "data-unverified" in visit and "data-lab-report" in visit
    assert "data-to-verify" in boss.get("/labs/").get_data(as_text=True)
    assert f'data-verify-row="{order}"' in boss.get("/labs/verify").get_data(as_text=True)
    assert "data-report-preliminary" in boss.get(f"/labs/report?ids={order}").get_data(as_text=True)

    # A doctor who reads results does not thereby release them.
    lab["sign_in"]("doc").post(f"/labs/order/{order}/verify")
    with lab["app"].app_context():
        assert _row(lab, order).verified_at is None

    boss.post(f"/labs/order/{order}/verify")
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.verified_by == lab["ids"]["admin"] and not row.awaiting_verification
    page = boss.get(f"/labs/report?ids={order}").get_data(as_text=True)
    assert "data-report-verified" in page and "data-report-preliminary" not in page


def test_whoever_the_hospital_grants_it_to_may_release(lab):
    from app.models import UserCapability
    from app.models.permissions import CAPABILITIES

    assert "lab_release" in CAPABILITIES
    _switch(lab)
    order = _resulted(lab)
    with lab["app"].app_context():
        lab["db"].session.add(UserCapability(user_id=lab["ids"]["doctor"],
                                             capability="lab_release"))
        lab["db"].session.commit()
    lab["sign_in"]("doc").post(f"/labs/order/{order}/verify")
    with lab["app"].app_context():
        assert _row(lab, order).verified_by == lab["ids"]["doctor"]


def test_a_result_typed_again_is_unverified_again(lab):
    _switch(lab)
    order = _resulted(lab)
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/order/{order}/verify")
    boss.post(f"/labs/order/{order}/result",
              data={"result_value": "9.1", "result_unit": "g/dL"})
    with lab["app"].app_context():
        row = _row(lab, order)
        assert row.verified_at is None and row.awaiting_verification


def test_the_report_carries_what_the_standard_lists(lab):
    order = _resulted(lab, result_text="عينة متجلّطة جزئياً")
    with lab["app"].app_context():
        row = _row(lab, order)
        row.result_comment = "يُعاد بعد أسبوع"
        row.ordered_by = lab["ids"]["doctor"]
        lab["db"].session.commit()
        number = row.patient.patient_number
    page = lab["sign_in"]("boss").get(f"/labs/report?ids={order}").get_data(as_text=True)
    for piece in (str(number), "د. أحمد", "دم", "11.2", "11 – 14.5",
                  "يُعاد بعد أسبوع", "data-report-comment"):
        assert piece in page, piece


def test_the_report_is_for_those_who_treat_the_child_and_one_child_only(lab):
    from app.models import Patient, Visit, VisitInvestigation

    order = _resulted(lab)
    assert lab["sign_in"]("desk").get(f"/labs/report?ids={order}").status_code == 403
    assert lab["sign_in"]("doc").get(f"/labs/report?ids={order}").status_code == 200
    with lab["app"].app_context():
        db = lab["db"]
        other = Patient(patient_number="P2", full_name="سارة", gender="female",
                        date_of_birth=date(2024, 5, 1), is_active=True)
        db.session.add(other)
        db.session.flush()
        visit = Visit(patient_id=other.id, doctor_id=lab["ids"]["doctor"])
        db.session.add(visit)
        db.session.flush()
        theirs = VisitInvestigation(visit_id=visit.id, patient_id=other.id, kind="lab",
                                    name="سكر", status="resulted", result_text="90")
        db.session.add(theirs)
        db.session.commit()
        theirs_id = theirs.id
    page = lab["sign_in"]("boss").get(f"/labs/report?ids={order},{theirs_id}").get_data(as_text=True)
    assert f'data-report-row="{order}"' in page and f'data-report-row="{theirs_id}"' not in page


def test_only_whoever_builds_the_lists_switches_release_on(lab):
    from app.utils import lab_release

    lab["sign_in"]("doc").post("/labs/verify-setting", data={"required": "1"})
    with lab["app"].app_context():
        assert lab_release.required() is False
    page = lab["sign_in"]("boss").get("/labs/settings").get_data(as_text=True)
    assert "data-verify-setting" in page
