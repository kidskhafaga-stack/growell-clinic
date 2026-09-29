"""Tests and scans ordered from the stay, and whose bill they land on.

Asked as *«ليه مش بتطلب من ملف الإقامة؟»*. What is held here:

* a stay with no visit gets exactly one encounter of its own — closed, on the
  ward, with no fee — and every order from the stay is written on it;
* an order from the stay carries the stay, reaches the lab's list, and is
  refused on a stay that has ended or with no name;
* the stay's bill takes its own orders and those at the visit it began from;
  the desk leaves the stay's own orders alone and nothing else moves — a
  clinic with no beds bills exactly as before;
* only the stay's «doctor's orders» right may order; the page shows the box
  to whoever holds it and the list to everybody.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_a_bed_bill_the_books_never_heard_of import (  # noqa: E402,F401
    _admit, _child, hospital)


def _catalogue(clinic, name="صورة دم كاملة", kind="lab", price=120,
               active=True, in_house=True):
    from app.models import Investigation, Service

    with clinic["app"].app_context():
        service = Service(name=f"تحليل {name}", category="lab", price=price,
                          is_active=True)
        clinic["db"].session.add(service)
        clinic["db"].session.flush()
        row = Investigation(name_ar=name, name_en="CBC" if kind == "lab" else None,
                            kind=kind, is_active=active, in_house=in_house,
                            service_id=service.id, sample_type="دم")
        clinic["db"].session.add(row)
        clinic["db"].session.commit()
        return row.id


def _order(clinic, stay_id, **form):
    return clinic["sign_in"]("doc").post(f"/beds/admission/{stay_id}/test",
                                         data=form)


def test_a_stay_with_no_visit_gets_one_encounter_of_its_own(hospital):
    from app.models import Admission, Visit, VisitInvestigation
    from app.utils import labs

    cbc = _catalogue(hospital)
    stay = _admit(hospital, _child(hospital, "بلا زيارة"))
    with hospital["app"].app_context():
        assert hospital["db"].session.get(Admission, stay).visit_id is None
        visits_before = Visit.query.count()
    reply = _order(hospital, stay, investigation_id=cbc, kind="lab")
    assert reply.status_code == 302 and "#tests" in reply.headers["Location"]
    _order(hospital, stay, name="وظائف كبد", kind="lab", notes="صائم")
    with hospital["app"].app_context():
        row = hospital["db"].session.get(Admission, stay)
        visit = hospital["db"].session.get(Visit, row.visit_id)
        assert (visit.channel, visit.status) == ("ward", "completed")
        assert visit.appointment_id is None
        orders = VisitInvestigation.query.order_by(VisitInvestigation.id).all()
        assert [(o.visit_id, o.admission_id) for o in orders] == [
            (visit.id, stay), (visit.id, stay)]
        assert orders[0].name == "صورة دم كاملة" and orders[1].request_notes == "صائم"
        assert Visit.query.count() == visits_before + 1
        # On the lab's own list, like any other order.
        assert {o.id for o in labs.worklist()} == {o.id for o in orders}
        encounter_id = visit.id
    # Said to be the stay's on the visit screen, not taken for a consultation.
    page = hospital["sign_in"]("doc").get(f"/visits/{encounter_id}").get_data(as_text=True)
    assert "data-ward-visit" in page


def test_a_stay_that_began_at_a_visit_orders_on_that_visit(hospital):
    from app.models import Admission, Visit, VisitInvestigation

    pid = _child(hospital, "من العيادة")
    with hospital["app"].app_context():
        visit = Visit(patient_id=pid, doctor_id=hospital["ids"]["doctor"])
        hospital["db"].session.add(visit)
        hospital["db"].session.commit()
        visit_id = visit.id
    stay = _admit(hospital, pid)
    with hospital["app"].app_context():
        hospital["db"].session.get(Admission, stay).visit_id = visit_id
        hospital["db"].session.commit()
        visits_before = Visit.query.count()
    _order(hospital, stay, name="أشعة صدر", kind="imaging", laterality="none")
    with hospital["app"].app_context():
        order = VisitInvestigation.query.one()
        assert (order.visit_id, order.admission_id, order.laterality) == (
            visit_id, stay, "none")
        assert Visit.query.count() == visits_before


def test_what_an_order_is_refused_for(hospital):
    from app.models import Admission, Role, User, VisitInvestigation

    stay = _admit(hospital, _child(hospital, "مرفوض"))
    _order(hospital, stay, name="  ", kind="lab")
    with hospital["app"].app_context():
        assert VisitInvestigation.query.count() == 0
        # A ward nurse has the beds and not the right to order.
        hospital["db"].session.add(Role(name="ward_nurse", label_ar="تمريض",
                                        modules="dashboard,beds", capabilities=""))
        nurse = User(username="nurse", full_name="ممرضة", role="ward_nurse",
                     is_active=True)
        nurse.set_password("secret")
        hospital["db"].session.add(nurse)
        hospital["db"].session.commit()
    nurse = hospital["sign_in"]("nurse")
    assert nurse.post(f"/beds/admission/{stay}/test",
                      data={"name": "صورة دم", "kind": "lab"}).status_code in (302, 403)
    page = nurse.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-stay-tests" in page and "data-order-test" not in page
    assert hospital["sign_in"]("desk").post(
        f"/beds/admission/{stay}/test",
        data={"name": "صورة دم", "kind": "lab"}).status_code in (302, 403, 404)
    with hospital["app"].app_context():
        assert VisitInvestigation.query.count() == 0
        hospital["db"].session.get(Admission, stay).discharged_at = datetime.utcnow()
        hospital["db"].session.commit()
    reply = _order(hospital, stay, name="صورة دم", kind="lab")
    assert reply.status_code == 302
    with hospital["app"].app_context():
        assert VisitInvestigation.query.count() == 0
    page = hospital["sign_in"]("doc").get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-order-test" not in page


def test_the_stay_page_lists_what_the_stay_owns_and_offers_the_box(hospital):
    from app.models import VisitInvestigation
    from app.utils import labs

    cbc = _catalogue(hospital)
    stay = _admit(hospital, _child(hospital, "الصفحة"))
    doc = hospital["sign_in"]("doc")
    page = doc.get(f"/beds/admission/{stay}").get_data(as_text=True)
    assert "data-order-test" in page and "data-stay-test=" not in page
    _order(hospital, stay, investigation_id=cbc, kind="lab")
    with hospital["app"].app_context():
        order = VisitInvestigation.query.one()
        order_id = order.id
    page = doc.get(f"/beds/admission/{stay}").get_data(as_text=True)
    row = page.split(f'data-stay-test="{order_id}"')[1].split("</li>")[0]
    assert "صورة دم كاملة" in row and 'data-test-state="requested"' in row
    assert "data-tests-waiting" in page
    with hospital["app"].app_context():
        labs.collect(hospital["db"].session.get(VisitInvestigation, order_id))
        hospital["db"].session.commit()
    row = doc.get(f"/beds/admission/{stay}").get_data(as_text=True).split(
        f'data-stay-test="{order_id}"')[1].split("</li>")[0]
    assert 'data-test-state="collected"' in row


def test_the_order_box_searches_the_catalogue(hospital):
    _catalogue(hospital, "صورة دم كاملة")
    _catalogue(hospital, "صورة دم قديمة", active=False)
    _catalogue(hospital, "صدر", kind="imaging", in_house=False)
    _catalogue(hospital, "صورة أشعة بطن", kind="imaging")
    doc = hospital["sign_in"]("doc")
    found = doc.get("/beds/investigation-search?q=صورة&kind=lab").get_json()
    assert [r["name"] for r in found] == ["صورة دم كاملة"]
    assert found[0]["sample"] == "دم" and found[0]["in_house"] is True
    scans = doc.get("/beds/investigation-search?q=صدر&kind=imaging").get_json()
    assert [(r["kind"], r["in_house"]) for r in scans] == [("imaging", False)]
    assert doc.get("/beds/investigation-search?q=ص").get_json() == []


def test_a_test_the_clinic_does_not_do_is_written_outside(hospital):
    from app.models import VisitInvestigation
    from app.utils import labs

    scan = _catalogue(hospital, "رنين", kind="imaging", in_house=False)
    stay = _admit(hospital, _child(hospital, "بره"))
    _order(hospital, stay, investigation_id=scan, kind="imaging",
           laterality="none")
    _order(hospital, stay, name="تحليل عادي", kind="lab", done_outside="1",
           outside_place="معمل بره")
    with hospital["app"].app_context():
        rows = VisitInvestigation.query.order_by(VisitInvestigation.id).all()
        assert [(r.done_outside, r.outside_place) for r in rows] == [
            (True, None), (True, "معمل بره")]
        assert labs.worklist(kind=None) == []


def test_the_stay_bills_its_own_orders_and_nothing_else_moves(hospital):
    """The stay's own orders go on the stay's bill and never the desk. What
    was ordered at a visit bills **exactly as it did before** — a running
    hospital's desk does not change under it."""
    from app.models import Visit, VisitInvestigation
    from app.models.admission import Admission
    from app.utils import bed_billing, labs

    cbc = _catalogue(hospital, price=120)
    pid = _child(hospital, "الفاتورة")
    with hospital["app"].app_context():
        db = hospital["db"]
        began = Visit(patient_id=pid, doctor_id=hospital["ids"]["doctor"])
        db.session.add(began)
        db.session.commit()
        began_id = began.id
    stay = _admit(hospital, pid, days_ago=2)
    with hospital["app"].app_context():
        db.session.get(Admission, stay).visit_id = began_id
        db.session.commit()
    _order(hospital, stay, investigation_id=cbc, kind="lab")
    with hospital["app"].app_context():
        from_stay = VisitInvestigation.query.one()
        mid = Visit(patient_id=pid, doctor_id=hospital["ids"]["doctor"])
        db.session.add(mid)
        db.session.flush()
        at_began = VisitInvestigation(visit_id=began_id, patient_id=pid,
                                      investigation_id=cbc, kind="lab",
                                      name="صورة دم كاملة")
        at_mid = VisitInvestigation(visit_id=mid.id, patient_id=pid,
                                    investigation_id=cbc, kind="lab",
                                    name="صورة دم كاملة")
        db.session.add_all([at_began, at_mid])
        db.session.flush()
        for row in (from_stay, at_began, at_mid):
            labs.collect(row)
        db.session.commit()
        ids = {"stay": from_stay.id, "began": at_began.id, "mid": at_mid.id}

        row = db.session.get(Admission, stay)
        assert {t.id for t in labs.unbilled(admission=row)} == {
            ids["stay"], ids["began"]}
        # The desk: everything it showed before, less the stay's own order.
        before = {t.id for t in labs.unbilled(patient_id=pid)}
        desk = {t.id for t in labs.unbilled(patient_id=pid, outside_stays=True)}
        assert before - desk == {ids["stay"]}
        assert desk == {ids["began"], ids["mid"]}
        assert {t.id for t in labs.unbilled(patient_ids=[pid],
                                            outside_stays=True)} == desk

        result = bed_billing.post(row)
        db.session.commit()
        assert result["tests"] == 2
        billed = {t.id: t.invoice_item_id for t in VisitInvestigation.query.all()}
        assert billed[ids["stay"]] and billed[ids["began"]] and not billed[ids["mid"]]
        assert bed_billing.post(row)["tests"] == 0


def test_a_clinic_with_no_beds_bills_at_the_desk_as_before(clinic):
    """No stay anywhere: the desk's list of drawn tests is exactly what it
    always was, and the lab's list asks nothing about beds."""
    from app.models import Investigation, Service, Setting, Visit, VisitInvestigation
    from app.utils import labs

    with clinic["app"].app_context():
        db = clinic["db"]
        Setting.set("mod_enabled:labs", "1")
        service = Service(name="تحليل", category="lab", price=90, is_active=True)
        db.session.add(service)
        db.session.flush()
        test = Investigation(name_ar="سكر", kind="lab", service_id=service.id)
        db.session.add(test)
        visit = Visit.query.first()
        db.session.flush()
        row = VisitInvestigation(visit_id=visit.id, patient_id=visit.patient_id,
                                 investigation_id=test.id, kind="lab", name="سكر")
        db.session.add(row)
        db.session.flush()
        labs.collect(row)
        db.session.commit()
        assert ([t.id for t in labs.unbilled(patient_id=visit.patient_id)]
                == [t.id for t in labs.unbilled(patient_id=visit.patient_id,
                                                outside_stays=True)] == [row.id])
        # And asks the database nothing about beds to say so.
        from sqlalchemy import event

        asked = []
        engine = db.engine
        listen = lambda *a: asked.append(a[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listen)
        try:
            assert labs.beds_of(labs.worklist(kind=None)) == {}
        finally:
            event.remove(engine, "before_cursor_execute", listen)
        assert not [q for q in asked if "care_bed_stays" in q or "bed_stays" in q]
    page = clinic["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-lab-bed" not in page


def test_the_lab_list_says_which_bed_to_walk_to(hospital):
    from app.models import Setting

    stay = _admit(hospital, _child(hospital, "على السرير"), bed_name="د٢")
    with hospital["app"].app_context():
        Setting.set("mod_enabled:labs", "1")
        hospital["db"].session.commit()
    _order(hospital, stay, name="صورة دم", kind="lab")
    page = hospital["sign_in"]("boss").get("/labs/").get_data(as_text=True)
    assert "data-lab-bed" in page and "الداخلي · د٢" in page


def test_another_stays_order_is_never_this_ones(hospital):
    """Two stays begun from one visit — a child re-admitted from the same
    emergency attendance. What the second stay ordered is its own."""
    from app.models import Visit, VisitInvestigation
    from app.models.admission import Admission
    from app.utils import labs

    cbc = _catalogue(hospital)
    pid = _child(hospital, "مرتين")
    with hospital["app"].app_context():
        began = Visit(patient_id=pid, doctor_id=hospital["ids"]["doctor"])
        hospital["db"].session.add(began)
        hospital["db"].session.commit()
        began_id = began.id
    first = _admit(hospital, pid, days_ago=6)
    with hospital["app"].app_context():
        row = hospital["db"].session.get(Admission, first)
        row.visit_id = began_id
        row.discharged_at = datetime.utcnow() - timedelta(days=3)
        hospital["db"].session.commit()
    second = _admit(hospital, pid, bed_name="د٢", days_ago=1)
    with hospital["app"].app_context():
        hospital["db"].session.get(Admission, second).visit_id = began_id
        hospital["db"].session.commit()
    _order(hospital, second, investigation_id=cbc, kind="lab")
    with hospital["app"].app_context():
        order = VisitInvestigation.query.one()
        labs.collect(order)
        hospital["db"].session.commit()
        db = hospital["db"]
        assert labs.unbilled(admission=db.session.get(Admission, first)) == []
        assert [t.id for t in labs.unbilled(
            admission=db.session.get(Admission, second))] == [order.id]


def test_a_stay_owing_no_night_yet_still_bills_its_tests(hospital):
    """Admitted this morning: no night is owed until tomorrow, and the blood
    drawn at the bed is still charged when somebody presses."""
    from app.models import VisitInvestigation
    from app.models.admission import Admission
    from app.utils import bed_billing, labs

    cbc = _catalogue(hospital)
    stay = _admit(hospital, _child(hospital, "النهارده"), days_ago=0)
    _order(hospital, stay, investigation_id=cbc, kind="lab")
    with hospital["app"].app_context():
        labs.collect(VisitInvestigation.query.one())
        hospital["db"].session.commit()
        row = hospital["db"].session.get(Admission, stay)
        assert bed_billing.outstanding(row) == []
        assert bed_billing.post(row)["tests"] == 1
