"""A checkout that issued an unpaid invoice under a button called "confirm".

Reported with four screenshots: pressed **Collect now** on the appointment
board, walked through the checkout, printed the receipt — and came back to the
board to find the row still saying *collect*. The invoice was there, at 480,
with 0.00 paid.

The program had done exactly what it was told. The collection box starts at
zero, so the path of least resistance through a screen every entry point calls
*collect* is to touch nothing and press the big blue button. What it did not
do was say which of two very different things that button was about to be.

**The fix is not to prefill the total.** That trades this mistake for a worse
one: a cashier who meant "collect later", and does not notice a figure they
never typed, records money that never entered the drawer. An unpaid invoice is
visible and chaseable; phantom cash in the till is neither.

So the amount stays as typed, and the button stops being ambiguous. Which act
is under the cursor is readable before it is pressed rather than discovered on
the next screen.
"""
import re


def _checkout_page(clinic):
    boss = clinic["sign_in"]("boss")
    boss.post("/finance/shift/open", data={"opening_float": "100"},
              follow_redirects=True)
    return boss, boss.get(
        f"/finance/collect/{clinic['ids']['child']}").get_data(as_text=True)


def test_the_button_names_both_acts(clinic):
    """One label for taking money and one for issuing a bill without it."""
    _boss, page = _checkout_page(clinic)
    assert "تأكيد وتحصيل" in page
    assert "إصدار فاتورة من غير تحصيل" in page


def test_which_one_is_shown_follows_what_is_typed(clinic):
    """Not which button opened the screen. A cashier can change their mind
    after arriving, and a label fixed at the door would go on describing an
    intention rather than the amounts in front of them."""
    _boss, page = _checkout_page(clinic)
    assert "get collecting()" in page
    body = page.split("get collecting()")[1][:120]
    assert "payments.some" in body
    assert "> 0" in body


def test_the_amount_is_not_prefilled(clinic):
    """The other fix, and the reason it was not taken: money recorded that
    nobody handed over is worse than a bill nobody paid."""
    _boss, page = _checkout_page(clinic)
    assert "payments: [{amount:0, method:'cash'}]" in page


def test_confirming_with_nothing_typed_still_leaves_it_unpaid(clinic):
    """The behaviour is unchanged — it was never the bug. Only the sentence
    on the button was."""
    from app.models import Invoice

    boss, _page = _checkout_page(clinic)
    boss.post(f"/finance/collect/{clinic['ids']['child']}", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"])], "line_desc": ["كشف"],
        "line_price": ["480"], "line_qty": ["1"], "line_no_commission": ["0"],
        "line_brand_id": [""], "line_dose_id": [""], "line_vs_id": [""],
        "line_dose_number": [""], "discount_id": "none",
        "amount": "0", "method": "cash"}, follow_redirects=True)

    with clinic["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.paid == 0.0
        assert invoice.status == "unpaid"


def test_a_typed_amount_still_collects(clinic):
    """And the ordinary case is untouched."""
    from app.models import Invoice

    boss, _page = _checkout_page(clinic)
    boss.post(f"/finance/collect/{clinic['ids']['child']}", data={
        "patient_id": clinic["ids"]["child"], "doctor_id": clinic["ids"]["doctor"],
        "line_service_id": [str(clinic["ids"]["exam"])], "line_desc": ["كشف"],
        "line_price": ["480"], "line_qty": ["1"], "line_no_commission": ["0"],
        "line_brand_id": [""], "line_dose_id": [""], "line_vs_id": [""],
        "line_dose_number": [""], "discount_id": "none",
        "amount": "480", "method": "cash"}, follow_redirects=True)

    with clinic["app"].app_context():
        invoice = Invoice.query.one()
        assert invoice.paid == 480.0
        assert invoice.status == "paid"
