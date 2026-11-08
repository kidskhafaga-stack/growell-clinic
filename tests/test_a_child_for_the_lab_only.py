"""A child who comes to the laboratory only — LAB_GLAB360_PLAN.md م-٦.

*«مريض جاي للمعمل بس»*: a paper from a doctor outside, no consultation here.
Reviewed first: every order sat on a visit, and the only visits were a
doctor's, so this child could not be put on the rack at all. Now:

* «مريض جاي للمعمل بس» on the lab's screen: the child, the outside doctor, a
  photo of the paper, and the tests;
* the tests are on the rack like any order, and the order says whose paper;
* the outside doctor is kept in the clinic's book, so the result can go back
  to them from the order (م-٤);
* it is nobody's consultation: the encounter is ``channel="lab"``, completed,
  and on no doctor's queue.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01"
       b"\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _post(lab, **extra):
    data = {"patient_id": lab["ids"]["child"], "doctor_name": "د. سامي عادل",
            "doctor_specialty": "أطفال", "doctor_place": "عيادة المعادي",
            "doctor_phone": "01001234567", "test_id": [lab["cbc"], lab["urine"]],
            "notes": "صايم"}
    data.update(extra)
    return lab["sign_in"]("boss").post("/labs/walk-in", data=data,
                                       content_type="multipart/form-data",
                                       follow_redirects=True)


def test_the_door_is_on_the_lab_screen(lab):
    page = lab["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-walkin-door" in page and "/labs/walk-in" in page
    form = lab["sign_in"]("boss").get("/labs/walk-in").get_data(as_text=True)
    assert "data-walkin-form" in form and "صورة دم" in form


def test_the_child_goes_on_the_rack_on_the_outside_doctor_s_paper(lab):
    from app.models import ExternalDoctor, PatientAttachment, Visit, VisitInvestigation

    r = _post(lab, paper=(io.BytesIO(PNG), "request.png"))
    assert r.status_code == 200 and "data-walkin-done" in r.get_data(as_text=True)
    with lab["app"].app_context():
        visit = Visit.query.filter_by(channel="lab").one()
        assert visit.status == "completed", "it is nobody's consultation"
        doc = lab["db"].session.get(ExternalDoctor, visit.outside_doctor_id)
        assert doc.name == "د. سامي عادل" and doc.phone == "01001234567"
        orders = VisitInvestigation.query.filter_by(visit_id=visit.id).all()
        assert sorted(o.investigation_id for o in orders) == sorted([lab["cbc"], lab["urine"]])
        assert all(o.status == "requested" and not o.done_outside for o in orders)
        att = PatientAttachment.query.filter_by(visit_id=visit.id).one()
        assert att.patient_id == lab["ids"]["child"]
        order_id = orders[0].id
    rack = lab["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert f"/labs/order/{order_id}" in rack, "on the bench's list like any order"
    page = lab["sign_in"]("boss").get(f"/labs/order/{order_id}").get_data(as_text=True)
    assert "data-outside-doctor" in page and "سامي عادل" in page


def test_the_same_doctor_is_kept_once(lab):
    from app.models import ExternalDoctor

    _post(lab)
    _post(lab, test_id=[lab["cbc"]])
    with lab["app"].app_context():
        assert ExternalDoctor.query.filter_by(name="د. سامي عادل").count() == 1


def test_what_is_missing_is_said(lab):
    from app.models import Visit

    for missing, word in (({"doctor_name": ""}, "اسم الدكتور"),
                          ({"test_id": []}, "تحليل واحد"),
                          ({"patient_id": ""}, "اختار الطفل")):
        r = _post(lab, **missing)
        assert r.status_code == 400 and word in r.get_data(as_text=True)
    with lab["app"].app_context():
        assert Visit.query.filter_by(channel="lab").count() == 0


def test_a_file_that_is_not_a_picture_is_refused(lab):
    from app.models import Visit

    r = _post(lab, paper=(io.BytesIO(b"MZ\x90\x00not a picture"), "x.exe"))
    assert r.status_code == 400
    with lab["app"].app_context():
        assert Visit.query.filter_by(channel="lab").count() == 0


def test_it_is_on_no_doctor_s_queue(lab):
    """The encounter is completed the moment it is written: the doctors' open
    visits are what they were."""
    from app.models import Visit

    with lab["app"].app_context():
        before = Visit.query.filter_by(status="open").count()
    _post(lab)
    with lab["app"].app_context():
        assert Visit.query.filter_by(status="open").count() == before
