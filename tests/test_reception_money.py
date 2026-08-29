"""Reception's day at the till, one case at a time.

The money screens are where a mistake is expensive and quiet: an invoice paid
twice, a refund larger than what was collected, a drawer that doesn't
reconcile at close. Each of these is a branch somebody wrote once and nobody
walks again by hand.

What's checked here is what reception can actually do wrong on purpose or by
accident — a double-click, a 500 note for a 150 bill, refunding a bill that
was only half paid, collecting with no shift open — and what the program is
supposed to do about it.
"""
from datetime import date

import pytest

# One clock. The program books, bills and lists "today" with
# ``local_today``; a test that builds or asserts with ``date.today``
# sits on a different day whenever the server's zone and the clinic's
# disagree — on a UTC server and a Cairo clinic, every night after
# 22:00. These twenty failed on the hour rather than on a change.
from app.utils.clock import local_today  # noqa: E402



# --------------------------------------------------------------- helpers --
def _open_shift(client, float_amount="100"):
    return client.post("/finance/shift/open",
                       data={"opening_float": float_amount},
                       follow_redirects=True)


def _bill(client, ids, price="200", service=None, quantity="1", **extra):
    """Reception raises an invoice for the child.

    Through the collection screen, which is now the only one — the invoice
    builder these tests were written against is gone. Raising the bill without
    paying it (no ``amount``) is deliberate: most of what follows is about what
    happens to a bill *after* it exists, so the payment has to be a separate
    step the test can vary.
    """
    data = {"patient_id": ids["child"], "doctor_id": ids["doctor"],
            "line_service_id": [str(service or ids["exam"])],
            "line_desc": ["كشف"], "line_price": [price],
            "line_qty": [quantity], "line_no_commission": ["0"],
            "line_brand_id": [""], "line_dose_id": [""], "line_vs_id": [""],
            "line_dose_number": [""], "discount_id": "none"}
    data.update(extra)
    return client.post(f"/finance/collect/{ids['child']}", data=data,
                       follow_redirects=True)


def _the_invoice(clinic):
    from app.models import Invoice

    with clinic["app"].app_context():
        return Invoice.query.order_by(Invoice.id).first().id


def _state(clinic, invoice_id):
    from app.models import Invoice

    with clinic["app"].app_context():
        inv = clinic["db"].session.get(Invoice, invoice_id)
        return {"total": inv.total, "paid": inv.paid, "balance": inv.balance,
                "status": inv.status, "refunded": inv.refunded,
                "tendered": inv.tendered, "change": inv.change_given,
                "payments": len(inv.payments),
                "commission": inv.doctor_share_total}


def _pay(client, invoice_id, amount, method="cash"):
    return client.post(f"/finance/invoices/{invoice_id}/payment",
                       data={"amount": amount, "method": method},
                       follow_redirects=True)


def _refund(client, invoice_id, amount, method="cash"):
    return client.post(f"/finance/invoices/{invoice_id}/refund",
                       data={"amount": amount, "method": method},
                       follow_redirects=True)


def _every_refund_needs_approval(clinic):
    """Turn off the small-refund shortcut for the tests about approval.

    A partial refund under the clinic's threshold now goes straight through —
    handing back fifty pounds of a vaccine difference should not stop the
    queue while a manager is found. The tests below are about the *approval*
    path, not about that line, so they pin the threshold at zero: every refund
    waits, which is exactly how the program behaved before the line existed.
    """
    from app.extensions import db
    from app.models import Setting

    with clinic["app"].app_context():
        Setting.set("refund_no_approval_under", "0")
        db.session.commit()


# ------------------------------------------------------------ the invoice --
def test_the_bill_carries_the_doctors_share(clinic):
    """The commission is snapshotted when the line is billed, so changing the
    service's rate next month never rewrites what this doctor earned today."""
    desk = clinic["sign_in"]("boss")
    _bill(desk, clinic["ids"])
    assert _state(clinic, _the_invoice(clinic))["commission"] == 80.0   # 40% of 200


def test_a_bill_with_no_lines_is_not_a_bill(clinic):
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    desk.post(f"/finance/collect/{clinic['ids']['child']}",
              data={"discount_id": "none"}, follow_redirects=True)
    with clinic["app"].app_context():
        assert Invoice.query.count() == 0


def test_the_second_charge_of_the_day_joins_the_same_bill(clinic):
    """A vaccine given after the exam was already billed must not raise a
    second invoice for the same child on the same day — the family gets one
    paper, and the day reconciles as one."""
    from app.models import Invoice

    desk = clinic["sign_in"]("boss")
    _bill(desk, clinic["ids"])
    _bill(desk, clinic["ids"], price="150", service=clinic["ids"]["nebul"])
    with clinic["app"].app_context():
        assert Invoice.query.count() == 1
        assert len(Invoice.query.one().items) == 2
    assert _state(clinic, _the_invoice(clinic))["total"] == 350.0


# ---------------------------------------------------------- collecting it --
def test_no_open_shift_means_no_money_in_the_drawer(clinic):
    """Every collection belongs to a till session. Without one there is
    nowhere to book the cash, and nothing to reconcile it against at close."""
    desk = clinic["sign_in"]("boss")
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    assert _state(clinic, invoice)["payments"] == 0


def test_paying_part_of_it_leaves_the_rest_owing(clinic):
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "50")
    state = _state(clinic, invoice)
    assert (state["paid"], state["balance"], state["status"]) == (50.0, 150.0,
                                                                  "partial")


def test_paying_it_all_settles_it(clinic):
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    state = _state(clinic, invoice)
    assert (state["paid"], state["balance"], state["status"]) == (200.0, 0.0,
                                                                  "paid")


def test_a_big_note_is_change_not_an_overpayment(clinic):
    """The patient hands over 500 for a 200 bill. The invoice takes 200; the
    other 300 is change on the counter, recorded so the receipt and the
    review can both see what happened."""
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "500")
    state = _state(clinic, invoice)
    assert state["paid"] == 200.0 and state["balance"] == 0.0
    assert state["tendered"] == 500.0 and state["change"] == 300.0


def test_the_change_is_said_out_loud(clinic):
    """A cashier who isn't told hands back nothing, and the patient leaves
    300 short."""
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    body = _pay(desk, _the_invoice(clinic), "500").get_data(as_text=True)
    assert "300" in body


def test_a_double_click_does_not_pay_twice(clinic):
    """A stale form or an impatient second click must not push the invoice
    into negative balance — which reads as the clinic owing the patient."""
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    _pay(desk, invoice, "200")
    state = _state(clinic, invoice)
    assert state["paid"] == 200.0 and state["balance"] == 0.0
    assert state["payments"] == 1


@pytest.mark.parametrize("amount", ["0", "-50", "", "abc"])
def test_a_nonsense_amount_collects_nothing(clinic, amount):
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, amount)
    assert _state(clinic, invoice)["payments"] == 0


def test_one_bill_can_be_settled_with_two_methods(clinic):
    """150 cash and 50 on the card is one collection, not two visits."""
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    desk.post(f"/finance/invoices/{invoice}/payment",
              data={"amount": ["150", "50"], "method": ["cash", "card"]},
              follow_redirects=True)
    state = _state(clinic, invoice)
    assert state["paid"] == 200.0 and state["payments"] == 2
    assert state["status"] == "paid"


# ------------------------------------------------------------ giving back --
def test_the_manager_refunds_directly(clinic):
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    _refund(desk, invoice, "60")
    state = _state(clinic, invoice)
    assert state["refunded"] == 60.0
    assert state["paid"] == 140.0
    assert state["status"] == "partial", "a refunded bill is no longer settled"


def test_you_cannot_give_back_more_than_was_collected(clinic):
    """The refund is capped at what actually came in. Otherwise a typo in the
    amount box takes money out of the drawer that never went into it."""
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "80")                      # only 80 of the 200 collected
    _refund(desk, invoice, "5000")
    state = _state(clinic, invoice)
    assert state["refunded"] == 80.0
    assert state["paid"] == 0.0
    assert state["status"] == "unpaid"


@pytest.mark.parametrize("amount", ["0", "-10", "abc"])
def test_a_nonsense_refund_gives_back_nothing(clinic, amount):
    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    _refund(desk, invoice, amount)
    assert _state(clinic, invoice)["refunded"] == 0.0


def test_staff_below_the_manager_file_a_request_instead(clinic):
    """Money doesn't leave the drawer on one person's say-so. The accountant's
    refund becomes a request; nothing moves until a manager decides."""
    from app.models import RefundRequest

    _every_refund_needs_approval(clinic)
    boss = clinic["sign_in"]("boss")
    _open_shift(boss)
    _bill(boss, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(boss, invoice, "200")

    acct = clinic["sign_in"]("acct")
    _refund(acct, invoice, "50")
    with clinic["app"].app_context():
        pending = RefundRequest.query.all()
        assert [(r.amount, r.status) for r in pending] == [(50.0, "pending")]
    assert _state(clinic, invoice)["paid"] == 200.0, "money moved before approval"


def test_approving_the_request_is_what_moves_the_money(clinic):
    from app.models import RefundRequest

    _every_refund_needs_approval(clinic)
    boss = clinic["sign_in"]("boss")
    _open_shift(boss)
    _bill(boss, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(boss, invoice, "200")
    _refund(clinic["sign_in"]("acct"), invoice, "50")

    with clinic["app"].app_context():
        request_id = RefundRequest.query.one().id
    boss.post(f"/finance/refund-requests/{request_id}/decide",
              data={"decision": "approve"}, follow_redirects=True)

    assert _state(clinic, invoice)["paid"] == 150.0
    with clinic["app"].app_context():
        assert RefundRequest.query.one().status == "approved"


def test_rejecting_it_leaves_the_money_where_it_was(clinic):
    from app.models import RefundRequest

    _every_refund_needs_approval(clinic)
    boss = clinic["sign_in"]("boss")
    _open_shift(boss)
    _bill(boss, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(boss, invoice, "200")
    _refund(clinic["sign_in"]("acct"), invoice, "50")

    with clinic["app"].app_context():
        request_id = RefundRequest.query.one().id
    boss.post(f"/finance/refund-requests/{request_id}/decide",
              data={"decision": "reject"}, follow_redirects=True)

    assert _state(clinic, invoice)["paid"] == 200.0
    with clinic["app"].app_context():
        assert RefundRequest.query.one().status == "rejected"


# ---------------------------------------------------- closing the drawer --
def test_the_drawer_expects_the_float_plus_what_came_in(clinic):
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    _bill(desk, clinic["ids"])
    _pay(desk, _the_invoice(clinic), "200")
    with clinic["app"].app_context():
        shift = CashierShift.query.one()
        assert shift.cash_collected == 200.0
        assert shift.expected_cash == 300.0


def test_a_card_payment_is_not_cash_in_the_drawer(clinic):
    """Counting card takings as cash is how a drawer comes up short by
    exactly the amount somebody paid on the machine."""
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    _bill(desk, clinic["ids"])
    _pay(desk, _the_invoice(clinic), "200", method="card")
    with clinic["app"].app_context():
        shift = CashierShift.query.one()
        assert shift.cash_collected == 0.0
        assert shift.expected_cash == 100.0


def test_a_cash_refund_comes_back_out_of_the_drawer(clinic):
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    _refund(desk, invoice, "50")
    with clinic["app"].app_context():
        assert CashierShift.query.one().expected_cash == 250.0


def test_closing_short_is_recorded_as_short(clinic):
    """The variance is the whole point of counting. It has to be a number
    somebody can be asked about, not a rounding away from zero."""
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    _bill(desk, clinic["ids"])
    _pay(desk, _the_invoice(clinic), "200")
    with clinic["app"].app_context():
        shift_id = CashierShift.query.one().id
    desk.post(f"/finance/shift/{shift_id}/close",
              data={"counted_cash": "280"}, follow_redirects=True)
    with clinic["app"].app_context():
        shift = clinic["db"].session.get(CashierShift, shift_id)
        assert shift.status == "closed"
        assert shift.variance == -20.0


def test_a_shift_is_not_closed_twice(clinic):
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    with clinic["app"].app_context():
        shift_id = CashierShift.query.one().id
    desk.post(f"/finance/shift/{shift_id}/close", data={"counted_cash": "100"},
              follow_redirects=True)
    desk.post(f"/finance/shift/{shift_id}/close", data={"counted_cash": "999"},
              follow_redirects=True)
    with clinic["app"].app_context():
        assert clinic["db"].session.get(CashierShift, shift_id).counted_cash == 100.0


def test_one_cashier_has_one_open_shift(clinic):
    from app.models import CashierShift

    desk = clinic["sign_in"]("boss")
    _open_shift(desk, "100")
    _open_shift(desk, "500")
    with clinic["app"].app_context():
        assert CashierShift.query.count() == 1


# ------------------------------------------------ the month that is closed --
def test_a_closed_month_refuses_a_collection(clinic):
    """Same rule the store obeys: a signed month takes no more money."""
    from app.utils.periods import close_period, ensure_month

    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    with clinic["app"].app_context():
        today = local_today()
        close_period(ensure_month(today.year, today.month))
        clinic["db"].session.commit()
    _pay(desk, invoice, "200")
    assert _state(clinic, invoice)["payments"] == 0


def test_a_closed_month_refuses_a_refund(clinic):
    from app.utils.periods import close_period, ensure_month

    desk = clinic["sign_in"]("boss")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    with clinic["app"].app_context():
        today = local_today()
        close_period(ensure_month(today.year, today.month))
        clinic["db"].session.commit()
    _refund(desk, invoice, "50")
    assert _state(clinic, invoice)["refunded"] == 0.0


# ------------------------------------------------------------ who may pay --
def test_reception_can_work_the_till_without_the_whole_finance_module(clinic):
    """Reception collects money; reception does not see the P&L. That's the
    ``cashier`` capability rather than the finance module."""
    desk = clinic["sign_in"]("desk")
    _open_shift(desk)
    _bill(desk, clinic["ids"])
    invoice = _the_invoice(clinic)
    _pay(desk, invoice, "200")
    assert _state(clinic, invoice)["paid"] == 200.0
    assert desk.get("/finance/journal").status_code == 403


def test_the_doctor_is_not_a_cashier(clinic):
    doctor = clinic["sign_in"]("doc")
    assert doctor.get("/finance/cashier").status_code == 403
