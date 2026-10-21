"""الكارت وتنبيه الاستقبال (CONTRACTS_PLAN.md ع-١).

* الكارت في ملف الطفل: الفئة وصاحب الاشتراك وتاريخ الإصدار وصورته.
* التجديد صف جديد بصورته — والصورة مطلوبة — والقديم بيفضل مقفول في السجل.
* الاستقبال بيشوف حالة الكارت عند الحجز، وفي لوحة اليوم، وعند الخزنة:
  ساري · هينتهي خلال ١٤ يوم · منتهي · عقد الشركة منتهي.
* الكارت المنتهي قرار قبل الدفع: «جدّد الكارت» أو «الزيارة دي كاش» — ومين قرر
  بيتسجّل على الفاتورة. مش فاتورة بتتحول كاش لوحدها.
* الإقامة بتتحسب بيوم الدخول: كارت انتهى في نص الإقامة بيغطيها.
* قايمة «الكروت اللي هتنتهي» للاستقبال.
"""
import io
import os
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00"
       b"\x00\x00IEND\xaeB`\x82")


def _photo(name="card.png"):
    return (io.BytesIO(PNG), name)


def _card(clinic, days_left, **extra):
    """A payer and a card for the fixture's child, ending ``days_left`` from today."""
    from app.models import PatientCoverage, PayerEntity
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        payer = PayerEntity(name="شركة النيل", entity_type="insurance")
        db.session.add(payer)
        db.session.flush()
        cov = PatientCoverage(patient_id=clinic["ids"]["child"], payer_id=payer.id,
                              membership_number="M-77", is_active=True,
                              expiry_date=local_today() + timedelta(days=days_left), **extra)
        db.session.add(cov)
        db.session.commit()
        return payer.id, cov.id


def _collect(client, clinic, **extra):
    data = {"line_desc": "كشف", "line_service_id": str(clinic["ids"]["exam"]),
            "line_price": "200", "line_qty": "1", "amount": "", "method": "cash"}
    data.update(extra)
    return client.post(f"/finance/collect/{clinic['ids']['child']}", data=data)


def test_the_card_has_its_details_and_its_picture(clinic):
    from app.models import PatientCoverage, PayerEntity

    with clinic["app"].app_context():
        clinic["db"].session.add(PayerEntity(name="نادي الشمس", entity_type="club"))
        clinic["db"].session.commit()
        payer = PayerEntity.query.one().id
    boss = clinic["sign_in"]("boss")
    boss.post(f"/patients/{clinic['ids']['child']}/coverage/new", data={
        "payer_id": payer, "membership_number": "S-1", "issue_date": "2026-01-01",
        "expiry_date": "2026-12-31", "plan_name": "ذهبية", "holder_name": "محمد علي",
        "holder_relation": "الأب", "card_front": _photo()}, content_type="multipart/form-data")
    with clinic["app"].app_context():
        cov = PatientCoverage.query.one()
        assert cov.plan_name == "ذهبية" and cov.holder_name == "محمد علي"
        assert str(cov.issue_date) == "2026-01-01" and cov.card_front
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "ذهبية" in page and "محمد علي" in page and 'data-card-photo="card_front"' in page


def test_a_renewal_needs_the_new_picture_and_keeps_the_old_card(clinic):
    from app.models import PatientCoverage
    from app.utils.clock import local_today

    _payer, cov_id = _card(clinic, days_left=-3, plan_name="فضية")
    boss = clinic["sign_in"]("boss")
    new_end = (local_today() + timedelta(days=365)).isoformat()
    # No picture: refused, nothing changes.
    boss.post(f"/patients/coverage/{cov_id}/renew", data={"expiry_date": new_end},
              content_type="multipart/form-data")
    with clinic["app"].app_context():
        assert PatientCoverage.query.count() == 1
    boss.post(f"/patients/coverage/{cov_id}/renew", data={
        "expiry_date": new_end, "issue_date": local_today().isoformat(),
        "card_front": _photo()}, content_type="multipart/form-data")
    with clinic["app"].app_context():
        old = clinic["db"].session.get(PatientCoverage, cov_id)
        new = PatientCoverage.query.filter_by(renewed_from_id=cov_id).one()
        assert not old.is_active and new.is_active and new.card_front
        assert new.membership_number == "M-77" and new.plan_name == "فضية"
        assert new.renewed_by == clinic["ids"]["admin"]
    page = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-old-cards" in page


def test_reception_sees_the_card_at_the_booking_the_board_and_the_till(clinic):
    from app.models import Appointment
    from app.utils.clock import local_today

    _card(clinic, days_left=5)
    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(Appointment(patient_id=clinic["ids"]["child"], doctor_id=clinic["ids"]["doctor"],
                                   appt_date=local_today(), appt_time=time(10, 0)))
        db.session.commit()
    desk = clinic["sign_in"]("desk")
    board = desk.get(f"/appointments/?date={local_today().isoformat()}").get_data(as_text=True)
    assert 'data-card-state="soon"' in board
    found = desk.get("/appointments/patient-search?q=طفل").get_json()["patients"]
    assert found and found[0]["card"]["state"] == "soon"
    till = clinic["sign_in"]("boss").get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert 'data-card-line' in till and 'data-card-state="soon"' in till


def test_an_expired_card_is_a_decision_before_the_money(clinic):
    from app.models import Invoice

    _card(clinic, days_left=-1)
    boss = clinic["sign_in"]("boss")
    till = boss.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-card-decision" in till and "data-card-renew" in till and "data-card-cash" in till
    # Without a decision: refused, no bill.
    _collect(boss, clinic)
    with clinic["app"].app_context():
        assert Invoice.query.count() == 0
    _collect(boss, clinic, coverage_cash="1")
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.coverage_decision == "cash" and inv.coverage_decided_by == clinic["ids"]["admin"]
        assert inv.payer_id is None
    # A second collection the same day is not asked again.
    till = boss.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-card-decision" not in till


def test_renewed_from_the_till_the_bill_goes_to_the_payer(clinic):
    from app.models import Invoice
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    boss = clinic["sign_in"]("boss")
    back = f"/finance/collect/{clinic['ids']['child']}"
    reply = boss.post(f"/patients/coverage/{cov_id}/renew", data={
        "expiry_date": (local_today() + timedelta(days=200)).isoformat(),
        "card_front": _photo(), "next": back}, content_type="multipart/form-data")
    assert reply.status_code == 302 and reply.headers["Location"].endswith(back)
    # A link to somewhere else is not followed.
    reply = boss.post(f"/patients/coverage/{cov_id}/renew", data={"next": "//evil.test/x"},
                      content_type="multipart/form-data")
    assert "evil.test" not in reply.headers.get("Location", "")
    assert "data-card-decision" not in boss.get(back).get_data(as_text=True)
    _collect(boss, clinic)
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id == payer and inv.coverage_decision is None


def test_the_payer_s_own_contract_ending_is_said_too(clinic):
    from app.models import PayerContract
    from app.utils import coverage_card
    from app.utils.clock import local_today

    payer, _ = _card(clinic, days_left=100)
    with clinic["app"].app_context():
        db = clinic["db"]
        db.session.add(PayerContract(payer_id=payer, start_date=local_today() - timedelta(days=400),
                                     end_date=local_today() - timedelta(days=2), is_active=True))
        db.session.commit()
        from app.models import Patient

        st = coverage_card.state(db.session.get(Patient, clinic["ids"]["child"]))
        assert st["state"] == "contract" and st["needs_decision"]


def test_a_stay_is_judged_on_the_day_it_began(clinic):
    from app.models import Admission, Invoice, Patient
    from app.utils import billing
    from app.utils.clock import local_today

    payer, _ = _card(clinic, days_left=-2)           # ran out two days ago
    with clinic["app"].app_context():
        db = clinic["db"]
        adm = Admission(patient_id=clinic["ids"]["child"],
                        admitted_at=datetime.utcnow() - timedelta(days=6))
        db.session.add(adm)
        db.session.flush()
        inv = Invoice(invoice_number="S-1", patient_id=clinic["ids"]["child"],
                      admission_id=adm.id, invoice_date=local_today())
        db.session.add(inv)
        db.session.flush()
        billing.apply_coverage(inv, db.session.get(Patient, clinic["ids"]["child"]))
        assert inv.payer_id == payer                  # the stay began under a valid card
        clinic_bill = Invoice(invoice_number="S-2", patient_id=clinic["ids"]["child"],
                              invoice_date=local_today())
        db.session.add(clinic_bill)
        db.session.flush()
        billing.apply_coverage(clinic_bill, db.session.get(Patient, clinic["ids"]["child"]))
        assert clinic_bill.payer_id is None           # today's clinic visit: the card is out


def test_the_list_reception_calls_from(clinic):
    _card(clinic, days_left=4)
    boss = clinic["sign_in"]("boss")
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert "data-expiring-row" in page and "M-77" in page
    profile = boss.get(f"/patients/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-expiring-door" in profile
    assert 'data-rep="patients.expiring_cards"' in boss.get("/reports/").get_data(as_text=True)
