"""Money to the piastre — MONEY_SAFETY_PLAN.md ف-٤.

The owner's own test sheet («بيانات تجريبية علشان فى ناس رافضة انها تطلع
بياناتها»): ten conversions, eight invoices with a discount and a payment, a
bill paid in three parts and refunded twice, the same payment sent twice and
a payment larger than what is owed. Run through the screens the cashier uses,
and every figure compared to the piastre — as a whole number of piastres,
never a float compared with a tolerance.
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


def P(text):
    """Piastres, from the sheet's «125.50»."""
    return int(Decimal(text) * 100)


def p(value):
    """Piastres, from what the program holds."""
    return int((Decimal(str(value)) * 100).to_integral_value())


@pytest.fixture()
def till():
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import Patient, Service, Setting, User
        from app.utils.accounting import ensure_seeded

        ensure_seeded()
        Setting.set("require_shift_to_collect", "0")
        boss = User(username="boss", full_name="المدير", role="admin", is_active=True)
        boss.set_password("secret")
        exam = Service(name="خدمة", category="consultation", price=100, is_active=True,
                       commission_type="none", commission_value=0)
        child = Patient(patient_number="P1", full_name="طفل", gender="male",
                        date_of_birth=date(2024, 1, 1), is_active=True)
        db.session.add_all([boss, exam, child])
        db.session.commit()
        ids = {"child": child.id, "exam": exam.id}

    client = app.test_client()
    client.post("/login", data={"username": "boss", "password": "secret"})
    return {"app": app, "db": db, "ids": ids, "c": client}


def _bill(till, price, discount="0", percent=False, n=[0]):
    from app.models import Invoice, InvoiceItem

    n[0] += 1
    with till["app"].app_context():
        db = till["db"]
        bill = Invoice(patient_id=till["ids"]["child"], invoice_number=f"INV-T{n[0]}",
                       invoice_date=date.today(), status="unpaid")
        db.session.add(bill)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=bill.id, service_id=till["ids"]["exam"],
                                   description="خدمة", quantity=1,
                                   unit_price=float(price), discount_value=float(discount),
                                   discount_is_percent=percent))
        db.session.commit()
        db.session.get(Invoice, bill.id).recalc_status()
        db.session.commit()
        return bill.id


def _pay(till, bill_id, amount, key=None):
    data = {"amount": [amount], "method": ["card"]}
    if key:
        data["form_key"] = key
    return till["c"].post(f"/finance/invoices/{bill_id}/payment", data=data)


def _refund(till, bill_id, amount):
    return till["c"].post(f"/finance/invoices/{bill_id}/refund",
                          data={"amount": amount, "method": "card"})


def _figures(till, bill_id):
    from app.models import Invoice

    with till["app"].app_context():
        bill = till["db"].session.get(Invoice, bill_id)
        return {"total": p(bill.total), "discount": p(bill.discount_total),
                "paid": p(bill.paid), "refunded": p(bill.refunded),
                "balance": p(bill.balance)}


# ------------------------------------------------- 2) invoices and payments --
INVOICES = [
    # number, service, discount, net, paid, left
    ("INV001", "100.00", "0.00", "100.00", "100.00", "0.00"),
    ("INV002", "125.50", "5.50", "120.00", "50.00", "70.00"),
    ("INV003", "250.75", "10.25", "240.50", "100.25", "140.25"),
    ("INV004", "99.99", "0.99", "99.00", "33.33", "65.67"),
    ("INV005", "500.00", "75.50", "424.50", "200.00", "224.50"),
    ("INV006", "10.01", "0.01", "10.00", "9.99", "0.01"),
    ("INV007", "300.00", "0.00", "300.00", "0.00", "300.00"),
    ("INV008", "80.00", "20.00", "60.00", "60.00", "0.00"),
]


@pytest.mark.parametrize("number,service,discount,net,paid,left", INVOICES,
                         ids=[r[0] for r in INVOICES])
def test_each_invoice_to_the_piastre(till, number, service, discount, net, paid, left):
    bill = _bill(till, service, discount)
    if P(paid):
        _pay(till, bill, paid)
    f = _figures(till, bill)
    assert f["discount"] == P(discount)
    assert f["total"] == P(net) == P(service) - P(discount)
    assert f["paid"] == P(paid)
    assert f["balance"] == P(left) == P(net) - P(paid)


# ----------------------------------- 3) a bill paid in parts and refunded --
def test_paid_in_three_parts_then_refunded(till):
    bill = _bill(till, "125.50", "5.50")                    # net 120.00
    _pay(till, bill, "50.25")
    assert _figures(till, bill)["balance"] == P("69.75")     # PAY001
    _pay(till, bill, "20.50")
    assert _figures(till, bill)["balance"] == P("49.25")     # PAY002
    _pay(till, bill, "49.25")
    f = _figures(till, bill)
    assert f["balance"] == 0 and f["paid"] == P("120.00")    # PAY003
    _refund(till, bill, "15.25")                             # REF001
    f = _figures(till, bill)
    assert f["refunded"] == P("15.25") and f["paid"] == P("104.75")
    _refund(till, bill, "120.00")                            # REF002: only what is left
    f = _figures(till, bill)
    assert f["refunded"] == P("120.00") and f["paid"] == 0


def test_the_same_payment_sent_twice_is_taken_once(till):
    bill = _bill(till, "125.50", "5.50")
    from app.utils.once import form_key

    key = form_key()
    _pay(till, bill, "50.25", key=key)
    _pay(till, bill, "50.25", key=key)                       # DUP001
    assert _figures(till, bill)["paid"] == P("50.25")


def test_more_than_is_owed_is_never_kept_as_a_payment(till):
    bill = _bill(till, "125.50", "5.50")
    _pay(till, bill, "50.25")
    _pay(till, bill, "100.00")                               # ERR001: 69.75 left
    f = _figures(till, bill)
    assert f["paid"] == P("120.00") and f["balance"] == 0


# ------------------------------------------- what the sheet's rules imply --
@pytest.mark.parametrize("price,percent,expected", [
    ("0.15", "50", "0.08"), ("0.50", "15", "0.08"), ("125.50", "15", "18.83"),
    ("0.29", "50", "0.15"), ("0.36", "12.5", "0.05"),
])
def test_a_percentage_discount_rounds_half_up(till, price, percent, expected):
    bill = _bill(till, price, percent, percent=True)
    f = _figures(till, bill)
    assert f["discount"] == P(expected)
    assert f["total"] == P(price) - P(expected)


def test_an_amount_with_three_decimals_is_refused_not_rounded(till):
    bill = _bill(till, "100.00")
    _pay(till, bill, "12.345")
    assert _figures(till, bill)["paid"] == 0


# ------------------------------------------------ 1) pounds to piastres --
CONVERSIONS = [("T001", "100.00", 10000), ("T002", "125.50", 12550),
               ("T003", "0.25", 25), ("T004", "0.01", 1), ("T005", "0.10", 10),
               ("T006", "999.99", 99999), ("T007", "0.00", 0),
               ("T008", "1500.75", 150075), ("T009", "12.34", 1234),
               ("T010", "87.65", 8765)]


@pytest.mark.parametrize("case,pounds_text,expected", CONVERSIONS,
                         ids=[c[0] for c in CONVERSIONS])
def test_pounds_to_piastres(case, pounds_text, expected):
    """From the text and from the float the database hands back — both."""
    from app.utils import money

    assert money.to_piastres(pounds_text) == expected
    assert money.to_piastres(float(pounds_text)) == expected
    assert money.pounds(expected) == float(pounds_text)


def test_a_third_decimal_is_refused_never_rounded():
    from app.utils import money

    for text in ("12.345", "0.001", "99.999"):
        with pytest.raises(money.MoneyError, match="too_precise"):
            money.parse_amount(text)
    assert money.parse_amount("١٢٫٥٠") == 12.5          # Arabic digits
    assert money.parse_amount("1,500.75") == 1500.75
    assert money.total([0.10] * 1000) == 100.0          # no drift in a long sum


# ------------------------------------------------------- the money check --
@pytest.fixture()
def books(tmp_path, monkeypatch):
    """An on-disk clinic — the fix takes real backups."""
    import config as app_config
    from app import create_app
    from app.extensions import db

    original = app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(tmp_path / "c.db")
    monkeypatch.setenv("BACKUP_PASSWORD", "")
    app = create_app("development")
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, BACKUP_PASSWORD="")
    static = tmp_path / "static"
    (static / "uploads").mkdir(parents=True)
    app.static_folder = str(static)
    app.instance_path = str(tmp_path / "instance")
    os.makedirs(app.instance_path, exist_ok=True)
    with app.app_context():
        db.create_all()
        from app.models import Invoice, InvoiceItem, Patient, PatientCredit, Payment, User
        from app.utils.accounting import ensure_seeded

        ensure_seeded()
        boss = User(username="boss", full_name="المدير", role="admin", is_active=True)
        boss.set_password("secret")
        kid = Patient(patient_number="P1", full_name="طفل", gender="male",
                      date_of_birth=date(2024, 1, 1), is_active=True)
        staff = Patient(patient_number="S1", full_name="موظفة", gender="female",
                        date_of_birth=date(1990, 1, 1), is_active=True)
        db.session.add_all([boss, kid, staff])
        db.session.flush()
        bill = Invoice(patient_id=kid.id, invoice_number="INV-B1",
                       invoice_date=date.today(), status="unpaid")
        db.session.add(bill)
        db.session.flush()
        # A share worked out before the piastre rule, stored as it came.
        item = InvoiceItem(invoice_id=bill.id, description="خدمة", quantity=1,
                           unit_price=125.5, discount_value=0, commission_amount=18.825)
        db.session.add(item)
        db.session.add(Payment(invoice_id=bill.id, amount=50.25, method="card"))
        # A member of staff who took a service and settles at the month's end.
        db.session.add(PatientCredit(patient_id=staff.id, kind="out", amount=70,
                                     method="cash"))
        db.session.commit()
        ids = {"item": item.id, "bill": bill.id, "staff": staff.id}
        yield {"app": app, "db": db, "ids": ids}
    app_config.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = original


def test_the_check_finds_a_stored_third_decimal_and_reads_only(books):
    from app.models import InvoiceItem
    from app.utils import money_check

    with books["app"].app_context():
        report = money_check.scan()
        off = [(r["table"], r["column"], r["id"], r["becomes"]) for r in report["off"]]
        assert off == [("invoice_items", "commission_amount", books["ids"]["item"], 18.83)]
        assert books["db"].session.get(InvoiceItem, books["ids"]["item"]).commission_amount == 18.825


def test_the_fix_rounds_with_backups_an_audit_line_and_equal_totals(books):
    from app.models import ActivityLog, InvoiceItem
    from app.utils import money_check
    from app.utils.backups import list_backups

    with books["app"].app_context():
        result = money_check.fix()
        assert len(result["changed"]) == 1 and result["totals_match"]
        assert result["before_backup"] and result["after_backup"]
        names = {b["name"] for b in list_backups()}
        assert {result["before_backup"], result["after_backup"]} <= names
        books["db"].session.expire_all()
        assert books["db"].session.get(InvoiceItem, books["ids"]["item"]).commission_amount == 18.83
        line = ActivityLog.query.filter_by(action="money.fix").one()
        assert line.entity == "invoice_items" and line.entity_id == books["ids"]["item"]
        assert "18.825" in line.detail and "18.83" in line.detail
        assert money_check.scan()["clean"]
        # Run again: nothing to do, nothing taken.
        again = money_check.fix()
        assert again["changed"] == [] and again["before_backup"] is None


def test_an_account_below_zero_is_listed_and_never_changed(books):
    """«فى ناس زي العاملين ممكن ياخدو خدمة وتفضل بالسالب لغاية ما يتسوى الحساب»."""
    from app.models import PatientCredit
    from app.utils import money_check

    with books["app"].app_context():
        assert money_check.scan()["negative"] == [books["ids"]["staff"]]
        money_check.fix()
        row = PatientCredit.query.filter_by(patient_id=books["ids"]["staff"]).one()
        assert row.amount == 70 and row.kind == "out"


def test_the_check_catches_unbalanced_books_and_an_overpaid_bill(books):
    from app.models import Payment
    from app.models.accounting import Account, JournalEntry, JournalLine
    from app.utils import money_check

    with books["app"].app_context():
        db = books["db"]
        accounts = Account.query.limit(2).all()
        good = JournalEntry(entry_number="JE-OK", memo="—")
        bad = JournalEntry(entry_number="JE-BAD", memo="—")
        db.session.add_all([good, bad])
        db.session.flush()
        db.session.add_all([
            JournalLine(entry_id=good.id, account_id=accounts[0].id, debit=0.1, credit=0),
            JournalLine(entry_id=good.id, account_id=accounts[0].id, debit=0.2, credit=0),
            JournalLine(entry_id=good.id, account_id=accounts[1].id, debit=0, credit=0.3),
            JournalLine(entry_id=bad.id, account_id=accounts[0].id, debit=100.01, credit=0),
            JournalLine(entry_id=bad.id, account_id=accounts[1].id, debit=0, credit=100)])
        db.session.add(Payment(invoice_id=books["ids"]["bill"], amount=100, method="card"))
        db.session.commit()
        report = money_check.scan()
        # 0.1 + 0.2 against 0.3 is balanced to the piastre — the float sum
        # 0.30000000000000004 would have called it off.
        assert report["unbalanced"] == [bad.id]
        assert books["ids"]["bill"] in report["overpaid"]


def test_the_screen_reads_then_fixes(books):
    client = books["app"].test_client()
    client.post("/login", data={"username": "boss", "password": "secret"})
    data = client.get("/settings/data").get_data(as_text=True)
    assert "data-money-check-door" in data and "/settings/data/money-check" in data
    page = client.get("/settings/data/money-check").get_data(as_text=True)
    assert "data-money-off" in page and "data-money-fix" in page
    assert 'data-money-owing="1"' in page
    page = client.post("/settings/data/money-check", follow_redirects=True).get_data(as_text=True)
    assert "data-money-fixed" in page and 'data-money-totals="match"' in page
    assert "data-money-clean" in page
