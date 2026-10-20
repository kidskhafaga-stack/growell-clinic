"""منشئ التقارير (REPORTS_PLAN.md ت-٢).

* المصدر والفترة والتقسيم، والمقارنة: فترة بفترة، ونفس الشهور السنة اللي فاتت،
  وطبيب جنب طبيب، ونقدي قصاد تعاقد، وشركة قصاد شركة.
* الأرقام هي أرقام البرنامج: قيمة الفاتورة = نصيب الأهل + نصيب الشركة، والتشخيص
  بيتعد مرة لكل زيارة وكود.
* إحصاء وصفي (العدد، المتوسط، الوسيط، الانحراف المعياري، الأقل، الأعلى).
* أرقام مجمّعة بس: اسم الطفل ما يطلعش في الصفحة.
* الفلوس بصلاحية المالية بس، والتقرير المحفوظ بيتحسب بصلاحيات اللي فاتحه.
"""
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

ROLES = ("boss", "doc", "desk", "acct")


def _table(html):
    """{row label: [cell values]} from the result table."""
    out = {}
    for label, body in re.findall(r'<tr data-row="([^"]*)">(.*?)</tr>', html, re.S):
        out[label] = [None if v == "" else float(v) for v in re.findall(r'data-v="([^"]*)"', body)]
    return out


def _cols(html):
    return re.findall(r'<th data-col="([^"]*)">', html)


def _add_visit(clinic, days_ago=0, doctor=None, child=None):
    from app.models import Visit
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        v = Visit(patient_id=child or clinic["ids"]["child"], doctor_id=doctor or clinic["ids"]["doctor"],
                  visit_date=local_today() - timedelta(days=days_ago))
        db.session.add(v)
        db.session.commit()
        return v.id


def test_it_opens_for_whoever_has_reports_and_money_needs_the_finance_rights(clinic):
    seen = False
    for role in ROLES:
        client = clinic["sign_in"](role)
        resp = client.get("/reports/builder")
        if resp.status_code != 200:
            assert resp.status_code in (302, 403)
            continue
        seen = True
        page = resp.get_data(as_text=True)
        sources = re.findall(r'name="src" value="(\w+)"', page)
        assert sources
        for key in sources:
            assert client.get(f"/reports/builder?src={key}").status_code == 200, (role, key)
        with clinic["app"].app_context():
            from app.models import User

            user = User.query.filter_by(username=role).one()
            money = user.can("finance_manage")
        assert ("bills" in sources) == money, role
        if not money:
            # Asking for it by hand does not get it either.
            page = client.get("/reports/builder?src=bills").get_data(as_text=True)
            assert 'value="bills" checked' not in page
    assert seen


def test_no_child_s_name_comes_out(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        p = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        p.full_name = "زياد المميز"
        clinic["db"].session.commit()
    boss = clinic["sign_in"]("boss")
    for src in ("visits", "diagnoses", "drugs", "appointments", "bills", "lines"):
        page = boss.get(f"/reports/builder?src={src}").get_data(as_text=True)
        assert "زياد المميز" not in page, src


def test_period_against_the_one_before(clinic):
    _add_visit(clinic, days_ago=3)
    _add_visit(clinic, days_ago=40)
    _add_visit(clinic, days_ago=45)
    page = clinic["sign_in"]("boss").get(
        "/reports/builder?src=visits&preset=30&by=doctor&vs=prev").get_data(as_text=True)
    rows = _table(page)
    total = rows["__total__"]
    # This month: the fixture's visit and today-3; before: two.
    assert total[0] == 2 and total[1] == 2 and total[2] == 0 and total[3] == 0


def test_the_same_months_last_year_line_up_month_by_month(clinic):
    page = clinic["sign_in"]("boss").get(
        "/reports/builder?src=visits&from=2026-01-01&to=2026-06-30&by=month&vs=year"
    ).get_data(as_text=True)
    labels = [k for k in _table(page) if k != "__total__"]
    assert labels[0] == "2026-01 / 2025-01" and labels[-1] == "2026-06 / 2025-06"
    assert len(labels) == 6


def test_doctor_beside_doctor(clinic):
    from app.models import User

    with clinic["app"].app_context():
        db = clinic["db"]
        u = User(username="doc2", full_name="د. منى", role="doctor", is_active=True)
        u.set_password("secret")
        db.session.add(u)
        db.session.commit()
        other = u.id
    _add_visit(clinic, doctor=other)
    _add_visit(clinic, doctor=other)
    page = clinic["sign_in"]("boss").get(
        "/reports/builder?src=visits&preset=30&by=month&split=doctor").get_data(as_text=True)
    cols = _cols(page)
    assert "د. منى" in cols and "د. أحمد" in cols
    total = _table(page)["__total__"]
    assert total[cols.index("د. منى")] == 2 and total[cols.index("د. أحمد")] == 1 and total[-1] == 3


def _bills(clinic):
    """One cash bill of 200 (paid), and one on a company: 300, of which the
    company covers 240 — the cover is kept as a discount, as billing does."""
    from app.models import Invoice, InvoiceItem, PayerEntity, Payment
    from app.utils.clock import local_today

    with clinic["app"].app_context():
        db = clinic["db"]
        co = PayerEntity(name="شركة النيل", entity_type="insurance")
        db.session.add(co)
        db.session.flush()
        cash = Invoice(invoice_number="B1", patient_id=clinic["ids"]["child"],
                       doctor_id=clinic["ids"]["doctor"], invoice_date=local_today(), status="paid")
        db.session.add(cash)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=cash.id, service_id=clinic["ids"]["exam"],
                                   description="كشف", unit_price=200, quantity=1))
        db.session.add(Payment(invoice_id=cash.id, amount=200, method="cash"))
        ins = Invoice(invoice_number="B2", patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"], invoice_date=local_today(),
                      payer_id=co.id, status="unpaid")
        db.session.add(ins)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=ins.id, service_id=clinic["ids"]["nebul"],
                                   description="جلسة تنفس", unit_price=300, quantity=1,
                                   discount_value=240, payer_amount=240))
        db.session.commit()


def test_cash_against_contracts_with_the_program_s_own_figures(clinic):
    _bills(clinic)
    boss = clinic["sign_in"]("boss")
    rows = _table(boss.get("/reports/builder?src=bills&preset=30&by=payer_kind&m=billed")
                  .get_data(as_text=True))
    assert rows["نقدي"][0] == 200 and rows["تعاقد"][0] == 300 and rows["__total__"][0] == 500
    rows = _table(boss.get("/reports/builder?src=bills&preset=30&by=payer&m=payer_share")
                  .get_data(as_text=True))
    assert rows["شركة النيل"][0] == 240 and rows["نقدي"][0] == 0
    rows = _table(boss.get("/reports/builder?src=bills&preset=30&by=payer&m=family")
                  .get_data(as_text=True))
    assert rows["شركة النيل"][0] == 60 and rows["نقدي"][0] == 200
    # The services, the same way.
    rows = _table(boss.get("/reports/builder?src=lines&preset=30&by=service&m=billed&split=payer_kind")
                  .get_data(as_text=True))
    assert rows["جلسة تنفس"][-1] == 300 and rows["كشف"][-1] == 200
    # A filter keeps one payer only.
    with clinic["app"].app_context():
        from app.models import PayerEntity

        co = PayerEntity.query.one().id
    rows = _table(boss.get(f"/reports/builder?src=bills&preset=30&by=payer&m=billed&f_payer={co}")
                  .get_data(as_text=True))
    assert set(rows) == {"شركة النيل", "__total__"}


def test_a_diagnosis_counts_once_per_visit_and_code(clinic):
    from app.models import Diagnosis

    with clinic["app"].app_context():
        db = clinic["db"]
        for kind in ("working", "final"):
            db.session.add(Diagnosis(visit_id=clinic["ids"]["visit"], code="J21.9",
                                     title="التهاب شعيبات", icd_version="10", dx_type=kind))
        db.session.commit()
    page = clinic["sign_in"]("boss").get(
        "/reports/builder?src=diagnoses&preset=30&by=diagnosis&q=شعيبات").get_data(as_text=True)
    rows = _table(page)
    assert rows["J21.9 — التهاب شعيبات"][0] == 1


def test_descriptive_statistics_of_the_age(clinic):
    from app.models import Patient

    with clinic["app"].app_context():
        db = clinic["db"]
        from app.utils.clock import local_today

        today = local_today()
        kids = []
        for n, months in enumerate((6, 12, 24)):
            p = Patient(patient_number=f"S{n}", full_name=f"ط{n}", gender="female",
                        date_of_birth=today - timedelta(days=round(months * 30.4375)), is_active=True)
            db.session.add(p)
            db.session.flush()
            kids.append(p.id)
        db.session.commit()
    for kid in kids:
        _add_visit(clinic, child=kid)
    page = clinic["sign_in"]("boss").get(
        "/reports/builder?src=visits&preset=30&by=gender&m=age_m&agg=stats").get_data(as_text=True)
    girls = _table(page)["أنثى"]
    n, mean, median, sd, low, high = girls
    assert n == 3 and median == 12 and low == 6 and high == 24
    assert abs(mean - 14) < 0.2 and abs(sd - 9.17) < 0.1


def test_saved_reports_are_the_question_and_run_with_the_opener_s_rights(clinic):
    from app.models import SavedReport

    boss = clinic["sign_in"]("boss")
    boss.post("/reports/builder/save", data={"query": "src=bills&preset=30&by=payer_kind",
                                             "name": "نقدي وتعاقد", "shared": "1"})
    boss.post("/reports/builder/save", data={"query": "src=visits", "name": ""})
    with clinic["app"].app_context():
        rows = SavedReport.query.all()
        assert len(rows) == 1 and rows[0].shared and "src=bills" in rows[0].args
        rid, query = rows[0].id, rows[0].args
    page = boss.get("/reports/builder").get_data(as_text=True)
    assert f'data-saved="{rid}"' in page and "نقدي وتعاقد" in page
    for role in ("doc", "desk", "acct"):
        client = clinic["sign_in"](role)
        if client.get("/reports/builder").status_code != 200:
            continue
        page = client.get("/reports/builder").get_data(as_text=True)
        assert f'data-saved="{rid}"' in page            # shared: listed
        with clinic["app"].app_context():
            from app.models import User

            money = User.query.filter_by(username=role).one().can("finance_manage")
        opened = client.get("/reports/builder?" + query).get_data(as_text=True)
        assert ('value="bills" checked' in opened) == money
        # Only the owner (or an admin) deletes it.
        assert client.post(f"/reports/builder/{rid}/delete").status_code == 403
    boss.post(f"/reports/builder/{rid}/delete")
    with clinic["app"].app_context():
        assert SavedReport.query.count() == 0


def test_csv_and_excel(clinic):
    boss = clinic["sign_in"]("boss")
    csv = boss.get("/reports/builder/export?src=visits&preset=30&by=doctor&fmt=csv")
    assert csv.status_code == 200 and "د. أحمد" in csv.get_data(as_text=True)
    xlsx = boss.get("/reports/builder/export?src=visits&preset=30&by=doctor&fmt=xlsx")
    assert xlsx.status_code == 200 and xlsx.data[:2] == b"PK"


def test_the_door_is_on_the_reports_page(clinic):
    page = clinic["sign_in"]("boss").get("/reports/").get_data(as_text=True)
    assert "data-builder-door" in page and 'data-rep="reports.builder"' in page
