"""A referral laboratory's account — a statement, not a ledger.

* the laboratory's **price list**, written by whoever builds the lists;
* each sample is charged at the price **when it was sent** — a price changed
  later does not rewrite what was sent, and a recalled sample drops out;
* a sample with **no agreed price** is counted apart, never at zero;
* the laboratory's **invoice** is matched against the statement and the
  difference kept as it was seen; nothing posts to the books.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest  # noqa: E402

from tests.test_a_sample_sent_to_another_lab import _drawn, _referral, _row  # noqa: E402
from tests.test_the_sample_nobody_drew import lab  # noqa: E402,F401


def _account(c, ref):
    from app.models import ReferralLab
    from app.utils import lab_sendout
    from app.utils.clock import local_today

    lab_row = c["db"].session.get(ReferralLab, ref)
    return lab_sendout.statement(lab_row, local_today().replace(day=1), local_today())


def test_each_sample_at_the_price_when_it_was_sent(lab):
    ref = _referral(lab)
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/referral-labs/{ref}/prices", data={f"price_{lab['urine']}": "150"})
    first = _drawn(lab, name="تحليل بول", test="urine")
    boss.post("/labs/send-out", data={"order_id": str(first), "lab_id": str(ref)})
    boss.post(f"/labs/referral-labs/{ref}/prices", data={f"price_{lab['urine']}": "200"})
    second = _drawn(lab, name="تحليل بول", test="urine")
    boss.post("/labs/send-out", data={"order_id": str(second), "lab_id": str(ref)})
    with lab["app"].app_context():
        assert (_row(lab, first).sent_cost, _row(lab, second).sent_cost) == (150, 200)
        data = _account(lab, ref)
        assert (data["total"], data["unpriced"], len(data["rows"])) == (350, 0, 2)
    page = boss.get(f"/labs/referral-labs/{ref}/account").get_data(as_text=True)
    assert f'data-statement-row="{first}"' in page and "data-statement-total" in page
    boss.post(f"/labs/order/{second}/recall")
    with lab["app"].app_context():
        assert _row(lab, second).sent_cost is None
        assert _account(lab, ref)["total"] == 150


def test_a_sample_with_no_agreed_price_is_counted_apart(lab):
    ref = _referral(lab)
    order = _drawn(lab)
    lab["sign_in"]("boss").post("/labs/send-out",
                                data={"order_id": str(order), "lab_id": str(ref)})
    with lab["app"].app_context():
        data = _account(lab, ref)
        assert (data["total"], data["unpriced"]) == (0, 1)
    page = lab["sign_in"]("boss").get(f"/labs/referral-labs/{ref}/account").get_data(as_text=True)
    assert "data-unpriced" in page


def test_the_invoice_is_matched_and_the_difference_kept(lab):
    from app.models import JournalEntry, ReferralInvoice
    from app.utils.clock import local_today

    ref = _referral(lab)
    boss = lab["sign_in"]("boss")
    boss.post(f"/labs/referral-labs/{ref}/prices", data={f"price_{lab['urine']}": "150"})
    order = _drawn(lab, name="تحليل بول", test="urine")
    boss.post("/labs/send-out", data={"order_id": str(order), "lab_id": str(ref)})
    today = local_today()
    with lab["app"].app_context():
        entries = JournalEntry.query.count()
    boss.post(f"/labs/referral-labs/{ref}/invoice",
              data={"number": "INV-9", "from": today.replace(day=1).isoformat(),
                    "to": today.isoformat(), "amount": "180"})
    with lab["app"].app_context():
        inv = ReferralInvoice.query.one()
        assert (inv.our_total, inv.amount, inv.difference) == (150, 180, 30)
        assert JournalEntry.query.count() == entries, "a statement posts nothing"
    page = boss.get(f"/labs/referral-labs/{ref}/account").get_data(as_text=True)
    assert "data-invoice-differs" in page


def test_only_the_lists_maker_prices_and_finance_matches(lab):
    from app.models import ReferralInvoice, ReferralLabPrice

    ref = _referral(lab)
    doc = lab["sign_in"]("doc")
    doc.post(f"/labs/referral-labs/{ref}/prices", data={f"price_{lab['urine']}": "1"})
    doc.post(f"/labs/referral-labs/{ref}/invoice",
             data={"number": "X", "from": date.today().isoformat(),
                   "to": date.today().isoformat(), "amount": "1"})
    with lab["app"].app_context():
        assert ReferralLabPrice.query.count() == 0 and ReferralInvoice.query.count() == 0
    page = lab["sign_in"]("boss").get("/labs/referral-labs").get_data(as_text=True)
    assert "data-to-referral-account" in page
