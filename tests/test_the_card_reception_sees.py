"""الكارت وتنبيه الاستقبال (CONTRACTS_PLAN.md ع-١).

* الكارت في ملف الطفل: الفئة وصاحب الاشتراك وتاريخ الإصدار وصورته.
* التجديد صف جديد بصورته — والصورة مطلوبة — والقديم بيفضل مقفول في السجل.
* الاستقبال بيشوف حالة الكارت عند الحجز، وفي لوحة اليوم، وعند الخزنة:
  ساري · هينتهي خلال ١٤ يوم · منتهي · عقد الشركة منتهي.
* الكارت المنتهي مش بيوقف الدفع ولا بيطلب قرار («مش عايز يبقى فيه كتير قرارات
  واسترجاع كتير»): الأهل يدفعوا كاش والفاتورة تستنى الكارت الجديد «المهلة» اللي
  العيادة حاطاها؛ ولما الكارت الجديد يتسجّل بتتحول للشركة لوحدها، والفرق بيروح
  رصيد للأسرة. خصم الفئة النقدي بيتشال من الخدمة اللي الشركة بتغطيها، والسطر اللي
  محتاج موافقة بيستنى الموافقة، والفاتورة عمرها ما تتحول لو هتعمل على الأهل فلوس.
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
            "line_price": "200", "line_qty": "1", "amount": "", "method": "instapay"}
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


def test_an_expired_card_stops_nothing_and_the_bill_waits(clinic):
    from app.models import Invoice

    _card(clinic, days_left=-1)
    boss = clinic["sign_in"]("boss")
    till = boss.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-card-expired" in till and 'data-card-wait="30"' in till
    assert "data-card-renew" in till and "data-card-cash" in till
    _collect(boss, clinic)                       # no decision asked for
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.coverage_decision == "waiting" and inv.coverage_decided_by == clinic["ids"]["admin"]
        assert inv.payer_id is None
    till = boss.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "data-card-expired" not in till and 'data-card-decided="waiting"' in till


def test_cash_for_good_and_a_clinic_that_does_not_wait(clinic):
    from app.models import Invoice, Setting

    _card(clinic, days_left=-1)
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, coverage_cash="1")
    with clinic["app"].app_context():
        assert Invoice.query.one().coverage_decision == "cash"
        Invoice.query.delete()
        Setting.set("card_wait_days", "0")
        clinic["db"].session.commit()
    till = boss.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert 'data-card-wait="0"' in till and "data-card-cash" not in till
    _collect(boss, clinic)
    with clinic["app"].app_context():
        assert Invoice.query.one().coverage_decision == "cash"


def _rate(clinic, payer, percent=80):
    from app.models import PayerServiceRate

    with clinic["app"].app_context():
        clinic["db"].session.add(PayerServiceRate(payer_id=payer, service_id=clinic["ids"]["exam"],
                                                  coverage_type="percent", coverage_value=percent))
        clinic["db"].session.commit()


def _renew(client, clinic, cov_id, issue, **extra):
    from app.utils.clock import local_today

    data = {"expiry_date": (local_today() + timedelta(days=300)).isoformat(),
            "issue_date": issue, "card_front": _photo()}
    data.update(extra)
    return client.post(f"/patients/coverage/{cov_id}/renew", data=data,
                       content_type="multipart/form-data")


def test_the_new_card_turns_the_waiting_bill_into_a_contract_bill(clinic):
    from app.models import Invoice, PatientCredit
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    _rate(clinic, payer, 80)
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="200")         # paid in full, in cash
    # The new card needs its issue date when bills are waiting for it.
    _renew(boss, clinic, cov_id, issue="")
    with clinic["app"].app_context():
        assert Invoice.query.one().coverage_decision == "waiting"
    reply = _renew(boss, clinic, cov_id, issue=(local_today() - timedelta(days=10)).isoformat())
    assert reply.status_code == 302
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id == payer and inv.coverage_decision == "converted"
        assert inv.total == 40 and inv.paid == 40 and inv.status == "paid"
        credit = PatientCredit.query.one()
        assert credit.amount == 160 and credit.kind == "in" and credit.invoice_id == inv.id


def test_the_cash_category_discount_comes_off_what_the_payer_covers(clinic):
    from app.models import Invoice, NamedDiscount, PatientCredit
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    _rate(clinic, payer, 80)
    with clinic["app"].app_context():
        disc = NamedDiscount(name="عضو النادي", value=10, is_percent=True, is_active=True)
        clinic["db"].session.add(disc)
        clinic["db"].session.commit()
        disc_id = disc.id
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="180", discount_id=str(disc_id))
    with clinic["app"].app_context():
        assert Invoice.query.one().total == 180
    _renew(boss, clinic, cov_id, issue=(local_today() - timedelta(days=10)).isoformat())
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        # 200 at the contract: 160 the payer's, 40 the family's — not 10% off as well.
        assert inv.payer_total == 160 and inv.total == 40
        assert PatientCredit.query.one().amount == 140


def test_a_card_that_starts_after_the_visit_does_not_take_it(clinic):
    from app.models import Invoice, PatientCredit
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    _rate(clinic, payer, 80)
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="200")
    _renew(boss, clinic, cov_id, issue=(local_today() + timedelta(days=1)).isoformat())
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id is None and inv.coverage_decision == "waiting" and inv.total == 200
        assert PatientCredit.query.count() == 0


def test_a_line_waiting_for_an_approval_is_credited_when_it_comes(clinic):
    from app.models import (InsuranceApproval, Invoice, PatientCredit, PayerContract,
                            PayerContractRule)
    from app.utils import approvals
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    with clinic["app"].app_context():
        db = clinic["db"]
        c = PayerContract(payer_id=payer, start_date=local_today() - timedelta(days=100),
                          end_date=local_today() + timedelta(days=300), is_active=True)
        db.session.add(c)
        db.session.flush()
        db.session.add(PayerContractRule(contract_id=c.id, scope="service",
                                         service_id=clinic["ids"]["exam"], coverage_type="percent",
                                         coverage_value=80, needs_approval=True))
        db.session.commit()
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="200")
    _renew(boss, clinic, cov_id, issue=(local_today() - timedelta(days=10)).isoformat())
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id == payer and inv.items[0].approval_needed
        assert PatientCredit.query.count() == 0     # nothing back before the payer agrees
        db = clinic["db"]
        ok = InsuranceApproval(patient_id=clinic["ids"]["child"], payer_id=payer,
                               service_id=clinic["ids"]["exam"], status="requested")
        db.session.add(ok)
        db.session.flush()
        approvals.decide(ok, True, None, number="A-1")
        db.session.commit()
        assert PatientCredit.query.one().amount == 160
        assert Invoice.query.one().total == 40


def test_the_wait_runs_out_into_cash_and_reception_sees_what_waits(clinic):
    from datetime import datetime

    from app.models import Invoice

    _card(clinic, days_left=-1)
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="200")
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert "data-waiting-row" in page
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        inv.coverage_decided_at = datetime.utcnow() - timedelta(days=31)
        clinic["db"].session.commit()
    page = boss.get("/patients/coverage/expiring").get_data(as_text=True)
    assert "data-waiting-none" in page
    with clinic["app"].app_context():
        assert Invoice.query.one().coverage_decision == "cash"


def test_the_wait_is_the_clinic_s_setting(clinic):
    from app.models import Setting
    from app.utils import coverage_card

    page = clinic["sign_in"]("boss").get("/settings/").get_data(as_text=True)
    assert "data-card-wait-setting" in page and 'name="card_wait_days"' in page
    with clinic["app"].app_context():
        assert coverage_card.wait_days() == 30
        for raw, want in (("45", 45), ("0", 0), ("abc", 30), ("999", 365), ("-3", 0)):
            Setting.set("card_wait_days", raw)
            assert coverage_card.wait_days() == want


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


def test_renewed_from_the_till_it_comes_back_and_the_bill_goes_to_the_payer(clinic):
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
    assert "data-card-expired" not in boss.get(back).get_data(as_text=True)
    _collect(boss, clinic)
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id == payer and inv.coverage_decision is None


def test_a_bill_that_would_leave_the_family_owing_stays_as_it_was(clinic):
    """The contract's price is 500 and the family's share half of it — more
    than the 200 they paid in cash: the bill is left as it was, and said."""
    from app.models import Invoice, PatientCredit, PayerContract, PayerContractRate
    from app.utils.clock import local_today

    payer, cov_id = _card(clinic, days_left=-1)
    with clinic["app"].app_context():
        db = clinic["db"]
        c = PayerContract(payer_id=payer, start_date=local_today() - timedelta(days=100),
                          end_date=local_today() + timedelta(days=300), is_active=True)
        db.session.add(c)
        db.session.flush()
        db.session.add(PayerContractRate(contract_id=c.id, service_id=clinic["ids"]["exam"],
                                         special_price=500, coverage_type="percent", coverage_value=50))
        db.session.commit()
    boss = clinic["sign_in"]("boss")
    _collect(boss, clinic, amount="200")
    _renew(boss, clinic, cov_id, issue=(local_today() - timedelta(days=10)).isoformat())
    with clinic["app"].app_context():
        inv = Invoice.query.one()
        assert inv.payer_id is None and inv.total == 200 and inv.paid == 200
        assert inv.coverage_decision == "waiting" and inv.items[0].unit_price == 200
        assert PatientCredit.query.count() == 0
