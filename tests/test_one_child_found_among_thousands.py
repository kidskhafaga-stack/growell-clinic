"""«انت بتعمل برده ليست للقائمة وده مش منطقي فى مستشفى او عيادة فيها اللاف
المرضى».

* اختيار الطفل بيدوّر في كل الملفات على السيرفر، ١٥ في المرة — مش لستة
  بأول ٥٠٠؛
* الطفل رقم ٥٠١ بيتلاقي — وده اللي كان مستحيل في شاشة التحصيل؛
* الفاتورة، وربط رقم مجهول في الرسايل، والتحصيل: نفس الاختيار؛
* البحث للي عنده شاشة بيسأل فيها «أنهي طفل» بس.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def crowd(clinic):
    """Five hundred and one children — the last one past the old list."""
    from app.models import Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add_all([
            Patient(patient_number=f"C{i:04d}", full_name=f"أ طفل {i:04d}", gender="male",
                    date_of_birth=date(2022, 1, 1), is_active=True)
            for i in range(500)])
        last = Patient(patient_number="Z9999", full_name="ي آخر طفل في القايمة", gender="female",
                       date_of_birth=date(2022, 1, 1), is_active=True)
        db.session.add(last)
        db.session.commit()
        clinic["ids"]["last"] = last.id
    return clinic


def test_the_search_reaches_every_file_fifteen_at_a_time(crowd):
    desk = crowd["sign_in"]("desk")
    found = desk.get("/patient-search?q=آخر طفل").get_json()
    assert [r["id"] for r in found] == [crowd["ids"]["last"]]
    assert len(desk.get("/patient-search?q=طفل").get_json()) == 15
    assert desk.get("/patient-search?q=أ").get_json() == [], "one letter is not a search"


def test_only_somebody_who_picks_children_may_search(crowd):
    from app.models import User
    from app.models.role import Role

    with crowd["app"].app_context():
        crowd["db"].session.add(Role(name="store_only", label_ar="مخزن", modules="inventory",
                                     capabilities=""))
        person = User(username="store", full_name="المخزن", role="store_only", is_active=True)
        person.set_password("secret")
        crowd["db"].session.add(person)
        crowd["db"].session.commit()
    assert crowd["sign_in"]("store").get("/patient-search?q=طفل").status_code == 403


def test_the_till_finds_the_five_hundred_and_first_child(crowd):
    page = crowd["sign_in"]("boss").get("/finance/collect").get_data(as_text=True)
    assert "data-collect-search" in page and "data-patient-picker" in page
    assert "آخر طفل" not in page, "no list rendered into the page"
    assert "/finance/collect/__ID__" in page


def test_the_invoice_s_patient_is_searched_not_listed(crowd):
    from app.models import Invoice
    from app.utils import accounting as acct

    with crowd["app"].app_context():
        acct.ensure_seeded()
        inv = Invoice(patient_id=crowd["ids"]["child"], invoice_number="INV-T1",
                      created_by=crowd["ids"]["admin"])
        crowd["db"].session.add(inv)
        crowd["db"].session.commit()
        iid = inv.id
    boss = crowd["sign_in"]("boss")
    page = boss.get(f"/finance/invoices/{iid}").get_data(as_text=True)
    assert "data-patient-picker" in page and '<select class="select" name="patient_id">' not in page
    boss.post(f"/finance/invoices/{iid}/edit", data={"patient_id": ""})           # retyped, not chosen
    with crowd["app"].app_context():
        assert crowd["db"].session.get(Invoice, iid).patient_id == crowd["ids"]["child"]
    boss.post(f"/finance/invoices/{iid}/edit", data={"patient_id": str(crowd["ids"]["last"])})
    with crowd["app"].app_context():
        assert crowd["db"].session.get(Invoice, iid).patient_id == crowd["ids"]["last"]


def test_an_unknown_number_is_linked_by_search(crowd):
    from datetime import datetime

    from app.models import MessageLog

    with crowd["app"].app_context():
        crowd["db"].session.add(MessageLog(direction="in", body="عايزة ميعاد",
                                           to_phone="01099999999", status="received",
                                           created_at=datetime.utcnow()))
        crowd["db"].session.commit()
    page = crowd["sign_in"]("desk").get("/messages/inbox/01099999999").get_data(as_text=True)
    assert "data-patient-picker" in page and "آخر طفل" not in page


def test_the_doctor_s_own_phrases_are_a_button_at_the_top_of_the_tab(clinic):
    """«الشاشة دي فين فى الاعدادات ؟» — the doctor's own phrases screen, a
    button at the top of «القوايم السريعة» rather than a line at its end."""
    page = clinic["sign_in"]().get("/settings/").get_data(as_text=True)
    assert "data-to-my-phrases" in page and "/visits/phrases" in page
