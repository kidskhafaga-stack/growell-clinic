"""One collection screen, and money can come back out of it.

Three things, reported together while looking at the checkout screen.

**"This screen should be the primary one, and if there is another, cancel
it."** There was another. The invoice *builder* did the same job with a patient
dropdown, a doctor dropdown, a payer, notes and a set of blank lines — and no
payment section at all, so you saved an invoice, opened it, and paid from a
third screen. It is gone. Every door that already knows the patient goes
straight to their checkout; the one door that cannot know — "collect" from the
invoices list — asks that single question and nothing else.

**"And put the refund in it, or find a way for refunds."** Refunding lived only
on the invoice view, which reception reaches by knowing an invoice number. So
the one thing a family asks for at the desk — *we paid for a vaccine we're not
taking* — sent the cashier hunting through a list. Money goes back out on the
screen it came in on, and the refusals return there too: a cashier told "bad
amount" and then dumped on a screen they never opened has lost the family as
well as the typo.

**"The quantity here isn't clear — there are up/down arrows and the number
isn't even visible."** The column was 70px. Once the browser drew its own
spinner inside the box there was no room left for the digits.
"""
import os
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The clinic's today, not the server's — the same clock the
# screens filter by. See conftest.py.
from app.utils.clock import local_today  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def desk(clinic):
    return clinic["sign_in"]("desk")


@pytest.fixture()
def boss(clinic):
    return clinic["sign_in"]("boss")


@pytest.fixture()
def owing(clinic):
    """A patient with an unbilled procedure — somebody reception owes a bill."""
    from app.models import Service, VisitService

    with clinic["app"].app_context():
        svc = clinic["db"].session.get(Service, clinic["ids"]["nebul"])
        clinic["db"].session.add(VisitService(
            visit_id=clinic["ids"]["visit"], service_id=svc.id,
            name=svc.name, quantity=1))
        clinic["db"].session.commit()
    return clinic


@pytest.fixture()
def paid_invoice(clinic):
    """An invoice with money actually collected on it."""
    from app.models import CashierShift, Invoice, InvoiceItem, Payment

    with clinic["app"].app_context():
        db = clinic["db"]
        shift = CashierShift(opened_by=clinic["ids"]["desk"], opening_float=0,
                             status="open")
        db.session.add(shift)
        db.session.flush()
        inv = Invoice(invoice_number="INV-REFUND-1",
                      patient_id=clinic["ids"]["child"],
                      doctor_id=clinic["ids"]["doctor"],
                      created_by=clinic["ids"]["desk"])
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="جلسة تنفس",
                                   unit_price=150, quantity=1))
        db.session.add(Payment(invoice_id=inv.id, amount=150, method="cash",
                               received_by=clinic["ids"]["desk"],
                               shift_id=shift.id))
        db.session.flush()
        inv.recalc_status()
        db.session.commit()
        return inv.id


def _read(*parts):
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, *parts), encoding="utf-8") as fh:
        return fh.read()


# ======================================================= the second screen ==
def test_the_invoice_builder_is_gone(clinic):
    """It was a second way to do the same job, and the worse one: it made you
    choose the patient standing in front of you and had nowhere to pay."""
    with clinic["app"].app_context():
        rules = {str(r) for r in clinic["app"].url_map.iter_rules()}
    assert "/finance/invoices/new" not in rules


def test_its_screen_went_with_it(clinic):
    """A template left behind is a screen somebody re-links to in six months."""
    root = os.path.join(os.path.dirname(__file__), "..")
    assert not os.path.exists(
        os.path.join(root, "app", "templates", "finance", "invoice_form.html"))


def test_nothing_still_points_at_it(clinic):
    """A dead link is worse than a second screen: it is a 500 at the desk."""
    import re

    root = os.path.join(os.path.dirname(__file__), "..", "app")
    for folder, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith((".html", ".py")):
                continue
            path = os.path.join(folder, fn)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            assert not re.search(r"url_for\(\s*['\"]finance\.invoice_new", body), path


def test_the_appointment_row_has_one_collect_button(clinic):
    """It had two side by side, going to two different screens that collect
    the same money."""
    board = _read("app", "templates", "appointments", "board.html")
    assert "finance.checkout" in board
    assert "invoice_new" not in board


def test_the_visit_bills_through_the_checkout(clinic):
    view = _read("app", "templates", "visits", "view.html")
    assert "finance.collect" in view


# ============================================== the one door that must ask ==
def test_there_is_a_door_for_when_nobody_is_named(clinic, desk):
    """"Collect" from the invoices list starts with no patient. Somebody has to
    be asked — but only that, and only here."""
    assert desk.get("/finance/collect").status_code == 200


def test_the_chooser_asks_that_and_nothing_else(clinic, desk):
    """The screen it replaced also wanted a doctor, a payer, notes and a set of
    blank lines, with a family at the desk."""
    body = desk.get("/finance/collect").get_data(as_text=True)
    assert 'name="doctor_id"' not in body
    assert 'name="payer_id"' not in body
    assert 'name="line_price"' not in body


def test_the_chooser_leads_to_the_checkout(clinic, desk):
    body = desk.get("/finance/collect").get_data(as_text=True)
    assert f"/finance/collect/{clinic['ids']['child']}" in body


def test_whoever_owes_money_is_already_on_it(owing, desk):
    """Almost always who reception is looking for, so they are there before
    anybody types."""
    body = desk.get("/finance/collect").get_data(as_text=True)
    assert "جلسة تنفس" in body


def test_the_search_covers_what_a_parent_says_at_the_desk(clinic, desk):
    """The name, the file number, the phone — not just the name."""
    from app.models import Patient

    body = desk.get("/finance/collect").get_data(as_text=True)
    with clinic["app"].app_context():
        child = clinic["db"].session.get(Patient, clinic["ids"]["child"])
        number = child.patient_number
    assert number in body


def test_the_invoices_list_collects_instead_of_building(clinic):
    page = _read("app", "templates", "finance", "invoices.html")
    assert "finance.collect_pick" in page


# ================================================== money back, same screen =
def test_the_refund_is_on_the_collection_screen(owing, desk, paid_invoice):
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    with owing["app"].test_request_context("/"):
        from app.i18n import t
        assert t("invoices.refund") in body
    assert f"/finance/invoices/{paid_invoice}/refund" in body


def test_only_invoices_with_money_on_them_are_offered(clinic, desk):
    """Refunding an unpaid invoice is not a refund, it is a discount, and it
    has its own way in."""
    from app.models import Invoice, InvoiceItem

    with clinic["app"].app_context():
        db = clinic["db"]
        inv = Invoice(invoice_number="INV-UNPAID-1",
                      patient_id=clinic["ids"]["child"],
                      created_by=clinic["ids"]["desk"])
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=inv.id, description="كشف",
                                   unit_price=200, quantity=1))
        db.session.commit()
        unpaid_id = inv.id

    body = desk.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert f"/finance/invoices/{unpaid_id}/refund" not in body


def test_no_refund_section_when_nothing_was_ever_paid(clinic, desk):
    """An empty box labelled "refund" invites somebody to go looking for the
    invoice on another screen — which is the habit this removes."""
    body = desk.get(f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)
    assert "/refund" not in body


def test_the_refund_form_cannot_ask_for_more_than_came_in(desk, owing, paid_invoice):
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    assert 'max="150.00"' in body


def test_an_admins_refund_goes_through_and_comes_back_here(boss, clinic, paid_invoice):
    from app.models import Invoice

    reply = boss.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "50", "method": "cash", "next": "collect"})
    assert reply.status_code == 302
    assert f"/finance/collect/{clinic['ids']['child']}" in reply.headers["Location"]

    with clinic["app"].app_context():
        inv = clinic["db"].session.get(Invoice, paid_invoice)
        assert inv.paid == 100


def test_a_cashiers_refund_becomes_a_request_and_comes_back_here(desk, clinic,
                                                                 paid_invoice):
    """Unless the clinic turned approval off, cash does not leave the drawer on
    a cashier's say-so — but they still must not be thrown onto another screen
    for asking.

    The whole 150 rather than a token 50: a partial refund under the clinic's
    threshold now goes straight through, so a small one would no longer be a
    request and this test would be measuring nothing. A cashier handing back
    everything they took is the act this screen is about.
    """
    from app.models import Invoice, RefundRequest

    reply = desk.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "150", "method": "cash", "next": "collect"})
    assert f"/finance/collect/{clinic['ids']['child']}" in reply.headers["Location"]

    with clinic["app"].app_context():
        assert RefundRequest.query.filter_by(invoice_id=paid_invoice).count() == 1
        inv = clinic["db"].session.get(Invoice, paid_invoice)
        assert inv.paid == 150, "money left the drawer without approval"
        assert inv.status != "refunded", "the invoice closed before approval"


def test_the_cashier_is_told_before_typing_that_it_needs_approval(desk, owing,
                                                                  paid_invoice):
    """Said before the form, not after the click. Somebody who types an amount
    and expects cash to come out should know a manager has to say yes."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    with owing["app"].test_request_context("/"):
        from app.i18n import t
        assert t("checkout.refund_approval") in body


def test_an_admin_is_not_told_that(boss, owing, paid_invoice):
    """A warning that is always there is furniture."""
    body = boss.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    with owing["app"].test_request_context("/"):
        from app.i18n import t
        assert t("checkout.refund_approval") not in body


def test_a_bad_amount_returns_to_the_desk_too(boss, clinic, paid_invoice):
    """The refusal has to go back the same way as the success, or a typo costs
    the cashier the screen they were working on."""
    reply = boss.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "0", "method": "cash", "next": "collect"})
    assert f"/finance/collect/{clinic['ids']['child']}" in reply.headers["Location"]


def test_the_invoice_view_refund_still_lands_where_it_did(boss, paid_invoice):
    """Adding a door must not move the existing one."""
    reply = boss.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "10", "method": "cash"})
    assert f"/finance/invoices/{paid_invoice}" in reply.headers["Location"]


def test_the_refund_form_is_not_nested_in_the_collection_form(owing, desk,
                                                              paid_invoice):
    """A form inside a form is invalid HTML and the browser silently drops one
    of them — here that would be either the refund or the whole collection."""
    body = desk.get(f"/finance/collect/{owing['ids']['child']}").get_data(as_text=True)
    refund_at = body.index("/refund")
    assert body.rindex("</form>", 0, refund_at) > body.index("<form"), \
        "the refund form opens while the collection form is still open"


# ============================================================ the quantity ==
def test_the_quantity_box_has_room_for_its_digits(clinic):
    """70px, minus the spinner arrows the browser draws inside it, left the
    number itself invisible."""
    page = _read("app", "templates", "finance", "checkout.html")
    qty = page[page.index("line_qty") - 400:page.index("line_qty") + 200]
    assert "min-width:84px" in qty


def test_the_quantity_column_was_widened_with_it(clinic):
    """Widening the input inside a 70px column just clips it instead."""
    page = _read("app", "templates", "finance", "checkout.html")
    head = page[:page.index("line_qty")]
    assert "width:110px" in head


def test_the_quantity_still_multiplies(owing, desk, clinic):
    """A styling change that quietly stopped the number being submitted would
    bill every family for one of everything."""
    from app.models import CashierShift, Invoice

    with clinic["app"].app_context():
        clinic["db"].session.add(CashierShift(
            opened_by=clinic["ids"]["desk"], opening_float=0, status="open"))
        clinic["db"].session.commit()

    desk.post(f"/finance/collect/{owing['ids']['child']}", data={
        "line_desc": "جلسة تنفس", "line_service_id": str(clinic["ids"]["nebul"]),
        "line_price": "150", "line_qty": "3", "line_no_commission": "0",
        "line_brand_id": "", "line_dose_id": "", "line_vs_id": "",
        "line_dose_number": "",
        "amount": "450", "method": "cash", "discount_id": "none",
    }, follow_redirects=True)

    with clinic["app"].app_context():
        invoice = (Invoice.query.filter_by(patient_id=clinic["ids"]["child"])
                   .order_by(Invoice.id.desc()).first())
        assert invoice.total == 450


# ==================================================== the screen still works
def test_the_appointment_door_still_opens(clinic, desk):
    from app.models import Appointment

    with clinic["app"].app_context():
        appt = Appointment(patient_id=clinic["ids"]["child"],
                           doctor_id=clinic["ids"]["doctor"],
                           appt_date=local_today(), appt_time=time(10, 0),
                           appt_type="new", status="scheduled")
        clinic["db"].session.add(appt)
        clinic["db"].session.commit()
        appt_id = appt.id

    assert desk.get(f"/finance/checkout/{appt_id}").status_code == 200


def test_both_languages_carry_the_new_words(clinic):
    import json

    keys = ["refund_approval", "pick_title", "pick_hint", "pick_search",
            "pick_none", "pick_owing"]
    for lang in ("ar", "en"):
        data = json.loads(_read("app", "i18n", "locales", f"{lang}.json"))
        for key in keys:
            assert data["checkout"].get(key), f"{lang}.checkout.{key}"


def test_reception_can_reach_the_refund_at_all(desk, paid_invoice):
    """It was behind `module_required("finance")`, which reception does not
    have — they hold the `cashier` capability. So the button sat on their
    screen and 403'd on submit, and the approval workflow below it was
    unreachable for the only people a family ever asks for money back from."""
    reply = desk.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "50", "method": "cash", "next": "collect"})
    assert reply.status_code != 403


def test_a_cashier_may_refund_directly_only_when_the_clinic_says_so(desk, clinic,
                                                                    paid_invoice):
    """The one behaviour the widened gate changes, stated out loud: with
    approval switched off, a cashier's refund is a refund. That is what the
    setting is named after."""
    from app.models import Invoice, Setting

    with clinic["app"].app_context():
        Setting.set("refund_approval_required", "0")
        clinic["db"].session.commit()

    desk.post(f"/finance/invoices/{paid_invoice}/refund", data={
        "amount": "50", "method": "cash", "next": "collect"})

    with clinic["app"].app_context():
        assert clinic["db"].session.get(Invoice, paid_invoice).paid == 100
