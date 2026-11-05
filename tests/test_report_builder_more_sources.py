"""منشئ التقارير — المصادر الخمسة اللي كانت «لسه» (REPORTS_PLAN.md ت-٢):
التحاليل والأشعة، التطعيمات، الرسايل، الإحالات، حركة المخزون.

كل مصدر بيعدّ اللي البرنامج متسجّل فيه زي ما هو، مجمّع بس (من غير أسماء أطفال)،
وكل واحد بصلاحية مديوله: التحاليل للمعمل أو الكشف، التطعيمات للتطعيمات، الرسايل
للرسايل، الإحالات للكشف، والمخزون للمخزن — كميات مش فلوس.
"""
import re
from datetime import datetime, timedelta

from app.utils.clock import local_today

ROWS = re.compile(r'<tr data-row="([^"]*)">(.*?)</tr>', re.S)


def _table(html):
    return {label: [None if v == "" else float(v) for v in re.findall(r'data-v="([^"]*)"', body)]
            for label, body in ROWS.findall(html)}


def _seed(clinic):
    from app.models import (Investigation, MessageLog, PatientVaccine, Vaccine, VaccineBrand,
                            Visit, VisitInvestigation)
    from app.models.referral import Referral
    from app.models.store import StockMovement, StoreItem, Warehouse

    db = clinic["db"]
    with clinic["app"].app_context():
        kid, doc = clinic["ids"]["child"], clinic["ids"]["doctor"]
        visit = Visit(patient_id=kid, doctor_id=doc, visit_date=local_today() - timedelta(days=2))
        db.session.add(visit)
        db.session.flush()
        cbc = Investigation(name_ar="صورة دم كاملة", name_en="CBC", kind="lab", category="Hematology")
        db.session.add(cbc)
        db.session.flush()
        for status in ("resulted", "requested"):
            db.session.add(VisitInvestigation(visit_id=visit.id, patient_id=kid,
                                              investigation_id=cbc.id, name="صورة دم كاملة",
                                              kind="lab", status=status))
        db.session.add(VisitInvestigation(visit_id=visit.id, patient_id=kid, name="أشعة صدر",
                                          kind="imaging", status="requested", done_outside=True))
        v = Vaccine(code="ZZV", name_ar="تطعيم تجربة", name_en="Test vaccine", is_mandatory=False)
        db.session.add(v)
        db.session.flush()
        b = VaccineBrand(vaccine_id=v.id, name="BrandX")
        db.session.add(b)
        db.session.flush()
        for n in (1, 2):
            db.session.add(PatientVaccine(patient_id=kid, vaccine_id=v.id, brand_id=b.id,
                                          dose_number=n, event_type="given",
                                          given_date=local_today() - timedelta(days=n)))
        now = datetime.utcnow() - timedelta(hours=3)
        for status in ("sent", "sent", "failed"):
            db.session.add(MessageLog(patient_id=kid, body="—", status=status, channel="whatsapp",
                                      direction="out", template_type="vaccine_due", created_at=now))
        db.session.add(Referral(patient_id=kid, visit_id=visit.id, kind="referral",
                                reason="—", sent_to="مستشفى أبو الريش", decided_by_id=doc,
                                decided_at=now))
        wh = Warehouse(name="المخزن الرئيسي")
        item = StoreItem(name="سرنجة ٣ سم", category="مستلزمات")
        db.session.add_all([wh, item])
        db.session.flush()
        for qty, kind in ((50, "in"), (-7, "out"), (-3, "out")):
            db.session.add(StockMovement(item_id=item.id, warehouse_id=wh.id, kind=kind, qty=qty,
                                         created_at=now))
        db.session.commit()


def test_each_new_source_counts_what_is_on_file(clinic):
    _seed(clinic)
    boss = clinic["sign_in"]("boss")

    def table(**args):
        q = "&".join(f"{k}={v}" for k, v in args.items())
        resp = boss.get(f"/reports/builder?preset=30&{q}")
        assert resp.status_code == 200, args
        return _table(resp.get_data(as_text=True))

    lab = table(src="investigations", by="test")
    assert lab.get("صورة دم كاملة", [None])[0] == 2 and lab.get("أشعة صدر", [None])[0] == 1
    assert table(src="investigations", by="where").get("برّه", [None])[0] == 1
    assert table(src="investigations", by="test_status").get("النتيجة طلعت", [None])[0] == 1

    vac = table(src="vaccines", by="vaccine")
    assert vac.get("تطعيم تجربة", [None])[0] == 2
    assert table(src="vaccines", by="vaccine", m="children").get("تطعيم تجربة", [None])[0] == 1

    msg = table(src="messages", by="msg_status")
    assert msg.get("اتبعتت", [None])[0] == 2 and msg.get("فشلت", [None])[0] == 1

    ref = table(src="referrals", by="sent_to")
    assert ref.get("مستشفى أبو الريش", [None])[0] == 1
    assert table(src="referrals", by="feedback").get("مفيش رد", [None])[0] == 1

    stock = table(src="stock", by="item")
    assert stock.get("سرنجة ٣ سم", [None])[0] == 10, "the quantity that left"
    assert table(src="stock", by="item", m="qty_in").get("سرنجة ٣ سم", [None])[0] == 50


def test_no_child_s_name_and_each_source_with_its_module(clinic):
    from app.models import Patient

    _seed(clinic)
    with clinic["app"].app_context():
        name = clinic["db"].session.get(Patient, clinic["ids"]["child"]).full_name
    boss = clinic["sign_in"]("boss")
    for src in ("investigations", "vaccines", "messages", "referrals", "stock"):
        page = boss.get(f"/reports/builder?src={src}&preset=30").get_data(as_text=True)
        assert name not in page, src
    # Someone without the module does not get the source.
    from app.models import User
    from app.utils import report_builder as rb

    with clinic["app"].app_context():
        desk = User.query.filter_by(username="desk").one()
        mine = rb.available(desk)
        if "stock" in mine:
            assert desk.can_open("inventory")
        if "messages" in mine:
            assert desk.can_open("messages")
