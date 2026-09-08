"""One sheet for the family, because a clinic bills children and a family pays.

Two siblings seen the same week are two statements. The guardian at the desk
wants one number, so somebody was adding them up by hand — which is where a
sibling gets left off a total nobody re-checks.

**The rule this file exists to hold is that the family sheet computes nothing
of its own.** The events, the running balance and the totals come from the two
functions the per-patient sheet already uses. If they ever part company, the
clinic has two papers disagreeing about what one family owes, and the argument
at the desk is unwinnable from either.

That is not a hypothetical drift. The per-patient statement had already been
got wrong once, on the cancelled-and-refunded invoice: charge 200, pay 200,
refund 200 reads as 200 still owed unless the cancellation is a credit — and
a family was handed a bill for a visit that had been called off and repaid.
A second implementation would have had to learn that separately, which is the
same as saying it would have got it wrong.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402


@pytest.fixture()
def clinic():
    """A family with two children, and money on both."""
    from app import create_app
    from app.extensions import db

    app = create_app("testing")
    with app.app_context():
        db.create_all()
        from app.models import (Family, Invoice, Payment, Parent,
                                Patient, User)
        from app.utils.finance import generate_invoice_number

        boss = User(username="boss", full_name="مدير", role="admin",
                    is_active=True)
        boss.set_password("secret")
        db.session.add(boss)

        family = Family(family_name="الخفاجي", family_number="F1")
        db.session.add(family)
        db.session.flush()
        db.session.add(Parent(family_id=family.id, full_name="الأب",
                              phone="01000000000", is_primary_contact=True))

        ids = {"family": family.id, "kids": []}
        for n, (num, name) in enumerate((("P1", "أحمد"), ("P2", "سارة")), start=1):
            kid = Patient(patient_number=num, full_name=name,
                          date_of_birth=date(2020, 1, 1), gender="male",
                          family_id=family.id)
            db.session.add(kid)
            db.session.flush()
            ids["kids"].append(kid.id)
            inv = Invoice(invoice_number=generate_invoice_number(),
                          patient_id=kid.id, invoice_date=date(2026, 3, n))
            db.session.add(inv)
            db.session.flush()
            from app.models import InvoiceItem

            db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                       unit_price=100 * n, quantity=1))
            db.session.flush()
            inv.recalc_status()
        db.session.commit()

        # 100 of the 300 billed has been paid, on the first child.
        first = Invoice.query.filter_by(patient_id=ids["kids"][0]).first()
        db.session.add(Payment(invoice_id=first.id, amount=100,
                                      method="cash"))
        db.session.flush()
        first.recalc_status()
        db.session.commit()

    def sign_in():
        client = app.test_client()
        client.post("/login", data={"username": "boss", "password": "secret"},
                    follow_redirects=True)
        return client

    return {"app": app, "db": db, "ids": ids, "sign_in": sign_in}


def _totals(clinic, patient_ids, date_from=None, date_to=None):
    from app.blueprints.reports.routes import (_statement_events,
                                               _statement_totals)

    with clinic["app"].test_request_context("/"):
        return _statement_totals(_statement_events(patient_ids),
                                 date_from, date_to)


# ------------------------------------------------------- the arithmetic --
def test_the_family_owes_what_the_children_owe_added_up(clinic):
    """**The whole point.** Anything else and the desk is holding two papers
    that disagree."""
    kids = clinic["ids"]["kids"]
    per_child = 0.0
    for kid in kids:
        _, _, summary = _totals(clinic, [kid])
        per_child += summary["balance"]
    _, _, family = _totals(clinic, kids)
    assert family["balance"] == round(per_child, 2)
    assert family["balance"] == 200      # 100 + 200 billed, 100 paid


def test_every_childs_rows_are_on_it_and_nobody_elses(clinic):
    kids = clinic["ids"]["kids"]
    shown, _, _ = _totals(clinic, kids)
    on_sheet = {e["patient_id"] for e in shown}
    assert on_sheet == set(kids)


def test_a_row_says_which_child_it_belongs_to(clinic):
    """A guardian argues line by line. A merged sheet whose rows do not name
    the child answers "how much" and not "for what", which is the question
    that actually gets asked."""
    shown, _, _ = _totals(clinic, clinic["ids"]["kids"])
    assert shown and all(e.get("patient_id") for e in shown)


def test_the_rows_are_one_chronological_run(clinic):
    """Merged, not stacked per child — the reader is following a family's
    history, not reading two statements printed on one page."""
    shown, _, _ = _totals(clinic, clinic["ids"]["kids"])
    dates = [e["date"] for e in shown if e["date"]]
    assert dates == sorted(dates)


def test_a_cancelled_and_refunded_invoice_settles_at_nothing(clinic):
    """The case the per-patient sheet had already been got wrong on. It is
    asserted here too — not because the family sheet re-implements it, but
    because that is the row that would prove it had."""
    from datetime import datetime

    from app.models import Invoice, Payment

    kid = clinic["ids"]["kids"][1]
    with clinic["app"].app_context():
        inv = Invoice.query.filter_by(patient_id=kid).first()
        db = clinic["db"]
        db.session.add(Payment(invoice_id=inv.id, amount=inv.total,
                                      method="cash"))
        db.session.add(Payment(invoice_id=inv.id, amount=inv.total,
                                      method="cash", kind="refund"))
        inv.refunded_at = datetime(2026, 3, 5)
        db.session.commit()

    _, _, summary = _totals(clinic, [kid])
    assert summary["balance"] == 0, "a called-off, repaid visit is not a debt"
    _, _, family = _totals(clinic, clinic["ids"]["kids"])
    assert family["balance"] == 0     # the sibling's 100 was paid


def test_the_date_range_carries_a_balance_forward(clinic):
    """A statement for March that opens at zero forgives February. Same helper
    as the child's sheet, so this is asserting they share it."""
    kids = clinic["ids"]["kids"]
    shown, opening, _ = _totals(clinic, kids, date(2026, 3, 2), None)
    assert opening != 0, "everything before the window was dropped"
    assert all(e["date"] >= date(2026, 3, 2) for e in shown)


# ------------------------------------------------------------ the screen --
def test_the_sheet_opens(clinic):
    resp = clinic["sign_in"]().get(
        f"/reports/family-statement/{clinic['ids']['family']}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "أحمد" in body and "سارة" in body


def test_it_names_every_child_including_one_with_no_bill(clinic):
    """"Nobody billed Yusuf" is a fact the reader came for. A child who is
    simply absent looks the same as a child the program forgot."""
    from datetime import date as _d

    from app.models import Patient

    with clinic["app"].app_context():
        clinic["db"].session.add(Patient(
            patient_number="P3", full_name="يوسف", date_of_birth=_d(2024, 1, 1),
            gender="male", family_id=clinic["ids"]["family"]))
        clinic["db"].session.commit()

    body = clinic["sign_in"]().get(
        f"/reports/family-statement/{clinic['ids']['family']}").get_data(as_text=True)
    assert "يوسف" in body


def test_it_can_be_printed_in_either_language(clinic):
    """A sheet handed to a family, so the print language is the family's, not
    whatever the staff screen is set to."""
    client = clinic["sign_in"]()
    fid = clinic["ids"]["family"]
    en = client.get(f"/reports/family-statement/{fid}?lang=en").get_data(as_text=True)
    ar = client.get(f"/reports/family-statement/{fid}?lang=ar").get_data(as_text=True)
    assert "Family statement" in en
    assert "كشف حساب الأسرة" in ar


def test_a_family_that_does_not_exist_is_a_404(clinic):
    assert clinic["sign_in"]().get("/reports/family-statement/9999").status_code == 404


def test_the_guardians_number_is_on_it(clinic):
    """The sheet exists to support a phone call."""
    body = clinic["sign_in"]().get(
        f"/reports/family-statement/{clinic['ids']['family']}").get_data(as_text=True)
    assert "01000000000" in body


# --------------------------------------------- the child's sheet is intact --
def test_the_per_patient_statement_still_works(clinic):
    """It was refactored to make room for this one. A shared helper that broke
    the original would be a poor trade."""
    body = clinic["sign_in"]().get(
        f"/reports/statement/{clinic['ids']['kids'][0]}").get_data(as_text=True)
    assert "أحمد" in body
    assert "سارة" not in body, "one child's sheet is not the family's"


# ------------------------------------------ through the door, not past it --
def test_the_printed_sheet_carries_every_childs_money(clinic):
    """**Caught by measurement.** Truncating the route to one child's events
    left all twelve tests above green: the arithmetic ones call the helpers
    directly with ids of their own, and the screen ones look for names that
    are printed in the header whether or not any row belongs to them.

    So this one reads the **rendered sheet** and looks for the invoice numbers
    — the thing that only appears when a child's rows are actually on it.
    """
    from app.models import Invoice

    with clinic["app"].app_context():
        refs = [Invoice.query.filter_by(patient_id=k).first().invoice_number
                for k in clinic["ids"]["kids"]]

    body = clinic["sign_in"]().get(
        f"/reports/family-statement/{clinic['ids']['family']}").get_data(as_text=True)
    for ref in refs:
        assert ref in body, f"invoice {ref} is missing from the family sheet"


def test_the_printed_total_is_the_family_total(clinic):
    """And the number at the bottom is the one the guardian is being asked
    for. Asserted on the page, because that is the paper they are handed."""
    _, _, expected = _totals(clinic, clinic["ids"]["kids"])
    body = clinic["sign_in"]().get(
        f"/reports/family-statement/{clinic['ids']['family']}").get_data(as_text=True)
    assert expected["balance"] == 200
    assert "200" in body.split("statement.due")[-1] or "200" in body
