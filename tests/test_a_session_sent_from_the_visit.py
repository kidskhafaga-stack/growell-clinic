"""«حوّلت طفل لجلسة نفس في الطوارئ» — من شاشة الكشف.

صاحب العيادة جرّب يحوّل طفل لجلسة نفس في الطوارئ من الزيارة. اللي اتبنى:

* اختيار **«علاج بس في الطوارئ»** جنب «طوارئ المستشفى عندنا»: الطبيب بيختار
  اللي يتعمل (جلسة تنفس، حقنة، غيار) والتفاصيل، والطفل بيوصل الطوارئ «علاج
  بس» **والأمر مكتوب باسم الطبيب** — جاهز للتمريض؛
* قواعد القسم زي ما هي: الطفل بيتفرز هناك، والجلسة بتتحسب هناك (مش على
  فاتورة الكشف) فمفيش حاجة بتتحسب مرتين؛
* الرجوع في التحويل شغال لحد ما حد في الطوارئ يلمس الطفل — والأمر بيمشي معاه؛
* **شاشة الطوارئ بتقص القديم مش الجديد**: لو فيه حضور قديم محدّش قفله،
  الطفل اللي لسه واصل بيبان.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def er_on(clinic):
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    return clinic


def _url(clinic, tail="/record"):
    return f"/visits/{clinic['ids']['visit']}{tail}"


def _send(clinic, **form):
    data = {"kind": "in_house_treatment", "er_service_id": clinic["ids"]["nebul"],
            "er_detail": "فاركولين ٠٫٥ مل + ملح ٣ مل", "referral_note": ""}
    data.update(form)
    return clinic["sign_in"]("doc").post(_url(clinic, "/refer"), data=data)


def test_the_choice_is_on_the_visit_only_with_an_emergency_department(clinic):
    from app.models import Setting

    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "0")
        clinic["db"].session.commit()
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert 'value="in_house_treatment"' not in page and "data-er-treatment" not in page

    with clinic["app"].app_context():
        Setting.set("mod_enabled:emergency", "1")
        clinic["db"].session.commit()
    page = clinic["sign_in"]("doc").get(_url(clinic)).get_data(as_text=True)
    assert 'value="in_house_treatment"' in page and "data-er-service" in page
    assert "جلسة تنفس" in page[page.index("data-er-service"):]
    assert "كشف" not in page[page.index("data-er-service"):page.index("data-er-detail")], \
        "a consultation is not something the department gives"


def test_the_child_arrives_for_treatment_with_the_order_written(er_on):
    from app.models import EmergencyOrder, EmergencyVisit, Visit

    clinic = er_on
    _send(clinic)
    with clinic["app"].app_context():
        row = EmergencyVisit.query.one()
        assert row.treatment_only and row.arrival == "referred"
        assert row.from_visit_id == clinic["ids"]["visit"]
        assert row.sent_reason == "جلسة تنفس", "the session is the reason when none is typed"
        order = EmergencyOrder.query.one()
        assert (order.name, order.service_id, order.source) == (
            "جلسة تنفس", clinic["ids"]["nebul"], "ours")
        assert order.prescriber_id == clinic["ids"]["doctor"]
        assert order.note == "فاركولين ٠٫٥ مل + ملح ٣ مل"
        assert order.state == "ready" and order.given_at is None
        assert row.triaged_at is None, "the department still triages"
        v = clinic["db"].session.get(Visit, clinic["ids"]["visit"])
        assert v.is_referred and not v.services, "charged in emergency, not on the visit"
        rid = row.id

    board = clinic["sign_in"]("boss").get("/emergency/").get_data(as_text=True)
    assert "data-walk-in" in board or "علاج" in board
    page = clinic["sign_in"]("boss").get(f"/emergency/attendance/{rid}").get_data(as_text=True)
    assert "جلسة تنفس" in page and "فاركولين" in page


def test_a_reason_typed_is_kept(er_on):
    from app.models import EmergencyVisit

    _send(er_on, referral_note="أزمة ربو")
    with er_on["app"].app_context():
        assert EmergencyVisit.query.one().sent_reason == "أزمة ربو"


def test_nothing_is_sent_without_choosing_what_to_give(er_on):
    from app.models import EmergencyVisit

    _send(er_on, er_service_id="")
    _send(er_on, er_service_id=er_on["ids"]["exam"])  # a consultation
    with er_on["app"].app_context():
        assert EmergencyVisit.query.count() == 0


def test_taken_back_before_anybody_touched_the_child(er_on):
    from app.models import EmergencyOrder, EmergencyVisit, Visit

    _send(er_on)
    er_on["sign_in"]("doc").post(_url(er_on, "/refer"), data={"undo": "1"})
    with er_on["app"].app_context():
        assert EmergencyVisit.query.count() == 0 and EmergencyOrder.query.count() == 0
        assert not er_on["db"].session.get(Visit, er_on["ids"]["visit"]).is_referred


def test_not_taken_back_once_the_session_was_given(er_on):
    from app.models import EmergencyOrder, EmergencyVisit

    _send(er_on)
    with er_on["app"].app_context():
        order = EmergencyOrder.query.one()
        order.given_at = datetime.utcnow()
        er_on["db"].session.commit()
    er_on["sign_in"]("doc").post(_url(er_on, "/refer"), data={"undo": "1"})
    with er_on["app"].app_context():
        assert EmergencyVisit.query.count() == 1


def test_the_plain_emergency_choice_is_as_it_was(er_on):
    from app.models import EmergencyOrder, EmergencyVisit

    er_on["sign_in"]("doc").post(_url(er_on, "/refer"), data={
        "kind": "in_house", "referral_note": "صعوبة تنفس"})
    with er_on["app"].app_context():
        row = EmergencyVisit.query.one()
        assert not row.treatment_only and row.sent_reason == "صعوبة تنفس"
        assert EmergencyOrder.query.count() == 0


def test_a_new_arrival_is_never_cut_off_by_old_open_ones(er_on):
    from app.models import EmergencyVisit, Patient
    from app.utils import emergency as er

    with er_on["app"].app_context():
        db = er_on["db"]
        old = datetime.utcnow() - timedelta(days=30)
        for i in range(5):
            other = Patient(patient_number=f"OLD{i}", full_name=f"قديم {i}", gender="male",
                            date_of_birth=datetime(2020, 1, 1).date(), is_active=True)
            db.session.add(other)
            db.session.flush()
            db.session.add(EmergencyVisit(patient_id=other.id, arrival="walk_in",
                                          arrived_at=old + timedelta(minutes=i)))
        db.session.commit()
    _send(er_on)
    with er_on["app"].app_context():
        rows = er.open_visits(limit=3)
        assert rows[-1].treatment_only, "the one who just arrived is on the list"
        assert [r.arrived_at for r in rows] == sorted(r.arrived_at for r in rows), \
            "still oldest first"
