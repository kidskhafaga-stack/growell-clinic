"""One money form, sent once (MONEY_SAFETY_PLAN.md ف-٣).

Measured before: the collection form sent twice — the back button, a network
retry, a second click after the browser's four-second guard — put the exam on
the bill twice and took 400 for a visit of 200. Each money form now carries a
key of its own (`utils/once`).
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_clock_offset_day import _bill_form  # noqa: E402

KEY = "a" * 32


def _bills(clinic):
    from app.models import Invoice

    with clinic["app"].app_context():
        return [(i.total, i.paid, len(i.items)) for i in Invoice.query.all()]


def test_the_collection_form_sent_twice_is_collected_once(clinic):
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    form = dict(_bill_form(ids), amount=["200"], method=["instapay"], form_key=KEY)
    first = desk.post(f"/finance/collect/{ids['child']}", data=form)
    again = desk.post(f"/finance/collect/{ids['child']}", data=form)
    assert _bills(clinic) == [(200, 200, 1)]
    # Sent back where the first one went — the receipt — and told on the
    # next screen (the receipt prints and opens the day's board).
    assert again.headers["Location"] == first.headers["Location"]
    board = desk.get("/appointments/").get_data(as_text=True)
    assert "اتسجل قبل كده" in board


def test_a_new_form_is_a_new_charge(clinic):
    """A second exam on the same day is a second page, with its own key."""
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    for key in ("b" * 32, "c" * 32):
        desk.post(f"/finance/collect/{ids['child']}",
                  data=dict(_bill_form(ids), amount=["200"], method=["instapay"],
                            form_key=key))
    assert _bills(clinic) == [(400, 400, 2)]


def test_a_form_turned_away_can_be_sent_again(clinic):
    """Nothing saved, nothing kept: the key goes with the refusal."""
    from app.models import FormKey

    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    empty = {"doctor_id": ids["doctor"], "discount_id": "none", "form_key": KEY}
    desk.post(f"/finance/collect/{ids['child']}", data=empty)
    with clinic["app"].app_context():
        assert FormKey.query.count() == 0
    desk.post(f"/finance/collect/{ids['child']}",
              data=dict(_bill_form(ids), amount=["200"], method=["instapay"], form_key=KEY))
    assert _bills(clinic) == [(200, 200, 1)]


def test_a_part_payment_sent_twice_is_taken_once(clinic):
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    desk.post(f"/finance/collect/{ids['child']}", data=_bill_form(ids))
    from app.models import Invoice

    with clinic["app"].app_context():
        bill = Invoice.query.one().id
    pay = {"amount": "50", "method": "instapay", "form_key": KEY}
    boss = clinic["sign_in"]()
    boss.post(f"/finance/invoices/{bill}/payment", data=pay)
    boss.post(f"/finance/invoices/{bill}/payment", data=pay)
    assert _bills(clinic) == [(200, 50, 1)]


def test_a_deposit_sent_twice_is_taken_once(clinic):
    from app.utils import patient_credit

    boss = clinic["sign_in"]()
    data = {"amount": "300", "method": "instapay", "form_key": KEY}
    for _ in range(2):
        boss.post(f"/finance/patient/{clinic['ids']['child']}/account/take", data=data)
    with clinic["app"].app_context():
        assert patient_credit.balance(clinic["ids"]["child"]) == 300


def test_without_a_key_a_form_works_as_it_always_did(clinic):
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    desk.post(f"/finance/collect/{ids['child']}",
              data=dict(_bill_form(ids), amount=["200"], method=["instapay"]))
    assert _bills(clinic) == [(200, 200, 1)]


def test_every_money_form_carries_a_fresh_key(clinic):
    desk = clinic["sign_in"]("desk")
    ids = clinic["ids"]
    pages = [desk.get(f"/finance/collect/{ids['child']}").get_data(as_text=True)
             for _ in range(2)]
    keys = [re.search(r'name="form_key" value="([0-9a-f]{32})"', p).group(1) for p in pages]
    assert keys[0] != keys[1]
    desk.post(f"/finance/collect/{ids['child']}", data=_bill_form(ids))
    from app.models import Invoice

    with clinic["app"].app_context():
        bill = Invoice.query.one().id
    boss = clinic["sign_in"]()
    page = boss.get(f"/finance/invoices/{bill}").get_data(as_text=True)
    assert page.count('name="form_key"') >= 1
    account = boss.get(f"/finance/patient/{ids['child']}/account").get_data(as_text=True)
    assert account.count('name="form_key"') >= 1
